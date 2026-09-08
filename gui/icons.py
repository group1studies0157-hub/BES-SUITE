"""
Bridge Engineering Suite — Vector Icon System
═══════════════════════════════════════════════════════════════
Thin-line SVG glyphs rendered in-memory to QIcon/QPixmap (no external
files, razor-sharp at any DPI). Colors default to live theme tokens, so
icons re-tint automatically per theme and per state (success/error/...).

Also keeps the bundled PNG app-tile registry used by the sidebar, top
bar, and Home/Knowledge dashboards.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from gui.styles import COLORS

_STROKE_W = 1.8

# 24×24 grid, stroke-style path data (fill:none, round caps/joins).
_PATHS: dict[str, str] = {
    # Actions
    "spark": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"/>'
             '<path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z"/>',
    "bolt": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    "gear": '<circle cx="12" cy="12" r="3.2"/>'
            '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06'
            'a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51'
            'a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82'
            'a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82'
            'l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3'
            'a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83'
            'l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09'
            'a1.65 1.65 0 0 0-1.51 1z"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
                '<path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
              '<path d="M7 8l5-5 5 5"/><path d="M12 3v12"/>',
    "attach": '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19'
              'a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/>'
           '<circle cx="12" cy="12" r="3"/>',
    "play": '<path d="M7 4.8v14.4a.6.6 0 0 0 .92.5l11.1-7.2a.6.6 0 0 0 0-1L7.92 4.3a.6.6 0 0 0-.92.5z"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>',
    "check": '<path d="M4.5 12.5l5 5 10-11"/>',
    "cross": '<path d="M6 6l12 12"/><path d="M18 6L6 18"/>',
    "warning": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86'
               'a2 2 0 0 0-3.42 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    # Edit / data
    "trash": '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
             '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
             '<path d="M10 11v6"/><path d="M14 11v6"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "edit": '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
            '<path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/>'
            '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    # Domain
    "water": '<path d="M12 2.7s6.5 7 6.5 11.8a6.5 6.5 0 0 1-13 0C5.5 9.7 12 2.7 12 2.7z"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
            '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    "ruler": '<path d="M3 17.2 17.2 3 21 6.8 6.8 21 3 17.2z"/>'
             '<path d="M8 12.2l1.8 1.8"/><path d="M11.2 9l1.8 1.8"/><path d="M14.4 5.8l1.8 1.8"/>',
    "clipboard": '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6'
                 'a2 2 0 0 1 2-2h2"/>'
                 '<rect x="8" y="2" width="8" height="4" rx="1"/>',
    "wave": '<path d="M2 12c1.67-3.5 3.33-3.5 5 0s3.33 3.5 5 0 3.33-3.5 5 0 3.33 3.5 5 0"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>'
                '<path d="M20 4L8.12 15.88"/><path d="M14.47 14.48L20 20"/>'
                '<path d="M8.12 8.12L12 12"/>',
    "map": '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/>'
           '<path d="M9 4v14"/><path d="M15 6v14"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/>',
    "repeat": '<path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/>'
              '<path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
    # Navigation / shell
    "home": '<path d="M3 10.5L12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>'
            '<path d="M9.5 21v-6h5v6"/>',
    "menu": '<path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 3.5V7h-3.5"/>',
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>'
            '<path d="M4 22v-7"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
            '<path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9'
              'a2 2 0 0 1 2 2z"/>',
    "chevron-left": '<path d="M15 18l-6-6 6-6"/>',
    "chevron-right": '<path d="M9 18l6-6-6-6"/>',
    "chevron-up": '<path d="M18 15l-6-6-6 6"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "arrow-right": '<path d="M4 12h16"/><path d="M13 5l7 7-7 7"/>',
    "star": '<path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5L2.5 9.4'
            'l6.6-.9 2.9-6z"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.2"/>'
           '<path d="M10.5 12.5L21 2"/><path d="M15.5 4.5l3 3"/><path d="M18.5 7.5l2.5-2.5"/>',
    # Home redesign extras
    "bell": '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>'
            '<path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    "shield": '<path d="M12 3l7 3v5c0 4.4-3 8-7 10-4-2-7-5.6-7-10V6l7-3z"/>'
              '<path d="M9 12l2 2 4-4"/>',
    "database": '<ellipse cx="12" cy="5.5" rx="7.5" ry="3"/>'
                '<path d="M4.5 5.5v13c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-13"/>'
                '<path d="M4.5 12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3"/>',
    "sun": '<circle cx="12" cy="12" r="4"/>'
           '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2"/>'
           '<path d="M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/>'
            '<path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
    "external": '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
                '<path d="M15 3h6v6"/><path d="M10 14L21 3"/>',
    "dots": '<circle cx="5" cy="12" r="1.1"/><circle cx="12" cy="12" r="1.1"/>'
            '<circle cx="19" cy="12" r="1.1"/>',
    "cloud": '<path d="M17.5 19a4.5 4.5 0 0 0 .42-8.98A7 7 0 0 0 4.06 12.3 3.5 3.5 0 0 0 6.5 19h11z"/>',
    "pulse": '<path d="M3 12h4l2.5-7 5 14 2.5-7h4"/>',
    "book-open": '<path d="M2 4h6a4 4 0 0 1 4 4v12a3 3 0 0 0-3-3H2V4z"/>'
                 '<path d="M22 4h-6a4 4 0 0 0-4 4v12a3 3 0 0 1 3-3h7V4z"/>',
    "bridge": '<path d="M3 17h18"/><path d="M4 17q8-12 16 0"/>'
              '<path d="M8 12.6V17M12 10.4V17M16 12.6V17"/>',
    "file-text": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
                 '<path d="M14 2v6h6"/><path d="M9 13h6M9 17h6"/>',
}

# Semantic kinds → COLORS token keys (for state-colored icons).
_STATE_COLORS = {
    "success": "success",
    "warning": "warning",
    "error": "error",
    "info": "info",
    "accent": "accent",
    "muted": "text_muted",
}


def names() -> list[str]:
    """Available glyph names."""
    return list(_PATHS)


def _svg_doc(name: str, color: str) -> str:
    body = _PATHS.get(name, _PATHS["info"])
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<g fill="none" stroke="{color}" stroke-width="{_STROKE_W}" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</g></svg>"
    )


def pixmap(name: str, color: str | None = None, size: int = 18,
           dpr: float = 2.0) -> QPixmap:
    """Render a glyph to a supersampled transparent pixmap (crisp at any DPI)."""
    color = color or COLORS["text_secondary"]
    renderer = QSvgRenderer(bytes(_svg_doc(name, color), "utf-8"))
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str | None = None, size: int = 18) -> QIcon:
    """Theme-tinted vector glyph as a QIcon."""
    return QIcon(pixmap(name, color, size))


def state_icon(name: str, kind: str = "info", size: int = 18) -> QIcon:
    """Glyph tinted with a semantic token (success/warning/error/info/accent/muted)."""
    token = _STATE_COLORS.get(kind, "info")
    return icon(name, COLORS.get(token, COLORS["info"]), size)


def tile_pixmap(name: str, size: int = 46, radius: int | None = None) -> QPixmap:
    """Accent-gradient rounded tile with an inverted glyph — app-tile fallback."""
    radius = radius if radius is not None else max(10, size // 4)
    ss = 2.0
    px = int(size * ss)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(ss, ss)

    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, _qt_color(COLORS["accent"]))
    grad.setColorAt(1.0, _qt_color(COLORS["accent_2"]))
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(size), float(size), float(radius), float(radius))
    painter.fillPath(path, grad)

    glyph = size * 0.55
    off = (size - glyph) / 2.0
    renderer = QSvgRenderer(bytes(_svg_doc(name, COLORS["text_inverted"]), "utf-8"))
    painter.translate(off, off)
    renderer.render(painter, QRectF(0.0, 0.0, glyph, glyph))
    painter.end()
    pm.setDevicePixelRatio(ss)
    return pm


def _qt_color(hex_str: str):
    from PyQt6.QtGui import QColor
    return QColor(hex_str)


def styled_button(label: str, icon_name: str | None = None, *, color: str | None = None,
                  size: int = 18, parent=None) -> QPushButton:
    """QPushButton with a vector glyph + plain-text label (no emoji)."""
    btn = QPushButton(label, parent)
    if icon_name:
        btn.setIcon(icon(icon_name, color, size))
        btn.setIconSize(QSize(size, size))
    return btn


def icon_label(text: str, icon_name: str | None = None, *, color: str | None = None,
               icon_size: int = 15, text_size: int = 15,
               weight: int = 700) -> QFrame:
    """Horizontal glyph + heading composition (card/section headers)."""
    wrap = QFrame()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    if icon_name:
        glyph = QLabel()
        glyph.setPixmap(pixmap(icon_name, color or COLORS["accent"], icon_size))
        glyph.setFixedSize(icon_size, icon_size)
        glyph.setScaledContents(True)
        lay.addWidget(glyph)
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{COLORS['text_primary']};font-size:{text_size}px;"
                      f"font-weight:{weight};background:transparent;")
    lay.addWidget(lbl)
    lay.addStretch()
    return wrap


# ── Bundled PNG app icons (nav / Home dashboard / top bar) ────────────────
_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")

_ICON_FILES = {
    "home": "home.png",
    "cd": "cd.png",
    "cad": "cad.png",
    "cad2": "cad2.png",
    "gadgen": "gadgen.png",
    "gad": "gad.png",
    "hydraulic": "hydraulic.png",
    "borelog": "borelog.png",
    "kb": "kb.png",
    "settings": "settings.png",
    "quiz": "quiz.png",
    "sync": "sync.png",
    "import": "import.png",
    "codesearch": "codesearch.png",
    "book": "book.png",
    "folder": "folder.png",
    "info": "info.png",
}


def icon_path(name: str) -> str | None:
    """Return the absolute path to a bundled app-tile PNG, or None if missing."""
    filename = _ICON_FILES.get(name)
    if not filename:
        return None
    path = os.path.join(_ICON_DIR, filename)
    return path if os.path.isfile(path) else None
