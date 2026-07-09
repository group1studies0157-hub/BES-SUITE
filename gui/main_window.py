"""Main application shell for Bridge Engineering Suite."""

from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QSettings,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont
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
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.ui_text import install_text_sanitizer

install_text_sanitizer()

from gui.styles import COLORS, THEME_NAMES, THEME_SWATCHES, apply_theme, current_theme
from gui.cd_panel import CDPanel
from gui.cad_panel import CADPanel
from gui.cad_panel2 import CAD2Panel
from gui.gad_panel import GADPanel
from gui.hydraulic_panel import HydraulicPanel
from gui.knowledge_panel import KnowledgePanel


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


class SidebarButton(QPushButton):
    """Sidebar nav button with a soft drop-shadow that lifts on hover and dips on press.

    Replaces the previous opacity-pulse: a widget can only own one graphicsEffect at a
    time, so the shadow now handles both the hover-lift and the press feedback instead
    of swapping effect types mid-interaction.
    """

    def __init__(self, text: str, obj_name: str = "sidebarButton", parent=None):
        super().__init__(parent)
        self._label = text
        self._collapsed = False
        self.setText(text)
        self.setCheckable(True)
        self.setMinimumHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName(obj_name)
        self.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(0, 0, 0, 0))
        self.setGraphicsEffect(self._shadow)

    def setCollapsed(self, collapsed: bool) -> None:
        """Show only a short initialism when the sidebar is a narrow icon rail."""
        self._collapsed = collapsed
        if collapsed:
            self.setText(self._label[:2].upper())
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
    """Sidebar frame that reports hover so the shell can auto-expand a collapsed rail."""

    hoverEntered = pyqtSignal()
    hoverLeft = pyqtSignal()

    def enterEvent(self, event):
        self.hoverEntered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hoverLeft.emit()
        super().leaveEvent(event)


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

        header = QLabel("Appearance")
        header.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        card_lay.addWidget(header)

        row = QFrame()
        row.setObjectName("settingsRow")
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(18, 16, 18, 16)
        row_lay.setSpacing(18)

        copy = QVBoxLayout()
        copy.setSpacing(4)
        name = QLabel("Theme Studio")
        name.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
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
            btn.setFixedSize(92, 36)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
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

        header = QLabel("API Keys")
        header.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
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
        lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))

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

        header = QLabel("About")
        header.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
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
                "color:#FFFFFF;border:none;border-radius:8px;font-weight:800;"
                "}"
            )
        return (
            "QPushButton{"
            f"background:{COLORS['input_bg']};color:{COLORS['text_secondary']};"
            f"border:1px solid {COLORS['border_dark']};border-radius:8px;font-weight:700;"
            "}"
            "QPushButton:hover{"
            f"border-color:{a};color:{COLORS['text_primary']};background:{COLORS['hover_bg']};"
            "}"
        )

    def _refresh_ui(self):
        theme = current_theme()
        for key, btn in self._theme_buttons.items():
            btn.setChecked(theme == key)
            btn.setStyleSheet(self._theme_style(key, theme == key))
        self._indicator.setText(f"Current theme: {THEME_NAMES.get(theme, 'Studio')}")

    def _set_theme(self, theme: str):
        apply_theme(theme, QApplication.instance())
        self._refresh_ui()
        self._win._sync_top_bar()
        if hasattr(self._win, "knowledge_panel"):
            panel = self._win.knowledge_panel
            if hasattr(panel, "_sync_theme"):
                panel._sync_theme()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_ui()


