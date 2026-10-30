"""Project data model.

The model mirrors the structure of CapCut drafts so that import/export is
lossless for the features PyCut supports:

* ``Project`` owns a ``materials`` dictionary (media files, texts, stickers...)
  and an ordered list of ``Track`` objects (bottom-most first = lowest Z).
* A ``Track`` has a ``kind`` (video/audio/text/sticker/effect/filter/adjust)
  and a list of non-overlapping ``Segment`` objects sorted by ``target.start``.
* A ``Segment`` references one ``Material`` and carries all per-clip settings
  (transform, speed, audio, colour adjust, mask, chroma, animation, transition,
  keyframes...).

All times are integers in microseconds. Positions in ``Transform`` are
normalised like CapCut: ``x`` in [-1, 1] spans the canvas width, ``y`` is
positive upwards. ``scale`` 1.0 means "fit the canvas" for the material.

Plain dataclasses are used (no Qt dependency) so the model can be used in
tests, worker threads and the exporter.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from enum import Enum
from typing import Any, Iterator

from .ids import new_id
from .timebase import US

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class TrackKind(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    TEXT = "text"
    STICKER = "sticker"
    EFFECT = "effect"
    FILTER = "filter"
    ADJUST = "adjust"


class MaterialKind(str, Enum):
    VIDEO = "video"
    PHOTO = "photo"
    GIF = "gif"
    AUDIO = "audio"
    TEXT = "text"
    STICKER = "sticker"      # image sticker / emoji / shape
    EFFECT = "effect"        # standalone video effect clip (effect track)
    FILTER = "filter"        # standalone filter clip (filter track)
    ADJUST = "adjust"        # adjustment layer (adjust track)
    COLOR = "color"          # solid colour clip


# Which material kinds may live on which track kind.
TRACK_ACCEPTS: dict[TrackKind, set[MaterialKind]] = {
    TrackKind.VIDEO: {MaterialKind.VIDEO, MaterialKind.PHOTO, MaterialKind.GIF, MaterialKind.COLOR,
                      MaterialKind.STICKER, MaterialKind.TEXT},
    TrackKind.AUDIO: {MaterialKind.AUDIO},
    TrackKind.TEXT: {MaterialKind.TEXT},
    TrackKind.STICKER: {MaterialKind.STICKER},
    TrackKind.EFFECT: {MaterialKind.EFFECT},
    TrackKind.FILTER: {MaterialKind.FILTER},
    TrackKind.ADJUST: {MaterialKind.ADJUST},
}

DEFAULT_TRACK_FOR_MATERIAL: dict[MaterialKind, TrackKind] = {
    MaterialKind.VIDEO: TrackKind.VIDEO,
    MaterialKind.PHOTO: TrackKind.VIDEO,
    MaterialKind.GIF: TrackKind.VIDEO,
    MaterialKind.COLOR: TrackKind.VIDEO,
    MaterialKind.AUDIO: TrackKind.AUDIO,
    MaterialKind.TEXT: TrackKind.TEXT,
    MaterialKind.STICKER: TrackKind.STICKER,
    MaterialKind.EFFECT: TrackKind.EFFECT,
    MaterialKind.FILTER: TrackKind.FILTER,
    MaterialKind.ADJUST: TrackKind.ADJUST,
}

BLEND_MODES = ["normal", "lighten", "screen", "overlay", "add", "darken", "multiply",
               "color_burn", "soft_light", "hard_light", "difference", "exclusion", "hue", "color"]

# Keyframe property names (CapCut ``KFType*`` vocabulary).
KF_POSITION_X = "KFTypePositionX"
KF_POSITION_Y = "KFTypePositionY"
KF_SCALE_X = "KFTypeScaleX"
KF_SCALE_Y = "KFTypeScaleY"
KF_ROTATION = "KFTypeRotation"
KF_ALPHA = "KFTypeAlpha"
KF_VOLUME = "KFTypeVolume"
KF_BRIGHTNESS = "KFTypeBrightness"
KF_CONTRAST = "KFTypeContrast"
KF_SATURATION = "KFTypeSaturation"
KF_TEMPERATURE = "KFTypeTemperature"
KF_HUE = "KFTypeHue"
KF_FILTER = "KFTypeFilter"
KF_MASK_CENTER_X = "KFTypeMaskCenterX"
KF_MASK_CENTER_Y = "KFTypeMaskCenterY"
KF_MASK_SIZE = "KFTypeMaskSize"
KF_MASK_FEATHER = "KFTypeMaskFeather"
KF_MASK_ROTATION = "KFTypeMaskRotation"

KEYFRAMEABLE_PROPERTIES = [
    KF_POSITION_X, KF_POSITION_Y, KF_SCALE_X, KF_SCALE_Y, KF_ROTATION, KF_ALPHA, KF_VOLUME,
    KF_BRIGHTNESS, KF_CONTRAST, KF_SATURATION, KF_TEMPERATURE, KF_HUE, KF_FILTER,
    KF_MASK_CENTER_X, KF_MASK_CENTER_Y, KF_MASK_SIZE, KF_MASK_FEATHER, KF_MASK_ROTATION,
]

CANVAS_RATIOS: dict[str, tuple[int, int]] = {
    "original": (1920, 1080),
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:3": (1440, 1080),
    "3:4": (1080, 1440),
    "2:1": (2160, 1080),
    "2.35:1": (2538, 1080),
    "1.85:1": (1998, 1080),
    "21:9": (2520, 1080),
}

# --------------------------------------------------------------------------- #
# Small value objects
# --------------------------------------------------------------------------- #


@dataclass
class TimeRange:
    start: int = 0
    duration: int = 0

    @property
    def end(self) -> int:
        return self.start + self.duration

    def contains(self, t: int) -> bool:
        return self.start <= t < self.end

    def overlaps(self, other: "TimeRange") -> bool:
        return self.start < other.end and other.start < self.end

    def copy(self) -> "TimeRange":
        return TimeRange(self.start, self.duration)


@dataclass
class Transform:
    x: float = 0.0            # normalised, [-1, 1] == canvas width
    y: float = 0.0            # normalised, positive up
    scale_x: float = 1.0
    scale_y: float = 1.0
    uniform_scale: bool = True
    rotation: float = 0.0     # degrees, clockwise
    flip_h: bool = False
    flip_v: bool = False
    alpha: float = 1.0        # opacity 0..1


@dataclass
class Keyframe:
    time_offset: int          # µs relative to segment target start
    value: float
    curve: str = "Line"       # Line | EaseIn | EaseOut | EaseInOut | Bezier
    left_control: tuple[float, float] = (0.0, 0.0)
    right_control: tuple[float, float] = (0.0, 0.0)
    id: str = field(default_factory=new_id)


@dataclass
class KeyframeTrack:
    property: str             # one of KF_* constants
    keyframes: list[Keyframe] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    def sorted(self) -> list[Keyframe]:
        return sorted(self.keyframes, key=lambda k: k.time_offset)

    def value_at(self, t_offset: int, default: float) -> float:
        from .keyframes import interpolate  # local import avoids a cycle
        return interpolate(self, t_offset, default)


@dataclass
class Speed:
    mode: int = 0             # 0 = constant, 1 = curve
    speed: float = 1.0
    curve_name: str = ""
    curve_points: list[tuple[float, float]] = field(default_factory=list)  # (x 0..1, multiplier)
    keep_pitch: bool = True
    frame_blending: str = "none"  # none | frame_blend | optical_flow (metadata only)


@dataclass
class AudioSettings:
    volume: float = 1.0       # linear gain, 0..2 (CapCut shows dB)
    muted: bool = False
    fade_in: int = 0          # µs
    fade_out: int = 0         # µs
    denoise: bool = False
    enhance_voice: bool = False
    normalize_loudness: bool = False
    target_lufs: float = -23.0
    pan: float = 0.0          # -1 .. 1
    pitch_shift: int = 0      # semitones
    channel_fill: str = "none"  # none | left_to_right | right_to_left


@dataclass
class ColorAdjust:
    """Primary colour corrections. All values are normalised -1..1 (0 = neutral)
    except ``vignette``/``sharpen``/``grain`` which are 0..1."""
    brightness: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    exposure: float = 0.0
    highlight: float = 0.0
    shadow: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    hue: float = 0.0
    fade: float = 0.0
    sharpen: float = 0.0
    vignette: float = 0.0
    grain: float = 0.0
    hsl: dict[str, tuple[float, float, float]] = field(default_factory=dict)  # colour -> (hue, sat, lum)
    curves: dict[str, list[tuple[float, float]]] = field(default_factory=dict)  # rgb/r/g/b -> points

    def is_identity(self) -> bool:
        return all(getattr(self, f.name) == 0.0 for f in fields(self)
                   if f.name not in ("hsl", "curves")) and not self.hsl and not self.curves


@dataclass
class FilterSettings:
    name: str = ""            # key in effects.FILTERS; "" = none
    intensity: float = 1.0    # 0..1


@dataclass
class Mask:
    kind: str = "none"        # none | line | mirror | circle | rectangle | heart | star | text | pen
    center_x: float = 0.0     # normalised like Transform
    center_y: float = 0.0
    width: float = 0.5        # fraction of canvas width
    height: float = 0.5
    rotation: float = 0.0
    feather: float = 0.0      # 0..1
    round_corner: float = 0.0
    invert: bool = False
    text: str = ""
    points: list[tuple[float, float]] = field(default_factory=list)  # pen mask polygon

    @property
    def enabled(self) -> bool:
        return self.kind != "none"


@dataclass
class ChromaKey:
    enabled: bool = False
    color: str = "#2DD201"
    intensity: float = 0.2    # tolerance
    shadow: float = 0.0       # edge softness
    auto_removal: bool = False  # AI background removal flag (needs optional model)


@dataclass
class Animation:
    in_name: str = ""         # key in effects.ANIMATIONS_IN
    in_duration: int = 500_000
    out_name: str = ""
    out_duration: int = 500_000
    loop_name: str = ""
    loop_duration: int = 1_000_000
    combo_name: str = ""


@dataclass
class Transition:
    """Transition attached to the *left* clip (applies between it and the next
    clip on the same track)."""
    name: str = "dissolve"    # key in transitions.TRANSITIONS
    duration: int = 500_000
    overlap: bool = True


@dataclass
class EffectInstance:
    name: str                 # key in effects.VIDEO_EFFECTS
    params: dict[str, float] = field(default_factory=dict)
    id: str = field(default_factory=new_id)


@dataclass
class Shadow:
    enabled: bool = False
    color: str = "#000000"
    alpha: float = 0.8
    distance: float = 5.0     # px at 1080p scale
    angle: float = -45.0
    blur: float = 4.0


@dataclass
class TextStyle:
    text: str = "Default text"
    font_family: str = "Segoe UI"
    font_path: str = ""
    size: float = 15.0        # CapCut "font_size" (approx. % of canvas height * 4)
    color: str = "#FFFFFF"
    alpha: float = 1.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    align: int = 1            # 0 left, 1 centre, 2 right
    vertical: bool = False
    letter_spacing: float = 0.0
    line_spacing: float = 0.02
    max_width: float = 0.82   # fraction of canvas width before wrapping
    stroke_width: float = 0.0  # 0..1 (fraction of font size)
    stroke_color: str = "#000000"
    shadow: Shadow = field(default_factory=Shadow)
    background_color: str = "#000000"
    background_alpha: float = 0.0
    background_radius: float = 0.0
    background_style: int = 0  # 0 = block, 1 = per-line
    glow: bool = False
    glow_color: str = "#FFFFFF"
    glow_strength: float = 0.5
    bubble: str = ""          # bubble preset name
    curve: float = 0.0        # curved text strength -1..1
    text_effect: str = ""     # preset text effect name
    bold_width: float = 0.0
    italic_degree: float = 0.0
    is_caption: bool = False  # created by auto/local captions
    words: list[tuple[int, int, str]] = field(default_factory=list)  # (start_us, end_us, word) for karaoke


@dataclass
class StickerStyle:
    kind: str = "emoji"       # emoji | shape | image
    value: str = "⭐"         # emoji char, shape name or image path
    fill_color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: float = 0.0
    shadow: Shadow = field(default_factory=Shadow)


@dataclass
class CanvasBackground:
    kind: str = "color"       # color | blur | image
    color: str = "#000000"
    blur: float = 0.0         # 0..1
    image: str = ""


@dataclass
class Stabilize:
    level: int = 0            # 0 off, 1 minimal crop, 2 recommended, 3 most stable


# --------------------------------------------------------------------------- #
# Materials
# --------------------------------------------------------------------------- #


@dataclass
class Material:
    """A media asset or a generated asset (text, sticker...)."""
    kind: MaterialKind
    id: str = field(default_factory=new_id)
    name: str = ""
    path: str = ""            # absolute file path for media
    duration: int = 0         # µs (photos: 0 = still)
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    has_video: bool = True
    codec: str = ""
    audio_codec: str = ""
    sample_rate: int = 0
    channels: int = 0
    size_bytes: int = 0
    rotation: int = 0         # container rotation metadata
    thumbnail: str = ""       # cached thumbnail path
    proxy_path: str = ""
    color_tag: str = ""
    folder: str = ""          # virtual folder in the media panel
    import_time: float = field(default_factory=time.time)
    capcut_local_id: str = "" # draft_meta_info.draft_materials id (round-trip)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_still(self) -> bool:
        return self.kind in (MaterialKind.PHOTO, MaterialKind.COLOR, MaterialKind.TEXT,
                             MaterialKind.STICKER, MaterialKind.EFFECT, MaterialKind.FILTER,
                             MaterialKind.ADJUST)

    @property
    def is_visual(self) -> bool:
        return self.kind != MaterialKind.AUDIO


# --------------------------------------------------------------------------- #
# Segments and tracks
# --------------------------------------------------------------------------- #


@dataclass
class Segment:
    material_id: str
    target: TimeRange = field(default_factory=TimeRange)
    source: TimeRange | None = None   # None for generated materials (text, stickers...)
    id: str = field(default_factory=new_id)
    name: str = ""
    transform: Transform = field(default_factory=Transform)
    speed: Speed = field(default_factory=Speed)
    audio: AudioSettings = field(default_factory=AudioSettings)
    adjust: ColorAdjust = field(default_factory=ColorAdjust)
    filter: FilterSettings = field(default_factory=FilterSettings)
    mask: Mask = field(default_factory=Mask)
    chroma: ChromaKey = field(default_factory=ChromaKey)
    animation: Animation = field(default_factory=Animation)
    transition: Transition | None = None
    effects: list[EffectInstance] = field(default_factory=list)
    keyframes: list[KeyframeTrack] = field(default_factory=list)
    blend_mode: str = "normal"
    canvas: CanvasBackground = field(default_factory=CanvasBackground)
    stabilize: Stabilize = field(default_factory=Stabilize)
    text: TextStyle | None = None
    sticker: StickerStyle | None = None
    crop: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)  # left, top, right, bottom (fractions)
    crop_ratio: str = "free"
    reverse: bool = False
    freeze: bool = False
    visible: bool = True
    locked: bool = False
    color_tag: str = ""
    group_id: str = ""
    render_index: int = 0
    is_placeholder: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    # -- time helpers -------------------------------------------------------
    @property
    def start(self) -> int:
        return self.target.start

    @start.setter
    def start(self, value: int) -> None:
        self.target.start = int(value)

    @property
    def duration(self) -> int:
        return self.target.duration

    @duration.setter
    def duration(self, value: int) -> None:
        self.target.duration = int(value)

    @property
    def end(self) -> int:
        return self.target.end

    def source_time_at(self, timeline_t: int) -> int:
        """Map an absolute timeline time to a source media time (µs)."""
        offset = max(0, min(timeline_t - self.target.start, self.target.duration))
        if self.freeze and self.source is not None:
            return self.source.start
        if self.source is None:
            return offset
        if self.speed.mode == 1 and self.speed.curve_points:
            from .speed import curve_source_offset
            src_off = curve_source_offset(self.speed.curve_points, offset, self.target.duration,
                                          self.source.duration)
        else:
            src_off = int(offset * self.speed.speed)
        if self.reverse:
            return self.source.end - 1 - src_off
        return self.source.start + src_off

    def keyframe_track(self, prop: str, create: bool = False) -> KeyframeTrack | None:
        for kt in self.keyframes:
            if kt.property == prop:
                return kt
        if create:
            kt = KeyframeTrack(property=prop)
            self.keyframes.append(kt)
            return kt
        return None

    def has_keyframes(self) -> bool:
        return any(kt.keyframes for kt in self.keyframes)

    def animated_value(self, prop: str, timeline_t: int, default: float) -> float:
        kt = self.keyframe_track(prop)
        if kt is None or not kt.keyframes:
            return default
        return kt.value_at(timeline_t - self.target.start, default)

    def clone(self, new_ids: bool = True) -> "Segment":
        seg = copy.deepcopy(self)
        if new_ids:
            seg.id = new_id()
            for kt in seg.keyframes:
                kt.id = new_id()
                for k in kt.keyframes:
                    k.id = new_id()
            for fx in seg.effects:
                fx.id = new_id()
        return seg


@dataclass
class Track:
    kind: TrackKind
    id: str = field(default_factory=new_id)
    name: str = ""
    segments: list[Segment] = field(default_factory=list)
    muted: bool = False
    locked: bool = False
    hidden: bool = False
    is_main: bool = False     # the magnetic main video track
    height: int = 0           # 0 = default for kind
    color: str = ""

    def sort(self) -> None:
        self.segments.sort(key=lambda s: s.target.start)

    def segment_at(self, t: int) -> Segment | None:
        for s in self.segments:
            if s.target.contains(t):
                return s
        return None

    def next_segment(self, seg: Segment) -> Segment | None:
        self.sort()
        idx = self.segments.index(seg)
        return self.segments[idx + 1] if idx + 1 < len(self.segments) else None

    def prev_segment(self, seg: Segment) -> Segment | None:
        self.sort()
        idx = self.segments.index(seg)
        return self.segments[idx - 1] if idx > 0 else None

    def free_space(self, start: int, duration: int, ignore: set[str] | None = None) -> bool:
        rng = TimeRange(start, duration)
        for s in self.segments:
            if ignore and s.id in ignore:
                continue
            if s.target.overlaps(rng):
                return False
        return True

    @property
    def end(self) -> int:
        return max((s.end for s in self.segments), default=0)

    def accepts(self, kind: MaterialKind) -> bool:
        return kind in TRACK_ACCEPTS[self.kind]


@dataclass
class Marker:
    time: int
    name: str = ""
    color: str = "#FF6B6B"
    id: str = field(default_factory=new_id)


# --------------------------------------------------------------------------- #
# Project
# --------------------------------------------------------------------------- #


@dataclass
class Project:
    name: str = "Untitled"
    id: str = field(default_factory=new_id)
    path: str = ""            # project folder (PyCut or CapCut draft folder)
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    ratio: str = "original"   # key of CANVAS_RATIOS
    background_color: str = "#000000"
    materials: dict[str, Material] = field(default_factory=dict)
    tracks: list[Track] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    modified: float = field(default_factory=time.time)
    image_duration: int = 5 * US  # default still-image duration
    cover_path: str = ""
    capcut_version: str = ""  # "new_version" when imported from CapCut
    source_format: str = "pycut"  # pycut | capcut
    media_folders: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    # -- construction --------------------------------------------------------
    @staticmethod
    def new(name: str = "Untitled", fps: float = 30.0, ratio: str = "16:9") -> "Project":
        w, h = CANVAS_RATIOS.get(ratio, (1920, 1080))
        p = Project(name=name, fps=fps, width=w, height=h, ratio=ratio)
        p.tracks.append(Track(kind=TrackKind.VIDEO, is_main=True, name="Main"))
        return p

    # -- queries -------------------------------------------------------------
    @property
    def duration(self) -> int:
        return max((t.end for t in self.tracks), default=0)

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 16 / 9

    def main_track(self) -> Track | None:
        for t in self.tracks:
            if t.is_main:
                return t
        for t in self.tracks:
            if t.kind == TrackKind.VIDEO:
                t.is_main = True
                return t
        return None

    def track_by_id(self, tid: str) -> Track | None:
        return next((t for t in self.tracks if t.id == tid), None)

    def find_segment(self, sid: str) -> tuple[Track, Segment] | None:
        for t in self.tracks:
            for s in t.segments:
                if s.id == sid:
                    return t, s
        return None

    def track_of(self, seg: Segment) -> Track | None:
        for t in self.tracks:
            if seg in t.segments:
                return t
        return None

    def iter_segments(self) -> Iterator[tuple[Track, Segment]]:
        for t in self.tracks:
            for s in t.segments:
                yield t, s

    def material_of(self, seg: Segment) -> Material | None:
        return self.materials.get(seg.material_id)

    def add_material(self, mat: Material) -> Material:
        self.materials[mat.id] = mat
        return mat

    def material_in_use(self, mid: str) -> bool:
        return any(s.material_id == mid for _, s in self.iter_segments())

    def add_track(self, kind: TrackKind, index: int | None = None) -> Track:
        tr = Track(kind=kind)
        if index is None:
            self.tracks.append(tr)
        else:
            self.tracks.insert(index, tr)
        return tr

    def remove_empty_tracks(self, keep_main: bool = True) -> None:
        self.tracks = [t for t in self.tracks if t.segments or (keep_main and t.is_main)]

    def set_ratio(self, ratio: str) -> None:
        self.ratio = ratio
        if ratio in CANVAS_RATIOS and ratio != "original":
            self.width, self.height = CANVAS_RATIOS[ratio]

    def touch(self) -> None:
        self.modified = time.time()

    def segments_at(self, t: int, visual_only: bool = False) -> list[tuple[Track, Segment]]:
        """Segments active at ``t`` ordered bottom → top (render order)."""
        out: list[tuple[Track, Segment]] = []
        for tr in self.tracks:
            if tr.hidden:
                continue
            if visual_only and tr.kind == TrackKind.AUDIO:
                continue
            s = tr.segment_at(t)
            if s is not None and s.visible:
                out.append((tr, s))
        return out


# --------------------------------------------------------------------------- #
# (De)serialisation of the native PyCut format
# --------------------------------------------------------------------------- #

_ENUM_FIELDS = {"kind"}


def to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        out = {}
        for f in fields(obj):
            out[f.name] = to_dict(getattr(obj, f.name))
        return out
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    return obj


def _build(cls: Any, data: Any) -> Any:
    """Recursively build a dataclass from ``data`` (tolerant to missing/extra keys)."""
    import typing

    if data is None:
        return None
    if not is_dataclass(cls):
        return data
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        val = data[f.name]
        hint = hints.get(f.name)
        kwargs[f.name] = _coerce(hint, val)
    return cls(**kwargs)


def _coerce(hint: Any, val: Any) -> Any:
    import types
    import typing

    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin is typing.Union or origin is types.UnionType:
        non_none = [a for a in args if a is not type(None)]
        if val is None:
            return None
        return _coerce(non_none[0], val)
    if origin is list:
        inner = args[0] if args else Any
        return [_coerce(inner, v) for v in val]
    if origin is tuple:
        return tuple(val)
    if origin is dict:
        kt, vt = args if args else (Any, Any)
        return {k: _coerce(vt, v) for k, v in val.items()}
    if isinstance(hint, type) and issubclass(hint, Enum):
        return hint(val)
    if is_dataclass(hint):
        return _build(hint, val)
    return val


def project_to_dict(project: Project) -> dict:
    d = to_dict(project)
    d["format"] = "pycut-project"
    d["format_version"] = 1
    return d


def project_from_dict(d: dict) -> Project:
    d = dict(d)
    d.pop("format", None)
    d.pop("format_version", None)
    p: Project = _build(Project, d)
    for t in p.tracks:
        t.sort()
    return p


def new_text_material(name: str = "Text") -> Material:
    return Material(kind=MaterialKind.TEXT, name=name)


def new_text_segment(project: Project, text: str = "Default text", start: int = 0,
                     duration: int = 3 * US) -> Segment:
    mat = project.add_material(new_text_material())
    seg = Segment(material_id=mat.id, target=TimeRange(start, duration), source=None,
                  text=TextStyle(text=text), render_index=14000)
    seg.name = text
    return seg
