"""Main application shell for Bridge Engineering Suite."""

from __future__ import annotations

import os

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QLineF,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSettings,
    QSize,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QSizePolicy,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.ui_text import install_text_sanitizer

install_text_sanitizer()

from gui.styles import COLORS, THEME_NAMES, THEME_SWATCHES, apply_theme, current_theme, status_label
from gui.icons import icon_label, icon_path as get_icon_path, pixmap as icon_pixmap, tile_pixmap
from gui.calculated_notes_panel import CalculatedNotesPanel
from gui.cd_panel import CDPanel
from gui.cad_panel import CADPanel
from gui.cad_panel2 import CAD2Panel
from gui.gad_generator_panel import GadGeneratorPanel
from gui.gad_panel import GADPanel
from gui.hydraulic_panel import HydraulicPanel
from gui.knowledge_panel import KnowledgePanel
from gui.sheets_sync_panel import SheetsSyncPanel
from gui.borelog_panel import BoreLogPanel


def _reduced_motion() -> bool:
    """Respect the Windows "show animations" accessibility preference."""
    try:
        import ctypes

        spi_get_client_area_animation = 0x1042
        flag = ctypes.c_int()
        ctypes.windll.user32.SystemParametersInfoW(
            spi_get_client_area_animation, 0, ctypes.byref(flag), 0
        )
        return not bool(flag.value)
    except Exception:
        return False


_ANIM_FAST = 130
_ANIM_PAGE = 190


def _restore_hydraulic_inputs(form, saved: dict) -> None:
    """Best-effort restore of Hydraulic Calcs form values across a theme-driven
    panel rebuild. Field names differ between the New Line and Doubling forms,
    so only set keys the target form actually knows about."""
    if not saved:
        return
    try:
        for key, value in saved.items():
            field = getattr(form, key, None)
            if field is None:
                continue
            if hasattr(field, "setText"):
                field.setText(str(value))
            elif hasattr(field, "setCurrentText"):
                field.setCurrentText(str(value))
        # Recompute any auto-derived helpers after the bulk restore.
        if hasattr(form, "_update_span_descs"):
            form._update_span_descs()
        if hasattr(form, "_recalc_tc_ratio"):
            form._tc_ratio_user_edited = False
            form._recalc_tc_ratio()
    except Exception:
        pass


class SidebarButton(QPushButton):
    """Sidebar nav button with a soft drop-shadow that lifts on hover and dips on press.

    Replaces the previous opacity-pulse: a widget can only own one graphicsEffect at a
    time, so the shadow now handles both the hover-lift and the press feedback instead
    of swapping effect types mid-interaction.
    """

    def __init__(self, text: str, obj_name: str = "sidebarButton", parent=None, icon_key: str = ""):
        super().__init__(parent)
        self._label = text
        self._icon_key = icon_key
        self._collapsed = False
        self.setText(text)
        self.setCheckable(True)
        self.setMinimumHeight(38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName(obj_name)

        path = get_icon_path(icon_key) if icon_key else None
        if path:
            self.setIcon(QIcon(path))
            self.setIconSize(QSize(18, 18))

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(0, 0, 0, 0))
        self.setGraphicsEffect(self._shadow)

    def setCollapsed(self, collapsed: bool) -> None:
        """Hide the label but keep the icon when the sidebar is a narrow icon rail."""
        self._collapsed = collapsed
        if collapsed:
            self.setText("")
            self.setToolTip(self._label)
        else:
            self.setText(self._label)
            self.setToolTip("")

    def enterEvent(self, event):
        self._animate_shadow(blur=22, dy=5, alpha=110)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_shadow(blur=0, dy=0, alpha=0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._animate_shadow(blur=6, dy=1, alpha=80, duration=70)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.underMouse():
            self._animate_shadow(blur=22, dy=5, alpha=110)
        else:
            self._animate_shadow(blur=0, dy=0, alpha=0)

    def _animate_shadow(self, blur: int, dy: int, alpha: int, duration: int = _ANIM_FAST) -> None:
        if _reduced_motion():
            self._shadow.setBlurRadius(blur)
            self._shadow.setOffset(0, dy)
            return

        accent = QColor(COLORS.get("accent", "#000000"))
        accent.setAlpha(alpha)
        self._shadow.setColor(accent)

        blur_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        blur_anim.setDuration(duration)
        blur_anim.setEndValue(float(blur))
        blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        offset_anim = QPropertyAnimation(self._shadow, b"offset", self)
        offset_anim.setDuration(duration)
        offset_anim.setEndValue(QPointF(0, dy))
        offset_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(blur_anim)
        group.addAnimation(offset_anim)
        self._shadow_anim = group
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


class Sidebar(QFrame):
    """Sidebar frame; expand/collapse is manual only (via the toggle button)."""
    pass


class BridgeLogo(QFrame):
    """White cable-stayed bridge mark on transparent ground (sidebar brand)."""

    def __init__(self, size: int = 40, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        try:
            self._paint()
        except Exception:
            import traceback
            traceback.print_exc()

    def _paint(self):
        from PyQt6.QtCore import QPointF

        painter = QPainter(self)
        try:
            self._paint_content(painter)
        finally:
            painter.end()

    def _paint_content(self, painter: QPainter):
        s = self._size
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Draw in the theme's primary text color so the mark stays visible on
        # both dark (graphite) and light sidebars.
        pen = QPen(QColor(COLORS.get("text_primary", "#16283C")), max(1.5, s * 0.045))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        deck_y = s * 0.78
        top_y = s * 0.14
        # deck
        painter.drawLine(QPointF(s * 0.04, deck_y), QPointF(s * 0.96, deck_y))
        # pylon pair
        painter.drawLine(QPointF(s * 0.30, deck_y), QPointF(s * 0.30, top_y))
        painter.drawLine(QPointF(s * 0.70, deck_y), QPointF(s * 0.70, top_y))
        # crossbeam
        painter.drawLine(QPointF(s * 0.30, top_y + s * 0.10), QPointF(s * 0.70, top_y + s * 0.10))
        # cables fanning to deck anchor points
        for t in (0.06, 0.16, 0.26):
            painter.drawLine(QPointF(s * 0.30, top_y + s * 0.02), QPointF(s * t, deck_y))
            painter.drawLine(QPointF(s * 0.70, top_y + s * 0.02), QPointF(s * (1.0 - t), deck_y))
        # centre cable crossing between pylons
        painter.drawLine(QPointF(s * 0.30, top_y + s * 0.02), QPointF(s * 0.50, deck_y - s * 0.02))
        painter.drawLine(QPointF(s * 0.70, top_y + s * 0.02), QPointF(s * 0.50, deck_y - s * 0.02))


class HeroBanner(QFrame):
    """Hero with a photo scene (rail arch bridge) and overlaid copy.

    The scene is gui/assets/icons/bridge.png; it is drawn scaled+cropped
    (cover-fit) in paintEvent, with a left-to-right sky wash and a bottom
    feature strip so white text stays readable (mock: 01_home).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeHero")
        self.setMinimumHeight(216)
        self._photo = self._load_photo()

    @staticmethod
    def _load_photo() -> QPixmap | None:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "assets", "icons", "bridge.png"
        )
        pm = QPixmap(path) if os.path.isfile(path) else QPixmap()
        return pm if not pm.isNull() else None

    def paintEvent(self, event):
        try:
            self._paint()
        except Exception:
            import traceback
            traceback.print_exc()

    def _paint(self):
        painter = QPainter(self)
        try:
            self._paint_content(painter)
        finally:
            painter.end()

    def _paint_content(self, painter: QPainter):
        from PyQt6.QtCore import QRectF

        w, h = self.width(), self.height()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # rounded clip to match the QSS radius
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 16.0, 16.0)
        painter.setClipPath(path)

        if self._photo is not None:
            # cover-fit: scale to fill, crop the sides; bias crop toward the
            # top so the bridge arches stay visible in the wide, short hero.
            pm = self._photo
            scale = max(w / pm.width(), h / pm.height())
            tw, th = pm.width() * scale, pm.height() * scale
            off_y = min((h - th) / 2, 0.0) * 0.45  # keep ~45% of the excess crop above
            painter.drawPixmap(
                QRectF((w - tw) / 2, off_y, tw, th), pm,
                QRectF(0, 0, pm.width(), pm.height()),
            )
        else:
            painter.fillRect(self.rect(), QColor("#9CC4E4"))

        # sky wash on the left third so the headline reads like the mock
        wash = QLinearGradient(0, 0, w * 0.62, 0)
        wash.setColorAt(0.0, QColor(255, 255, 255, 246))
        wash.setColorAt(0.42, QColor(255, 255, 255, 214))
        wash.setColorAt(0.72, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), wash)

        # soft dark band at the bottom for the feature strip
        band = QLinearGradient(0, h - 64, 0, h)
        band.setColorAt(0.0, QColor(8, 30, 55, 0))
        band.setColorAt(1.0, QColor(8, 30, 55, 130))
        painter.fillRect(QRectF(0, h - 64, w, 64), band)

        painter.setClipping(False)
        pen = QPen(QColor(255, 255, 255, 26))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 16.0, 16.0)


class PromoCard(QFrame):
    """Sidebar promo: cable-stayed bridge photo with overlaid tagline text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidePromo")
        self.setMinimumHeight(150)
        self._photo = self._load_photo()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(2)
        for line in ("ENGINEERING", "BRIDGES", "FOR A BETTER", "TOMORROW"):
            lbl = QLabel(line)
            lbl.setObjectName("sidePromoTitle")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        lay.addStretch()

    @staticmethod
    def _load_photo() -> QPixmap | None:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "assets", "side_promo.png"
        )
        pm = QPixmap(path) if os.path.isfile(path) else QPixmap()
        return pm if not pm.isNull() else None

    def paintEvent(self, event):
        try:
            self._paint()
        except Exception:
            import traceback
            traceback.print_exc()

    def _paint(self):
        painter = QPainter(self)
        try:
            self._paint_content(painter)
        finally:
            painter.end()

    def _paint_content(self, painter: QPainter):
        w, h = self.width(), self.height()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 14.0, 14.0)
        painter.setClipPath(clip)
        if self._photo is not None:
            pm = self._photo
            scale = max(w / pm.width(), h / pm.height())
            tw, th = pm.width() * scale, pm.height() * scale
            painter.drawPixmap(
                QRectF((w - tw) / 2, (h - th) / 2, tw, th),
                pm, QRectF(0, 0, pm.width(), pm.height()),
            )
        else:
            painter.fillRect(self.rect(), QColor("#0B2A4E"))
        painter.setClipping(False)