class MainWindow(QMainWindow):
    _PAGE_INFO = [
        ("CD Processing", "Run consolidated construction document workflows."),
        ("CAD Process", "Convert scanned drawings into structured CAD output."),
        ("CAD Process 2", "Dimension-first bridge drawing extraction and DXF generation."),
        ("GAD Checking", "Verify corrected drawings against marked-up observations."),
        ("Hydraulic Calcs", "Calculate waterway and bridge hydraulic adequacy."),
        ("Knowledge Base", "Search manuals and practice exam-style questions."),
        ("Settings", "Theme, local credentials, and application details."),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bridge Engineering Suite v2.0")
        self.setMinimumSize(1080, 700)
        self.resize(1280, 820)

        self._sidebar_expanded_w = 248
        self._sidebar_collapsed_w = 64
        self._sidebar_pinned = QSettings("BES", "BridgeEngineeringSuite").value(
            "sidebar_pinned", True, type=bool
        )
        self._sidebar_hover_timer = QTimer(self)
        self._sidebar_hover_timer.setSingleShot(True)
        self._sidebar_hover_timer.timeout.connect(self._collapse_sidebar_if_unpinned)

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
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(14)

        self.top_bar = self._build_top_bar()
        content_layout.addWidget(self.top_bar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")
        content_layout.addWidget(self.stack, 1)

        self.cd_panel = CDPanel()
        self.cad_panel = CADPanel()
        self.cad2_panel = CAD2Panel()
        self.gad_panel = GADPanel()
        self.hydraulic_panel = HydraulicPanel()
        self.knowledge_panel = KnowledgePanel()
        self.settings_panel = SettingsPanel(self)

        for panel in (
            self.cd_panel,
            self.cad_panel,
            self.cad2_panel,
            self.gad_panel,
            self.hydraulic_panel,
            self.knowledge_panel,
            self.settings_panel,
        ):
            self.stack.addWidget(panel)

        root.addWidget(content_shell, 1)
        self._switch(0)

    def _build_sidebar(self) -> QFrame:
        sidebar = Sidebar()
        sidebar.setObjectName("sidebar")
        start_w = self._sidebar_expanded_w if self._sidebar_pinned else self._sidebar_collapsed_w
        sidebar.setMinimumWidth(start_w)
        sidebar.setMaximumWidth(start_w)
        sidebar.hoverEntered.connect(self._on_sidebar_hover_enter)
        sidebar.hoverLeft.connect(self._on_sidebar_hover_leave)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(8)

        brand = QFrame()
        brand.setObjectName("brandCard")
        brand_lay = QHBoxLayout(brand)
        brand_lay.setContentsMargins(12, 12, 12, 12)
        brand_lay.setSpacing(10)

        mark = QLabel("B")
        mark.setObjectName("appMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(38, 38)
        brand_lay.addWidget(mark)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        logo = QLabel("BES")
        logo.setObjectName("logoLabel")
        subtitle = QLabel("Bridge Engineering Suite")
        subtitle.setObjectName("subLabel")
        brand_text.addWidget(logo)
        brand_text.addWidget(subtitle)

        self._brand_text_wrap = QWidget()
        self._brand_text_wrap.setLayout(brand_text)
        self._brand_text_wrap.setStyleSheet("background: transparent;")
        brand_lay.addWidget(self._brand_text_wrap, 1)

        self.btn_pin = QPushButton("<<")
        self.btn_pin.setObjectName("pinButton")
        self.btn_pin.setFixedSize(26, 26)
        self.btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pin.clicked.connect(self._toggle_pin)
        brand_lay.addWidget(self.btn_pin)

        layout.addWidget(brand)

        layout.addSpacing(12)
        self.nav_label_workflows = QLabel("WORKFLOWS")
        self.nav_label_workflows.setObjectName("navLabel")
        layout.addWidget(self.nav_label_workflows)

        self.btn_cd = SidebarButton("CD Processing")
        self.btn_cad = SidebarButton("CAD Process")
        self.btn_cad2 = SidebarButton("CAD Process 2")
        self.btn_gad = SidebarButton("GAD Checking")
        self.btn_hydro = SidebarButton("Hydraulic Calcs")

        self.btn_cd.clicked.connect(lambda: self._switch(0))
        self.btn_cad.clicked.connect(lambda: self._switch(1))
        self.btn_cad2.clicked.connect(lambda: self._switch(2))
        self.btn_gad.clicked.connect(lambda: self._switch(3))
        self.btn_hydro.clicked.connect(lambda: self._switch(4))

        self._sidebar_buttons = [self.btn_cd, self.btn_cad, self.btn_cad2, self.btn_gad, self.btn_hydro]
        for btn in self._sidebar_buttons:
            layout.addWidget(btn)

        layout.addSpacing(12)
        self.nav_label_reference = QLabel("REFERENCE")
        self.nav_label_reference.setObjectName("navLabel")
        layout.addWidget(self.nav_label_reference)

        self.btn_kb = SidebarButton("Knowledge Base")
        self.btn_kb.clicked.connect(lambda: self._switch(5))
        layout.addWidget(self.btn_kb)
        self._sidebar_buttons.append(self.btn_kb)

        layout.addStretch()
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("divider")
        layout.addWidget(divider)

        self.btn_settings = SidebarButton("Settings", obj_name="settingsBtn")
        self.btn_settings.clicked.connect(lambda: self._switch(6))
        layout.addWidget(self.btn_settings)
        self._sidebar_buttons.append(self.btn_settings)

        self.version_label = QLabel("v2.0 local build")
        self.version_label.setObjectName("versionLabel")
        layout.addWidget(self.version_label)

        collapsed = not self._sidebar_pinned
        self._brand_text_wrap.setVisible(not collapsed)
        self.btn_pin.setVisible(not collapsed)
        self.btn_pin.setText(">>" if collapsed else "<<")
        self.btn_pin.setToolTip("Expand sidebar" if collapsed else "Collapse sidebar")
        self.nav_label_workflows.setVisible(not collapsed)
        self.nav_label_reference.setVisible(not collapsed)
        self.version_label.setVisible(not collapsed)
        for btn in self._sidebar_buttons:
            btn.setCollapsed(collapsed)

        return sidebar

    # -- Sidebar auto-hide / rail-collapse -------------------------------

    def _on_sidebar_hover_enter(self):
        self._sidebar_hover_timer.stop()
        if not self._sidebar_pinned:
            self._set_sidebar_width(self._sidebar_expanded_w, animate=True)
            self._set_sidebar_labels_visible(True)

    def _on_sidebar_hover_leave(self):
        if not self._sidebar_pinned:
            self._sidebar_hover_timer.start(280)

    def _collapse_sidebar_if_unpinned(self):
        if not self._sidebar_pinned:
            self._set_sidebar_width(self._sidebar_collapsed_w, animate=True)
            self._set_sidebar_labels_visible(False)

    def _toggle_pin(self):
        self._sidebar_pinned = not self._sidebar_pinned
        QSettings("BES", "BridgeEngineeringSuite").setValue("sidebar_pinned", self._sidebar_pinned)
        collapsed = not self._sidebar_pinned
        self._set_sidebar_width(
            self._sidebar_collapsed_w if collapsed else self._sidebar_expanded_w, animate=True
        )
        self._set_sidebar_labels_visible(not collapsed)
        self.btn_pin.setText(">>" if collapsed else "<<")
        self.btn_pin.setToolTip("Expand sidebar" if collapsed else "Collapse sidebar")
        for btn in self._sidebar_buttons:
            btn.setCollapsed(collapsed)

    def _set_sidebar_labels_visible(self, visible: bool):
        self._brand_text_wrap.setVisible(visible)
        self.btn_pin.setVisible(visible)
        self.nav_label_workflows.setVisible(visible)
        self.nav_label_reference.setVisible(visible)
        self.version_label.setVisible(visible)

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
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.page_title = QLabel()
        self.page_title.setObjectName("topTitle")
        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("topSubtitle")
        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)
        layout.addLayout(title_col, 1)

        # Slot for panel-specific controls (e.g. Hydraulic Calcs' mode
        # dropdown + Smart Extract hint) rendered right next to the page
        # title instead of duplicating a second title row inside the panel.
        self.top_bar_extra_container = QFrame()
        self.top_bar_extra_container.setObjectName("topBarExtra")
        self.top_bar_extra_container.setVisible(False)
        self._top_bar_extra_layout = QHBoxLayout(self.top_bar_extra_container)
        self._top_bar_extra_layout.setContentsMargins(0, 0, 0, 0)
        self._top_bar_extra_layout.setSpacing(10)
        layout.addWidget(self.top_bar_extra_container)

        self.quick_theme_buttons: dict[str, QPushButton] = {}
        theme_rail = QFrame()
        theme_rail.setObjectName("quickThemeRail")
        theme_layout = QHBoxLayout(theme_rail)
        theme_layout.setContentsMargins(8, 7, 8, 7)
        theme_layout.setSpacing(6)

        self.quick_theme_group = QButtonGroup(self)
        self.quick_theme_group.setExclusive(True)
        for key, label in THEME_NAMES.items():
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(22, 22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Theme: {label}")
            btn.clicked.connect(lambda checked=False, theme=key: self._set_theme_from_top(theme))
            self.quick_theme_group.addButton(btn)
            self.quick_theme_buttons[key] = btn
            theme_layout.addWidget(btn)

        layout.addWidget(theme_rail)

        self.theme_pill = QLabel()
        self.theme_pill.setObjectName("topPill")
        layout.addWidget(self.theme_pill)
        return bar

    def _sync_top_bar(self):
        idx = self.stack.currentIndex() if hasattr(self, "stack") else 0
        title, subtitle = self._PAGE_INFO[idx]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        self.theme_pill.setText(f"Theme: {THEME_NAMES.get(current_theme(), 'Studio')}")
        self._sync_theme_swatches()
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

    def _sync_theme_swatches(self):
        if not hasattr(self, "quick_theme_buttons"):
            return

        for key, btn in self.quick_theme_buttons.items():
            a, b = THEME_SWATCHES[key]
            active = key == current_theme()
            btn.setChecked(active)
            border = COLORS["text_primary"] if active else COLORS["border_dark"]
            width = 2 if active else 1
            btn.setStyleSheet(
                "QPushButton{"
                f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {a},stop:1 {b});"
                f"border:{width}px solid {border};"
                "border-radius:7px;"
                "}"
                "QPushButton:hover{"
                f"border:2px solid {COLORS['text_primary']};"
                "}"
            )

    def _set_theme_from_top(self, theme: str):
        apply_theme(theme, QApplication.instance())
        self._sync_top_bar()
        if hasattr(self, "settings_panel"):
            self.settings_panel._refresh_ui()
        if hasattr(self, "knowledge_panel"):
            panel = self.knowledge_panel
            if hasattr(panel, "_sync_theme"):
                panel._sync_theme()

    def _switch(self, index: int):
        changed = hasattr(self, "stack") and index != self.stack.currentIndex()
        self.stack.setCurrentIndex(index)

        self.btn_cd.setChecked(index == 0)
        self.btn_cad.setChecked(index == 1)
        self.btn_cad2.setChecked(index == 2)
        self.btn_gad.setChecked(index == 3)
        self.btn_hydro.setChecked(index == 4)
        self.btn_kb.setChecked(index == 5)
        self.btn_settings.setChecked(index == 6)

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
