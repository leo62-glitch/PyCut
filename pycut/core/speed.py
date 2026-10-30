"""Speed curves (CapCut "Curve" speed): piecewise-linear multiplier over the
normalised clip duration. Presets mirror CapCut's names."""
from __future__ import annotations

SPEED_CURVE_PRESETS: dict[str, list[tuple[float, float]]] = {
    "custom": [(0.0, 1.0), (0.5, 1.0), (1.0, 1.0)],
    "montage": [(0.0, 1.0), (0.3, 2.5), (0.5, 0.4), (0.7, 2.5), (1.0, 1.0)],
    "hero": [(0.0, 1.0), (0.4, 3.0), (0.5, 0.2), (0.6, 3.0), (1.0, 1.0)],
    "bullet": [(0.0, 3.0), (0.45, 3.0), (0.5, 0.1), (0.55, 3.0), (1.0, 3.0)],
    "jump_cut": [(0.0, 1.0), (0.2, 4.0), (0.4, 1.0), (0.6, 4.0), (0.8, 1.0), (1.0, 4.0)],
    "flash_in": [(0.0, 0.2), (0.3, 3.0), (1.0, 1.0)],
    "flash_out": [(0.0, 1.0), (0.7, 3.0), (1.0, 0.2)],
}


def _integrate(points: list[tuple[float, float]], x: float) -> float:
    """Integral of the multiplier curve from 0 to x (x in 0..1)."""
    pts = sorted(points)
    if not pts:
        return x
    if pts[0][0] > 0:
        pts.insert(0, (0.0, pts[0][1]))
    if pts[-1][0] < 1:
        pts.append((1.0, pts[-1][1]))
    total = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x0:
            break
        xe = min(x, x1)
        if x1 == x0:
            continue
        ye = y0 + (y1 - y0) * (xe - x0) / (x1 - x0)
        total += (y0 + ye) / 2 * (xe - x0)
    return total


def average_speed(points: list[tuple[float, float]]) -> float:
    return max(1e-6, _integrate(points, 1.0))


def curve_source_offset(points: list[tuple[float, float]], target_offset: int,
                        target_duration: int, source_duration: int) -> int:
    """Map a timeline offset inside the clip to a source offset using the curve.

    The curve's x axis is the *timeline* position (0..1). The accumulated
    integral of the multiplier gives the consumed source time, normalised so the
    whole source is consumed over the whole target duration."""
    if target_duration <= 0:
        return 0
    x = max(0.0, min(1.0, target_offset / target_duration))
    consumed = _integrate(points, x) / average_speed(points)
    return int(min(source_duration - 1, max(0, consumed * source_duration)))


def target_duration_for_curve(points: list[tuple[float, float]], source_duration: int) -> int:
    return int(source_duration / average_speed(points))
