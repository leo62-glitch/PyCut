"""Read and write CapCut Desktop 9.x drafts (``draft_content.json`` + ``draft_meta_info.json``).

Format reference: capcut_draft_format.md (80 real drafts analysed, new_version 171 -> 189).

Strategy
--------
* **Export** starts from a real, minimal draft shipped in ``resources/`` so every key CapCut
  expects is present, then fills it from the PyCut model.
* **Import** maps what PyCut understands onto the model and *keeps the rest verbatim*
  (store effects, transitions, masks, text templates, unknown tracks...) in ``extra`` fields,
  so a CapCut -> PyCut -> CapCut round trip does not destroy what PyCut cannot edit yet.
* Things PyCut creates that need CapCut store resources (transitions, video effects, masks,
  filters, stickers) cannot be fabricated; they are reported in the returned warnings.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..core.ids import new_id
from ..core.model import (
    Animation, AudioSettings, ChromaKey, EffectInstance, Keyframe, KeyframeTrack, Marker, Mask,
    Material, MaterialKind, Project, Segment, Shadow, Speed, TextStyle, TimeRange, Track,
    TrackKind, Transform, Transition, CANVAS_RATIOS,
)

RES = Path(__file__).resolve().parent.parent / "resources"
PHOTO_DURATION_US = 10_800_000_000        # CapCut stores photos as 3 h clips
CAPCUT_NEW_VERSION = "189.0.0"
VIDEO_ANNEX = ["speeds", "placeholder_infos", "canvases", "material_animations",
               "sound_channel_mappings", "material_colors", "vocal_separations"]
AUDIO_ANNEX = ["speeds", "placeholder_infos", "beats", "sound_channel_mappings", "vocal_separations"]
TEXT_ANNEX = ["material_animations"]
MANAGED = {"speeds", "chromas", "audio_fades"}          # regenerated from the model
SUPPORTED_TRACKS = {"video", "audio", "text"}
MAIN_GROUP = {"videos", "audios", "texts"}


@dataclass
class ExportOptions:
    app_version: str = "9.6.0"
    app_dir: str = ""     # e.g. C:/Users/me/AppData/Local/CapCut/Apps/9.6.0 (fonts, chroma path)
    copy_media: bool = False


# --------------------------------------------------------------------------- helpers
@lru_cache(maxsize=1)
def _tpl() -> dict:
    return json.loads((RES / "capcut_minimal_draft_content.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _defaults() -> dict:
    return json.loads((RES / "capcut_defaults.json").read_text(encoding="utf-8"))


def _cp(x):
    return copy.deepcopy(x)


def _hex_to_rgb(h: str) -> list[float]:
    h = (h or "#FFFFFF").lstrip("#")
    return [round(int(h[i:i + 2], 16) / 255, 4) for i in (0, 2, 4)]


def _rgb_to_hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02X}" for c in rgb[:3])


def _norm_path(p: str) -> str:
    return p.replace("\\", "/") if p else p


def _template_parts() -> dict:
    t = _tpl()
    m = t["materials"]
    vtr = next(tr for tr in t["tracks"] if tr["type"] == "video")
    ttr = next(tr for tr in t["tracks"] if tr["type"] == "text")
    annex = {g: m[g][0] for g in m if m[g] and g not in ("videos", "texts")}
    return {"video_mat": m["videos"][0], "text_mat": m["texts"][0],
            "video_seg": vtr["segments"][0], "text_seg": ttr["segments"][0], "annex": annex}


def _fresh_annex(group: str) -> dict:
    d = _cp(_template_parts()["annex"].get(group) or _defaults()[group])
    d["id"] = new_id()
    return d


def _empty_doc() -> dict:
    doc = _cp(_tpl())
    doc["tracks"] = []
    doc["materials"] = {g: [] for g in doc["materials"]}
    doc["id"] = new_id()
    doc["new_version"] = CAPCUT_NEW_VERSION
    return doc


def _flat_text(ts: TextStyle, font: str) -> dict:
    return {"font_size": float(ts.size), "font_path": _norm_path(font), "text_color": ts.color.upper(),
            "text_alpha": ts.alpha, "alignment": ts.align, "typesetting": 1 if ts.vertical else 0,
            "line_max_width": ts.max_width, "line_spacing": ts.line_spacing,
            "letter_spacing": ts.letter_spacing, "has_shadow": ts.shadow.enabled,
            "shadow_color": ts.shadow.color, "shadow_alpha": ts.shadow.alpha,
            "shadow_distance": ts.shadow.distance, "shadow_angle": ts.shadow.angle,
            "border_width": ts.stroke_width, "border_color": ts.stroke_color,
            "background_color": ts.background_color, "background_alpha": ts.background_alpha,
            "background_style": ts.background_style, "background_round_radius": ts.background_radius,
            "bold_width": ts.bold_width, "italic_degree": ts.italic_degree, "underline": ts.underline}


# =========================================================================== EXPORT
class _Exporter:
    def __init__(self, project: Project, opts: ExportOptions):
        self.p = project
        self.o = opts
        raw = project.extra.get("capcut_doc")
        self.doc = _cp(raw) if raw else _empty_doc()
        self.doc["tracks"] = []
        groups = set(_tpl()["materials"]) | set(self.doc.get("materials", {}))
        self.doc["materials"] = {g: [] for g in sorted(groups)}
        self.mats = self.doc["materials"]
        self.warnings: list[str] = []
        self.mat_done: dict[str, str] = {}      # PyCut material id -> CapCut main material id
        self.z = 0          # video/overlay stacking order
        self.tz = 0         # text stacking order (14000+)
        self.local_meta: list[dict] = []
        self._warned: set[str] = set()

    def warn(self, msg: str) -> None:
        if msg not in self._warned:
            self._warned.add(msg)
            self.warnings.append(msg)

    # -- materials -----------------------------------------------------------------
    def font_path(self) -> str:
        if self.o.app_dir:
            return f"{_norm_path(self.o.app_dir)}/Resources/Font/SystemFont/en.ttf"
        return _template_parts()["text_mat"].get("font_path", "")

    def media_material(self, m: Material) -> str:
        if m.id in self.mat_done:
            return self.mat_done[m.id]
        P = _template_parts()
        if m.kind == MaterialKind.AUDIO:
            d = _cp(m.extra.get("capcut_raw") or _defaults()["audios"])
            d.update(id=m.id, type=d.get("type") or "extract_music", name=m.name, path=_norm_path(m.path),
                     duration=int(m.duration), category_name="local")
            if not m.extra.get("capcut_raw"):
                d["type"] = "extract_music"
                d["check_flag"] = 1
            self.mats["audios"].append(d)
            meta_type = "music"
        else:
            d = _cp(m.extra.get("capcut_raw") or P["video_mat"])
            kind = {MaterialKind.PHOTO: "photo", MaterialKind.GIF: "gif"}.get(m.kind, "video")
            d.update(id=m.id, type=kind, path=_norm_path(m.path), material_name=m.name or Path(m.path).name,
                     width=m.width, height=m.height, has_audio=bool(m.has_audio and kind == "video"),
                     category_name="local",
                     duration=PHOTO_DURATION_US if kind == "photo" else int(m.duration))
            d["local_material_id"] = m.capcut_local_id or str(uuid.uuid4())
            m.capcut_local_id = d["local_material_id"]
            self.mats["videos"].append(d)
            meta_type = {"photo": "photo", "gif": "gif"}.get(kind, "video")
        now = int(time.time())
        self.local_meta.append({
            "id": d.get("local_material_id") or str(uuid.uuid4()), "metetype": meta_type,
            "file_Path": _norm_path(m.path), "extra_info": m.name or Path(m.path).name,
            "width": m.width, "height": m.height, "duration": int(d["duration"]),
            "create_time": now, "import_time": now, "import_time_ms": now * 1_000_000,
            "item_source": 1, "md5": "", "material_color_tag": "", "ai_group_type": "", "enter_from": 0,
            "roughcut_time_range": {"start": 0, "duration": int(d["duration"])},
            "sub_time_range": {"start": -1, "duration": -1}, "type": 0})
        self.mat_done[m.id] = d["id"]
        return d["id"]

    def text_material(self, seg: Segment) -> dict:
        P = _template_parts()
        ts = seg.text
        raw = seg.extra.get("capcut_text_raw")
        d = _cp(raw or P["text_mat"])
        d["id"] = new_id() if not raw else raw["id"]
        text = ts.text
        font = ts.font_path or self.font_path()
        style: dict = {"fill": {"content": {"render_type": "solid", "solid": {"color": _hex_to_rgb(ts.color)}}},
                       "font": {"path": _norm_path(font), "id": ""}, "size": int(round(ts.size)),
                       "range": [0, len(text)]}
        if ts.bold:
            style["bold"] = True
        if ts.italic:
            style["italic"] = True
        if ts.underline:
            style["underline"] = True
        content = {"text": text, "styles": [style]}
        if raw:  # keep unknown style keys (effectStyle, strokes, ...) of the first run
            try:
                old = json.loads(raw["content"])
                keep = {k: v for k, v in old["styles"][0].items() if k not in style}
                style.update(keep)
            except (KeyError, ValueError, IndexError):
                pass
        flat = _flat_text(ts, font)
        if raw:   # only touch the fields the user actually changed since import
            imp = _import_text(raw)
            base = _flat_text(imp, imp.font_path)
            flat = {k: v for k, v in flat.items() if base.get(k) != v}
        flat["content"] = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        d.update({k: v for k, v in flat.items() if k in d or k == "content"})
        self.mats["texts"].append(d)
        return d

    # -- segment pieces -----------------------------------------------------------------
    def clip_of(self, tr: Transform) -> dict:
        sx = tr.scale_x
        sy = tr.scale_x if tr.uniform_scale else tr.scale_y
        return {"scale": {"x": sx, "y": sy}, "rotation": tr.rotation, "transform": {"x": tr.x, "y": tr.y},
                "flip": {"vertical": tr.flip_v, "horizontal": tr.flip_h}, "alpha": tr.alpha}

    def keyframes_of(self, seg: Segment) -> list[dict]:
        out = []
        for kt in seg.keyframes:
            if not kt.keyframes:
                continue
            if seg.transform.uniform_scale and kt.property == "KFTypeScaleY":
                continue
            if kt.property.startswith("KFTypeMask") or kt.property == "KFTypeFilter":
                self.warn(f"Keyframes {kt.property} ignorés à l'export")
                continue
            lst = []
            for k in kt.sorted():
                if k.curve != "Line":
                    self.warn("Courbes d'interpolation non linéaires exportées en linéaire")
                lst.append({"id": new_id(), "curveType": "Line", "time_offset": int(k.time_offset),
                            "left_control": {"x": 0.0, "y": 0.0}, "right_control": {"x": 0.0, "y": 0.0},
                            "values": [k.value], "string_value": "", "graphID": ""})
            out.append({"id": new_id(), "material_id": "", "property_type": kt.property, "keyframe_list": lst})
        return out

    def annex_for(self, seg: Segment, kind: str) -> list[str]:
        """Create the annex materials of a segment and return their ids (in CapCut order)."""
        required = {"video": VIDEO_ANNEX, "audio": AUDIO_ANNEX, "text": TEXT_ANNEX}[kind]
        kept: dict[str, list[dict]] = {}
        for item in seg.extra.get("capcut_annex", []):
            kept.setdefault(item["group"], []).append(_cp(item["obj"]))
        refs: list[str] = []

        def emit(group: str, obj: dict) -> None:
            self.mats.setdefault(group, []).append(obj)
            refs.append(obj["id"])

        for g in required:
            if g == "speeds":
                sp = seg.speed
                obj = kept.get("speeds", [None])[0] or _fresh_annex("speeds")
                obj.update(mode=sp.mode, speed=sp.speed if sp.mode == 0 else 1.0)
                obj["curve_speed"] = ({"name": sp.curve_name or "custom", "speed_points":
                                       [{"x": x, "y": y} for x, y in sp.curve_points]}
                                      if sp.mode == 1 and sp.curve_points else None)
                emit("speeds", obj)
            elif g == "material_animations":
                for obj in kept.get(g, [])[:1] or [_fresh_annex(g)]:
                    emit(g, obj)
                if seg.animation.in_name or seg.animation.out_name or seg.animation.loop_name:
                    if not kept.get(g):
                        self.warn("Animations d'entrée/sortie créées dans PyCut non exportées (ressources du store)")
            else:
                for obj in kept.get(g, [])[:1] or [_fresh_annex(g) if g != "beats" else {**_cp(_defaults()["beats"]), "id": new_id()}]:
                    emit(g, obj)
        if kind != "text" and (seg.audio.fade_in or seg.audio.fade_out):
            obj = {**_cp(_defaults()["audio_fades"]), "id": new_id(), "fade_in_duration": int(seg.audio.fade_in),
                   "fade_out_duration": int(seg.audio.fade_out)}
            emit("audio_fades", obj)
        if seg.chroma.enabled:
            base = kept.get("chromas", [None])[0] or {**_cp(_defaults()["chromas"]), "id": new_id()}
            path = f"{_norm_path(self.o.app_dir)}/Resources/Chroma2" if self.o.app_dir else base.get("path", "")
            base.update(type="chroma", color=seg.chroma.color.lower() + "ff", intensity_value=seg.chroma.intensity,
                        shadow_value=seg.chroma.shadow, path=path, version="v2")
            emit("chromas", base)
        # preserved store-based materials, only while the feature is still enabled in the model
        for g, objs in kept.items():
            if g in required or g in MANAGED:
                continue
            for obj in objs:
                if g == "transitions":
                    if seg.transition is None:
                        continue
                    obj["duration"] = int(seg.transition.duration)
                    obj["is_overlap"] = seg.transition.overlap
                elif g == "common_mask":
                    if seg.mask.kind == "none":
                        continue
                    cfg = obj.setdefault("config", {})
                    cfg.update(width=seg.mask.width, height=seg.mask.height, centerX=seg.mask.center_x,
                               centerY=seg.mask.center_y, rotation=seg.mask.rotation, feather=seg.mask.feather,
                               roundCorner=seg.mask.round_corner, invert=seg.mask.invert)
                elif g == "video_effects":
                    if obj["id"] not in {fx.id for fx in seg.effects}:
                        continue
                emit(g, obj)
        if seg.transition is not None and not any(i["group"] == "transitions" for i in seg.extra.get("capcut_annex", [])):
            self.warn(f"Transition « {seg.transition.name} » créée dans PyCut non exportée (ressource du store CapCut)")
        if seg.mask.kind != "none" and not any(i["group"] == "common_mask" for i in seg.extra.get("capcut_annex", [])):
            self.warn(f"Masque « {seg.mask.kind} » créé dans PyCut non exporté (ressource du store CapCut)")
        for fx in seg.effects:
            if not any(i["obj"].get("id") == fx.id for i in seg.extra.get("capcut_annex", [])):
                self.warn(f"Effet « {fx.name} » créé dans PyCut non exporté (ressource du store CapCut)")
        if seg.filter.name:
            self.warn("Filtres non exportés (ressources du store CapCut)")
        if seg.freeze:
            self.warn("Image figée exportée comme clip normal")
        return refs

    def build_segment(self, seg: Segment, kind: str, track_index: int, main_id: str) -> dict:
        P = _template_parts()
        d = _cp(seg.extra.get("capcut_raw_seg") or (P["text_seg"] if kind == "text" else P["video_seg"]))
        d["id"] = seg.id
        d["material_id"] = main_id
        d["extra_material_refs"] = self.annex_for(seg, kind)
        d["target_timerange"] = {"start": int(seg.start), "duration": int(seg.duration)}
        d["source_timerange"] = None if seg.source is None or kind == "text" else \
            {"start": int(seg.source.start), "duration": int(seg.source.duration)}
        d["render_timerange"] = {"start": 0, "duration": 0}
        d["speed"] = seg.speed.speed if seg.speed.mode == 0 else 1.0
        d["volume"] = 0.0 if seg.audio.muted else seg.audio.volume
        if not seg.audio.muted and seg.audio.volume > 0:
            d["last_nonzero_volume"] = seg.audio.volume
        d["reverse"] = seg.reverse
        d["visible"] = seg.visible
        d["track_render_index"] = track_index
        d["group_id"] = seg.group_id
        if seg.color_tag or "segment_color_tag" in d:
            d["segment_color_tag"] = seg.color_tag
        d["is_placeholder"] = seg.is_placeholder
        if kind == "audio":
            d["clip"] = None
            d["uniform_scale"] = None
            d["hdr_settings"] = None
            d["render_index"] = 0
        else:
            d["clip"] = self.clip_of(seg.transform)
            d["uniform_scale"] = {"on": seg.transform.uniform_scale, "value": seg.transform.scale_x}
            if kind == "text":
                d["render_index"] = 14000 + self.tz
                self.tz += 1
            else:
                d["render_index"] = self.z
                self.z += 1
        d["common_keyframes"] = self.keyframes_of(seg)
        d["keyframe_refs"] = []
        return d

    # -- whole project -----------------------------------------------------------------
    def run(self) -> dict:
        p, doc = self.p, self.doc
        doc["id"] = p.id
        doc["fps"] = float(p.fps)
        doc["duration"] = int(p.duration)
        doc["canvas_config"] = {"ratio": p.ratio if p.ratio in CANVAS_RATIOS else "original",
                                "width": p.width, "height": p.height, "background": None}
        doc["platform"]["app_version"] = self.o.app_version
        doc["last_modified_platform"]["app_version"] = self.o.app_version
        # unsupported raw content imported earlier (sticker/effect/filter/adjust tracks and their materials)
        raw = p.extra.get("capcut_raw", {})
        for g, lst in raw.get("materials", {}).items():
            self.mats.setdefault(g, []).extend(_cp(lst))
        unsupported = {TrackKind.STICKER, TrackKind.EFFECT, TrackKind.FILTER, TrackKind.ADJUST}
        for idx, tr in enumerate(p.tracks):
            if tr.kind in unsupported:
                if tr.segments:
                    self.warn(f"Pistes « {tr.kind.value} » non exportées (ressources du store CapCut)")
                continue
            kind = tr.kind.value
            ctr = {"id": tr.id, "type": kind, "segments": [], "flag": 0, "attribute": 1 if tr.hidden else 0,
                   "name": tr.name if tr.name not in ("", "Main") else "", "is_default_name": tr.name in ("", "Main")}
            if kind == "video" and not tr.is_main:
                ctr["flag"] |= 2
            if tr.locked:
                ctr["flag"] |= 1
            if tr.muted:
                ctr["flag"] |= 4
            for seg in sorted(tr.segments, key=lambda s: s.start):
                mat = p.materials.get(seg.material_id)
                if mat is None:
                    self.warn("Segment sans matériau ignoré")
                    continue
                if kind == "text":
                    main_id = self.text_material(seg)["id"]
                else:
                    main_id = self.media_material(mat)
                ctr["segments"].append(self.build_segment(seg, kind, idx, main_id))
            doc["tracks"].append(ctr)
        # raw tracks (kept as-is, after the editable ones)
        doc["tracks"].extend(_cp(raw.get("tracks", [])))
        doc["render_index_track_mode_on"] = True
        return doc


def _meta_for(project: Project, doc: dict, folder: Path, local_meta: list[dict]) -> dict:
    now_us = int(time.time() * 1_000_000)
    meta = _cp(_defaults()["draft_meta_info"])
    meta.update(
        draft_id=doc["id"], draft_name=folder.name, draft_fold_path=_norm_path(str(folder)),
        draft_root_path=_norm_path(str(folder.parent)), draft_cover="draft_cover.jpg",
        tm_draft_create=int(project.created * 1_000_000), tm_draft_modified=now_us,
        tm_duration=int(doc["duration"]),
        draft_timeline_materials_size_=sum(m.size_bytes for m in project.materials.values()),
        draft_new_version="", draft_segment_extra_info=[], draft_materials=[
            {"type": 0, "value": local_meta}, {"type": 1, "value": []}, {"type": 2, "value": []},
            {"type": 3, "value": []}, {"type": 6, "value": []}, {"type": 7, "value": []},
            {"type": 8, "value": []}])
    return meta


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def export_draft(project: Project, root_dir: str | os.PathLike, name: str | None = None,
                 options: ExportOptions | None = None, update_root_index: bool = True) -> tuple[Path, list[str]]:
    """Write ``project`` as a CapCut draft folder inside ``root_dir`` (``com.lveditor.draft``).

    Returns ``(draft_folder, warnings)``. Never overwrites a folder that is not a draft written
    by us: an existing folder gets a `` (n)`` suffix.
    """
    opts = options or ExportOptions()
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)
    base = (name or project.name or "PyCut").strip()
    folder, n = root / base, 1
    while folder.exists() and not (folder / ".pycut").exists():
        folder = root / f"{base} ({n})"
        n += 1
    folder.mkdir(parents=True, exist_ok=True)
    ex = _Exporter(project, opts)
    doc = ex.run()
    if opts.copy_media:
        mdir = folder / "media"
        mdir.mkdir(exist_ok=True)
        for g in ("videos", "audios"):
            for m in doc["materials"][g]:
                src = Path(m["path"])
                if src.is_file():
                    shutil.copy2(src, mdir / src.name)
                    m["path"] = _norm_path(str(mdir / src.name))
    _dump(folder / "draft_content.json", doc)
    meta = _meta_for(project, doc, folder, ex.local_meta)
    _dump(folder / "draft_meta_info.json", meta)
    (folder / ".pycut").write_text(project.id, encoding="utf-8")
    now = int(time.time())
    (folder / "draft_settings").write_text(
        f"[General]\ndraft_create_time={int(project.created)}\ndraft_last_edit_time={now}\n"
        "real_edit_seconds=0\nreal_edit_keys=0\ncloud_last_modify_platform=windows\n", encoding="utf-8")
    if project.cover_path and Path(project.cover_path).is_file():
        shutil.copy2(project.cover_path, folder / "draft_cover.jpg")
    if update_root_index:
        _update_root_index(root, meta, folder)
    return folder, ex.warnings


def _update_root_index(root: Path, meta: dict, folder: Path) -> None:
    idx_path = root / "root_meta_info.json"
    try:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        idx = {"root_path": _norm_path(str(root)), "draft_ids": 0, "all_draft_store": []}
    store = [e for e in idx.get("all_draft_store", []) if e.get("draft_id") != meta["draft_id"]]
    item = _cp(_defaults()["root_store_item"])
    item.update(
        draft_id=meta["draft_id"], draft_name=meta["draft_name"], draft_fold_path=meta["draft_fold_path"],
        draft_json_file=_norm_path(str(folder)) + "\\draft_content.json",
        draft_cover=_norm_path(str(folder)) + "\\draft_cover.jpg", draft_root_path=meta["draft_root_path"],
        tm_draft_create=meta["tm_draft_create"], tm_draft_modified=meta["tm_draft_modified"],
        tm_duration=meta["tm_duration"], draft_timeline_materials_size=meta["draft_timeline_materials_size_"])
    store.insert(0, item)
    idx["all_draft_store"] = store
    idx["draft_ids"] = len(store)
    if idx_path.exists():
        shutil.copy2(idx_path, idx_path.with_suffix(".json.pycut.bak"))
    _dump(idx_path, idx)


# =========================================================================== IMPORT
_KIND = {"video": MaterialKind.VIDEO, "photo": MaterialKind.PHOTO, "gif": MaterialKind.GIF}


def _import_text(raw: dict) -> TextStyle:
    ts = TextStyle()
    try:
        content = json.loads(raw.get("content") or "{}")
    except ValueError:
        content = {}
    ts.text = content.get("text", "")
    st = (content.get("styles") or [{}])[0]
    ts.size = float(st.get("size", raw.get("font_size", ts.size)))
    fill = st.get("fill", {}).get("content", {}).get("solid", {}).get("color")
    ts.color = _rgb_to_hex(fill) if fill else (raw.get("text_color") or "#FFFFFF")[:7].upper()
    ts.font_path = st.get("font", {}).get("path") or raw.get("font_path", "")
    ts.bold, ts.italic, ts.underline = bool(st.get("bold")), bool(st.get("italic")), bool(st.get("underline", raw.get("underline")))
    ts.alpha = raw.get("text_alpha", 1.0)
    ts.align = raw.get("alignment", 1)
    ts.vertical = raw.get("typesetting", 0) == 1
    ts.max_width = raw.get("line_max_width", ts.max_width)
    ts.line_spacing = raw.get("line_spacing", ts.line_spacing)
    ts.letter_spacing = raw.get("letter_spacing", 0.0)
    ts.stroke_width = raw.get("border_width", 0.0) if raw.get("border_color") not in (None, "") else 0.0
    ts.stroke_color = raw.get("border_color") or "#000000"
    ts.background_color = raw.get("background_color") or "#000000"
    ts.background_alpha = raw.get("background_alpha", 0.0)
    ts.background_style = raw.get("background_style", 0)
    ts.background_radius = raw.get("background_round_radius", 0.0)
    ts.bold_width = raw.get("bold_width", 0.0)
    ts.italic_degree = raw.get("italic_degree", 0.0)
    ts.shadow = Shadow(enabled=bool(raw.get("has_shadow")), color=raw.get("shadow_color") or "#000000",
                       alpha=raw.get("shadow_alpha", 0.8), distance=raw.get("shadow_distance", 5.0),
                       angle=raw.get("shadow_angle", -45.0))
    return ts


def read_draft(path: str | os.PathLike) -> Project:
    """Load a CapCut draft folder (or its ``draft_content.json``) as a ``Project``."""
    path = Path(path)
    f = path / "draft_content.json" if path.is_dir() else path
    doc = json.loads(f.read_text(encoding="utf-8"))
    index: dict[str, tuple[str, dict]] = {}
    for g, lst in doc.get("materials", {}).items():
        for obj in lst:
            if isinstance(obj, dict) and "id" in obj:
                index[obj["id"]] = (g, obj)
    cc = doc.get("canvas_config", {})
    p = Project(name=f.parent.name, id=doc.get("id") or new_id(), path=str(f.parent), fps=float(doc.get("fps", 30)),
                width=cc.get("width", 1920), height=cc.get("height", 1080), ratio=cc.get("ratio", "original"),
                capcut_version=str(doc.get("new_version", "")), source_format="capcut")
    meta_file = f.parent / "draft_meta_info.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            p.name = meta.get("draft_name") or p.name
            p.created = meta.get("tm_draft_create", 0) / 1_000_000 or p.created
        except ValueError:
            pass
    cover = f.parent / "draft_cover.jpg"
    p.cover_path = str(cover) if cover.exists() else ""

    mats: dict[str, Material] = {}
    used_main: set[str] = set()
    raw_tracks: list[dict] = []
    for ti, ctr in enumerate(doc.get("tracks", [])):
        kind = ctr.get("type")
        if kind not in SUPPORTED_TRACKS:
            raw_tracks.append(ctr)
            continue
        flag = ctr.get("flag", 0)
        tr = Track(kind=TrackKind(kind), id=ctr.get("id") or new_id(), name=ctr.get("name", ""),
                   muted=bool(flag & 4), locked=bool(flag & 1), hidden=bool(ctr.get("attribute", 0) & 1))
        for cs in ctr.get("segments", []):
            gm = index.get(cs.get("material_id"))
            if gm is None:
                continue
            group, mraw = gm
            if kind == "text":
                m = Material(kind=MaterialKind.TEXT, id=mraw["id"], name=(json.loads(mraw.get("content", "{}") or "{}").get("text", "") if mraw.get("content") else "")[:40])
            elif mraw["id"] in mats:
                m = mats[mraw["id"]]
            elif kind == "audio":
                m = Material(kind=MaterialKind.AUDIO, id=mraw["id"], name=mraw.get("name", ""), path=mraw.get("path", ""),
                             duration=mraw.get("duration", 0), has_audio=True, has_video=False)
            else:
                m = Material(kind=_KIND.get(mraw.get("type"), MaterialKind.VIDEO), id=mraw["id"],
                             name=mraw.get("material_name", ""), path=mraw.get("path", ""),
                             duration=0 if mraw.get("type") == "photo" else mraw.get("duration", 0),
                             width=mraw.get("width", 0), height=mraw.get("height", 0),
                             has_audio=bool(mraw.get("has_audio")), capcut_local_id=mraw.get("local_material_id", ""))
            if kind != "text":
                m.extra["capcut_raw"] = _cp(mraw)
            mats[m.id] = m
            used_main.add(mraw["id"])

            tgt = cs["target_timerange"]
            src = cs.get("source_timerange")
            seg = Segment(material_id=m.id, id=cs.get("id") or new_id(),
                          target=TimeRange(tgt["start"], tgt["duration"]),
                          source=TimeRange(src["start"], src["duration"]) if src else None, name=m.name)
            clip = cs.get("clip") or {}
            sc, tf, fl = clip.get("scale", {}), clip.get("transform", {}), clip.get("flip", {})
            us = cs.get("uniform_scale") or {}
            seg.transform = Transform(x=tf.get("x", 0.0), y=tf.get("y", 0.0), scale_x=sc.get("x", 1.0),
                                      scale_y=sc.get("y", 1.0), uniform_scale=bool(us.get("on", True)),
                                      rotation=clip.get("rotation", 0.0), flip_h=bool(fl.get("horizontal")),
                                      flip_v=bool(fl.get("vertical")), alpha=clip.get("alpha", 1.0))
            seg.audio = AudioSettings(volume=cs.get("volume", 1.0))
            seg.reverse = bool(cs.get("reverse"))
            seg.visible = cs.get("visible", True)
            seg.group_id = cs.get("group_id", "")
            seg.color_tag = cs.get("segment_color_tag", "")
            seg.render_index = cs.get("render_index", 0)
            seg.is_placeholder = bool(cs.get("is_placeholder"))
            seg.speed = Speed(speed=cs.get("speed", 1.0))
            annex: list[dict] = []
            for ref in cs.get("extra_material_refs", []):
                ag = index.get(ref)
                if ag is None:
                    continue
                g, obj = ag
                if g == "speeds":
                    seg.speed.mode = obj.get("mode", 0)
                    seg.speed.speed = obj.get("speed", 1.0)
                    cv = obj.get("curve_speed")
                    if cv:
                        seg.speed.curve_name = cv.get("name", "")
                        seg.speed.curve_points = [(pt["x"], pt["y"]) for pt in cv.get("speed_points", [])]
                    continue
                if g == "chromas":
                    seg.chroma = ChromaKey(enabled=True, color=(obj.get("color") or "#2dd201")[:7].upper(),
                                           intensity=obj.get("intensity_value", 0.2), shadow=obj.get("shadow_value", 0.0))
                    continue
                if g == "audio_fades":
                    seg.audio.fade_in = obj.get("fade_in_duration", 0)
                    seg.audio.fade_out = obj.get("fade_out_duration", 0)
                    continue
                if g == "transitions":
                    seg.transition = Transition(name=obj.get("name", ""), duration=obj.get("duration", 500000),
                                                overlap=bool(obj.get("is_overlap")))
                elif g == "common_mask":
                    cfg = obj.get("config", {})
                    seg.mask = Mask(kind=obj.get("resource_type", "none"), center_x=cfg.get("centerX", 0.0),
                                    center_y=cfg.get("centerY", 0.0), width=cfg.get("width", 0.5),
                                    height=cfg.get("height", 0.5), rotation=cfg.get("rotation", 0.0),
                                    feather=cfg.get("feather", 0.0), round_corner=cfg.get("roundCorner", 0.0),
                                    invert=bool(cfg.get("invert")))
                elif g == "video_effects":
                    seg.effects.append(EffectInstance(name=obj.get("name", ""), id=obj["id"]))
                annex.append({"group": g, "obj": _cp(obj)})
            seg.extra["capcut_annex"] = annex
            seg.extra["capcut_raw_seg"] = {k: _cp(v) for k, v in cs.items()
                                           if k not in ("common_keyframes", "extra_material_refs")}
            for ck in cs.get("common_keyframes", []):
                kt = KeyframeTrack(property=ck.get("property_type", ""))
                for k in ck.get("keyframe_list", []):
                    vals = k.get("values") or [0.0]
                    kt.keyframes.append(Keyframe(time_offset=k.get("time_offset", 0), value=vals[0],
                                                 curve=k.get("curveType", "Line") or "Line"))
                seg.keyframes.append(kt)
            if kind == "text":
                seg.text = _import_text(mraw)
                seg.name = seg.text.text[:40]
                m.name = seg.name
                seg.extra["capcut_text_raw"] = _cp(mraw)
                seg.source = None
            tr.segments.append(seg)
        p.tracks.append(tr)
    if not any(t.is_main for t in p.tracks):
        flags = {c["id"]: c.get("flag", 0) for c in doc.get("tracks", []) if c.get("type") == "video"}
        for t in p.tracks:
            if t.kind == TrackKind.VIDEO and flags.get(t.id, 0) & 2 == 0:
                t.is_main = True
                break
    p.materials = mats
    # keep everything we cannot edit so that a round trip is lossless
    p.extra["capcut_raw"] = {"tracks": raw_tracks, "materials": _raw_materials_for(raw_tracks, index)}
    shell = {k: v for k, v in doc.items() if k not in ("tracks", "materials")}
    p.extra["capcut_doc"] = shell | {"materials": {g: [] for g in doc.get("materials", {})}, "tracks": []}
    for t in p.tracks:
        t.sort()
    return p


def _raw_materials_for(raw_tracks: list[dict], index: dict) -> dict[str, list[dict]]:
    """Materials referenced by tracks PyCut cannot edit (stickers, effects, filters, adjustments)."""
    out: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for tr in raw_tracks:
        for s in tr.get("segments", []):
            for ref in [s.get("material_id"), *s.get("extra_material_refs", [])]:
                if ref in index and ref not in seen:
                    seen.add(ref)
                    g, obj = index[ref]
                    out.setdefault(g, []).append(_cp(obj))
    return out
