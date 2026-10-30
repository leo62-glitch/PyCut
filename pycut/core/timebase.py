"""Time helpers. All timeline times are integers in microseconds (like CapCut drafts)."""
from __future__ import annotations

US = 1_000_000  # microseconds per second


def sec_to_us(seconds: float) -> int:
    return int(round(seconds * US))


def us_to_sec(us: int) -> float:
    return us / US


def frame_duration_us(fps: float) -> int:
    return int(round(US / fps))


def snap_to_frame(us: int, fps: float) -> int:
    fd = US / fps
    return int(round(round(us / fd) * fd))


def us_to_frames(us: int, fps: float) -> int:
    return int(round(us * fps / US))


def frames_to_us(frames: int, fps: float) -> int:
    return int(round(frames * US / fps))


def format_timecode(us: int, fps: float = 30.0, show_frames: bool = True, show_hours: bool = True) -> str:
    """``HH:MM:SS:FF`` (or ``MM:SS:FF``). Negative values are clamped to 0."""
    us = max(0, int(us))
    total_frames = us_to_frames(us, fps)
    fps_i = max(1, int(round(fps)))
    frames = total_frames % fps_i
    total_seconds = total_frames // fps_i
    s = total_seconds % 60
    m = (total_seconds // 60) % 60
    h = total_seconds // 3600
    if show_frames:
        core = f"{m:02d}:{s:02d}:{frames:02d}"
    else:
        core = f"{m:02d}:{s:02d}"
    return f"{h:02d}:{core}" if show_hours else core


def format_duration_short(us: int) -> str:
    """Human-friendly duration used in media thumbnails: ``01:23`` or ``1:02:03``."""
    total = int(round(us / US))
    s = total % 60
    m = (total // 60) % 60
    h = total // 3600
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_timecode(text: str, fps: float = 30.0) -> int | None:
    """Parse ``HH:MM:SS:FF``, ``MM:SS:FF``, ``MM:SS`` or plain seconds into µs."""
    text = text.strip()
    if not text:
        return None
    try:
        if ":" not in text:
            return sec_to_us(float(text.replace(",", ".")))
        parts = [int(p) for p in text.split(":")]
    except ValueError:
        return None
    frames = 0
    if len(parts) == 4:
        h, m, s, frames = parts
    elif len(parts) == 3:
        h, m, s = 0, parts[0], parts[1]
        frames = parts[2]
    elif len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    else:
        return None
    return (h * 3600 + m * 60 + s) * US + frames_to_us(frames, fps)
