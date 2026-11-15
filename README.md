# PyCut (REA Claude Fable)

A desktop video editor inspired by CapCut, written in 100% Python (PySide6 + OpenCV). Independent project, not affiliated with CapCut/ByteDance.

## Run (Windows)
```powershell
cd PyCut
pip install PySide6 numpy opencv-python
python run.py
```
Optional: install **ffmpeg** (in the PATH) to get audio in exports and more accurate media info.
`python run.py "<PyCut project folder or CapCut draft>"` opens a project directly.

## What works
- Home: project creation, list of your PyCut projects **and of your CapCut drafts** (read-only, opening = imported copy)
- Editor: media library (import, drag and drop), player (frame-by-frame preview, playback), full timeline
  (move, trim, split, duplicate, copy/paste, overlays, text/audio tracks, snapping, zoom, markers),
  inspector (position, scale, rotation, opacity, volume, fades, speed, reverse, colour adjustments, text)
- Undo/Redo, autosave, MP4 video export, CapCut draft export/import
- Shortcuts: Space, Ctrl+Z / Ctrl+Shift+Z, Ctrl+B (split), Delete, Ctrl+C/V/D, ←/→ (frame), Home/End, Q/W (trim), S (snap), M (marker), Ctrl+E, Ctrl+S

## Not yet (shown as "coming soon")
Transitions, effects, filters, masks, chroma key, stickers, auto captions, animations, AI features, microphone recording,
audio playback in the preview (audio is only mixed at export), real waveforms.

## CapCut drafts
```
python tools/capcut_check.py            # tests import/export on ALL your drafts (read-only)
python tools/capcut_check.py "<draft folder>"
```
Menu → File → *Export to a CapCut draft…* (close CapCut first). CapCut store items (transitions, effects,
masks…) are preserved as-is on import but cannot be created from PyCut; they are reported on export.

## Tests
`pip install pytest && python -m pytest -q` (23 tests, including offscreen UI tests)
