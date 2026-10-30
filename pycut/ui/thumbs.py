"""Thumbnail cache (first frame of videos, images). Returns QPixmap scaled to a fixed height."""
from __future__ import annotations

import cv2
from PySide6.QtGui import QImage, QPixmap

from ..core.model import Material, MaterialKind


class ThumbCache:
    def __init__(self, height: int = 116) -> None:
        self.h = height
        self._c: dict[str, QPixmap | None] = {}

    def get(self, m: Material) -> QPixmap | None:
        key = m.path or m.id
        if key in self._c:
            return self._c[key]
        pm = None
        try:
            if m.kind == MaterialKind.PHOTO or m.kind == MaterialKind.GIF and False:
                img = QImage(m.path)
                if not img.isNull():
                    pm = QPixmap.fromImage(img.scaledToHeight(self.h))
            elif m.kind in (MaterialKind.VIDEO, MaterialKind.GIF):
                cap = cv2.VideoCapture(m.path)
                ok, frame = cap.read()
                cap.release()
                if ok:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w = rgb.shape[:2]
                    img = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()
                    pm = QPixmap.fromImage(img.scaledToHeight(self.h))
        except Exception:
            pm = None
        self._c[key] = pm
        return pm
