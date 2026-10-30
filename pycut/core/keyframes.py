"""Keyframe interpolation (linear + easing + cubic Bézier handles)."""
from __future__ import annotations

from .model import Keyframe, KeyframeTrack

EASINGS = ["Line", "EaseIn", "EaseOut", "EaseInOut", "Bezier"]


def _ease(kind: str, t: float, k0: Keyframe | None = None, k1: Keyframe | None = None) -> float:
    if kind == "EaseIn":
        return t * t * t
    if kind == "EaseOut":
        u = 1 - t
        return 1 - u * u * u
    if kind == "EaseInOut":
        return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2
    if kind == "Bezier" and k0 is not None and k1 is not None:
        # control points stored as normalised (x, y) offsets from each key.
        x1, y1 = k0.right_control
        x2, y2 = k1.left_control
        return _cubic_bezier_y(t, max(0.0, min(1.0, x1)), y1, max(0.0, min(1.0, 1 + x2)), 1 + y2)
    return t


def _cubic_bezier_y(x: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Solve y for x on a CSS-style cubic Bézier (0,0)-(x1,y1)-(x2,y2)-(1,1)."""
    def bez(a: float, b: float, s: float) -> float:
        return 3 * a * (1 - s) ** 2 * s + 3 * b * (1 - s) * s ** 2 + s ** 3

    lo, hi = 0.0, 1.0
    s = x
    for _ in range(24):
        if bez(x1, x2, s) < x:
            lo = s
        else:
            hi = s
        s = (lo + hi) / 2
    return bez(y1, y2, s)


def interpolate(track: KeyframeTrack, t_offset: int, default: float) -> float:
    keys = track.sorted()
    if not keys:
        return default
    if t_offset <= keys[0].time_offset:
        return keys[0].value
    if t_offset >= keys[-1].time_offset:
        return keys[-1].value
    for a, b in zip(keys, keys[1:]):
        if a.time_offset <= t_offset <= b.time_offset:
            span = b.time_offset - a.time_offset
            if span <= 0:
                return b.value
            t = (t_offset - a.time_offset) / span
            t = _ease(a.curve, t, a, b)
            return a.value + (b.value - a.value) * t
    return default


def set_keyframe(track: KeyframeTrack, t_offset: int, value: float, tolerance: int = 1) -> Keyframe:
    """Insert or update a keyframe at ``t_offset``."""
    for k in track.keyframes:
        if abs(k.time_offset - t_offset) <= tolerance:
            k.value = value
            return k
    k = Keyframe(time_offset=t_offset, value=value)
    track.keyframes.append(k)
    track.keyframes.sort(key=lambda x: x.time_offset)
    return k


def remove_keyframe(track: KeyframeTrack, t_offset: int, tolerance: int = 1) -> bool:
    before = len(track.keyframes)
    track.keyframes = [k for k in track.keyframes if abs(k.time_offset - t_offset) > tolerance]
    return len(track.keyframes) != before


def keyframe_times(segment_keyframes: list[KeyframeTrack]) -> list[int]:
    times: set[int] = set()
    for kt in segment_keyframes:
        for k in kt.keyframes:
            times.add(k.time_offset)
    return sorted(times)
