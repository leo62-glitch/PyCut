"""Frame compositor used by the preview player and the video export.

``Compositor.render(project, t_us, w, h)`` returns a ``QImage`` of the canvas at time ``t_us``.
Video frames come from OpenCV (``FrameSource``), text is drawn with QPainter.
Supported: transform (position/scale/rotation/flip/opacity) with keyframes, crop, reverse/speed,
brightness/contrast/saturation, text style (colour, stroke, shadow, background, alignment).
Not yet: masks, chroma key, effects, filters, transitions, animations, blend modes.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from ..core.model import (
    KF_ALPHA, KF_POSITION_X, KF_POSITION_Y, KF_ROTATION, KF_SCALE_X, KF_SCALE_Y, MaterialKind, Project,
    Segment, TrackKind,
)
from ..core.timebase import US


class FrameSource:
    """Keeps one ``cv2.VideoCapture`` per file and reads frames, sequentially when possible."""

    def __init__(self) -> None:
        self._caps: dict[str, tuple[cv2.VideoCapture, int, float]] = {}
        self._stills: dict[str, QImage] = {}
        self._last: dict[str, tuple[int, np.ndarray]] = {}

    def close(self) -> None:
        for cap, _, _ in self._caps.values():
            cap.release()
        self._caps.clear()
        self._last.clear()

    def still(self, path: str) -> QImage | None:
        if path not in self._stills:
            img = QImage(path)
            self._stills[path] = img if not img.isNull() else None
        return self._stills[path]

    def video_frame(self, path: str, t_us: int) -> np.ndarray | None:
        entry = self._caps.get(path)
        if entry is None:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                self._caps[path] = (cap, -2, 30.0)
                return None
            self._caps[path] = entry = (cap, -1, cap.get(cv2.CAP_PROP_FPS) or 30.0)
        cap, last_idx, fps = entry
        if not cap.isOpened():
            return None
        idx = max(0, int(round(t_us * fps / US)))
        cached = self._last.get(path)
        if cached and cached[0] == idx:
            return cached[1]
        if idx != last_idx + 1:
            if 0 < idx - last_idx <= 6:           # short forward jump: just read ahead
                for _ in range(idx - last_idx - 1):
                    cap.read()
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            return cached[1] if cached else None
        self._caps[path] = (cap, idx, fps)
        self._last[path] = (idx, frame)
        return frame


def _np_to_qimage(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a)
    h, w = a.shape[:2]
    return QImage(a.data, w, h, a.strides[0], QImage.Format_BGR888).copy()


def _adjust(frame: np.ndarray, seg: Segment) -> np.ndarray:
    adj = seg.adjust
    if adj.is_identity():
        return frame
    out = frame.astype(np.float32)
    out += adj.brightness * 2.0 + adj.exposure * 1.5
    out = (out - 128.0) * (1.0 + adj.contrast / 100.0) + 128.0 if abs(adj.contrast) > 1 else out
    if abs(adj.saturation) > 0.5:
        gray = out.mean(axis=2, keepdims=True)
        out = gray + (out - gray) * (1.0 + adj.saturation / 100.0)
    return np.clip(out, 0, 255).astype(np.uint8)


class Compositor:
    def __init__(self) -> None:
        self.source = FrameSource()

    def close(self) -> None:
        self.source.close()

    # -- main entry ---------------------------------------------------------------
    def render(self, project: Project, t_us: int, width: int, height: int) -> QImage:
        img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(project.background_color))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for tr, seg in project.segments_at(t_us, visual_only=True):
            mat = project.material_of(seg)
            if mat is None:
                continue
            alpha = seg.animated_value(KF_ALPHA, t_us, seg.transform.alpha)
            if mat.kind == MaterialKind.TEXT and seg.text:
                self._draw_text(p, seg, t_us, width, height, alpha)
            elif mat.kind in (MaterialKind.VIDEO, MaterialKind.PHOTO, MaterialKind.GIF):
                self._draw_media(p, project, seg, mat, t_us, width, height, alpha)
        p.end()
        return img

    # -- helpers ---------------------------------------------------------------
    def _place(self, p: QPainter, seg: Segment, t_us: int, w: int, h: int) -> tuple[float, float]:
        tf = seg.transform
        x = seg.animated_value(KF_POSITION_X, t_us, tf.x)
        y = seg.animated_value(KF_POSITION_Y, t_us, tf.y)
        sx = seg.animated_value(KF_SCALE_X, t_us, tf.scale_x)
        sy = sx if tf.uniform_scale else seg.animated_value(KF_SCALE_Y, t_us, tf.scale_y)
        rot = seg.animated_value(KF_ROTATION, t_us, tf.rotation)
        p.translate(w / 2 + x * w / 2, h / 2 - y * h / 2)
        p.rotate(rot)
        p.scale(sx * (-1 if tf.flip_h else 1), sy * (-1 if tf.flip_v else 1))
        return sx, sy

    def _draw_media(self, p, project, seg, mat, t_us, w, h, alpha) -> None:
        if mat.kind == MaterialKind.PHOTO:
            qi = self.source.still(mat.path)
        else:
            frame = self.source.video_frame(mat.path, seg.source_time_at(t_us))
            if frame is None:
                return
            qi = _np_to_qimage(_adjust(frame, seg))
        if qi is None:
            return
        cl, ct, cr, cb = seg.crop
        if (cl, ct, cr, cb) != (0.0, 0.0, 1.0, 1.0):
            qi = qi.copy(int(cl * qi.width()), int(ct * qi.height()), max(1, int((cr - cl) * qi.width())),
                         max(1, int((cb - ct) * qi.height())))
        fit = min(w / qi.width(), h / qi.height())
        dw, dh = qi.width() * fit, qi.height() * fit
        p.save()
        p.setOpacity(max(0.0, min(1.0, alpha)))
        self._place(p, seg, t_us, w, h)
        p.drawImage(QRectF(-dw / 2, -dh / 2, dw, dh), qi)
        p.restore()

    def _draw_text(self, p, seg, t_us, w, h, alpha) -> None:
        ts = seg.text
        if not ts.text:
            return
        px = max(4.0, ts.size * 4 * h / 1080)
        font = QFont(ts.font_family or "Segoe UI")
        font.setPixelSize(int(px))
        font.setBold(ts.bold)
        font.setItalic(ts.italic)
        font.setUnderline(ts.underline)
        font.setLetterSpacing(QFont.AbsoluteSpacing, ts.letter_spacing)
        max_w = max(40.0, ts.max_width * w)
        fm = QFontMetricsF(font)
        flags = Qt.TextWordWrap | {0: Qt.AlignLeft, 1: Qt.AlignHCenter, 2: Qt.AlignRight}.get(ts.align, Qt.AlignHCenter)
        rect = fm.boundingRect(QRectF(0, 0, max_w, 10_000), int(flags), ts.text)
        rect.moveCenter(QPointF(0, 0))
        p.save()
        p.setOpacity(max(0.0, min(1.0, alpha * ts.alpha)))
        self._place(p, seg, t_us, w, h)
        if ts.background_alpha > 0:
            bg = QColor(ts.background_color)
            bg.setAlphaF(ts.background_alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            m = px * 0.25
            p.drawRoundedRect(rect.adjusted(-m, -m * 0.5, m, m * 0.5), ts.background_radius * px, ts.background_radius * px)
        if ts.shadow.enabled:
            sh = QColor(ts.shadow.color)
            sh.setAlphaF(ts.shadow.alpha)
            a = math.radians(ts.shadow.angle)
            d = ts.shadow.distance * h / 1080
            p.setPen(sh)
            p.setFont(font)
            p.drawText(rect.translated(math.cos(a) * d, -math.sin(a) * d), int(flags), ts.text)
        if ts.stroke_width > 0:
            path = QPainterPath()
            lines = fm.boundingRect(rect, int(flags), ts.text)
            path.addText(rect.left(), rect.top() + fm.ascent(), font, ts.text) if "\n" not in ts.text and \
                fm.horizontalAdvance(ts.text) <= max_w else None
            p.setPen(QPen(QColor(ts.stroke_color), ts.stroke_width * px * 0.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
        p.setPen(QColor(ts.color))
        p.setFont(font)
        p.drawText(rect, int(flags), ts.text)
        p.restore()
