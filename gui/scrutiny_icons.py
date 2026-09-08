"""
gui/scrutiny_icons.py — Bridge Engineering Suite
═══════════════════════════════════════════════
Trendy colour badges for Scrutiny-panel features.

Each badge is a rounded-square tile filled with a per-feature colour
gradient, carrying a hand-drawn vector glyph (pure QPainter geometry —
no fonts, no emoji, razor-sharp at any DPI).

Usage:
    lbl = feature_badge("gradient")          # 44 px QLabel, ready to add
    pm  = make_badge("vc", size=64)          # raw QPixmap
    acc = FEATURE_ACCENTS["loop"]            # ("#F472B6", "#DB2777")
"""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap,
)

# ── Feature registry: kind → gradient colours (light → deep) ────────────────
FEATURE_ACCENTS: dict[str, tuple[str, str]] = {
    "vc":       ("#22D3EE", "#0284C7"),   # Vertical Clearance Calculator
    "table":    ("#A78BFA", "#7C3AED"),   # Reference table
    "gradient": ("#34D399", "#059669"),   # Gradient Checker
    "corner":   ("#FBBF24", "#D97706"),   # Corner-Block RL Check
    "loop":     ("#F472B6", "#DB2777"),   # Loop Interface
    "status":   ("#60A5FA", "#2563EB"),   # Status Updation
    "borelog":  ("#FB923C", "#EA580C"),   # Bore Log → DXF
}


# ── Vector glyphs (drawn inside a square rect, white, stroke-width lw) ──────

def _g_ruler(p: QPainter, r: QRectF, lw: float) -> None:
    """Diagonal ruler with tick marks (VC calculator)."""
    p.save()
    p.translate(r.center())
    p.rotate(-45)
    w, h = r.width() * 1.00, r.height() * 0.46
    rect = QRectF(-w / 2, -h / 2, w, h)
    p.drawRoundedRect(rect, lw, lw)
    for i in range(1, 5):
        x = -w / 2 + i * (w / 5)
        ln = h * (0.30 if i % 2 == 0 else 0.50)
        p.drawLine(QPointF(x, -h / 2 + lw / 2), QPointF(x, -h / 2 + ln))
    p.restore()


def _g_table(p: QPainter, r: QRectF, lw: float) -> None:
    """Data table: header band + column split (reference table)."""
    path = QPainterPath()
    path.addRoundedRect(r, lw, lw)
    hdr_h = r.height() * 0.34
    hdr = QPainterPath()
    hdr.addRect(QRectF(r.left(), r.top(), r.width(), hdr_h))
    p.fillPath(hdr.intersected(path), QBrush(QColor("#FFFFFF")))
    p.drawPath(path)
    p.drawLine(QPointF(r.left() + r.width() * 0.55, r.top() + hdr_h),
               QPointF(r.left() + r.width() * 0.55, r.bottom()))
    p.drawLine(QPointF(r.left(), r.top() + hdr_h),
               QPointF(r.right(), r.top() + hdr_h))


def _g_gradient(p: QPainter, r: QRectF, lw: float) -> None:
    """Chart axes + rising trend line with nodes (gradient checker)."""
    m = r.width() * 0.06
    ox, oy = r.left() + m, r.bottom() - m          # axis origin
    ax_top = QPointF(ox, r.top() + m)
    ax_right = QPointF(r.right() - m, oy)
    p.drawLine(QPointF(ox, ax_top.y()), QPointF(ox, oy))
    p.drawLine(QPointF(ox, oy), QPointF(ax_right.x(), oy))

    pts = [
        QPointF(ox + r.width() * 0.10, oy - r.height() * 0.14),
        QPointF(r.center().x(), oy - r.height() * 0.48),
        QPointF(ax_right.x() - r.width() * 0.04, r.top() + m + r.height() * 0.10),
    ]
    p.drawPolyline(*pts)
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.setPen(Qt.PenStyle.NoPen)
    rad = lw * 0.85
    for pt in pts:
        p.drawEllipse(pt, rad, rad)


def _g_corner(p: QPainter, r: QRectF, lw: float) -> None:
    """Opposing corner brackets + centre mark (corner-block RL check)."""
    m = r.width() * 0.10
    L = r.width() * 0.40
    tl_x, tl_y = r.left() + m, r.top() + m
    br_x, br_y = r.right() - m, r.bottom() - m
    p.drawLine(QPointF(tl_x + L, tl_y), QPointF(tl_x, tl_y))
    p.drawLine(QPointF(tl_x, tl_y), QPointF(tl_x, tl_y + L))
    p.drawLine(QPointF(br_x - L, br_y), QPointF(br_x, br_y))
    p.drawLine(QPointF(br_x, br_y), QPointF(br_x, br_y - L))
    c = r.center()
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(c, lw * 1.1, lw * 1.1)


