"""Test the CapCut importer/exporter on your real drafts (read-only on CapCut's folder).

    python tools/capcut_check.py                      # check every draft in the default CapCut folder
    python tools/capcut_check.py "C:/.../0529"        # check one draft folder
    python tools/capcut_check.py --export-to out_dir  # also write re-exported drafts to out_dir

For each draft: import -> export to a temp folder -> verify that every reference resolves,
durations match and segment timings survive. Nothing is ever written inside CapCut's folder.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pycut.io.capcut import export_draft, read_draft  # noqa: E402

DEFAULT_ROOT = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut/User Data/Projects/com.lveditor.draft"


def check(folder: Path, out_root: Path) -> list[str]:
    errs: list[str] = []
    p = read_draft(folder)
    out, warns = export_draft(p, out_root, folder.name, update_root_index=False)
    doc = json.loads((out / "draft_content.json").read_text(encoding="utf-8"))
    ids = {o["id"] for lst in doc["materials"].values() for o in lst}
    for tr in doc["tracks"]:
        for s in tr["segments"]:
            for r in [s["material_id"], *s["extra_material_refs"]]:
                if r not in ids:
                    errs.append(f"référence cassée {r}")
    src = json.loads((folder / "draft_content.json").read_text(encoding="utf-8"))
    def timings(d):
        return sorted((t["type"], s["target_timerange"]["start"], s["target_timerange"]["duration"])
                      for t in d["tracks"] for s in t["segments"])
    if timings(src) != timings(doc):
        errs.append("les positions/durées des segments ont changé")
    if src["duration"] != doc["duration"]:
        errs.append(f"durée {src['duration']} -> {doc['duration']}")
    nseg = sum(len(t.segments) for t in p.tracks)
    print(f"{'OK ' if not errs else 'ERR'} {folder.name:<20} {len(p.tracks)} pistes, {nseg} segments"
          + (f", {len(warns)} avertissements" if warns else ""))
    for w in warns:
        print("      ·", w)
    for e in errs:
        print("      !", e)
    return errs


def main(argv):
    export_to = None
    if "--export-to" in argv:
        i = argv.index("--export-to")
        export_to = Path(argv[i + 1])
        del argv[i:i + 2]
    targets = [Path(a) for a in argv[1:]] or sorted(d for d in DEFAULT_ROOT.iterdir()
                                                    if (d / "draft_content.json").exists())
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        out_root = export_to or Path(tmp)
        for t in targets:
            try:
                bad += bool(check(t, out_root))
            except Exception as e:  # report and go on
                bad += 1
                print(f"ERR {t.name}: {type(e).__name__}: {e}")
    print(f"\n{len(targets) - bad}/{len(targets)} brouillons OK")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
