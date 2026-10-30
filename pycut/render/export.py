"""Video export through the compositor (OpenCV VideoWriter, H.264/mp4v). Audio is added with ffmpeg if installed."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PySide6.QtGui import QImage

from ..core.model import MaterialKind, Project, TrackKind
from ..core.timebase import US
from .preview import Compositor

RESOLUTIONS = {"480p": 480, "720p": 720, "1080p": 1080, "2K": 1440, "4K": 2160}


def export_size(project: Project, short_side: int) -> tuple[int, int]:
    w, h = project.width, project.height
    k = short_side / min(w, h)
    return int(round(w * k / 2)) * 2, int(round(h * k / 2)) * 2


def _qimage_to_bgr(img) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_BGR888)
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8, img.height() * img.bytesPerLine()).reshape(img.height(), img.bytesPerLine())
    return arr[:, : img.width() * 3].reshape(img.height(), img.width(), 3).copy()


def audio_command(project: Project, video: str, out: str, ffmpeg: str) -> list[str] | None:
    """ffmpeg command mixing every audible segment (volume, trim, speed, delay) over the silent video."""
    inputs, filters, labels = [], [], []
    for tr, seg in project.iter_segments():
        mat = project.material_of(seg)
        if mat is None or tr.muted or seg.audio.muted or not mat.has_audio or seg.source is None:
            continue
        if mat.kind not in (MaterialKind.AUDIO, MaterialKind.VIDEO):
            continue
        i = len(inputs)
        inputs += ["-i", mat.path]
        s, d = seg.source.start / US, seg.source.duration / US
        chain = f"[{i + 1}:a]atrim=start={s:.4f}:duration={d:.4f},asetpts=PTS-STARTPTS"
        sp = seg.speed.speed if seg.speed.mode == 0 else 1.0
        while sp > 2.0:
            chain += ",atempo=2.0"; sp /= 2.0
        while sp < 0.5:
            chain += ",atempo=0.5"; sp /= 0.5
        if abs(sp - 1.0) > 1e-3:
            chain += f",atempo={sp:.4f}"
        if seg.reverse:
            chain += ",areverse"
        chain += f",volume={seg.audio.volume:.3f}"
        if seg.audio.fade_in:
            chain += f",afade=t=in:d={seg.audio.fade_in / US:.3f}"
        if seg.audio.fade_out:
            chain += f",afade=t=out:st={max(0, seg.duration - seg.audio.fade_out) / US:.3f}:d={seg.audio.fade_out / US:.3f}"
        ms = int(seg.start / 1000)
        chain += f",adelay={ms}|{ms}[a{i}]"
        filters.append(chain)
        labels.append(f"[a{i}]")
    if not labels:
        return None
    mix = "".join(labels) + f"amix=inputs={len(labels)}:normalize=0[aout]"
    return [ffmpeg, "-y", "-i", video, *inputs, "-filter_complex", ";".join(filters + [mix]), "-map", "0:v",
            "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out]


def export_video(project: Project, out_path: str, short_side: int = 1080, fps: float | None = None,
                 progress: Callable[[float], bool] | None = None) -> str:
    """Render the project to ``out_path``. ``progress(frac)`` returns False to cancel. Returns notes."""
    fps = fps or project.fps
    w, h = export_size(project, short_side)
    total = max(1, int(round(project.duration * fps / US)))
    comp = Compositor()
    tmp = Path(tempfile.mkdtemp()) / "video.mp4"
    writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        raise RuntimeError("Impossible de créer le fichier vidéo")
    try:
        for i in range(total):
            frame = comp.render(project, int(i * US / fps), w, h)
            writer.write(_qimage_to_bgr(frame))
            if progress and i % 3 == 0 and progress(i / total) is False:
                writer.release()
                return "annulé"
    finally:
        writer.release()
        comp.close()
    ffmpeg = shutil.which("ffmpeg")
    note = ""
    if ffmpeg:
        cmd = audio_command(project, str(tmp), out_path, ffmpeg)
        if cmd and subprocess.run(cmd, capture_output=True).returncode == 0:
            return "ok (vidéo + audio)"
        if not cmd:
            shutil.move(str(tmp), out_path)
            return "ok (aucun son)"
        note = "mixage audio échoué, vidéo sans son"
    else:
        note = "ffmpeg introuvable : vidéo sans son (installez ffmpeg pour l'audio)"
    shutil.move(str(tmp), out_path)
    return "ok — " + note
