"""Main application shell for Bridge Engineering Suite."""

from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QSettings,
    QSize,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QIcon, QPixmap
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
from gui.icons import icon_label, icon_path as get_icon_path, tile_pixmap
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
        self._win._sync_top_bar()
        if hasattr(self._win, "knowledge_panel"):
            panel = self._win.knowledge_panel
            if hasattr(panel, "_sync_theme"):
                panel._sync_theme()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_ui()


class HomeAppCard(QFrame):
    """One store-style row: icon, name/description, optional badge, Open button."""

    def __init__(self, win: "MainWindow", index: int, icon_key: str, name: str, meta: str,
                 badge: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("storeCard")
        self._search_key = f"{name} {meta}".lower()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setObjectName("storeIcon")
        icon_lbl.setFixedSize(46, 46)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setScaledContents(False)
        path = get_icon_path(icon_key)
        if path:
            pix = QPixmap(path).scaled(
                46, 46, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            icon_lbl.setPixmap(pix)
        else:
            icon_lbl.setPixmap(tile_pixmap(icon_key or "folder", 46))
        layout.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("storeAppName")
        meta_lbl = QLabel(meta)
        meta_lbl.setObjectName("storeAppMeta")
        meta_lbl.setWordWrap(True)
        text_col.addWidget(name_lbl)
        text_col.addWidget(meta_lbl)
        layout.addLayout(text_col, 1)

        if badge:
            badge_lbl = QLabel(badge)
            badge_lbl.setObjectName("tagInfo")
            layout.addWidget(badge_lbl)

        open_btn = QPushButton("Open")
        open_btn.setObjectName("openBtn")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setFixedWidth(84)
        open_btn.clicked.connect(lambda: win._switch(index))
        layout.addWidget(open_btn)

    def matches(self, query: str) -> bool:
        return query in self._search_key


class HomePanel(QWidget):
    """Microsoft Store-style landing dashboard: hero banner, search/category chips,
    and app-card sections that open each workflow via the existing sidebar navigation."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self._win = win
        self._cards: list[HomeAppCard] = []
        self._section_frames: dict[str, QFrame] = {}
        self._build()

    def _build(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        layout.addWidget(self._hero())

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("storeSearch")
        self.search.setPlaceholderText("Search tools and workflows...")
        self.search.setFixedHeight(36)
        self.search.textChanged.connect(self._filter_text)
        top_row.addWidget(self.search, 1)

        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        for label in ("All", "Workflow Tools", "Reference"):
            chip = QPushButton(label)
            chip.setObjectName("chipButton")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _checked=False, l=label: self._filter_category(l))
            self._chip_group.addButton(chip)
            top_row.addWidget(chip)
            if label == "All":
                chip.setChecked(True)
        layout.addLayout(top_row)

        sections_row = QHBoxLayout()
        sections_row.setSpacing(20)

        workflow_card, workflow_cards = self._section(
            "Workflow Tools",
            [
                ("cd", "CD Processing", "Consolidated construction-document workflow.", 1, None),
                ("cad", "CAD Process", "Scanned drawings into structured CAD output.", 2, None),
                ("cad2", "CAD Process 2", "Dimension-first drawing extraction and DXF.", 3, "AI-Powered"),
                ("gadgen", "GAD Generator", "Prompt + dimensions → parametric GAD as AutoLISP + DXF.", 4, None),
                ("gad", "GAD Checking", "Verify corrected drawings against markups.", 5, "AI-Powered"),
                ("hydraulic", "Hydraulic Calcs", "Waterway and bridge hydraulic adequacy.", 6, "AI-Powered"),
                ("borelog", "Bore Log → DXF", "Convert bore-log reports into AutoCAD DXF drawings.", 7, None),
            ],
        )
        reference_card, reference_cards = self._section(
            "Reference & Settings",
            [
                ("kb", "Knowledge Base", "Search manuals and practice exam questions.", 8, "AI-Powered"),
                ("sync", "Sheets Sync", "Pull live project tracking data from Google Sheets.", 9, None),
                ("settings", "Settings", "Theme, local credentials, and app details.", 10, None),
            ],
        )

        sections_row.addWidget(workflow_card, 1)
        sections_row.addWidget(reference_card, 1)
        layout.addLayout(sections_row)
        layout.addStretch()

        self._cards = workflow_cards + reference_cards
        self._section_frames = {"Workflow Tools": workflow_card, "Reference": reference_card}

    def _hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("heroBanner")
        lay = QVBoxLayout(hero)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(6)

        kicker = QLabel("BRIDGE ENGINEERING SUITE")
        kicker.setObjectName("heroKicker")
        title = QLabel("Everything you need, in one workspace")
        title.setObjectName("heroTitle")
        title.setWordWrap(True)
        subtitle = QLabel("Jump into a workflow tool below, or pick up where you left off.")
        subtitle.setObjectName("heroSubtitle")
        subtitle.setWordWrap(True)

        lay.addWidget(kicker)
        lay.addWidget(title)
        lay.addWidget(subtitle)
        return hero

    def _section(self, title: str, items: list[tuple]) -> tuple[QFrame, list["HomeAppCard"]]:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        header = QLabel(title)
        header.setObjectName("sectionHeader")
        lay.addWidget(header)

        cards: list[HomeAppCard] = []
        for icon_key, name, meta, index, badge in items:
            row = HomeAppCard(self._win, index, icon_key, name, meta, badge)
            lay.addWidget(row)
            cards.append(row)

        lay.addStretch()
        return card, cards

    def _filter_text(self, text: str):
        query = text.strip().lower()
        for card in self._cards:
            card.setVisible(card.matches(query))

    def _filter_category(self, label: str):
        self.search.clear()
        show_workflow = label in ("All", "Workflow Tools")
        show_reference = label in ("All", "Reference")
        self._section_frames["Workflow Tools"].setVisible(show_workflow)
        self._section_frames["Reference"].setVisible(show_reference)


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

        self._sidebar_expanded_w = 176
        self._sidebar_collapsed_w = 56
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
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(14)

        self.top_bar = self._build_top_bar()
        content_layout.addWidget(self.top_bar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")
        content_layout.addWidget(self.stack, 1)

        self.home_panel = HomePanel(self)
        self.cd_panel = CDPanel()
        self.cad_panel = CADPanel()
        self.cad2_panel = CAD2Panel()
        self.gadgen_panel = GadGeneratorPanel()
        self.gad_panel = GADPanel()
        self.hydraulic_panel = HydraulicPanel()
        self.knowledge_panel = KnowledgePanel()
        self.borelog_panel = BoreLogPanel()
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
            self.sheets_sync_panel,
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

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(4)

        brand = QFrame()
        brand.setObjectName("brandCard")
        brand_lay = QHBoxLayout(brand)
        brand_lay.setContentsMargins(10, 10, 10, 10)
        brand_lay.setSpacing(8)

        mark = QLabel("B")
        mark.setObjectName("appMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(32, 32)
        brand_lay.addWidget(mark)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        logo = QLabel("BES")
        logo.setObjectName("logoLabel")
        subtitle = QLabel("Bridge Eng. Suite")
        subtitle.setObjectName("subLabel")
        brand_text.addWidget(logo)
        brand_text.addWidget(subtitle)

        self._brand_text_wrap = QWidget()
        self._brand_text_wrap.setLayout(brand_text)
        self._brand_text_wrap.setStyleSheet("background: transparent;")
        brand_lay.addWidget(self._brand_text_wrap, 1)

        self.btn_pin = QPushButton("<<")
        self.btn_pin.setObjectName("pinButton")
        self.btn_pin.setFixedSize(22, 22)
        self.btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pin.clicked.connect(self._toggle_pin)
        brand_lay.addWidget(self.btn_pin)

        layout.addWidget(brand)

        self.btn_home = SidebarButton("Home", icon_key="home")
        self.btn_home.clicked.connect(lambda: self._switch(0))
        layout.addWidget(self.btn_home)
        self._sidebar_buttons = [self.btn_home]

        layout.addSpacing(8)
        self.nav_label_workflows = QLabel("WORKFLOWS")
        self.nav_label_workflows.setObjectName("navLabel")
        layout.addWidget(self.nav_label_workflows)

        self.btn_cd = SidebarButton("CD Processing", icon_key="cd")
        self.btn_cad = SidebarButton("CAD Process", icon_key="cad")
        self.btn_cad2 = SidebarButton("CAD Process 2", icon_key="cad2")
        self.btn_gadgen = SidebarButton("GAD Generator", icon_key="gadgen")
        self.btn_gad = SidebarButton("GAD Checking", icon_key="gad")
        self.btn_hydro = SidebarButton("Hydraulic Calcs", icon_key="hydraulic")
        self.btn_borelog = SidebarButton("Bore Log", icon_key="borelog")

        self.btn_cd.clicked.connect(lambda: self._switch(1))
        self.btn_cad.clicked.connect(lambda: self._switch(2))
        self.btn_cad2.clicked.connect(lambda: self._switch(3))
        self.btn_gadgen.clicked.connect(lambda: self._switch(4))
        self.btn_gad.clicked.connect(lambda: self._switch(5))
        self.btn_hydro.clicked.connect(lambda: self._switch(6))
        self.btn_borelog.clicked.connect(lambda: self._switch(7))

        self._sidebar_buttons += [self.btn_cd, self.btn_cad, self.btn_cad2, self.btn_gadgen, self.btn_gad, self.btn_hydro, self.btn_borelog]
        for btn in (self.btn_cd, self.btn_cad, self.btn_cad2, self.btn_gadgen, self.btn_gad, self.btn_hydro, self.btn_borelog):
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
        self.btn_sheets.clicked.connect(lambda: self._switch(9))
        layout.addWidget(self.btn_sheets)
        self._sidebar_buttons.append(self.btn_sheets)

        layout.addStretch()
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("divider")
        layout.addWidget(divider)

        self.btn_settings = SidebarButton("Settings", obj_name="settingsBtn", icon_key="settings")
        self.btn_settings.clicked.connect(lambda: self._switch(10))
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

    # -- Sidebar collapse (manual toggle only) ---------------------------

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

        self.page_icon = QLabel()
        self.page_icon.setObjectName("topIcon")
        self.page_icon.setFixedSize(34, 34)
        self.page_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.page_icon)
        layout.addLayout(title_col)

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
        layout.addStretch()

        # Theme selector/swatches removed from here — Settings panel already
        # has the full theme picker (see SettingsPanel, ~line 236) and is
        # the single source of truth for theme changes now. This reclaims
        # the top-bar space for panel-specific buttons (e.g. Hydraulic
        # Calcs' Smart Extract / Show Preview) instead of duplicating
        # theme controls on every page.
        return bar

    def _sync_top_bar(self):
        idx = self.stack.currentIndex() if hasattr(self, "stack") else 0
        title, subtitle = self._PAGE_INFO[idx]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        path = get_icon_path(self._PAGE_ICON_KEYS[idx])
        if path:
            pix = QPixmap(path).scaled(
                34, 34, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.page_icon.setPixmap(pix)
        else:
            self.page_icon.clear()
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
        self.btn_sheets.setChecked(index == 9)
        self.btn_settings.setChecked(index == 10)

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
