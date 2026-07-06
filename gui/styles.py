"""
styles.py  —  Bridge Engineering Suite
═══════════════════════════════════════
Universal theming engine for PyQt6.

WHY THIS WORKS WHEN PLAIN QSS DOESN'T
───────────────────────────────────────
A QStyleSheet alone cannot dark-theme every widget:
  • Native OS widgets (scrollbars, checkboxes, title-bar) ignore QSS on Windows/Mac
  • QAbstractItemView, QHeaderView, QToolTip, QMenuBar all need QPalette roles filled

The correct approach (used by VS Code Qt, PyCharm, Qt Creator):
  1. app.setStyle("Fusion")          → turns off OS-native drawing on all widgets
  2. app.setPalette(palette)         → fills ALL 46 QPalette roles so every widget
                                       (even ones we never styled by name) picks up
                                       the right background/foreground/highlight
  3. app.setStyleSheet(qss)          → accent colours, border-radius, custom rules

PUBLIC API
──────────
  from gui.styles import COLORS, STYLESHEET, apply_theme, build_palette

  # at app startup (called before MainWindow.__init__)
  apply_theme(QSettings(...).value("ui_theme", "dark"), app)

  # from SettingsPanel when user clicks Dark/Light
  apply_theme("dark", QApplication.instance())

NOTE: Qt Style Sheets do not support CSS transitions/animations; "subtle
effects" here are expressed through refined :hover / :focus / :pressed states.
"""

from PyQt6.QtCore    import Qt, QSettings
from PyQt6.QtGui     import QColor, QPalette
from PyQt6.QtWidgets import QApplication

# ── Accent colour (teal-green — unchanged across themes) ───────────────────
ACCENT       = "#00C8A0"
ACCENT_DIM   = "#00A080"
ACCENT_GLOW  = "rgba(0,200,160,0.14)"
ACCENT_SOLID = "#003D30"   # dark bg tint for highlighted rows in dark mode

# ══════════════════════════════════════════════════════════════════════════════
#  DARK palette  (refined slate — VS-Code / JetBrains style)
# ══════════════════════════════════════════════════════════════════════════════
_DARK = {
    # Sidebar  — deep warm slate, sits clearly behind the content plane
    "navy":           "#181B21",
    "navy_light":     "#23272F",
    "navy_border":    "#30353F",
    # Accent  — teal unchanged
    "accent":         ACCENT,
    "accent_dim":     ACCENT_DIM,
    "accent_glow":    ACCENT_GLOW,
    # Text  — brighter primary for AA contrast, calm secondary/muted ramp
    "white":          "#E6EBF2",
    "off_white":      "#1E2127",      # main app background  (warm dark slate)
    "text_primary":   "#E6EBF2",
    "text_secondary": "#9AA4B2",
    "text_muted":     "#656D7A",
    "text_sidebar":   "#CBD5E1",
    # Borders / surfaces  — clear separation without harsh contrast
    "border":         "#2E333C",
    "border_dark":    "#3C424D",
    "input_bg":       "#262A32",
    "card_bg":        "#23272F",
    "hover_bg":       "#2C313A",
    "progress_track": "#30353F",
    # Status  — kept vivid so they stand out on the softer background
    "success":        "#4AC26B",
    "success_bg":     "#152621",
    "warning":        "#E3A24A",
    "warning_bg":     "#2A1F11",
    "error":          "#F07070",
    "error_bg":       "#2C1616",
    "info":           "#6AADFF",
    "info_bg":        "#151F33",
    # Settings
    "settings_bg":    "#23272F",
    "settings_row":   "#2C313A",
}

# ══════════════════════════════════════════════════════════════════════════════
#  LIGHT palette  (clean, cool white)
# ══════════════════════════════════════════════════════════════════════════════
_LIGHT = {
    "navy":           "#0F1923",
    "navy_light":     "#1A2736",
    "navy_border":    "#2A3A4A",
    "accent":         ACCENT,
    "accent_dim":     ACCENT_DIM,
    "accent_glow":    ACCENT_GLOW,
    "white":          "#FFFFFF",
    "off_white":      "#F5F7FA",
    "text_primary":   "#161B26",
    "text_secondary": "#546073",
    "text_muted":     "#8A94A8",
    "text_sidebar":   "#CBD5E1",
    "border":         "#E4E9F0",
    "border_dark":    "#CBD5E1",
    "input_bg":       "#FBFCFE",
    "card_bg":        "#FFFFFF",
    "hover_bg":       "#EEF2F7",
    "progress_track": "#E4E9F0",
    "success":        "#10B981",
    "success_bg":     "#ECFDF5",
    "warning":        "#F59E0B",
    "warning_bg":     "#FFFBEB",
    "error":          "#EF4444",
    "error_bg":       "#FEF2F2",
    "info":           "#3B82F6",
    "info_bg":        "#EFF6FF",
    "settings_bg":    "#FFFFFF",
    "settings_row":   "#EEF2F7",
}


