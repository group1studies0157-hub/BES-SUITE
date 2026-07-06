"""
main_window.py  —  Bridge Engineering Suite
Layout: sidebar (left, 210 px) + stacked content area (right)

Sidebar nav (top→bottom):
  PROCESSES:    CD Processing | CAD Process | CAD Process 2
                GAD Checking  | Hydraulic Calculations
  STUDY TOOLS:  Knowledge Base
  ── divider ──
  ⚙ Settings   ← bottom-left, always visible

Stack indices:
  0  CD Processing
  1  CAD Process
  2  CAD Process 2
  3  GAD Checking
  4  Hydraulic Calculations   ← NEW
  5  Knowledge Base
  6  Settings
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame,
    QScrollArea, QButtonGroup, QApplication, QLineEdit,
    QGraphicsOpacityEffect
)
from PyQt6.QtCore import (
    Qt, QPoint, QPropertyAnimation, QParallelAnimationGroup,
    QEasingCurve, QAbstractAnimation
)
from PyQt6.QtGui  import QFont


# ── Motion helpers ───────────────────────────────────────────────────────────
def _reduced_motion() -> bool:
    """Respect the OS 'show animations' preference (accessibility).

    Windows exposes this via SPI_GETCLIENTAREAANIMATION; when the user has
    turned UI animations off, every micro-animation below is skipped. If the
    query is unavailable we default to motion-enabled. This is the desktop
    equivalent of CSS `prefers-reduced-motion`, which Qt Style Sheets lack.
    """
    try:
        import ctypes
        SPI_GETCLIENTAREAANIMATION = 0x1042
        flag = ctypes.c_int()
        ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(flag), 0
        )
        return not bool(flag.value)
    except Exception:
        return False


_ANIM_FAST = 140   # ms — button press feedback
_ANIM_PAGE = 200   # ms — page fade/slide

from gui.styles import apply_theme, COLORS, STYLESHEET, current_theme, build_palette
from gui.cd_panel          import CDPanel
from gui.cad_panel         import CADPanel
from gui.cad_panel2        import CAD2Panel
from gui.knowledge_panel   import KnowledgePanel
from gui.gad_panel         import GADPanel
from gui.hydraulic_panel   import HydraulicPanel      # ← NEW


# ─────────────────────────────────────────────────────────────────────────────
class SidebarButton(QPushButton):
    def __init__(self, text, icon="", obj_name="sidebarButton", parent=None):
        super().__init__(parent)
        self.setText(f"  {icon}  {text}" if icon else f"  {text}")
        self.setCheckable(True)
        self.setMinimumHeight(48)
        self.setFont(QFont("Segoe UI", 10))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName(obj_name)

    # ── Press feedback: quick opacity dip (scale would fight the layout) ──────
    def mousePressEvent(self, e):
        if not _reduced_motion():
            self._pulse()
        super().mousePressEvent(e)

    def _pulse(self):
        eff = self.graphicsEffect()
        if not isinstance(eff, QGraphicsOpacityEffect):
            eff = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(_ANIM_FAST)
        anim.setKeyValueAt(0.0, 1.0)
        anim.setKeyValueAt(0.5, 0.55)
        anim.setKeyValueAt(1.0, 1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_anim = anim  # keep a reference alive
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


# ─────────────────────────────────────────────────────────────────────────────
class SettingsPanel(QWidget):
    """Full-page settings panel — stack index 6."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self._win = win
        self._build()

    def _build(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(48, 40, 48, 48)
        lay.setSpacing(0)
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # ── Header ────────────────────────────────────────────────────────
        lbl_title = QLabel("Settings")
        lbl_title.setObjectName("panelTitle")
        lay.addWidget(lbl_title)

        lbl_sub = QLabel("Changes apply instantly across the entire application — no restart needed.")
        lbl_sub.setObjectName("panelSubtitle")
        lay.addWidget(lbl_sub)

        lay.addSpacing(32)

        # ── Appearance card ───────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(28, 24, 28, 24)
        card_lay.setSpacing(20)

        card_hdr = QLabel("Appearance")
        card_hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        card_lay.addWidget(card_hdr)

        # ── Theme row ─────────────────────────────────────────────────────
        row = QFrame()
        row.setObjectName("settingsRow")
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(18, 16, 18, 16)
        row_lay.setSpacing(16)

        icon_lbl = QLabel("🎨")
        icon_lbl.setFixedWidth(30)
        icon_lbl.setFont(QFont("Segoe UI", 16))
        row_lay.addWidget(icon_lbl)

        info = QVBoxLayout()
        info.setSpacing(3)
        th_name = QLabel("Theme")
        th_name.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        th_desc = QLabel(
            "Dark mode uses a deep black background with white text — just like "
            "Windows 11 dark mode.  Light mode uses a clean white surface."
        )
        th_desc.setWordWrap(True)
        th_desc.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;")
        info.addWidget(th_name)
        info.addWidget(th_desc)
        row_lay.addLayout(info, 1)

        self._btn_dark  = QPushButton("🌙  Dark")
        self._btn_light = QPushButton("☀️  Light")

        for btn in (self._btn_dark, self._btn_light):
            btn.setFixedHeight(40)
            btn.setFixedWidth(110)
            btn.setCheckable(True)
            btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_grp = QButtonGroup(self)
        self._btn_grp.setExclusive(True)
        self._btn_grp.addButton(self._btn_dark)
        self._btn_grp.addButton(self._btn_light)

        self._btn_dark .clicked.connect(lambda: self._set_theme("dark"))
        self._btn_light.clicked.connect(lambda: self._set_theme("light"))

        pair = QHBoxLayout()
        pair.setSpacing(8)
        pair.addWidget(self._btn_dark)
        pair.addWidget(self._btn_light)
        row_lay.addLayout(pair)

        card_lay.addWidget(row)

        self._indicator = QLabel()
        self._indicator.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:11px;"
            f"font-style:italic;padding-left:4px;"
        )
        card_lay.addWidget(self._indicator)

        lay.addWidget(card)
        lay.addSpacing(20)

        # ── API Keys card ─────────────────────────────────────────────────
        api_card = QFrame()
        api_card.setObjectName("card")
        api_lay = QVBoxLayout(api_card)
        api_lay.setContentsMargins(28, 24, 28, 24)
        api_lay.setSpacing(16)

        api_hdr = QLabel("API Keys")
        api_hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        api_lay.addWidget(api_hdr)

        api_sub = QLabel(
            "Keys are saved locally and used by CAD Process, GAD Verification, "
            "and Knowledge Base. Gemini is tried first when both are provided."
        )
        api_sub.setWordWrap(True)
        api_sub.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;")
        api_lay.addWidget(api_sub)

        def _make_key_row(label, icon, placeholder, setting_key, env_var):
            row = QFrame()
            row.setObjectName("settingsRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(18, 14, 18, 14)
            rl.setSpacing(12)

            icon_l = QLabel(icon)
            icon_l.setFixedWidth(28)
            icon_l.setFont(QFont("Segoe UI", 16))
            rl.addWidget(icon_l)

            info = QVBoxLayout()
            info.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            info.addWidget(lbl)
            from PyQt6.QtCore import QSettings as _QS
            saved = _QS("BES", "BridgeEngineeringSuite").value(setting_key, "")
            if not saved:
                import os as _os
                saved = _os.environ.get(env_var, "")
            inp = QLineEdit()
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            inp.setPlaceholderText(placeholder)
            inp.setFixedHeight(34)
            if saved:
                inp.setText(saved)
            info.addWidget(inp)
            rl.addLayout(info, 1)

            save_btn = QPushButton("Save")
            save_btn.setObjectName("primaryBtn")
            save_btn.setFixedHeight(34)
            save_btn.setFixedWidth(72)

            def _save(key=setting_key, field=inp):
                from PyQt6.QtCore import QSettings as _QS2
                _QS2("BES", "BridgeEngineeringSuite").setValue(key, field.text().strip())
                save_btn.setText("✓ Saved")
                from PyQt6.QtCore import QTimer as _QT
                _QT.singleShot(1500, lambda: save_btn.setText("Save"))

            save_btn.clicked.connect(_save)
            rl.addWidget(save_btn)

            show_btn = QPushButton("👁")
            show_btn.setObjectName("secondaryBtn")
            show_btn.setFixedHeight(34)
            show_btn.setFixedWidth(40)
            show_btn.setCheckable(True)

            def _toggle_vis(checked, field=inp):
                field.setEchoMode(
                    QLineEdit.EchoMode.Normal if checked
                    else QLineEdit.EchoMode.Password
                )

            show_btn.clicked.connect(_toggle_vis)
            rl.addWidget(show_btn)

            return row

        anthropic_row = _make_key_row(
            "Anthropic (Claude) API Key", "🤖",
            "sk-ant-api03-…",
            "anthropic_api_key", "ANTHROPIC_API_KEY"
        )
        api_lay.addWidget(anthropic_row)

        gemini_row = _make_key_row(
            "Google (Gemini) API Key", "✨",
            "AIzaSy…",
            "gemini_api_key", "GEMINI_API_KEY"
        )
        api_lay.addWidget(gemini_row)

        key_hint = QLabel(
            "Get Claude keys at console.anthropic.com  •  "
            "Get Gemini keys at aistudio.google.com"
        )
        key_hint.setStyleSheet(f"color:{COLORS['text_muted']};font-size:10px;font-style:italic;")
        api_lay.addWidget(key_hint)

        lay.addWidget(api_card)
        lay.addSpacing(20)

        about = QFrame()
        about.setObjectName("card")
        ab_lay = QVBoxLayout(about)
        ab_lay.setContentsMargins(28, 20, 28, 20)
        ab_lay.setSpacing(6)

        ab_hdr = QLabel("About")
        ab_hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        ab_lay.addWidget(ab_hdr)

        for txt, muted in [
            ("Bridge Engineering Suite  v2.0", False),
            ("Local Build  •  Python / PyQt6", True),
            ("AI: Anthropic Claude + Google Gemini (dual-key auto-fallback)", True),
        ]:
            l = QLabel(txt)
            l.setStyleSheet(
                f"color:{COLORS['text_muted'] if muted else COLORS['text_primary']};"
                f"font-size:{'11' if muted else '13'}px;"
            )
            ab_lay.addWidget(l)

        lay.addWidget(about)
        lay.addStretch()

        self._refresh_ui()

    # ── Internal ─────────────────────────────────────────────────────────
    def _refresh_ui(self):
        t = current_theme()
        self._btn_dark .setChecked(t == "dark")
        self._btn_light.setChecked(t == "light")

        active = (
            f"QPushButton{{background:{COLORS['accent']};color:#0D1117;"
            f"border:none;border-radius:8px;font-weight:700;font-size:11px;}}"
            f"QPushButton:hover{{background:{COLORS['accent_dim']};}}"
        )
        idle = (
            f"QPushButton{{background:{COLORS['input_bg']};color:{COLORS['text_secondary']};"
            f"border:1.5px solid {COLORS['border_dark']};border-radius:8px;font-size:11px;}}"
            f"QPushButton:hover{{background:{COLORS['hover_bg']};color:{COLORS['text_primary']};}}"
        )
        self._btn_dark .setStyleSheet(active if t == "dark"  else idle)
        self._btn_light.setStyleSheet(active if t == "light" else idle)
        self._indicator.setText(
            f"Current theme: {'🌙 Dark' if t == 'dark' else '☀️ Light'}"
        )

    def _set_theme(self, theme: str):
        app = QApplication.instance()
        apply_theme(theme, app)
        self._refresh_ui()
        if hasattr(self._win, "knowledge_panel"):
            kp = self._win.knowledge_panel
            if hasattr(kp, "_sync_theme"):
                kp._sync_theme()

    def showEvent(self, e):
        super().showEvent(e)
        self._refresh_ui()


# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bridge Engineering Suite  v2.0")
        self.setMinimumSize(1000, 680)
        self.resize(1200, 800)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(12, 20, 12, 20)
        sb.setSpacing(4)

        # Logo
        logo = QLabel("⬡  BES")
        logo.setObjectName("logoLabel")
        logo.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        sb.addWidget(logo)

        tagline = QLabel("Bridge Engineering Suite")
        tagline.setObjectName("subLabel")
        tagline.setFont(QFont("Segoe UI", 8))
        sb.addWidget(tagline)

        sb.addSpacing(24)

        # ── PROCESSES section ─────────────────────────────────────────────
        proc_hdr = QLabel("PROCESSES")
        proc_hdr.setObjectName("navLabel")
        proc_hdr.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        sb.addWidget(proc_hdr)
        sb.addSpacing(4)

        self.btn_cd    = SidebarButton("CD Processing",          "⚙")
        self.btn_cad   = SidebarButton("CAD Process",            "✏")
        self.btn_cad2  = SidebarButton("CAD Process 2",          "📐")
        self.btn_gad   = SidebarButton("GAD Checking",           "📋")
        self.btn_hydro = SidebarButton("Hydraulic Calcs",        "💧")   # ← NEW

        self.btn_cd.setChecked(True)

        self.btn_cd   .clicked.connect(lambda: self._switch(0))
        self.btn_cad  .clicked.connect(lambda: self._switch(1))
        self.btn_cad2 .clicked.connect(lambda: self._switch(2))
        self.btn_gad  .clicked.connect(lambda: self._switch(3))
        self.btn_hydro.clicked.connect(lambda: self._switch(4))           # ← NEW

        sb.addWidget(self.btn_cd)
        sb.addWidget(self.btn_cad)
        sb.addWidget(self.btn_cad2)
        sb.addWidget(self.btn_gad)
        sb.addWidget(self.btn_hydro)                                       # ← NEW

        # ── STUDY TOOLS section ───────────────────────────────────────────
        sb.addSpacing(16)
        study_hdr = QLabel("STUDY TOOLS")
        study_hdr.setObjectName("navLabel")
        study_hdr.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        sb.addWidget(study_hdr)
        sb.addSpacing(4)

        self.btn_kb = SidebarButton("Knowledge Base", "📚")
        self.btn_kb.clicked.connect(lambda: self._switch(5))              # was 4
        sb.addWidget(self.btn_kb)

        # ── Settings at bottom ────────────────────────────────────────────
        sb.addStretch()

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setObjectName("divider")
        sb.addWidget(div)
        sb.addSpacing(6)

        self.btn_settings = SidebarButton("Settings", "⚙", obj_name="settingsBtn")
        self.btn_settings.clicked.connect(lambda: self._switch(6))        # was 5
        sb.addWidget(self.btn_settings)

        sb.addSpacing(6)
        ver = QLabel("v2.0  •  Local Build")
        ver.setObjectName("versionLabel")
        ver.setFont(QFont("Segoe UI", 8))
        sb.addWidget(ver)

        # ── Content stack ─────────────────────────────────────────────────
        # Index:  0=CD  1=CAD  2=CAD2  3=GAD  4=Hydraulic  5=KB  6=Settings
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")

        self.cd_panel          = CDPanel()
        self.cad_panel         = CADPanel()
        self.cad2_panel        = CAD2Panel()
        self.gad_panel         = GADPanel()
        self.hydraulic_panel   = HydraulicPanel()                          # ← NEW
        self.knowledge_panel   = KnowledgePanel()
        self.settings_panel    = SettingsPanel(self)

        for w in (self.cd_panel, self.cad_panel, self.cad2_panel,
                  self.gad_panel, self.hydraulic_panel,                   # ← NEW
                  self.knowledge_panel, self.settings_panel):
            self.stack.addWidget(w)

        root.addWidget(sidebar)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setObjectName("separator")
        root.addWidget(sep)

        root.addWidget(self.stack)

    def _switch(self, index: int):
        changed = index != self.stack.currentIndex()
        self.stack.setCurrentIndex(index)
        self.btn_cd      .setChecked(index == 0)
        self.btn_cad     .setChecked(index == 1)
        self.btn_cad2    .setChecked(index == 2)
        self.btn_gad     .setChecked(index == 3)
        self.btn_hydro   .setChecked(index == 4)                          # ← NEW
        self.btn_kb      .setChecked(index == 5)
        self.btn_settings.setChecked(index == 6)
        if changed:
            self._animate_page(self.stack.currentWidget())

    def _animate_page(self, page):
        """Fade + subtle slide-in for the newly shown page.

        The graphics effect is detached and the original position restored on
        completion, so the panel's normal layout, sizing and behaviour are
        left exactly as before once the 200 ms transition ends.
        """
        if page is None or _reduced_motion():
            return

        eff = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(eff)
        eff.setOpacity(0.0)

        fade = QPropertyAnimation(eff, b"opacity", self)
        fade.setDuration(_ANIM_PAGE)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        home = page.pos()
        slide = QPropertyAnimation(page, b"pos", self)
        slide.setDuration(_ANIM_PAGE)
        slide.setStartValue(QPoint(home.x() + 20, home.y()))
        slide.setEndValue(home)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        group.addAnimation(slide)

        def _restore():
            page.setGraphicsEffect(None)
            page.move(home)

        group.finished.connect(_restore)
        self._page_anim = group  # keep a reference alive
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
