"""
gui/animated_extract_button.py  —  Bridge Engineering Suite
═══════════════════════════════════════════════════════════
Animated "Smart Extract" button — replaces a plain QPushButton with one
that visibly shows extraction progress instead of doing nothing while a
SmartExtractWidget's hidden worker runs in the background.

Design reference: a CodePen "fizzy button" SCSS pattern — checkbox-driven,
multi-hue confetti spots (hsla(350+random(399), ...): spans the whole hue
wheel, not one accent color) that continuously rotate/drift while the
button is busy, then an overshoot-eased "pop" morph on completion
(cubic-bezier(0.39, 2.01, 0.27, 0.75) — the >1 control point is what makes
it bounce past its target before settling) and a checkmark that scales in
right after (tinted with the active theme's success token).

Adapted for real async progress rather than a fixed decorative delay:
  - spot orbit runs for as long as extraction actually takes (tied to the
    worker's real duration, not a hardcoded ~4s)
  - percent-fill bar along the bottom edge still carries the actual number,
    since the original design never needed to communicate a real progress
    value — ours does (rendered as an accent→accent_2 gradient)
  - "shrink into a small circle" from the source is reinterpreted as an
    expanding pulse ring, since a real button has to stay a clickable
    rectangle rather than morph shape
  - while working, a soft accent glow breathes along the button border
    (phase-derived from the existing orbit timer — no extra timers)

States
──────
  idle     : normal "Smart Extract" label with spark glyph
  working  : percent-fill bar + ambient multi-hue confetti spots orbiting
             + breathing border glow, label shows "<stage message>  NN%"
  success  : overshoot pulse ring + spots burst outward and fade + success
             tinted "Extracted" label, then auto-reverts to idle
  error    : brief error tinted "Extraction failed" label, then auto-reverts

Usage (see hydraulic_panel.py for the wiring):
    btn = AnimatedProgressButton("Smart Extract")
    btn.clicked.connect(...)
    extractor.progressChanged.connect(btn.set_progress)
    extractor.extractionFinished.connect(lambda fields: btn.finish(True))
    extractor.extractionFailed.connect(lambda msg: btn.finish(False))
    extractor.extractionCancelled.connect(btn.cancel)
    # and call btn.start() right before triggering the extraction
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QRectF, pyqtProperty, QSize
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QIcon
from PyQt6.QtWidgets import QPushButton

from gui.styles import COLORS
from gui.icons import icon

_ICON_SIZE = 16


class AnimatedProgressButton(QPushButton):

    def __init__(self, text: str = "Smart Extract", parent=None):
        super().__init__(text, parent)
        self._base_text = text
        self._base_icon = icon("spark", COLORS["accent"], _ICON_SIZE)
        self.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self.setIcon(self._base_icon)
        self._percent = 0.0
        self._state = "idle"      # idle | working | success | error
        self._spots: list[tuple[float, float, float, float, float]] = []  # hue, radius, speed, phase, size
        self._orbit_phase = 0.0
        self._burst = 0.0
        self._pulse = 0.0
        self._session = 0   # bumped on every start() so a stale safety timer can't reset a fresh run

        self.setObjectName("secondaryBtn")
        self.setMinimumHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Deliberately never disabled — this button stays clickable even
        # while "working" so the user can always click again to cancel a
        # stuck/slow extraction (e.g. a hung AI call) and start a new one.
        # See hydraulic_panel.py's _trigger_smart_extract, which calls
        # cancel_current() on the active extractor before calling start().

        self._fill_anim = QPropertyAnimation(self, b"percent")
        self._fill_anim.setDuration(350)
        self._fill_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Continuous ambient rotation while "working" — matches the source's
        # `rotate 4s ... infinite` on button_spots. A ticking timer (not a
        # looped QPropertyAnimation) since the duration is open-ended: we
        # don't know how long extraction will actually take.
        self._orbit_timer = QTimer(self)
        self._orbit_timer.setInterval(30)
        self._orbit_timer.timeout.connect(self._tick_orbit)

        # Overshoot "pop" on completion — OutBack is Qt's closest built-in
        # analog to the source's cubic-bezier(0.39, 2.01, 0.27, 0.75).
        self._pulse_anim = QPropertyAnimation(self, b"pulseProgress")
        self._pulse_anim.setDuration(420)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.OutBack)

        self._burst_anim = QPropertyAnimation(self, b"burstProgress")
        self._burst_anim.setDuration(650)
        self._burst_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._burst_anim.finished.connect(lambda: QTimer.singleShot(500, self._reset))

    # ── animated properties (Qt property system drives smooth interpolation) ──

    def _get_percent(self) -> float:
        return self._percent

    def _set_percent(self, v: float):
        self._percent = v
        self.update()

    percent = pyqtProperty(float, _get_percent, _set_percent)

    def _get_burst(self) -> float:
        return self._burst

    def _set_burst(self, v: float):
        self._burst = v
        self.update()

    burstProgress = pyqtProperty(float, _get_burst, _set_burst)

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, v: float):
        self._pulse = v
        self.update()

    pulseProgress = pyqtProperty(float, _get_pulse, _set_pulse)

    # ── public control surface ──────────────────────────────────────────────

    def start(self):
        """Call right before triggering the extraction (after cancelling
        any previous one — see hydraulic_panel.py)."""
        self._session += 1
        session = self._session
        self._state = "working"
        self.setToolTip("Extraction in progress — click again to cancel and pick a different file.")
        self._fill_anim.stop()
        self._percent = 0.0
        self._spots = self._make_spots(22)
        self._orbit_phase = 0.0
        self._orbit_timer.start()
        self.setText("Starting...")
        self.update()
        # Genuine deadlock/crash safety net only — normal cancellation goes
        # through cancel(), so this is a generous timeout, and it's scoped
        # to this specific session so a fresh restart isn't reset by an old
        # timer that was already ticking down.
        QTimer.singleShot(30000, lambda: self._check_still_working(session))

    def set_progress(self, pct: int, msg: str):
        """Connect to SmartExtractWidget.progressChanged(int, str)."""
        if self._state != "working":
            self._state = "working"
            if not self._orbit_timer.isActive():
                self._spots = self._make_spots(22)
                self._orbit_timer.start()
        self._fill_anim.stop()
        self._fill_anim.setStartValue(self._percent)
        self._fill_anim.setEndValue(float(max(0, min(100, pct))))
        self._fill_anim.start()
        self.setText(f"{msg}  {pct}%")

    def finish(self, success: bool = True):
        """Connect to extractionFinished / extractionFailed."""
        self._orbit_timer.stop()
        self._fill_anim.stop()
        self._set_percent(100.0)
        self.setToolTip("")
        if success:
            self._state = "success"
            self.setStyleSheet(f"QPushButton {{ color: {COLORS['success']}; }}")
            self.setIcon(icon("check", COLORS["success"], _ICON_SIZE))
            self.setText("Extracted")
            self._pulse_anim.setStartValue(0.0)
            self._pulse_anim.setEndValue(1.0)
            self._pulse_anim.start()
            self._burst_anim.setStartValue(0.0)
            self._burst_anim.setEndValue(1.0)
            self._burst_anim.start()
        else:
            self._state = "error"
            self.setStyleSheet(f"QPushButton {{ color: {COLORS['error']}; }}")
            self.setIcon(icon("cross", COLORS["error"], _ICON_SIZE))
            self.setText("Extraction failed")
            QTimer.singleShot(1400, self._reset)

    def cancel(self):
        """Connect to SmartExtractWidget.extractionCancelled — fires either
        when the user closed the file picker without selecting anything,
        or when a previous in-flight extraction was just aborted to make
        way for a new one."""
        if self._state == "working":
            self._orbit_timer.stop()
            self._reset()

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _make_spots(n: int):
        """
        hue spans the full wheel (matches the source's hsla(350+random(399))
        — effectively any hue, wrapped), not a single accent color.
        """
        pts = []
        for _ in range(n):
            hue    = random.uniform(0, 360)
            radius = random.uniform(14, 30)
            speed  = random.uniform(0.6, 1.4)
            phase  = random.uniform(0, 360)
            size   = random.uniform(2.0, 4.0)
            pts.append((hue, radius, speed, phase, size))
        return pts

    def _tick_orbit(self):
        self._orbit_phase = (self._orbit_phase + 4.0) % 360.0
        self.update()

    def _check_still_working(self, session: int):
        if self._state == "working" and session == self._session:
            self._orbit_timer.stop()
            self._reset()

    def _reset(self):
        self._state = "idle"
        self._percent = 0.0
        self._burst = 0.0
        self._pulse = 0.0
        self._spots = []
        self.setToolTip("")
        self.setStyleSheet("")
        self.setText(self._base_text)
        self.setIcon(self._base_icon)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)   # native button chrome + current text first

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2.0, self.height() / 2.0

        if self._state == "working":
            # percent-fill bar — the real progress number the source design
            # never had to communicate; accent→accent_2 gradient fill
            w = self.width() * (self._percent / 100.0)
            if w > 0:
                grad = QLinearGradient(0, 0, self.width(), 0)
                grad.setColorAt(0.0, QColor(COLORS["accent"]))
                grad.setColorAt(1.0, QColor(COLORS["accent_2"]))
                painter.fillRect(QRectF(0, self.height() - 3, w, 3), grad)

            # breathing border glow while working — phase rides the existing
            # orbit timer (no extra timers), alpha oscillating ~0.15–0.45
            glow = 0.30 + 0.15 * math.sin(math.radians(self._orbit_phase * 2))
            edge = QColor(COLORS["accent_light"])
            edge.setAlphaF(max(0.0, min(0.5, glow)))
            painter.setPen(edge)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 9, 9)

            # ambient multi-hue orbiting spots (source: continuous `rotate`
            # + per-spot hsla hue), opacity ~0.6 to match the source's
            # spot-#{i} keyframe end-state opacity
            for hue, radius, speed, phase, size in self._spots:
                ang = math.radians(phase + self._orbit_phase * speed)
                x = cx + radius * math.cos(ang)
                y = cy + radius * math.sin(ang) * 0.4   # flattened to hug a pill-shaped button
                color = QColor.fromHsvF((hue % 360) / 360.0, 0.55, 0.85)
                color.setAlphaF(0.6)
                painter.setBrush(color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QRectF(x - size / 2, y - size / 2, size, size))

        elif self._state == "success":
            # overshoot pulse ring (OutBack easing does the bounce-past-100%
            # feel of the source's cubic-bezier(0.39, 2.01, 0.27, 0.75))
            if self._pulse > 0:
                ring_r = 6 + self._pulse * max(self.width(), self.height()) * 0.6
                pen_color = QColor(COLORS["success"])
                pen_color.setAlphaF(max(0.0, 1.0 - self._pulse))
                painter.setPen(pen_color)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2))

            # spots burst outward from their orbit position and fade
            if self._burst > 0 and self._spots:
                t = self._burst
                for hue, radius, speed, phase, size in self._spots:
                    r = radius + t * 34
                    ang = math.radians(phase + self._orbit_phase * speed)
                    x = cx + r * math.cos(ang)
                    y = cy + r * math.sin(ang) * 0.6
                    color = QColor.fromHsvF((hue % 360) / 360.0, 0.55, 0.9)
                    color.setAlphaF(max(0.0, 0.7 * (1.0 - t)))
                    painter.setBrush(color)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(QRectF(x - size / 2, y - size / 2, size, size))

        painter.end()