# ── QPalette builder ─────────────────────────────────────────────────────────
def build_palette(theme: str) -> QPalette:
    """
    Build a complete QPalette covering all roles / groups so Fusion style
    dark-themes every widget — including ones we never name in QSS.
    """
    p   = QPalette()
    c   = lambda h: QColor(h)

    if theme == "dark":
        bg      = "#1E2127"
        bg_alt  = "#262A32"
        bg_btn  = "#2C313A"
        txt     = "#E6EBF2"
        txt_dis = "#656D7A"
        bdr     = "#3C424D"
        hl      = ACCENT
        hl_txt  = "#0D1117"
        base    = "#23272F"
        tooltip_bg  = "#2C313A"
        tooltip_txt = "#E6EBF2"
        link    = "#6AADFF"
        mid     = "#262A32"
        shadow  = "#0F1216"
    else:
        bg      = "#F5F7FA"
        bg_alt  = "#EAEEF4"
        bg_btn  = "#FFFFFF"
        txt     = "#161B26"
        txt_dis = "#A0AABF"
        bdr     = "#CBD5E1"
        hl      = ACCENT
        hl_txt  = "#0D1117"
        base    = "#FFFFFF"
        tooltip_bg  = "#FFFFFF"
        tooltip_txt = "#161B26"
        link    = "#2563EB"
        mid     = "#E4E9F0"
        shadow  = "#9CA3AF"

    # Active
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Window,          c(bg))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText,      c(txt))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Base,            c(base))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.AlternateBase,   c(bg_alt))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Text,            c(txt))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Button,          c(bg_btn))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText,      c(txt))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight,       c(hl))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText, c(hl_txt))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.ToolTipBase,     c(tooltip_bg))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.ToolTipText,     c(tooltip_txt))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Link,            c(link))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.LinkVisited,     c(link))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Mid,             c(mid))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Midlight,        c(bg_alt))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Dark,            c(bg_alt))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Shadow,          c(shadow))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.BrightText,      c("#FF6B6B"))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Light,           c(bg_btn))
    p.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.PlaceholderText, c(txt_dis))

    # Inactive (background windows) — same as active
    for role, color in [
        (QPalette.ColorRole.Window,          c(bg)),
        (QPalette.ColorRole.WindowText,      c(txt)),
        (QPalette.ColorRole.Base,            c(base)),
        (QPalette.ColorRole.AlternateBase,   c(bg_alt)),
        (QPalette.ColorRole.Text,            c(txt)),
        (QPalette.ColorRole.Button,          c(bg_btn)),
        (QPalette.ColorRole.ButtonText,      c(txt)),
        (QPalette.ColorRole.Highlight,       c(hl)),
        (QPalette.ColorRole.HighlightedText, c(hl_txt)),
        (QPalette.ColorRole.ToolTipBase,     c(tooltip_bg)),
        (QPalette.ColorRole.ToolTipText,     c(tooltip_txt)),
        (QPalette.ColorRole.PlaceholderText, c(txt_dis)),
    ]:
        p.setColor(QPalette.ColorGroup.Inactive, role, color)

    # Disabled
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Window,      c(bg))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText,  c(txt_dis))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base,        c(bg))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,        c(txt_dis))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button,      c(bg_btn))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,  c(txt_dis))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight,   c(bdr))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, c(txt_dis))

    return p


