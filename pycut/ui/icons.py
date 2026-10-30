"""Original line icons (24x24, stroke based) drawn from simple SVG paths. No third-party assets."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

P = {
    "home": "M4 11l8-7 8 7M6 10v9h12v-9",
    "templates": "M5 5h6v14H5zM14 7l5 1.5-3 11-3-.8",
    "video_studio": "M4 6h16v12H4zM9 10l5 2-5 2z",
    "design": "M5 5h14v14H5zM8 15l3-3 2 2 3-4 2 3",
    "tools": "M5 5h5v5H5zM14 5h5v5h-5zM5 14h5v5H5zM14 14h5v5h-5z",
    "sparkle": "M12 4l1.8 5.2L19 11l-5.2 1.8L12 18l-1.8-5.2L5 11l5.2-1.8z",
    "marketing": "M7 5h10v14H7zM10 9h4M10 13h4",
    "library": "M4 7h6l2 2h8v10H4z",
    "plus": "M12 5v14M5 12h14",
    "chevron_down": "M6 9l6 6 6-6",
    "chevron_up": "M6 15l6-6 6 6",
    "chevron_right": "M9 6l6 6-6 6",
    "close": "M6 6l12 12M18 6L6 18",
    "search": "M11 5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM16 16l4 4",
    "trash": "M5 7h14M9 7V5h6v2M7 7l1 12h8l1-12M10 11v5M14 11v5",
    "grid": "M5 5h6v6H5zM13 5h6v6h-6zM5 13h6v6H5zM13 13h6v6h-6z",
    "cloud": "M7 17a4 4 0 0 1 0-8 5 5 0 0 1 9.5 1A3.5 3.5 0 0 1 16 17z",
    "menu": "M5 7h14M5 12h14M5 17h14",
    "undo": "M9 8L5 12l4 4M5 12h9a5 5 0 0 1 0 10",
    "redo": "M15 8l4 4-4 4M19 12h-9a5 5 0 0 0 0 10",
    "split": "M12 4v16M6 8h4v8H6zM14 8h4v8h-4z",
    "trim_l": "M10 4v16M10 12h10M14 8l-4 4 4 4",
    "trim_r": "M14 4v16M14 12H4M10 8l4 4-4 4",
    "delete": "M6 7h12M9 7V5h6v2M8 7l1 12h6l1-12",
    "shield": "M12 4l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V7z",
    "select": "M7 4l10 8-5 1 3 6-2 1-3-6-3 3z",
    "mic": "M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3zM6 12a6 6 0 0 0 12 0M12 18v3",
    "magnet": "M6 4v8a6 6 0 0 0 12 0V4h-4v8a2 2 0 0 1-4 0V4z",
    "snap": "M4 12h6M14 12h6M12 5v14M9 9l-3 3 3 3M15 9l3 3-3 3",
    "link": "M10 14a4 4 0 0 0 5.6 0l3-3a4 4 0 0 0-5.6-5.6l-1 1M14 10a4 4 0 0 0-5.6 0l-3 3A4 4 0 0 0 11 18.6l1-1",
    "zoom_in": "M11 5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM16 16l4 4M9 11h4M11 9v4",
    "zoom_out": "M11 5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM16 16l4 4M9 11h4",
    "fit": "M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4M9 12h6",
    "play": "M8 5l11 7-11 7z",
    "pause": "M8 5v14M16 5v14",
    "fullscreen": "M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5",
    "ratio": "M5 7h14v10H5z",
    "crop": "M7 3v14h14M3 7h14v14",
    "multimedia": "M5 6h14v12H5zM10 9.5l4.5 2.5-4.5 2.5z",
    "sound": "M9 18V6l10-2v12M9 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0zM19 16a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z",
    "text": "M5 6h14M12 6v13M9 19h6",
    "sticker": "M12 4a8 8 0 1 0 8 8 4 4 0 0 1-4-4 4 4 0 0 1-4-4zM9 12h.01M13 15c1 .6 2 .6 3 0",
    "effects": "M12 4l2 5 5 .5-4 3.5 1.5 5-4.5-3-4.5 3L9 13 5 9.500l5-.5z",
    "transitions": "M5 6l7 6-7 6zM19 6l-7 6 7 6z",
    "captions": "M5 6h14v10H9l-4 3zM8 10h8M8 13h5",
    "filters": "M12 4a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM8 14a5 5 0 1 0 8 0",
    "adjust": "M5 8h8M17 8h2M5 16h2M11 16h8M15 6v4M9 14v4",
    "models": "M5 7h14v12H5zM9 7V4h6v3",
    "avatar": "M12 5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM5 19a7 7 0 0 1 14 0",
    "generate": "M5 5h9M5 5v14h14v-9M17 4v6M14 7h6",
    "record": "M4 7h11v10H4zM15 11l5-3v8l-5-3z",
    "share": "M12 15V4M8 8l4-4 4 4M5 14v6h14v-6",
    "export": "M12 4v11M8 11l4 4 4-4M5 19h14",
    "folder": "M4 7h6l2 2h8v9H4z",
    "image": "M4 5h16v14H4zM8 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM4 17l5-5 4 4 3-3 4 4",
    "edit": "M5 19l1-4 9-9 3 3-9 9zM14 7l3 3",
    "lock": "M7 11h10v8H7zM9 11V8a3 3 0 0 1 6 0v3",
    "unlock": "M7 11h10v8H7zM9 11V8a3 3 0 0 1 5.5-1.5",
    "eye": "M3 12s3.5-6 9-6 9 6 9 6-3.500 6-9 6-9-6-9-6zM12 9.500a2.500 2.500 0 1 0 0 5 2.500 2.500 0 0 0 0-5z",
    "eye_off": "M4 5l16 14M9 7a8 8 0 0 1 3-1c5.500 0 9 6 9 6a15 15 0 0 1-3 3.500M6 9c-2 1.500-3 3-3 3s3.500 6 9 6c1 0 2-.2 3-.6",
    "volume": "M5 10v4h3l5 4V6l-5 4zM16 9a4 4 0 0 1 0 6",
    "mute": "M5 10v4h3l5 4V6l-5 4zM16 9l5 6M21 9l-5 6",
    "video": "M4 7h11v10H4zM15 11l5-3v8l-5-3z",
    "audio": "M8 8v8M12 5v14M16 8v8M4 11v2M20 11v2",
    "logo": "M5 7l7-3 7 3-7 3zM5 11l7 3 7-3M5 15l7 3 7-3",
    "reverse": "M5 9h11a3 3 0 0 1 0 6H8M8 6L5 9l3 3",
    "copy": "M8 8h10v11H8zM6 16V5h9",
    "freeze": "M12 3v18M5.500 7.500l13 9M18.500 7.500l-13 9",
    "settings": "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 3v3M12 18v3M3 12h3M18 12h3M5.600 5.600l2 2M16.400 16.400l2 2M5.600 18.400l2-2M16.400 7.600l2-2",
    "help": "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM9.500 9.500a2.500 2.500 0 1 1 3.500 2.300c-.7.400-1 .9-1 1.700M12 17h.01",
    "info": "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 11v5M12 8h.01",
    "upload": "M12 16V5M8 9l4-4 4 4M5 15v4h14v-4",
    "send": "M5 12l14-7-5 14-2-6z",
    "minimize": "M6 12h12",
    "maximize": "M6 6h12v12H6z",
}


@lru_cache(maxsize=2048)
def pixmap(name: str, color: str = "#E1E1E1", size: int = 20, width: float = 1.7, fill: bool = False) -> QPixmap:
    path = P.get(name, P["plus"])
    fill_attr = color if fill else "none"
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill_attr}" stroke="{color}" '
           f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"><path d="{path}"/></svg>')
    scale = 2
    img = QImage(size * scale, size * scale, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size * scale, size * scale))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(scale)
    return pm


def icon(name: str, color: str = "#E1E1E1", size: int = 20, **kw) -> QIcon:
    return QIcon(pixmap(name, color, size, **kw))