class SettingsPanel(QWidget):
    """Full-page settings panel."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self._win = win
        self._theme_buttons: dict[str, QPushButton] = {}
        self._build()

    def _build(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(42, 34, 42, 42)
        layout.setSpacing(18)
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        title = QLabel("Settings")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        subtitle = QLabel("Personalize the interface and manage local AI provider keys.")
        subtitle.setObjectName("panelSubtitle")
        layout.addWidget(subtitle)

        layout.addWidget(self._appearance_card())
        layout.addWidget(self._api_card())
        layout.addWidget(self._about_card())
        layout.addStretch()

        self._refresh_ui()

    def _appearance_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 22, 24, 22)
        card_lay.setSpacing(16)

        header = icon_label("Appearance", "settings", text_size=14)
        card_lay.addWidget(header)

        row = QFrame()
        row.setObjectName("settingsRow")
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(18, 16, 18, 16)
        row_lay.setSpacing(18)

        copy = QVBoxLayout()
        copy.setSpacing(4)
        name = QLabel("Theme Studio")
        name.setStyleSheet("font-size:13px;font-weight:700;background:transparent;")
        desc = QLabel("Switch between polished color systems without restarting the app.")
        desc.setObjectName("panelSubtitle")
        desc.setWordWrap(True)
        copy.addWidget(name)
        copy.addWidget(desc)
        row_lay.addLayout(copy, 1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self._btn_grp = QButtonGroup(self)
        self._btn_grp.setExclusive(True)

        for i, (key, label) in enumerate(THEME_NAMES.items()):
            btn = QPushButton(label)
            btn.setFixedSize(104, 44)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, theme=key: self._set_theme(theme))
            self._btn_grp.addButton(btn)
            self._theme_buttons[key] = btn
            grid.addWidget(btn, i // 3, i % 3)

        row_lay.addLayout(grid)
        card_lay.addWidget(row)

        self._indicator = QLabel()
        self._indicator.setObjectName("panelSubtitle")
        card_lay.addWidget(self._indicator)
        return card

    def _api_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 22, 24, 22)
        card_lay.setSpacing(14)

        header = icon_label("API Keys", "key", text_size=14)
        card_lay.addWidget(header)

        sub = QLabel("Keys are stored locally and used by CAD, GAD, and Knowledge Base tools.")
        sub.setObjectName("panelSubtitle")
        sub.setWordWrap(True)
        card_lay.addWidget(sub)

        card_lay.addWidget(
            self._make_key_row(
                "Anthropic Claude API Key",
                "sk-ant-api03-...",
                "anthropic_api_key",
                "ANTHROPIC_API_KEY",
            )
        )
        card_lay.addWidget(
            self._make_key_row(
                "Google Gemini API Key",
                "AIzaSy...",
                "gemini_api_key",
                "GEMINI_API_KEY",
            )
        )

        hint = QLabel("Claude: console.anthropic.com    Gemini: aistudio.google.com")
        hint.setObjectName("panelSubtitle")
        card_lay.addWidget(hint)
        return card

    def _make_key_row(self, label: str, placeholder: str, setting_key: str, env_var: str) -> QFrame:
        row = QFrame()
        row.setObjectName("settingsRow")
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(18, 14, 18, 14)
        row_lay.setSpacing(12)

        info = QVBoxLayout()
        info.setSpacing(5)
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size:12px;font-weight:600;background:transparent;")

        from PyQt6.QtCore import QSettings as _QSettings
        import os

        saved = _QSettings("BES", "BridgeEngineeringSuite").value(setting_key, "")
        if not saved:
            saved = os.environ.get(env_var, "")

        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText(placeholder)
        field.setFixedHeight(36)
        if saved:
            field.setText(saved)

        info.addWidget(lbl)
        info.addWidget(field)
        row_lay.addLayout(info, 1)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryBtn")
        save_btn.setFixedSize(78, 36)

        def _save():
            from PyQt6.QtCore import QSettings as _QSettings2, QTimer

            _QSettings2("BES", "BridgeEngineeringSuite").setValue(setting_key, field.text().strip())
            save_btn.setText("Saved")
            QTimer.singleShot(1400, lambda: save_btn.setText("Save"))

        save_btn.clicked.connect(_save)
        row_lay.addWidget(save_btn)

        show_btn = QPushButton("Show")
        show_btn.setObjectName("secondaryBtn")
        show_btn.setCheckable(True)
        show_btn.setFixedSize(76, 36)

        def _toggle(checked: bool):
            field.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
            show_btn.setText("Hide" if checked else "Show")

        show_btn.clicked.connect(_toggle)
        row_lay.addWidget(show_btn)
        return row

    def _about_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(6)

        header = icon_label("About", "info", text_size=14)
        layout.addWidget(header)

        for text in (
            "Bridge Engineering Suite v2.0",
            "Local desktop build powered by Python and PyQt6",
            "AI providers: Anthropic Claude and Google Gemini with fallback support",
        ):
            label = QLabel(text)
            label.setObjectName("panelSubtitle")
            layout.addWidget(label)
        return card

    def _theme_style(self, key: str, active: bool) -> str:
        a, b = THEME_SWATCHES[key]
        if active:
            return (
                "QPushButton{"
                f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {a},stop:1 {b});"
                "color:#FFFFFF;border:none;border-radius:12px;font-weight:800;"
                "}"
            )
        return (
            "QPushButton{"
            f"background:{COLORS['input_bg']};color:{COLORS['text_secondary']};"
            f"border:1px solid {COLORS['border_dark']};border-radius:12px;font-weight:700;"
            "}"
            "QPushButton:hover{"
            f"border-color:{a};color:{COLORS['text_primary']};background:{COLORS['hover_bg']};"
            "}"
        )

    def _refresh_ui(self):
        theme = current_theme()
        for key, btn in self._theme_buttons.items():
            is_active = theme == key
            btn.setChecked(is_active)
            btn.setText(f"\u2713  {THEME_NAMES[key]}" if is_active else THEME_NAMES[key])
            btn.setStyleSheet(self._theme_style(key, is_active))
        self._indicator.setText(f"Current theme: {THEME_NAMES.get(theme, 'Studio')}")

    def _set_theme(self, theme: str):
        apply_theme(theme, QApplication.instance())
        self._refresh_ui()
        win = self._win
        win._sync_top_bar()
        # Rebuild content panels so construction-time inline styles pick up
        # the new theme's font colors proportionally.
        win._rebuild_themed_panels()
        if hasattr(win, "knowledge_panel"):
            panel = win.knowledge_panel
            if hasattr(panel, "_sync_theme"):
                panel._sync_theme()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_ui()


class BlueprintThumb(QFrame):
    """Faint 'blueprint' technical-drawing thumbnail for tool cards."""

    def __init__(self, kind: str = "plan", parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setObjectName("toolThumb")
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event):
        # An exception raised inside a Qt paint callback aborts the whole
        # process (exit 0xC0000409) instead of just skipping a frame, so
        # degrade to the plain widget rather than take the app down.
        try:
            self._paint_blueprint()
        except Exception:
            import traceback

            traceback.print_exc()

    def _paint_blueprint(self):
        # PyQt6 has no int-arg drawLine/drawRect overloads that accept float
        # coordinates: use the QLineF/QRectF float primitives throughout.
        painter = QPainter(self)
        try:
            self._paint_blueprint_content(painter)
        finally:
            painter.end()

    def _paint_blueprint_content(self, painter: QPainter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        # White CAD-sheet look with fine linework (mock: 01_home thumbnails)
        painter.fillRect(rect, QColor("#FFFFFF"))

        line = QColor("#E2EAF3")
        painter.setPen(QPen(line, 1))
        step = 16
        x = 0.0
        while x < rect.width():
            painter.drawLine(QLineF(x, 0, x, rect.height()))
            x += step
        y = 0.0
        while y < rect.height():
            painter.drawLine(QLineF(0, y, rect.width(), y))
            y += step

        line = QColor("#46587A")
        line.setAlpha(220)
        painter.setPen(QPen(line, 1.3))
        m = 12
        w = rect.width() - 2 * m
        h = rect.height() - 2 * m
        top = rect.top() + m
        left = rect.left() + m
        kind = self._kind
        # a simple bridge cross-section / plan silhouette per kind
        if kind == "bridge":
            painter.drawLine(QLineF(left, top + h * 0.5, left + w, top + h * 0.5))
            for i in range(1, 6):
                xb = left + w * i / 6
                painter.drawLine(QLineF(xb, top + h * 0.18, xb, top + h * 0.82))
            painter.drawRect(QRectF(left + w * 0.05, top + h * 0.25, w * 0.9, h * 0.5))
        elif kind == "girder":
            painter.drawLine(QLineF(left, top + h * 0.7, left + w, top + h * 0.7))
            painter.drawLine(QLineF(left, top + h * 0.4, left + w, top + h * 0.4))
            for i in range(0, 7):
                xb = left + w * i / 6
                painter.drawLine(QLineF(xb, top + h * 0.4, xb, top + h * 0.7))
        elif kind == "gad":
            painter.drawRect(QRectF(left, top + h * 0.15, w, h * 0.7))
            line = QColor("#46587A")
            line.setAlpha(140)
            painter.setPen(QPen(line, 1))
            for i in range(1, 8):
                xc = left + w * i / 8
                painter.drawLine(QLineF(xc, top + h * 0.15, xc, top + h * 0.85))
        elif kind == "hydraulic":
            wl = left + w * 0.35
            painter.drawLine(QLineF(left, top + h * 0.3, left + w, top + h * 0.3))
            painter.drawLine(QLineF(wl, top + h * 0.1, wl, top + h * 0.9))
            painter.drawEllipse(QRectF(left + w * 0.1, top + h * 0.5, w * 0.2, h * 0.3))
        elif kind == "bore":
            cx = left + w * 0.5
            painter.drawLine(QLineF(cx, top, cx, top + h))
            for i in range(1, 6):
                yy = top + h * i / 6
                painter.drawLine(QLineF(cx - 8, yy, cx + 8, yy))
        else:  # plan / general
            painter.drawRect(QRectF(left, top, w, h))
            painter.drawLine(QLineF(left, top + h * 0.5, left + w, top + h * 0.5))
            painter.drawLine(QLineF(left + w * 0.5, top, left + w * 0.5, top + h))


class HomePanel(QWidget):
    """Landing dashboard matching the reference design: hero, search/filter
    toolbar, Workflow Tools grid, Reference & Settings, a right rail with
    greeting, recent projects, quick links, and a status footer, plus an
    intelligence band. Every Open button / card is wired to a real panel."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self._win = win
        self._tool_cards: list[QFrame] = []
        self._section_frames: dict[str, QFrame] = {}
        self._section_grids: dict[str, QGridLayout] = {}
        self._build()

    def _build(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        content = QVBoxLayout(container)
        content.setContentsMargins(18, 16, 18, 18)
        content.setSpacing(12)
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content.addWidget(self._hero())
        content.addLayout(self._search_toolbar())

        main_row = QHBoxLayout()
        main_row.setSpacing(14)
        main_row.addLayout(self._left_column(), 1)
        main_row.addWidget(self._right_rail())
        content.addLayout(main_row)

        content.addWidget(self._ai_band())
        content.addStretch()

    # -- Hero -------------------------------------------------------------

    def _hero(self) -> QFrame:
        hero = HeroBanner()
        lay = QVBoxLayout(hero)
        lay.setContentsMargins(30, 22, 22, 12)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(3)
        title = QLabel("Bridge Engineering Suite")
        title.setObjectName("heroKicker")
        left.addWidget(title)

        subtitle = QLabel("From Concept to Construction")
        subtitle.setObjectName("heroTitle")
        subtitle.setWordWrap(True)
        left.addWidget(subtitle)

        tagline = QLabel("Integrated tools for railway & highway bridge engineering.")
        tagline.setObjectName("heroSubtitle")
        tagline.setWordWrap(True)
        left.addWidget(tagline)
        top.addLayout(left, 3)

        quote = QFrame()
        quote.setObjectName("heroQuote")
        ql = QHBoxLayout(quote)
        ql.setContentsMargins(16, 12, 16, 12)
        ql.setSpacing(10)
        qmark = QLabel("“")
        # light-blue mark on the dark glass quote card (card bg is theme-independent)
        qmark.setStyleSheet("color:#BFDBFE;font-size:34px;font-weight:800;background:transparent;")
        ql.addWidget(qmark)
        qtitle = QLabel("Stronger Infrastructure for a Connected Tomorrow")
        qtitle.setObjectName("heroQuoteTitle")
        qtitle.setWordWrap(True)
        ql.addWidget(qtitle, 1)
        qbtns = QVBoxLayout()
        qbtns.setSpacing(6)
        for _ in range(2):
            b = QPushButton()
            b.setObjectName("heroArrowBtn")
            b.setIcon(QIcon(icon_pixmap("chevron-right", "#FFFFFF", 14)))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            qbtns.addWidget(b)
        ql.addLayout(qbtns)
        top.addWidget(quote, 1)
        lay.addLayout(top)

        lay.addStretch()

        features = QHBoxLayout()
        features.setSpacing(26)
        for text, ico, col in (
            ("Faster Workflows", "bolt", "#F59E0B"),
            ("Standards Compliant", "shield", "#1668C7"),
            ("AI-Powered Assistance", "gear", "#0EA5E9"),
            ("Your Knowledge, Always Available", "database", "#16A34A"),
        ):
            chip = QFrame()
            chip.setStyleSheet("background:transparent;")
            fl = QHBoxLayout(chip)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(7)
            glyph = QLabel()
            glyph.setPixmap(icon_pixmap(ico, col, 20))
            glyph.setFixedSize(20, 20)
            glyph.setScaledContents(True)
            fl.addWidget(glyph)
            words = text.split(" ")
            if len(words) >= 3:
                body = f"{words[0]} {words[1]}<br>{' '.join(words[2:])}"
            else:
                body = text
            txt = QLabel(body)
            txt.setObjectName("heroFeature")
            txt.setTextFormat(Qt.TextFormat.RichText)
            fl.addWidget(txt)
            features.addWidget(chip)
        features.addStretch()
        lay.addLayout(features)
        return hero

    # -- Search + filter toolbar ------------------------------------------

    def _search_toolbar(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)

        bar = QFrame()
        bar.setObjectName("searchToolbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("homeSearch")
        self.search.setPlaceholderText("Search tools, workflows, standards, or type a question...")
        self.search.setFixedHeight(38)
        self.search.textChanged.connect(self._filter_text)
        lay.addWidget(self.search, 1)
        hint = QLabel("Ctrl + K")
        hint.setObjectName("searchHint")
        lay.addWidget(hint)
        col.addWidget(bar)

        chips = QHBoxLayout()
        chips.setSpacing(10)
        chips.addStretch()
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        for label, wide in (
            ("All", False),
            ("Workflow Tools", True),
            ("Checks & Calcs", True),
            ("Reference", True),
            ("Favorites", True),
        ):
            chip = QPushButton(label)
            chip.setObjectName("chipButton")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFixedHeight(34)
            chip.setMinimumWidth(130 if wide else 74)
            chip.clicked.connect(lambda _checked=False, l=label: self._filter_category(l))
            self._chip_group.addButton(chip)
            chips.addWidget(chip)
            if label == "All":
                chip.setChecked(True)
        chips.addStretch()
        col.addLayout(chips)
        return col

    def _left_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(10)

        col.addWidget(self._section_header(
            "Workflow Tools", "Create, process and generate bridge drawings with ease.",
            "bridge", self._view_all_workflow))
        wf_grid = QGridLayout()
        wf_grid.setHorizontalSpacing(12)
        wf_grid.setVerticalSpacing(12)
        wf_cards = self._workflow_cards()
        for i, card in enumerate(wf_cards):
            wf_grid.addWidget(card, i // 3, i % 3)
        self._section_grids["Workflow Tools"] = wf_grid
        col.addLayout(wf_grid)

        col.addSpacing(4)
        col.addWidget(self._section_header(
            "Reference & Settings", "Access knowledge resources, sync data and configure your workspace.",
            "book-open", self._view_all_reference))
        ref_grid = QGridLayout()
        ref_grid.setHorizontalSpacing(12)
        ref_grid.setVerticalSpacing(12)
        ref_cards = self._reference_cards()
        for i, card in enumerate(ref_cards):
            ref_grid.addWidget(card, i // 3, i % 3)
        self._section_grids["Reference"] = ref_grid
        col.addLayout(ref_grid)
        return col

    def _section_header(self, title: str, subtitle: str, icon_name: str, handler) -> QFrame:
        head = QFrame()
        head.setStyleSheet("background:transparent;")
        row = QHBoxLayout(head)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)
        glyph = QLabel()
        glyph.setPixmap(icon_pixmap(icon_name, COLORS.get("accent", "#1668C7"), 24))
        glyph.setFixedSize(26, 26)
        glyph.setScaledContents(True)
        row.addWidget(glyph)
        col = QVBoxLayout()
        col.setSpacing(1)
        lbl = QLabel(title)
        lbl.setObjectName("sectionTitle")
        col.addWidget(lbl)
        sub = QLabel(subtitle)
        sub.setObjectName("panelSubtitle")
        col.addWidget(sub)
        row.addLayout(col, 1)
        btn = QPushButton("View All  \u2192")
        btn.setObjectName("viewAllBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(handler)
        row.addWidget(btn)
        return head

    # (icon_key, title, desc, page_index, thumb_kind, tile_color, ai_badge)
    _WORKFLOW_SPECS = [
        ("cd", "CD Processing", "Consolidated construction-document workflow.", 1, "plan", "#1668C7", False),
        ("cad", "CAD Process", "Scanned drawings into structured CAD output.", 2, "bridge", "#16A34A", False),
        ("cad2", "CAD Process 2", "Dimension-first drawing extraction and DXF.", 3, "girder", "#7C3AED", True),
        ("gadgen", "GAD Generator", "Prompt + dimensions \u2192 parametric GAD as AutoLISP + DXF.", 4, "gad", "#EA580C", False),
        ("gad", "GAD Checking", "Verify corrected drawings against markups.", 5, "bridge", "#0D9488", True),
        ("hydraulic", "Hydraulic Calcs", "Waterway and bridge hydraulic adequacy.", 6, "hydraulic", "#DC2626", True),
    ]

    _REFERENCE_SPECS = [
        ("kb", "Knowledge Base", "Search manuals, codes and practice exam questions.", 8, "book", "#7C3AED", True),
        ("sync", "Sheets Sync", "Pull live project tracking data from Google Sheets.", 9, "plan", "#1668C7", False),
    ]

    def _workflow_cards(self) -> list[QFrame]:
        return [self._tool_card(*spec) for spec in self._WORKFLOW_SPECS]

    def _reference_cards(self) -> list[QFrame]:
        return [self._tool_card(*spec) for spec in self._REFERENCE_SPECS]

    @staticmethod
    def _tile_pixmap(glyph: str, color: str, size: int = 46) -> QPixmap:
        """Solid rounded tile with a white vector glyph (tool-card icon)."""
        ss = 2.0
        px = int(size * ss)
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(ss, ss)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(size), float(size), 12.0, 12.0)
        painter.fillPath(path, QColor(color))
        glyph_size = size * 0.52
        renderer_pix = icon_pixmap(glyph, "#FFFFFF", int(glyph_size * ss))
        painter.drawPixmap(
            int((size - glyph_size) / 2 * ss), int((size - glyph_size) / 2 * ss),
            int(glyph_size * ss), int(glyph_size * ss), renderer_pix,
        )
        painter.end()
        pm.setDevicePixelRatio(ss)
        return pm

    def _tool_card(self, icon_key: str, title: str, desc: str, index: int,
                   kind: str, tile_color: str, ai_badge: bool) -> QFrame:
        card = QFrame()
        card.setObjectName("toolCard")
        card._search_key = f"{title} {desc}".lower()
        card.setMinimumHeight(220)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        tile = QLabel()
        tile.setObjectName("toolIconTile")
        tile.setFixedSize(46, 46)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile_path = get_icon_path(icon_key)
        if tile_path and os.path.isfile(tile_path):
            pm = QPixmap(tile_path).scaled(
                34, 34, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            tile.setPixmap(pm)
        else:
            tile.setPixmap(self._tile_pixmap(icon_key or "folder", tile_color))
        top.addWidget(tile)

        t_lbl = QLabel(title)
        t_lbl.setObjectName("toolTitle")
        top.addWidget(t_lbl, 1)

        star = QPushButton()
        star.setObjectName("starBtn")
        star.setIcon(QIcon(icon_pixmap("star", "#B9C6D6", 15)))
        star.setCursor(Qt.CursorShape.PointingHandCursor)
        star.setFixedSize(20, 20)
        star.clicked.connect(lambda _=False, b=star: self._toggle_fav(b))
        top.addWidget(star, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        desc_lbl = QLabel(desc)
        desc_lbl.setObjectName("toolDesc")
        desc_lbl.setWordWrap(True)
        lay.addWidget(desc_lbl)

        thumb_wrap = QFrame()
        thumb_wrap.setStyleSheet("background:transparent;")
        tl = QVBoxLayout(thumb_wrap)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        thumb = BlueprintThumb(kind)
        tl.addWidget(thumb)
        if ai_badge:
            badge = QLabel("AI-Powered")
            badge.setObjectName("aiBadge")
            badge.setParent(thumb)
            badge.adjustSize()
            badge.move(10, thumb.height() - badge.height() - 10)
            badge.show()
            thumb._ai_badge = badge  # keep a reference alive
        lay.addWidget(thumb_wrap, 1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        learn_icon = QLabel()
        learn_icon.setPixmap(icon_pixmap("book-open", COLORS.get("text_tertiary", "#7E8FA6"), 13))
        learn_icon.setFixedSize(13, 13)
        learn_icon.setScaledContents(True)
        foot.addWidget(learn_icon)
        learn = QPushButton("Learn More")
        learn.setObjectName("learnBtn")
        learn.setCursor(Qt.CursorShape.PointingHandCursor)
        learn.clicked.connect(lambda: self._learn_more(title, index))
        foot.addWidget(learn)
        foot.addStretch()
        open_btn = QPushButton("Open  \u2192")
        open_btn.setObjectName("openBtn")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(lambda: self._win._switch(index))
        foot.addWidget(open_btn)
        lay.addLayout(foot)

        self._tool_cards.append(card)
        return card

    def _toggle_fav(self, button: QPushButton):
        checked = button.property("fav")
        if checked:
            button.setProperty("fav", False)
            button.setIcon(QIcon(icon_pixmap("star", COLORS.get("text_tertiary", "#7E8FA6"), 16)))
        else:
            button.setProperty("fav", True)
            button.setIcon(QIcon(icon_pixmap("star", COLORS.get("warning", "#FBBF24"), 16)))

    def _learn_more(self, title: str, index: int):
        self._win._switch(index)

    def _view_all_workflow(self):
        self._win._switch(1)

    def _view_all_reference(self):
        self._win._switch(8)

    # ── Right rail ────────────────────────────────────────────────────────
    def _right_rail(self) -> QFrame:
        rail = QFrame()
        rail.setFixedWidth(320)
        rail.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        lay.addWidget(self._greeting_card())
        lay.addWidget(self._recent_projects_card())
        lay.addWidget(self._quick_links_card())

        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        status_row.addWidget(self._system_status_card(), 1)
        status_row.addWidget(self._secure_card(), 1)
        lay.addSpacing(2)
        lay.addLayout(status_row)
        lay.addStretch()
        return rail

    def _greeting_card(self) -> QFrame:
        import datetime

        card = QFrame()
        card.setObjectName("railSection")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        now = datetime.datetime.now()
        hour = now.hour
        greeting = "Good Morning" if hour < 12 else ("Good Afternoon" if hour < 18 else "Good Evening")

        sun = QLabel()
        sun.setPixmap(icon_pixmap("sun", "#F59E0B", 34))
        sun.setFixedSize(34, 34)
        sun.setScaledContents(True)
        lay.addWidget(sun)

        col = QVBoxLayout()
        col.setSpacing(1)
        g = QLabel(greeting + ",")
        g.setObjectName("greetingSub")
        col.addWidget(g)
        name = QLabel("Manoj Steve")
        name.setObjectName("greetingName")
        col.addWidget(name)
        sub = QLabel("Build with precision. Design for generations.")
        sub.setObjectName("secureSub")
        sub.setWordWrap(True)
        col.addWidget(sub)
        lay.addLayout(col, 1)

        date_box = QFrame()
        date_box.setObjectName("dateBox")
        db_lay = QVBoxLayout(date_box)
        db_lay.setContentsMargins(10, 6, 10, 6)
        db_lay.setSpacing(0)
        day = QLabel(now.strftime("%a\n%d %b %Y"))
        day.setObjectName("dateLabel")
        day.setAlignment(Qt.AlignmentFlag.AlignCenter)
        db_lay.addWidget(day)
        clock = QLabel(now.strftime("%I:%M %p"))
        clock.setObjectName("greetingTime")
        clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        db_lay.addWidget(clock)
        lay.addWidget(date_box)
        return card

    def _recent_projects_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("railSection")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(6, 10, 6, 8)
        lay.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(10, 0, 6, 4)
        glyph = QLabel()
        glyph.setPixmap(icon_pixmap("clock", COLORS.get("accent", "#1668C7"), 18))
        glyph.setFixedSize(18, 18)
        glyph.setScaledContents(True)
        head.addWidget(glyph)
        title = QLabel("Recent Projects")
        title.setObjectName("railHeader")
        head.addWidget(title)
        head.addStretch()
        btn = QPushButton("View All  \u2192")
        btn.setObjectName("viewAllBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self._win._switch(1))
        head.addWidget(btn)
        lay.addLayout(head)

        data = [
            ("ROB_124_CD", "CD Processing  \u2022  2 hours ago", "In Progress", "info", 1),
            ("RailwayBridge_GAD", "GAD Generator  \u2022  Yesterday", "Completed", "success", 4),
            ("MinorBridge_Hydraulics", "Hydraulic Calcs  \u2022  3 days ago", "In Progress", "info", 6),
            ("YardRemodelling_CAD", "CAD Process  \u2022  5 days ago", "Completed", "success", 2),
            ("BoxCulvert_Check", "GAD Checking  \u2022  1 week ago", "Review", "warning", 5),
        ]
        for name, meta, status, kind, index in data:
            row = QFrame()
            row.setObjectName("projectRow")
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 8, 10, 8)
            rl.setSpacing(9)
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon_pixmap("file-text", COLORS.get("accent", "#1668C7"), 16))
            icon_lbl.setFixedSize(16, 16)
            icon_lbl.setScaledContents(True)
            rl.addWidget(icon_lbl)
            c = QVBoxLayout()
            c.setSpacing(1)
            n = QLabel(name)
            n.setObjectName("projectName")
            c.addWidget(n)
            m = QLabel(meta)
            m.setObjectName("projectMeta")
            c.addWidget(m)
            rl.addLayout(c, 1)
            rl.addWidget(status_label(status, kind, size=10))
            dots = QLabel()
            dots.setPixmap(icon_pixmap("dots", COLORS.get("text_tertiary", "#7E8FA6"), 14))
            dots.setFixedSize(14, 14)
            dots.setScaledContents(True)
            rl.addWidget(dots)
            row.mouseReleaseEvent = lambda ev, i=index: self._win._switch(i)
            lay.addWidget(row)
        return card

    def _quick_links_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("railSection")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 8, 4)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 6, 2)
        glyph = QLabel()
        glyph.setPixmap(icon_pixmap("link", COLORS.get("accent", "#1668C7"), 18))
        glyph.setFixedSize(18, 18)
        glyph.setScaledContents(True)
        head.addWidget(glyph)
        title = QLabel("Quick Links")
        title.setObjectName("railHeader")
        head.addWidget(title)
        head.addStretch()
        btn = QPushButton("Edit")
        btn.setObjectName("viewAllBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        head.addWidget(btn)
        lay.addLayout(head)

        links = [
            ("IR Codes & Manuals", "https://www.iricen.gov.in/iricen/CodeManualNew.jsp"),
            ("RDSO Drawings", "http://10.100.2.4/index.aspx"),
            ("E.DAS - 2.0", "https://edas.rcil.gov.in/"),
            ("RRB Secunderabad", "https://rrbsecunderabad.gov.in/"),
            ("Indian Railways Codes & Manuals", "https://indianrailways.gov.in/railwayboard/view_section.jsp?lang=0&id=0%2C5%2C377"),
        ]
        for name, url in links:
            row = QFrame()
            row.setObjectName("quickLinkRow")
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setToolTip(url)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 9, 8, 9)
            rl.setSpacing(8)
            n = QLabel(name)
            n.setObjectName("quickLinkName")
            rl.addWidget(n, 1)
            glyph = QLabel()
            glyph.setPixmap(icon_pixmap("external", COLORS.get("accent", "#1668C7"), 14))
            glyph.setFixedSize(14, 14)
            glyph.setScaledContents(True)
            rl.addWidget(glyph)
            row.mouseReleaseEvent = lambda ev, u=url: self._win._open_quick_link(u)
            lay.addWidget(row)
        lay.addStretch()
        return card

    def _system_status_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("systemStatusCard")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        pulse = QLabel()
        pulse.setPixmap(icon_pixmap("pulse", "#16A34A", 22))
        pulse.setFixedSize(22, 22)
        pulse.setScaledContents(True)
        lay.addWidget(pulse)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel("System Status")
        t.setObjectName("systemStatusTitle")
        col.addWidget(t)
        s = QLabel("\u25CF All systems operational")
        s.setObjectName("systemStatusSub")
        col.addWidget(s)
        lay.addLayout(col, 1)
        return card

    def _secure_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("systemStatusCard")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        shield = QLabel()
        shield.setPixmap(icon_pixmap("shield", "#16A34A", 22))
        shield.setFixedSize(22, 22)
        shield.setScaledContents(True)
        lay.addWidget(shield)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel("Your data is secure")
        t.setObjectName("secureTitle")
        col.addWidget(t)
        s = QLabel("and stays on your machine.")
        s.setObjectName("secureSub")
        col.addWidget(s)
        lay.addLayout(col, 1)
        return card

    def _ai_band(self) -> QFrame:
        band = QFrame()
        band.setObjectName("aiBand")
        lay = QHBoxLayout(band)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)

        chip = QFrame()
        chip.setObjectName("aiBandChip")
        chip.setFixedSize(44, 44)
        cl = QVBoxLayout(chip)
        cl.setContentsMargins(0, 0, 0, 0)
        mark = QLabel("AI")
        mark.setObjectName("aiBandChipText")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(mark)
        lay.addWidget(chip)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        kicker = QLabel("Engineering Intelligence, Built In")
        kicker.setObjectName("aiBandKicker")
        copy.addWidget(kicker)
        sub = QLabel("Let AI assist with code lookup, design checks, and smart suggestions.")
        sub.setObjectName("aiBandSub")
        copy.addWidget(sub)
        lay.addLayout(copy, 1)

        btn = QPushButton("Explore AI Features  \u2192")
        btn.setObjectName("aiBandBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self._win._switch(1))
        lay.addWidget(btn)
        return band

    def _filter_text(self, text: str):
        query = text.strip().lower()
        for card in getattr(self, "_tool_cards", []):
            key = getattr(card, "_search_key", "")
            card.setVisible(query in key)

    def _filter_category(self, label: str):
        query = self.search.text().strip().lower()
        self._filter_text(self.search.text())

    def focus_search(self):
        self.search.setFocus()


class MainWindow(QMainWindow):
    _PAGE_INFO = [
        ("Home", "Overview of every workflow tool in the suite."),
        ("CD Processing", "Run consolidated construction document workflows."),
        ("CAD Process", "Convert scanned drawings into structured CAD output."),
        ("CAD Process 2", "Dimension-first bridge drawing extraction and DXF generation."),
        ("GAD Generator", "Prompt + dimensions → parametric GAD as AutoLISP + DXF."),
        ("GAD Checking", "Verify corrected drawings against marked-up observations."),
        ("Hydraulic Calcs", "Calculate waterway and bridge hydraulic adequacy."),
        ("Bore Log → DXF", "Convert bore-log reports into AutoCAD DXF drawings."),
        ("Knowledge Base", "Search manuals and practice exam-style questions."),
        ("Sheets Sync", "Pull live project tracking data from Google Sheets."),
        ("Settings", "Theme, local credentials, and application details."),
    ]
    _PAGE_ICON_KEYS = ["home", "cd", "cad", "cad2", "gadgen", "gad", "hydraulic", "borelog", "kb", "import", "settings"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bridge Engineering Suite v2.0")
        self.setMinimumSize(1080, 700)
        avail = QApplication.primaryScreen().availableGeometry()
        w = max(self.minimumWidth(),  min(1280, avail.width()  - 40))
        h = max(self.minimumHeight(), min(820,  avail.height() - 60))
        self.resize(w, h)
        self.move(avail.center().x() - w // 2, avail.center().y() - h // 2)

        self._sidebar_expanded_w = 220
        self._sidebar_collapsed_w = 64
        self._sidebar_pinned = QSettings("BES", "BridgeEngineeringSuite").value(
            "sidebar_pinned", True, type=bool
        )

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = self._build_sidebar()
        root.addWidget(self.sidebar)

        content_shell = QWidget()
        content_shell.setObjectName("contentShell")
        content_layout = QVBoxLayout(content_shell)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.top_bar = self._build_top_bar()
        content_layout.addWidget(self.top_bar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")
        content_layout.addWidget(self.stack, 1)

        self.footer_bar = self._build_footer_bar()
        content_layout.addWidget(self.footer_bar)

        self.home_panel = HomePanel(self)
        self.cd_panel = CDPanel()
        self.cad_panel = CADPanel()
        self.cad2_panel = CAD2Panel()
        self.gadgen_panel = GadGeneratorPanel()
        self.gad_panel = GADPanel()
        self.hydraulic_panel = HydraulicPanel()
        self.knowledge_panel = KnowledgePanel()
        self.borelog_panel = BoreLogPanel()
        self.calculated_notes_panel = CalculatedNotesPanel()
        self.sheets_sync_panel = SheetsSyncPanel()
        self.settings_panel = SettingsPanel(self)

        for panel in (
            self.home_panel,
            self.cd_panel,
            self.cad_panel,
            self.cad2_panel,
            self.gadgen_panel,
            self.gad_panel,
            self.hydraulic_panel,
            self.borelog_panel,
            self.knowledge_panel,
            self.calculated_notes_panel,  # page 9  (sidebar: after Bore Log)
            self.sheets_sync_panel,       # page 10
            self.settings_panel,          # page 11
        ):
            self.stack.addWidget(panel)

        root.addWidget(content_shell, 1)
        self._switch(0)

    # -- Theme re-skin -----------------------------------------------------
    # Panels bake COLORS[...] into inline QSS at construction time, so a
    # runtime theme switch left them with the old font colors. Rather than
    # chase every inline style, rebuild the panels once on switch — cheap
    # (a few hundred ms), fully correct, and it preserves form values in the
    # Hydraulic Calcs forms via _swap_panel.

    def _rebuild_themed_panels(self):
        """Recreate content panels so inline styles pick up the new theme."""
        current = self.stack.currentIndex()
        swaps = (
            (0, "home_panel", lambda: HomePanel(self)),
            (1, "cd_panel", CDPanel),
            (2, "cad_panel", CADPanel),
            (3, "cad2_panel", CAD2Panel),
            (4, "gadgen_panel", GadGeneratorPanel),
            (5, "gad_panel", GADPanel),
            (6, "hydraulic_panel", HydraulicPanel),
            (8, "knowledge_panel", KnowledgePanel),
            (9, "calculated_notes_panel", CalculatedNotesPanel),
            (11, "settings_panel", lambda: SettingsPanel(self)),
        )
        for index, attr, factory in swaps:
            self._swap_panel(index, attr, factory())
        # BoreLog (7) and Sheets Sync (10) follow the global QSS closely enough
        # not to need a rebuild; skip them to keep their session state.
        # Calculated Notes (9) IS rebuilt (theme-baked styles) but carries its
        # session notes across via export/restore.
        self.stack.setCurrentIndex(current)
        self._sync_top_bar()

    def _swap_panel(self, index: int, attr: str, new_panel: QWidget):
        """Replace the panel at `index`, copying `attr` onto self and
        transferring form values from the old Hydraulic panel if needed."""
        old = self.stack.widget(index)
        old_was_hydraulic = old is self.hydraulic_panel
        old_inputs = None
        if old_was_hydraulic:
            try:
                form = (self.hydraulic_panel._form_newline
                        if self.hydraulic_panel._mode == "1"
                        else self.hydraulic_panel._form_doubling)
                if form is not None:
                    old_inputs = form.get_inputs()
            except Exception:
                old_inputs = None

        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(index, new_panel)
        setattr(self, attr, new_panel)

        if old_was_hydraulic and old_inputs:
            new_form = (new_panel._form_newline if new_panel._mode == "1"
                        else new_panel._form_doubling)
            if new_form is not None:
                _restore_hydraulic_inputs(new_form, old_inputs)

        # Preserve Calculated Notes session entries across themed rebuilds.
        if attr == "calculated_notes_panel" and isinstance(old, CalculatedNotesPanel) \
                and isinstance(new_panel, CalculatedNotesPanel):
            try:
                new_panel.restore_entries(old.export_entries())
            except Exception:
                pass

    def _build_footer_bar(self) -> QFrame:
        """Bottom status strip: version, all-systems status, tagline (no 'AI')."""
        bar = QFrame()
        bar.setObjectName("footerBar")
        bar.setFixedHeight(30)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(8)

        version = QLabel("BES v2.0  |  Local Build")
        version.setObjectName("footerSecure")
        lay.addWidget(version)

        lay.addStretch()

        dot = QLabel()
        dot.setObjectName("statusDot")
        dot.setFixedSize(8, 8)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(dot)
        status = QLabel("All systems operational")
        status.setObjectName("footerStatus")
        lay.addWidget(status)

        lay.addStretch()

        tagline = QLabel("PEOPLE  |  PLACES  |  POSSIBILITIES")
        tagline.setObjectName("footerText")
        lay.addWidget(tagline)
        return bar

    def _build_sidebar(self) -> QFrame:
        sidebar = Sidebar()
        sidebar.setObjectName("sidebar")
        start_w = self._sidebar_expanded_w if self._sidebar_pinned else self._sidebar_collapsed_w
        sidebar.setMinimumWidth(start_w)
        sidebar.setMaximumWidth(start_w)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(4)

        brand = QFrame()
        brand.setObjectName("brandCard")
        brand_lay = QHBoxLayout(brand)
        # Slim margins + tight spacing give the text column every pixel of the
        # 220px sidebar so "Bridge Engineering Suite" and the tagline render
        # in full instead of clipping.
        brand_lay.setContentsMargins(8, 8, 6, 8)
        brand_lay.setSpacing(6)

        mark = BridgeLogo(34)
        self._brand_mark = mark
        brand_lay.addWidget(mark)

        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(2)
        logo = QLabel("BES")
        logo.setObjectName("logoLabel")
        subtitle = QLabel("Bridge Engineering Suite")
        subtitle.setObjectName("subLabel")
        tagline = QLabel("Design · Analyse\nDraft · Deliver")
        tagline.setObjectName("sideTagline")
        # Explicit two-line break keeps the tagline balanced; wordWrap is a
        # safety net if the column ever gets narrower than either line.
        tagline.setWordWrap(True)
        tagline.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        brand_text.addWidget(logo)
        brand_text.addWidget(subtitle)
        brand_text.addWidget(tagline)

        self._brand_text_wrap = QWidget()
        self._brand_text_wrap.setLayout(brand_text)
        self._brand_text_wrap.setStyleSheet("background: transparent;")
        brand_lay.addWidget(self._brand_text_wrap, 1)

        self.btn_pin = QPushButton("<<")
        self.btn_pin.setObjectName("pinButton")
        self.btn_pin.setFixedSize(20, 20)
        self.btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pin.clicked.connect(self._toggle_pin)
        brand_lay.addWidget(self.btn_pin)

        self._brand_card = brand
        self._brand_lay = brand_lay
        layout.addWidget(brand)

        self.btn_home = SidebarButton("Home", icon_key="home")
        self.btn_home.clicked.connect(lambda: self._switch(0))
        layout.addWidget(self.btn_home)
        self._sidebar_buttons = [self.btn_home]

        layout.addSpacing(8)
        self.nav_label_drawings = QLabel("DRAWINGS")
        self.nav_label_drawings.setObjectName("navLabel")
        layout.addWidget(self.nav_label_drawings)

        self.btn_cd = SidebarButton("CD Processing", icon_key="cd")
        self.btn_cad = SidebarButton("CAD Process", icon_key="cad")
        self.btn_cad2 = SidebarButton("CAD Process 2", icon_key="cad2")
        self.btn_gadgen = SidebarButton("GAD Generator", icon_key="gadgen")

        self.btn_cd.clicked.connect(lambda: self._switch(1))
        self.btn_cad.clicked.connect(lambda: self._switch(2))
        self.btn_cad2.clicked.connect(lambda: self._switch(3))
        self.btn_gadgen.clicked.connect(lambda: self._switch(4))

        self._sidebar_buttons += [self.btn_cd, self.btn_cad, self.btn_cad2, self.btn_gadgen]
        for btn in (self.btn_cd, self.btn_cad, self.btn_cad2, self.btn_gadgen):
            layout.addWidget(btn)

        layout.addSpacing(8)
        self.nav_label_checks = QLabel("CHECKS & CALCS")
        self.nav_label_checks.setObjectName("navLabel")
        layout.addWidget(self.nav_label_checks)

        self.btn_gad = SidebarButton("GAD Checking", icon_key="gad")
        self.btn_hydro = SidebarButton("Hydraulic Calcs", icon_key="hydraulic")
        self.btn_borelog = SidebarButton("Bore Log", icon_key="borelog")
        self.btn_calcnotes = SidebarButton("Calculated Notes", icon_key="calcnotes")

        self.btn_gad.clicked.connect(lambda: self._switch(5))
        self.btn_hydro.clicked.connect(lambda: self._switch(6))
        self.btn_borelog.clicked.connect(lambda: self._switch(7))
        self.btn_calcnotes.clicked.connect(lambda: self._switch(9))

        self._sidebar_buttons += [self.btn_gad, self.btn_hydro, self.btn_borelog,
                                  self.btn_calcnotes]
        for btn in (self.btn_gad, self.btn_hydro, self.btn_borelog, self.btn_calcnotes):
            layout.addWidget(btn)

        layout.addSpacing(8)
        self.nav_label_reference = QLabel("REFERENCE")
        self.nav_label_reference.setObjectName("navLabel")
        layout.addWidget(self.nav_label_reference)

        self.btn_kb = SidebarButton("Knowledge Base", icon_key="kb")
        self.btn_kb.clicked.connect(lambda: self._switch(8))
        layout.addWidget(self.btn_kb)
        self._sidebar_buttons.append(self.btn_kb)

        self.btn_sheets = SidebarButton("Sheets Sync", icon_key="import")
        self.btn_sheets.clicked.connect(lambda: self._switch(10))
        layout.addWidget(self.btn_sheets)
        self._sidebar_buttons.append(self.btn_sheets)

        for text, key, index in (("IRC Codes", "codesearch", 8), ("Standards Library", "book", 8)):
            alias = SidebarButton(text, icon_key=key)
            alias.setCheckable(False)
            alias.clicked.connect(lambda _=False, i=index: self._switch(i))
            layout.addWidget(alias)
            self._sidebar_buttons.append(alias)

        layout.addSpacing(8)
        self.nav_label_projects = QLabel("PROJECTS")
        self.nav_label_projects.setObjectName("navLabel")
        layout.addWidget(self.nav_label_projects)

        self.btn_project = SidebarButton("Project Manager", icon_key="folder")
        self.btn_project.setCheckable(False)
        self.btn_project.clicked.connect(lambda: self._switch(10))
        layout.addWidget(self.btn_project)
        self._sidebar_buttons.append(self.btn_project)

        layout.addSpacing(6)
        self.btn_help = SidebarButton("Help & Support", obj_name="settingsBtn", icon_key="info")
        self.btn_help.clicked.connect(self._open_help)
        layout.addWidget(self.btn_help)
        self._sidebar_buttons.append(self.btn_help)

        layout.addStretch()

        # Promo card — cable-stayed bridge photo with tagline overlay
        promo = PromoCard()
        self._side_promo = promo
        layout.addWidget(promo)

        layout.addSpacing(6)
        self.version_label = QLabel("BES v2.0  |  Local Build")
        self.version_label.setObjectName("versionLabel")
        layout.addWidget(self.version_label)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        status_dot = QLabel()
        status_dot.setObjectName("statusDot")
        status_dot.setFixedSize(8, 8)
        status_row.addWidget(status_dot)
        self._side_status = QLabel("All systems operational")
        self._side_status.setObjectName("sideStatus")
        status_row.addWidget(self._side_status)
        status_row.addStretch()
        self._side_status_row = QWidget()
        self._side_status_row.setLayout(status_row)
        self._side_status_row.setStyleSheet("background: transparent;")
        layout.addWidget(self._side_status_row)

        collapsed = not self._sidebar_pinned
        self._apply_sidebar_collapse(collapsed)

        return sidebar

    def _apply_sidebar_collapse(self, collapsed: bool):
        """Apply collapsed/expanded state to the sidebar chrome.

        The pin toggle stays visible in BOTH states — it is the only control
        that can bring the process names back after a collapse, so hiding it
        used to strand the sidebar as a bare icon rail forever.
        """
        self._brand_text_wrap.setVisible(not collapsed)
        self._brand_mark.setVisible(not collapsed)
        # Tighten the brand card so the lone pin button fits the narrow rail.
        self._brand_lay.setContentsMargins(4, 4, 4, 4) if collapsed else \
            self._brand_lay.setContentsMargins(8, 8, 6, 8)
        self.btn_pin.setVisible(True)
        self.btn_pin.setText(">>" if collapsed else "<<")
        self.btn_pin.setToolTip("Expand sidebar" if collapsed else "Collapse sidebar")
        self.nav_label_drawings.setVisible(not collapsed)
        self.nav_label_checks.setVisible(not collapsed)
        self.nav_label_reference.setVisible(not collapsed)
        self.nav_label_projects.setVisible(not collapsed)
        self.version_label.setVisible(not collapsed)
        self._side_promo.setVisible(not collapsed)
        self._side_status_row.setVisible(not collapsed)
        for btn in self._sidebar_buttons:
            btn.setCollapsed(collapsed)

    def _open_help(self):
        """Open a compact Help & Support summary (same content as Settings > About)."""
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.information(
            self,
            "Help & Support",
            "Bridge Engineering Suite v2.0\n\n"
            "Workflow tools: CD Processing, CAD Process, CAD Process 2, "
            "GAD Generator, GAD Checking, Hydraulic Calcs, Bore Log.\n\n"
            "Reference: Knowledge Base, Sheets Sync.\n\n"
            "API keys and themes live in Settings. "
            "Everything runs locally on this machine.",
        )

    # -- Sidebar collapse (manual toggle only) ---------------------------

    def _toggle_pin(self):
        self._sidebar_pinned = not self._sidebar_pinned
        QSettings("BES", "BridgeEngineeringSuite").setValue("sidebar_pinned", self._sidebar_pinned)
        collapsed = not self._sidebar_pinned
        self._set_sidebar_width(
            self._sidebar_collapsed_w if collapsed else self._sidebar_expanded_w, animate=True
        )
        self._apply_sidebar_collapse(collapsed)

    def _set_sidebar_labels_visible(self, visible: bool):
        self._apply_sidebar_collapse(not visible)

    def _set_sidebar_width(self, target: int, animate: bool):
        if not animate or _reduced_motion():
            self.sidebar.setMinimumWidth(target)
            self.sidebar.setMaximumWidth(target)
            return

        group = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            anim = QPropertyAnimation(self.sidebar, prop, self)
            anim.setDuration(_ANIM_PAGE)
            anim.setStartValue(self.sidebar.width())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(anim)
        self._sidebar_width_anim = group
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        # 66px carries 34px-tall controls plus breathing room; 62px with the
        # old margins left ~21px of usable height, which crushed the Hydraulic
        # Calcs mode dropdown and Smart Extract controls into a squeezed strip.
        bar.setFixedHeight(66)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        # Tagline strip on the left (mock: SAFE BRIDGES | SMARTER ENGINEERING | ...)
        # Decorative — hidden whenever a panel contributes top-bar controls so
        # the Hydraulic Calcs dropdown/Smart Extract row never gets squeezed.
        tagline = QLabel()
        tagline.setObjectName("topTagline")
        tagline.setText("SAFE BRIDGES   |   SMARTER ENGINEERING   |   BRIGHTER TOMORROW")
        layout.addWidget(tagline)
        self._tagline_label = tagline

        # Slot for panel-specific controls (e.g. Hydraulic Calcs' mode
        # dropdown + Smart Extract hint) rendered right next to the tagline
        # instead of duplicating a second title row inside the panel.
        # Stretch 1 + expanding height so panel controls are never squeezed:
        # the tagline and search yield leftover space to them instead.
        self.top_bar_extra_container = QFrame()
        self.top_bar_extra_container.setObjectName("topBarExtra")
        self.top_bar_extra_container.setVisible(False)
        self._top_bar_extra_layout = QHBoxLayout(self.top_bar_extra_container)
        self._top_bar_extra_layout.setContentsMargins(8, 0, 8, 0)
        self._top_bar_extra_layout.setSpacing(10)
        layout.addWidget(self.top_bar_extra_container, 1)

        layout.addStretch()

        # Global search
        self.global_search = QLineEdit()
        self.global_search.setObjectName("topSearch")
        self.global_search.setPlaceholderText("Search tools, standards, help...")
        self.global_search.setFixedSize(240, 34)
        self.global_search.returnPressed.connect(self._global_search_submitted)
        layout.addWidget(self.global_search)

        hint = QLabel("Ctrl + K")
        hint.setObjectName("searchHint")
        layout.addWidget(hint)
        self._search_hint = hint

        # Notification bell
        self.btn_bell = QPushButton()
        self.btn_bell.setObjectName("topIconBtn")
        self.btn_bell.setIcon(QIcon(icon_pixmap("bell", COLORS.get("text_secondary", "#42566E"), 17)))
        self.btn_bell.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bell.setToolTip("Notifications")
        self.btn_bell.clicked.connect(self._show_notifications)
        badge = QLabel(self.btn_bell)
        badge.setFixedSize(9, 9)
        badge.setStyleSheet("background:#EF4444;border-radius:4px;")
        badge.move(21, 5)
        badge.show()
        layout.addWidget(self.btn_bell)

        # Settings shortcut
        self.btn_top_settings = QPushButton()
        self.btn_top_settings.setObjectName("topIconBtn")
        self.btn_top_settings.setIcon(QIcon(icon_pixmap("gear", COLORS.get("text_secondary", "#C7D2E0"), 16)))
        self.btn_top_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_top_settings.setToolTip("Settings")
        self.btn_top_settings.clicked.connect(lambda: self._switch(11))
        layout.addWidget(self.btn_top_settings)

        # Profile chip
        profile = QFrame()
        profile.setObjectName("profileChip")
        profile.setFixedHeight(34)
        p_lay = QHBoxLayout(profile)
        p_lay.setContentsMargins(6, 3, 10, 3)
        p_lay.setSpacing(8)
        avatar = QLabel("MS")
        avatar.setObjectName("avatarLabel")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(28, 28)
        p_lay.addWidget(avatar)
        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        name_lbl = QLabel("Manoj Steve")
        name_lbl.setObjectName("profileName")
        sub_lbl = QLabel("Bridge Engineer")
        sub_lbl.setObjectName("profileSub")
        name_col.addWidget(name_lbl)
        name_col.addWidget(sub_lbl)
        p_lay.addLayout(name_col)
        chev = QPushButton()
        chev.setObjectName("profileChevron")
        chev.setIcon(QIcon(icon_pixmap("chevron-down", COLORS.get("text_secondary", "#C7D2E0"), 14)))
        chev.setCursor(Qt.CursorShape.PointingHandCursor)
        chev.setFixedSize(18, 18)
        chev.clicked.connect(self._show_profile_menu)
        p_lay.addWidget(chev)
        self._profile_chip = profile
        layout.addWidget(profile)

        # Theme selector/swatches removed from here — Settings panel already
        # has the full theme picker (see SettingsPanel, ~line 236) and is
        # the single source of truth for theme changes now. This reclaims
        # the top-bar space for panel-specific buttons (e.g. Hydraulic
        # Calcs' Smart Extract / Show Preview) instead of duplicating
        # theme controls on every page.
        return bar

    def _global_search_submitted(self):
        """Route a top-bar search to the closest matching tool panel."""
        query = self.global_search.text().strip().lower()
        if not query:
            return
        routes = [
            ("cd", 1), ("construction document", 1),
            ("cad process 2", 3), ("cad", 2), ("drawing", 2),
            ("gad generator", 4), ("gad", 5), ("check", 5),
            ("hydraulic", 6), ("bore", 7),
            ("knowledge", 8), ("manual", 8), ("quiz", 8),
            ("sheet", 10), ("sync", 10), ("track", 10),
            ("setting", 11), ("theme", 11), ("key", 11), ("api", 11),
            ("calculator", 9), ("calculated", 9), ("notes", 9),
            ("home", 0),
        ]
        for needle, index in routes:
            if needle in query:
                self._switch(index)
                return
        self._switch(0)

    def _show_notifications(self):
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.information(
            self,
            "Notifications",
            "You are up to date.\n\nNo new notifications at the moment.",
        )

    def _show_profile_menu(self):
        menu = QMenu(self)
        menu.addAction("Profile — Manoj Steve")
        menu.addAction("Workspace — Local Build")
        menu.addSeparator()
        act_home = menu.addAction("Home")
        act_home.triggered.connect(lambda: self._switch(0))
        menu.exec(self._profile_chip.mapToGlobal(
            self._profile_chip.rect().bottomLeft()))

    def _open_quick_link(self, url: str):
        """Quick Links rail: open the reference site in the local browser."""
        QDesktopServices.openUrl(QUrl(url))

    def _sync_top_bar(self):
        # The redesigned top bar is a global strip (tagline + search + profile);
        # page identity is carried by each panel's own header, so there is
        # nothing per-page to sync here beyond panel-contributed controls.
        self._sync_top_bar_extra()

    def _sync_top_bar_extra(self):
        """Let the active panel contribute compact controls next to the page title."""
        panel = self.stack.currentWidget() if hasattr(self, "stack") else None
        widget = None
        if panel is not None and hasattr(panel, "top_bar_extra_widget"):
            widget = panel.top_bar_extra_widget()

        layout = self._top_bar_extra_layout
        while layout.count():
            item = layout.takeAt(0)
            taken = item.widget()
            if taken is not None:
                taken.setParent(None)

        if widget is not None:
            layout.addWidget(widget)
        self.top_bar_extra_container.setVisible(widget is not None)
        # Panel controls take over the tagline's strip — the tagline is
        # decorative, the mode dropdown must stay readable.
        self._tagline_label.setVisible(widget is None)
        # Slim the global chrome to hand even more width to the panel row.
        self.global_search.setFixedWidth(240 if widget is None else 170)
        self._search_hint.setVisible(widget is None)

    def _switch(self, index: int):
        changed = hasattr(self, "stack") and index != self.stack.currentIndex()
        self.stack.setCurrentIndex(index)

        self.btn_home.setChecked(index == 0)
        self.btn_cd.setChecked(index == 1)
        self.btn_cad.setChecked(index == 2)
        self.btn_cad2.setChecked(index == 3)
        self.btn_gadgen.setChecked(index == 4)
        self.btn_gad.setChecked(index == 5)
        self.btn_hydro.setChecked(index == 6)
        self.btn_borelog.setChecked(index == 7)
        self.btn_kb.setChecked(index == 8)
        self.btn_sheets.setChecked(index == 10)
        self.btn_calcnotes.setChecked(index == 9)

        self._sync_top_bar()
        if changed:
            self._animate_page(self.stack.currentWidget())

    def _animate_page(self, page):
        if page is None or _reduced_motion():
            return

        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        effect.setOpacity(0.0)

        def restore():
            page.setGraphicsEffect(None)

        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(_ANIM_PAGE)
        fade.setStartValue(0.35)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.finished.connect(restore)
        self._page_anim = fade
        fade.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