# ── QSS builder ──────────────────────────────────────────────────────────────
def _build_qss(C: dict) -> str:
    """
    Build the QSS string.  With Fusion + QPalette already set, this QSS only
    needs to add: accent colours, border-radius, sidebar, cards, and widgets
    whose shape/colour can't be expressed via QPalette alone.
    """
    return f"""
/* ══ Reset & root ══════════════════════════════════════════════════════════ */
* {{
    font-family: 'Segoe UI', 'SF Pro Display', Arial, sans-serif;
    outline: none;
}}

QMainWindow, QWidget, QDialog {{
    background-color: {C['off_white']};
    color: {C['text_primary']};
}}

QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: {C['off_white']};
    border: none;
}}

/* ══ Sidebar ════════════════════════════════════════════════════════════════ */
QFrame#sidebar {{
    background-color: {C['navy']};
    border: none;
    border-right: 1px solid {C['navy_border']};
}}

QLabel#logoLabel   {{ color: {C['accent']};  padding-left:4px; letter-spacing:2.5px; font-weight:700; }}
QLabel#subLabel    {{ color: {C['text_muted']}; padding-left:4px; letter-spacing:0.5px; }}
QLabel#navLabel    {{ color: {C['text_muted']}; padding-left:8px; letter-spacing:1.8px; font-size:11px; font-weight:600; }}
QLabel#versionLabel{{ color: {C['navy_border']}; padding-left:4px; }}

QPushButton#sidebarButton, QPushButton#settingsBtn {{
    background-color: transparent;
    color: {C['text_sidebar']};
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#sidebarButton:hover, QPushButton#settingsBtn:hover {{
    background-color: {C['navy_light']};
    color: {C['white']};
}}
QPushButton#sidebarButton:pressed, QPushButton#settingsBtn:pressed {{
    background-color: {C['navy_border']};
}}
QPushButton#sidebarButton:checked, QPushButton#settingsBtn:checked {{
    background-color: {ACCENT_GLOW};
    color: {C['accent']};
    border: 1px solid rgba(0,200,160,0.35);
    font-weight: 600;
}}

QFrame#divider {{
    border: none;
    border-top: 1px solid {C['navy_border']};
    color: {C['navy_border']};
}}
QFrame#separator {{
    border: none;
    border-left: 1px solid {C['border']};
    max-width: 1px;
    color: {C['border']};
}}

/* ══ Content area ═══════════════════════════════════════════════════════════ */
QStackedWidget#contentArea {{
    background-color: {C['off_white']};
}}

/* ══ Typography ═════════════════════════════════════════════════════════════ */
QLabel#panelTitle    {{ font-size:23px; font-weight:700; color:{C['text_primary']}; letter-spacing:0.2px; }}
QLabel#panelSubtitle {{ font-size:13px; color:{C['text_secondary']}; }}
QLabel#sectionTitle  {{ color:{C['text_primary']}; font-weight:600; }}
QLabel#fieldLabel    {{ font-size:12px; font-weight:600; color:{C['text_secondary']}; letter-spacing:0.5px; }}
QLabel#stepLabel     {{ color:{C['text_secondary']}; font-size:12px; }}
QLabel#stepLabelActive {{ color:{C['accent']}; font-size:12px; font-weight:600; }}
QLabel#stepLabelDone   {{ color:{C['success']}; font-size:12px; }}

/* ══ Cards ══════════════════════════════════════════════════════════════════ */
QFrame#card {{
    background-color: {C['card_bg']};
    border: 1px solid {C['border']};
    border-radius: 12px;
}}
QFrame#accentCard {{
    background-color: {C['card_bg']};
    border: 1px solid {C['border']};
    border-radius: 12px;
    border-left: 3px solid {C['accent']};
}}

/* ══ Buttons ════════════════════════════════════════════════════════════════ */
QPushButton#primaryBtn {{
    background-color: {C['accent']};
    color: #0D1117;
    border: none;
    border-radius: 8px;
    padding: 11px 24px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#primaryBtn:hover   {{ background-color: {C['accent_dim']}; }}
QPushButton#primaryBtn:pressed {{ background-color: #009070; padding-top:12px; padding-bottom:10px; }}
QPushButton#primaryBtn:disabled{{
    background-color: {C['border_dark']};
    color: {C['text_muted']};
}}

QPushButton#secondaryBtn {{
    background-color: transparent;
    color: {C['text_primary']};
    border: 1px solid {C['border_dark']};
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#secondaryBtn:hover    {{ background-color:{C['hover_bg']}; border-color:{C['accent']}; color:{C['accent']}; }}
QPushButton#secondaryBtn:pressed  {{ background-color:{C['border']}; }}
QPushButton#secondaryBtn:disabled {{ color:{C['text_muted']}; border-color:{C['border']}; }}

QPushButton#dangerBtn {{
    background-color: transparent;
    color: {C['error']};
    border: 1px solid rgba(239,68,68,0.35);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#dangerBtn:hover  {{ background-color:{C['error_bg']}; border-color:{C['error']}; }}
QPushButton#dangerBtn:pressed{{ background-color:{C['error_bg']}; }}

/* ══ Inputs ═════════════════════════════════════════════════════════════════ */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {C['input_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: {C['text_primary']};
    selection-background-color: {C['accent']};
    selection-color: #0D1117;
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{ border-color: {C['border_dark']}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {C['accent']};
    background-color: {C['card_bg']};
}}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{ color:{C['text_muted']}; background-color:{C['off_white']}; }}
QLineEdit::placeholder {{ color: {C['text_muted']}; }}

QComboBox {{
    background-color: {C['input_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: {C['text_primary']};
}}
QComboBox:hover  {{ border-color: {C['border_dark']}; }}
QComboBox:focus  {{ border-color: {C['accent']}; }}
QComboBox::drop-down {{ border: none; padding-right: 10px; }}
QComboBox::down-arrow {{ width:12px; height:12px; }}
QComboBox QAbstractItemView {{
    background-color: {C['card_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    color: {C['text_primary']};
    selection-background-color: {C['accent']};
    selection-color: #0D1117;
    padding: 4px;
    outline: none;
}}

/* ══ Spin box ═══════════════════════════════════════════════════════════════ */
QSpinBox, QDoubleSpinBox {{
    background-color: {C['input_bg']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 4px 8px;
    color: {C['text_primary']};
}}
QSpinBox:hover, QDoubleSpinBox:hover {{ border-color:{C['border_dark']}; }}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color:{C['accent']}; }}

/* ══ Check / Radio ══════════════════════════════════════════════════════════ */
QCheckBox, QRadioButton {{
    color: {C['text_primary']};
    spacing: 8px;
    font-size: 13px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1.5px solid {C['border_dark']};
    border-radius: 4px;
    background-color: {C['input_bg']};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {C['accent']}; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {C['accent']};
    border-color: {C['accent']};
}}

/* ══ Tabs ════════════════════════════════════════════════════════════════════ */
QTabWidget::pane {{
    border: 1px solid {C['border']};
    border-radius: 8px;
    background-color: {C['card_bg']};
}}
QTabBar::tab {{
    background-color: transparent;
    color: {C['text_secondary']};
    border: none;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {C['accent']};
    border-bottom: 2px solid {C['accent']};
    font-weight: 600;
}}
QTabBar::tab:hover {{ color:{C['text_primary']}; background-color:{C['hover_bg']}; border-radius:6px; }}

/* ══ Progress bar ═══════════════════════════════════════════════════════════ */
QProgressBar {{
    background-color: {C['progress_track']};
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color:{C['accent']}; border-radius:4px; }}

/* ══ Scrollbars ═════════════════════════════════════════════════════════════ */
QScrollBar:vertical {{
    background: transparent;
    width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C['border_dark']};
    border-radius: 5px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['text_muted']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {C['border_dark']};
    border-radius: 5px;
    min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: {C['text_muted']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ══ List / Table ═══════════════════════════════════════════════════════════ */
QListWidget {{
    background-color: {C['input_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 4px;
    font-size: 13px;
    color: {C['text_primary']};
    outline: none;
}}
QListWidget::item {{
    border-radius: 6px;
    padding: 8px 10px;
    color: {C['text_primary']};
}}
QListWidget::item:selected {{
    background-color: {C['accent']};
    color: #0D1117;
}}
QListWidget::item:hover {{ background-color:{C['hover_bg']}; }}

QTableWidget {{
    background-color: {C['input_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    gridline-color: {C['border']};
    color: {C['text_primary']};
    alternate-background-color: {C['hover_bg']};
    outline: none;
}}
QTableWidget::item {{ padding: 2px; }}
QTableWidget::item:selected {{
    background-color: {C['accent']};
    color: #0D1117;
}}
QHeaderView::section {{
    background-color: {C['card_bg']};
    color: {C['text_secondary']};
    border: none;
    border-bottom: 1px solid {C['border']};
    padding: 6px;
    font-weight: 600;
    font-size: 11px;
}}

/* ══ Toolbar / Menu ═════════════════════════════════════════════════════════ */
QMenuBar {{
    background-color: {C['navy']};
    color: {C['text_sidebar']};
    border-bottom: 1px solid {C['navy_border']};
}}
QMenuBar::item:selected {{ background-color:{C['navy_light']}; color:{C['white']}; border-radius:4px; }}
QMenu {{
    background-color: {C['card_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 4px;
    color: {C['text_primary']};
}}
QMenu::item {{ padding:7px 20px; border-radius:5px; }}
QMenu::item:selected {{ background-color:{C['accent']}; color:#0D1117; }}
QMenu::separator {{ height:1px; background:{C['border']}; margin:4px 0; }}

/* ══ Tooltip ════════════════════════════════════════════════════════════════ */
QToolTip {{
    background-color: {C['card_bg']};
    color: {C['text_primary']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 11px;
}}

/* ══ Status tags ════════════════════════════════════════════════════════════ */
QLabel#tagSuccess {{ background:{C['success_bg']}; color:{C['success']}; border-radius:4px; padding:2px 8px; font-size:11px; font-weight:600; }}
QLabel#tagWarning {{ background:{C['warning_bg']}; color:{C['warning']}; border-radius:4px; padding:2px 8px; font-size:11px; font-weight:600; }}
QLabel#tagInfo    {{ background:{C['info_bg']};    color:{C['info']};    border-radius:4px; padding:2px 8px; font-size:11px; font-weight:600; }}

/* ══ Drop zones ═════════════════════════════════════════════════════════════ */
QFrame#dropZone {{
    background-color: {C['input_bg']};
    border: 2px dashed {C['border_dark']};
    border-radius: 12px;
}}
QFrame#dropZone:hover {{ border-color: {C['text_muted']}; }}
QFrame#dropZoneActive {{
    background-color: {C['accent_glow']};
    border: 2px dashed {C['accent']};
    border-radius: 12px;
}}

/* ══ Dialog ═════════════════════════════════════════════════════════════════ */
QDialog {{
    background-color: {C['card_bg']};
}}
QLabel#dialogTitle {{ font-size:16px; font-weight:600; color:{C['text_primary']}; }}
QLabel#dialogSub   {{ font-size:12px; color:{C['text_secondary']}; }}

/* ══ Splitter ═══════════════════════════════════════════════════════════════ */
QSplitter::handle {{ background-color:{C['border']}; }}
QSplitter::handle:hover {{ background-color:{C['accent']}; }}
QSplitter::handle:horizontal {{ width:1px; }}
QSplitter::handle:vertical   {{ height:1px; }}

/* ══ Slider ═════════════════════════════════════════════════════════════════ */
QSlider::groove:horizontal {{
    height: 4px; border-radius:2px;
    background: {C['progress_track']};
}}
QSlider::handle:horizontal {{
    background: {C['accent']};
    border: none; width:14px; height:14px;
    margin: -5px 0; border-radius:7px;
}}
QSlider::handle:horizontal:hover {{ background: {C['accent_dim']}; }}
QSlider::sub-page:horizontal {{ background:{C['accent']}; border-radius:2px; }}
"""


