"""Media probing: ffprobe when available, OpenCV / Qt as fallbacks. Also thumbnails."""
from __future__ import annotations

import json
import mimetypes
import shutil
import subprocess
import wave
from pathlib import Path

from .model import Material, MaterialKind
from .timebase import US

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".3gp"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
GIF_EXT = {".gif"}
AUDIO_EXT = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wma"}
MEDIA_FILTER = "Médias (" + " ".join("*" + e for e in sorted(VIDEO_EXT | IMAGE_EXT | GIF_EXT | AUDIO_EXT)) + ")"


def kind_of(path: str) -> MaterialKind | None:
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXT:
        return MaterialKind.VIDEO
    if ext in IMAGE_EXT:
        return MaterialKind.PHOTO
    if ext in GIF_EXT:
        return MaterialKind.GIF
    if ext in AUDIO_EXT:
        return MaterialKind.AUDIO
    return None


def _ffprobe(path: str) -> dict | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                             capture_output=True, text=True, timeout=20)
        return json.loads(out.stdout)
    except Exception:
        return None


def probe(path: str) -> Material | None:
    path = str(Path(path))
    kind = kind_of(path)
    if kind is None or not Path(path).is_file():
        return None
    m = Material(kind=kind, name=Path(path).name, path=path, size_bytes=Path(path).stat().st_size)
    info = _ffprobe(path)
    if info:
        for s in info.get("streams", []):
            if s["codec_type"] == "video" and not m.width:
                m.width, m.height = s.get("width", 0), s.get("height", 0)
                m.codec = s.get("codec_name", "")
                try:
                    a, b = s.get("avg_frame_rate", "0/1").split("/")
                    m.fps = float(a) / float(b) if float(b) else 0.0
                except ValueError:
                    pass
                rot = (s.get("tags") or {}).get("rotate")
                if rot in ("90", "270", "-90"):
                    m.width, m.height = m.height, m.width
            elif s["codec_type"] == "audio":
                m.has_audio = True
                m.audio_codec = s.get("codec_name", "")
                m.sample_rate = int(s.get("sample_rate", 0) or 0)
                m.channels = s.get("channels", 0)
        dur = float(info.get("format", {}).get("duration", 0) or 0)
        m.duration = int(dur * US)
    elif kind in (MaterialKind.VIDEO, MaterialKind.GIF):
        import cv2
        cap = cv2.VideoCapture(path)
        if cap.isOpened():
            m.width, m.height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            m.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            m.duration = int(n / m.fps * US) if m.fps else 0
            m.has_audio = kind == MaterialKind.VIDEO   # unknown without ffprobe: assume yes
        cap.release()
    elif kind == MaterialKind.PHOTO:
        from PySide6.QtGui import QImage
        img = QImage(path)
        m.width, m.height = img.width(), img.height()
    elif kind == MaterialKind.AUDIO:
        m.has_audio, m.has_video = True, False
        if path.lower().endswith(".wav"):
            try:
                with wave.open(path) as w:
                    m.duration = int(w.getnframes() / w.getframerate() * US)
                    m.sample_rate, m.channels = w.getframerate(), w.getnchannels()
            except wave.Error:
                pass
    if kind == MaterialKind.AUDIO:
        m.has_video = False
    if kind == MaterialKind.PHOTO:
        m.duration = 0
    if kind != MaterialKind.PHOTO and m.duration <= 0:
        m.duration = 5 * US
    return m