def _g_loop(p: QPainter, r: QRectF, lw: float) -> None:
    """Circular refresh arrows (loop interface)."""
    c = r.center()
    rad = r.width() * 0.34
    start_deg, span_deg = 210.0, 290.0              # gap sits upper-right
    rect = QRectF(c.x() - rad, c.y() - rad, rad * 2, rad * 2)
    p.drawArc(rect, int(start_deg * 16), int(span_deg * 16))

    end_deg = math.radians(start_deg + span_deg)
    ex, ey = c.x() + rad * math.cos(end_deg), c.y() - rad * math.sin(end_deg)
    dx, dy = -math.sin(end_deg), -math.cos(end_deg)  # CCW tangent on screen
    ah = lw * 2.4
    tip = QPointF(ex + dx * ah, ey + dy * ah)
    px, py = -dy, dx                                 # perpendicular
    base = QPointF(ex, ey)
    wing = ah * 0.62
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.setPen(Qt.PenStyle.NoPen)
    tri = QPainterPath()
    tri.moveTo(tip)
    tri.lineTo(base.x() + px * wing, base.y() + py * wing)
    tri.lineTo(base.x() - px * wing, base.y() - py * wing)
    tri.closeSubpath()
    p.drawPath(tri)


def _g_status(p: QPainter, r: QRectF, lw: float) -> None:
    """Stacked checklist rows (status updation sheet)."""
    bar_h = lw * 1.7
    gap = r.height() * 0.26
    widths = (1.00, 0.74, 0.48)
    y = r.top() + (r.height() - (3 * bar_h + 2 * gap)) / 2
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.setPen(Qt.PenStyle.NoPen)
    for w_frac in widths:
        row = QRectF(r.left(), y, r.width() * w_frac, bar_h)
        p.drawRoundedRect(row, bar_h / 2, bar_h / 2)
        y += bar_h + gap


def _g_borelog(p: QPainter, r: QRectF, lw: float) -> None:
    """Ground line, soil strata and a drill rod (bore log)."""
    gy = r.top() + r.height() * 0.30
    p.drawLine(QPointF(r.left(), gy), QPointF(r.right(), gy))       # ground

    s1_y, s2_y = gy + r.height() * 0.20, gy + r.height() * 0.44
    p.drawLine(QPointF(r.left(), s1_y),
               QPointF(r.left() + r.width() * 0.30, s1_y))          # stratum 1
    p.drawLine(QPointF(r.right() - r.width() * 0.30, s2_y),
               QPointF(r.right(), s2_y))                            # stratum 2

    cx = r.center().x()
    top = QPointF(cx, r.top() + r.height() * 0.08)
    bot = QPointF(cx, gy + r.height() * 0.52)
    p.drawLine(top, bot)                                            # drill rod

    bw = lw * 1.6                                                   # drill bit
    tri = QPainterPath()
    tri.moveTo(bot.x(), bot.y() + bw * 1.6)
    tri.lineTo(bot.x() - bw, bot.y())
    tri.lineTo(bot.x() + bw, bot.y())
    tri.closeSubpath()
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(tri)


_GLYPHS = {
    "vc": _g_ruler,
    "table": _g_table,
    "gradient": _g_gradient,
    "corner": _g_corner,
    "loop": _g_loop,
    "status": _g_status,
    "borelog": _g_borelog,
}


# ── GAD sheet integration helpers ───────────────────────────────────────────

def borelog_badge_html(label: str = "BORE LOG", size: int = 11) -> str:
    """Return an inline HTML badge string for bore-log observations
    in the GAD scrutiny report, matching the style of the existing
    ATTENDED / MISSED / PARTIAL badges.

    Usage in gad_panel.py::_build_html::

        from gui.scrutiny_icons import borelog_badge_html
        html = borelog_badge_html()  # → '<span …>BORE LOG</span>'
    """
    c1, c2 = FEATURE_ACCENTS["borelog"]
    return (
        f"<span style='background:#1A0F05;color:{c2};"
        f"border:1px solid {c2};border-radius:4px;"
        f"padding:2px 10px;font-size:{size}px;font-weight:700;"
        f"letter-spacing:.4px;white-space:nowrap;'>"
        f"🔶 {label}</span>"
    )


def borelog_zone_icon() -> str:
    """Return the emoji icon for the BORE LOG zone, for use in
    zone-based iteration (matches _ZONE_ICONS style)."""
    return "🔶"


# ── Badge renderer ──────────────────────────────────────────────────────────

_SS = 3  # super-sample factor for crisp edges at any zoom / Hi-DPI


def make_badge(kind: str, size: int = 44, radius_ratio: float = 0.30) -> QPixmap:
    """Render a feature badge as a crisp QPixmap of `size` logical pixels."""
    c1, c2 = FEATURE_ACCENTS.get(kind, ("#8B949E", "#6E7681"))
    pm = QPixmap(size * _SS, size * _SS)
    pm.setDevicePixelRatio(_SS)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor(c1))
    grad.setColorAt(1.0, QColor(c2))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * radius_ratio, size * radius_ratio)

    pad = size * 0.24
    inner = QRectF(pad, pad, size - pad * 2, size - pad * 2)
    pen = QPen(QColor("#FFFFFF"), max(1.5, size * 0.075))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    _GLYPHS.get(kind, _g_status)(p, inner, pen.widthF())

    p.end()
    return pm


def feature_badge(kind: str, size: int = 44) -> "object":
    """Convenience: a QLabel holding the badge, ready to drop into a layout.

    Imported lazily so this module stays usable outside Qt-widget contexts.
    """
    from PyQt6.QtWidgets import QLabel
    lbl = QLabel()
    lbl.setPixmap(make_badge(kind, size))
    lbl.setFixedSize(size, size)
    return lbl