# ══════════════════════════════════════════════════════════════════════════════
#  Module-level globals  (mutated by apply_theme)
# ══════════════════════════════════════════════════════════════════════════════
def _saved_theme() -> str:
    return QSettings("BES", "BridgeEngineeringSuite").value("ui_theme", "dark")


_current_theme : str  = _saved_theme()
COLORS         : dict = dict(_DARK if _current_theme == "dark" else _LIGHT)
STYLESHEET     : str  = _build_qss(COLORS)


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC  apply_theme()
# ══════════════════════════════════════════════════════════════════════════════
def apply_theme(theme: str, app: QApplication | None = None) -> None:
    """
    Switch theme globally.  Pass the QApplication instance to apply instantly.

    Steps:
      1. Update COLORS / STYLESHEET module globals
      2. Set Fusion style (once — idempotent)
      3. Push QPalette  → covers EVERY widget incl. native-drawn ones
      4. Push QSS       → accent, radius, sidebar, custom widgets
    """
    global _current_theme, COLORS, STYLESHEET

    _current_theme = theme
    palette_dict   = _DARK if theme == "dark" else _LIGHT
    COLORS.clear();  COLORS.update(palette_dict)
    STYLESHEET     = _build_qss(COLORS)

    QSettings("BES", "BridgeEngineeringSuite").setValue("ui_theme", theme)

    if app is None:
        app = QApplication.instance()
    if app is None:
        return

    # 1. Fusion style — disables OS-native drawing → honours our palette + QSS
    app.setStyle("Fusion")
    # 2. Full QPalette — fills all 46 roles for all colour groups
    app.setPalette(build_palette(theme))
    # 3. QSS on top — accent colours, radius, sidebar custom widgets
    app.setStyleSheet(STYLESHEET)


def get_stylesheet() -> str:
    return STYLESHEET

def current_theme() -> str:
    return _current_theme
