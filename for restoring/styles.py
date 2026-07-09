"""Application-wide theme and stylesheet support for Bridge Engineering Suite."""

from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


THEME_NAMES = {
    "dark": "Graphite",
    "light": "Studio",
    "ocean": "Ocean",
    "sunset": "Ember",
    "forest": "Meadow",
    "royal": "Prism",
}

THEME_SWATCHES = {
    "dark": ("#22D3EE", "#A78BFA"),
    "light": ("#2563EB", "#06B6D4"),
    "ocean": ("#0891B2", "#14B8A6"),
    "sunset": ("#F97316", "#E11D48"),
    "forest": ("#16A34A", "#84CC16"),
    "royal": ("#7C3AED", "#EC4899"),
}


_THEMES = {
    "dark": {
        "navy": "#101522",
        "navy_light": "#1B2433",
        "navy_border": "#303A4D",
        "sidebar_top": "#111827",
        "sidebar_bottom": "#172033",
        "accent": "#22D3EE",
        "accent_dim": "#0891B2",
        "accent_2": "#A78BFA",
        "accent_3": "#38BDF8",
        "accent_glow": "rgba(34,211,238,0.16)",
        "accent_text": "#071318",
        "white": "#F8FAFC",
        "off_white": "#151A24",
        "panel_grad_1": "#171D28",
        "panel_grad_2": "#111827",
        "text_primary": "#E5EEF8",
        "text_secondary": "#A9B5C7",
        "text_muted": "#708095",
        "text_sidebar": "#DCE7F5",
        "border": "#2A3444",
        "border_dark": "#435168",
        "input_bg": "#1E2634",
        "card_bg": "#1A2230",
        "card_hover": "#202B3A",
        "hover_bg": "#253146",
        "progress_track": "#2C3748",
        "success": "#34D399",
        "success_bg": "#0F2B24",
        "warning": "#FBBF24",
        "warning_bg": "#33250B",
        "error": "#FB7185",
        "error_bg": "#35131B",
        "info": "#60A5FA",
        "info_bg": "#11233E",
        "settings_bg": "#1A2230",
        "settings_row": "#202B3A",
    },
    "light": {
        "navy": "#102033",
        "navy_light": "#1A3654",
        "navy_border": "#315B86",
        "sidebar_top": "#0E263F",
        "sidebar_bottom": "#15395D",
        "accent": "#2563EB",
        "accent_dim": "#1D4ED8",
        "accent_2": "#06B6D4",
        "accent_3": "#7C3AED",
        "accent_glow": "rgba(37,99,235,0.12)",
        "accent_text": "#FFFFFF",
        "white": "#FFFFFF",
        "off_white": "#F4F7FB",
        "panel_grad_1": "#F8FBFF",
        "panel_grad_2": "#EEF5FF",
        "text_primary": "#172033",
        "text_secondary": "#526070",
        "text_muted": "#8290A3",
        "text_sidebar": "#DCEBFF",
        "border": "#DDE6F0",
        "border_dark": "#BAC7D8",
        "input_bg": "#FFFFFF",
        "card_bg": "#FFFFFF",
        "card_hover": "#F7FAFF",
        "hover_bg": "#EAF2FF",
        "progress_track": "#DDE6F0",
        "success": "#059669",
        "success_bg": "#EAFBF4",
        "warning": "#D97706",
        "warning_bg": "#FFF7E6",
        "error": "#DC2626",
        "error_bg": "#FFF1F2",
        "info": "#2563EB",
        "info_bg": "#EAF2FF",
        "settings_bg": "#FFFFFF",
        "settings_row": "#F3F7FC",
    },
    "ocean": {
        "navy": "#06202A",
        "navy_light": "#0B3442",
        "navy_border": "#14505F",
        "sidebar_top": "#052E3A",
        "sidebar_bottom": "#075264",
        "accent": "#0891B2",
        "accent_dim": "#0E7490",
        "accent_2": "#14B8A6",
        "accent_3": "#3B82F6",
        "accent_glow": "rgba(8,145,178,0.14)",
        "accent_text": "#FFFFFF",
        "white": "#F8FEFF",
        "off_white": "#EAF8FB",
        "panel_grad_1": "#F0FBFD",
        "panel_grad_2": "#DFF4FF",
        "text_primary": "#09212B",
        "text_secondary": "#3B6470",
        "text_muted": "#7697A0",
        "text_sidebar": "#D7F7FF",
        "border": "#C9E6ED",
        "border_dark": "#8DC9D6",
        "input_bg": "#F6FDFF",
        "card_bg": "#FFFFFF",
        "card_hover": "#F5FCFF",
        "hover_bg": "#DDF4F8",
        "progress_track": "#C9E6ED",
        "success": "#059669",
        "success_bg": "#E8FFF5",
        "warning": "#D97706",
        "warning_bg": "#FFF7E6",
        "error": "#DC2626",
        "error_bg": "#FFF1F2",
        "info": "#0284C7",
        "info_bg": "#E0F2FE",
        "settings_bg": "#FFFFFF",
        "settings_row": "#E7F7FB",
    },
    "sunset": {
        "navy": "#281826",
        "navy_light": "#3B2235",
        "navy_border": "#5B334A",
        "sidebar_top": "#3B1631",
        "sidebar_bottom": "#6B2A3E",
        "accent": "#F97316",
        "accent_dim": "#EA580C",
        "accent_2": "#E11D48",
        "accent_3": "#F59E0B",
        "accent_glow": "rgba(249,115,22,0.16)",
        "accent_text": "#FFFFFF",
        "white": "#FFF7ED",
        "off_white": "#FFF4EA",
        "panel_grad_1": "#FFF8F1",
        "panel_grad_2": "#FFE8EA",
        "text_primary": "#2A1510",
        "text_secondary": "#765348",
        "text_muted": "#A98276",
        "text_sidebar": "#FFE8D4",
        "border": "#F4D1C3",
        "border_dark": "#E6A489",
        "input_bg": "#FFFBF7",
        "card_bg": "#FFFFFF",
        "card_hover": "#FFFAF5",
        "hover_bg": "#FFE7D5",
        "progress_track": "#F4D1C3",
        "success": "#16A34A",
        "success_bg": "#ECFDF3",
        "warning": "#B45309",
        "warning_bg": "#FFF7E6",
        "error": "#E11D48",
        "error_bg": "#FFF1F2",
        "info": "#7C3AED",
        "info_bg": "#F3E8FF",
        "settings_bg": "#FFFFFF",
        "settings_row": "#FFEBDD",
    },
    "forest": {
        "navy": "#102018",
        "navy_light": "#193326",
        "navy_border": "#28513B",
        "sidebar_top": "#0F2A1C",
        "sidebar_bottom": "#1F4D34",
        "accent": "#16A34A",
        "accent_dim": "#15803D",
        "accent_2": "#84CC16",
        "accent_3": "#06B6D4",
        "accent_glow": "rgba(22,163,74,0.14)",
        "accent_text": "#FFFFFF",
        "white": "#F6FFF9",
        "off_white": "#EEF8EF",
        "panel_grad_1": "#F4FBF5",
        "panel_grad_2": "#E3F6E8",
        "text_primary": "#102018",
        "text_secondary": "#456552",
        "text_muted": "#76927F",
        "text_sidebar": "#DCFCE7",
        "border": "#CDE5D1",
        "border_dark": "#93C5A0",
        "input_bg": "#FAFFFB",
        "card_bg": "#FFFFFF",
        "card_hover": "#F8FFF9",
        "hover_bg": "#E1F3E6",
        "progress_track": "#CDE5D1",
        "success": "#16A34A",
        "success_bg": "#EAFBF0",
        "warning": "#CA8A04",
        "warning_bg": "#FEFCE8",
        "error": "#DC2626",
        "error_bg": "#FEF2F2",
        "info": "#0284C7",
        "info_bg": "#E0F2FE",
        "settings_bg": "#FFFFFF",
        "settings_row": "#E5F4E8",
    },
    "royal": {
        "navy": "#171735",
        "navy_light": "#242454",
        "navy_border": "#36367A",
        "sidebar_top": "#21174B",
        "sidebar_bottom": "#4C1D95",
        "accent": "#7C3AED",
        "accent_dim": "#6D28D9",
        "accent_2": "#EC4899",
        "accent_3": "#22D3EE",
        "accent_glow": "rgba(124,58,237,0.16)",
        "accent_text": "#FFFFFF",
        "white": "#FBFAFF",
        "off_white": "#F5F3FF",
        "panel_grad_1": "#F8F5FF",
        "panel_grad_2": "#FCE7F3",
        "text_primary": "#20143E",
        "text_secondary": "#655586",
        "text_muted": "#9588B2",
        "text_sidebar": "#EDE9FE",
        "border": "#DDD6FE",
        "border_dark": "#BFAAF8",
        "input_bg": "#FCFBFF",
        "card_bg": "#FFFFFF",
        "card_hover": "#FBFAFF",
        "hover_bg": "#EDE9FE",
        "progress_track": "#DDD6FE",
        "success": "#10B981",
        "success_bg": "#ECFDF5",
        "warning": "#F59E0B",
        "warning_bg": "#FFFBEB",
        "error": "#EF4444",
        "error_bg": "#FEF2F2",
        "info": "#6366F1",
        "info_bg": "#EEF2FF",
        "settings_bg": "#FFFFFF",
        "settings_row": "#EEE9FF",
    },
}


def _theme_dict(theme: str) -> dict:
    return _THEMES.get(theme, _THEMES["light"])


def _saved_theme() -> str:
    value = QSettings("BES", "BridgeEngineeringSuite").value("ui_theme", "light")
    return value if value in _THEMES else "light"


def build_palette(theme: str) -> QPalette:
    p = QPalette()
    c = QColor
    C = _theme_dict(theme)

    bg = C["panel_grad_1"]
    base = C["card_bg"]
    alt = C["hover_bg"]
    text = C["text_primary"]
    muted = C["text_muted"]
    button = C["card_bg"]
    highlight = C["accent"]
    highlighted_text = C.get("accent_text", "#FFFFFF")

    roles = {
        QPalette.ColorRole.Window: bg,
        QPalette.ColorRole.WindowText: text,
        QPalette.ColorRole.Base: base,
        QPalette.ColorRole.AlternateBase: alt,
        QPalette.ColorRole.Text: text,
        QPalette.ColorRole.Button: button,
        QPalette.ColorRole.ButtonText: text,
        QPalette.ColorRole.Highlight: highlight,
        QPalette.ColorRole.HighlightedText: highlighted_text,
        QPalette.ColorRole.ToolTipBase: base,
        QPalette.ColorRole.ToolTipText: text,
        QPalette.ColorRole.Link: C["info"],
        QPalette.ColorRole.LinkVisited: C["info"],
        QPalette.ColorRole.Mid: C["border"],
        QPalette.ColorRole.Midlight: alt,
        QPalette.ColorRole.Dark: C["border_dark"],
        QPalette.ColorRole.Shadow: C["navy"],
        QPalette.ColorRole.BrightText: C["error"],
        QPalette.ColorRole.Light: C["white"],
        QPalette.ColorRole.PlaceholderText: muted,
    }

    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, color in roles.items():
            p.setColor(group, role, c(color))

    disabled_roles = dict(roles)
    disabled_roles.update({
        QPalette.ColorRole.WindowText: muted,
        QPalette.ColorRole.Text: muted,
        QPalette.ColorRole.ButtonText: muted,
        QPalette.ColorRole.Highlight: C["border_dark"],
        QPalette.ColorRole.HighlightedText: muted,
    })
    for role, color in disabled_roles.items():
        p.setColor(QPalette.ColorGroup.Disabled, role, c(color))

    return p


def _build_qss(C: dict) -> str:
    return f"""
* {{
    font-family: 'Segoe UI', Arial, sans-serif;
    outline: none;
}}

QMainWindow, QWidget, QDialog {{
    background-color: {C['panel_grad_1']};
    color: {C['text_primary']};
}}

QLabel, QCheckBox, QRadioButton {{
    background-color: transparent;
}}

QWidget#contentShell, QStackedWidget#contentArea, QScrollArea,
QScrollArea > QWidget > QWidget {{
    background-color: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                      stop:0 {C['panel_grad_1']},
                                      stop:1 {C['panel_grad_2']});
    border: none;
}}

QFrame#sidebar {{
    background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                      stop:0 {C['sidebar_top']},
                                      stop:1 {C['sidebar_bottom']});
    border: none;
    border-right: 1px solid {C['navy_border']};
}}

QFrame#brandCard {{
    background-color: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
}}

QLabel#appMark {{
    background-color: {C['accent']};
    color: {C.get('accent_text', '#FFFFFF')};
    border-radius: 8px;
    font-size: 16px;
    font-weight: 800;
}}

QLabel#logoLabel {{
    color: {C['white']};
    font-size: 15px;
    font-weight: 800;
}}

QLabel#subLabel, QLabel#versionLabel {{
    color: {C['text_sidebar']};
    font-size: 11px;
}}

QLabel#navLabel {{
    color: {C['text_sidebar']};
    font-size: 10px;
    font-weight: 800;
    padding-left: 6px;
}}

QPushButton#sidebarButton, QPushButton#settingsBtn {{
    background-color: transparent;
    color: {C['text_sidebar']};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 11px 13px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton#sidebarButton:hover, QPushButton#settingsBtn:hover {{
    background-color: rgba(255,255,255,0.09);
    border-color: rgba(255,255,255,0.13);
    color: {C['white']};
}}

QPushButton#sidebarButton:pressed, QPushButton#settingsBtn:pressed {{
    background-color: rgba(255,255,255,0.15);
}}

QPushButton#sidebarButton:checked, QPushButton#settingsBtn:checked {{
    background-color: {C['accent_glow']};
    color: {C['white']};
    border: 1px solid {C['accent']};
    font-weight: 800;
}}

QFrame#divider {{
    border: none;
    border-top: 1px solid {C['navy_border']};
}}

QFrame#topBar {{
    background-color: {C['card_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
}}

QFrame#quickThemeRail {{
    background-color: {C['settings_row']};
    border: 1px solid {C['border']};
    border-radius: 8px;
}}

QLabel#topTitle {{
    color: {C['text_primary']};
    font-size: 18px;
    font-weight: 800;
}}

QLabel#topSubtitle {{
    color: {C['text_secondary']};
    font-size: 12px;
}}

QLabel#topPill {{
    background-color: {C['accent_glow']};
    color: {C['accent_dim']};
    border: 1px solid {C['accent']};
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 800;
}}

QLabel#panelTitle {{
    color: {C['text_primary']};
    font-size: 24px;
    font-weight: 800;
}}

QLabel#panelSubtitle {{
    color: {C['text_secondary']};
    font-size: 13px;
}}

QLabel#sectionTitle {{
    color: {C['text_primary']};
    font-weight: 800;
}}

QLabel#fieldLabel {{
    color: {C['text_secondary']};
    font-size: 12px;
    font-weight: 800;
}}

QLabel#stepLabel {{
    color: {C['text_secondary']};
    font-size: 12px;
}}

QLabel#stepLabelActive {{
    color: {C['accent_dim']};
    font-size: 12px;
    font-weight: 800;
}}

QLabel#stepLabelDone {{
    color: {C['success']};
    font-size: 12px;
    font-weight: 700;
}}

QFrame#card, QFrame#accentCard {{
    background-color: {C['card_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
}}

QFrame#card:hover, QFrame#accentCard:hover {{
    background-color: {C['card_hover']};
    border-color: {C['border_dark']};
}}

QFrame#accentCard {{
    border-left: 4px solid {C['accent']};
}}

QFrame#settingsRow {{
    background-color: {C['settings_row']};
    border: 1px solid {C['border']};
    border-radius: 8px;
}}

QFrame#settingsRow:hover {{
    border-color: {C['accent']};
}}

QPushButton#primaryBtn {{
    background-color: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                      stop:0 {C['accent']},
                                      stop:1 {C['accent_2']});
    color: {C.get('accent_text', '#FFFFFF')};
    border: none;
    border-radius: 7px;
    padding: 11px 22px;
    font-size: 13px;
    font-weight: 800;
}}

QPushButton#primaryBtn:hover {{
    background-color: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                      stop:0 {C['accent_2']},
                                      stop:1 {C['accent_3']});
}}

QPushButton#primaryBtn:pressed {{
    background-color: {C['accent_dim']};
    padding-top: 12px;
    padding-bottom: 10px;
}}

QPushButton#primaryBtn:disabled {{
    background-color: {C['border_dark']};
    color: {C['text_muted']};
}}

QPushButton#secondaryBtn {{
    background-color: {C['input_bg']};
    color: {C['text_primary']};
    border: 1px solid {C['border_dark']};
    border-radius: 7px;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 700;
}}

QPushButton#secondaryBtn:hover {{
    background-color: {C['hover_bg']};
    border-color: {C['accent']};
    color: {C['accent_dim']};
}}

QPushButton#secondaryBtn:pressed {{
    background-color: {C['border']};
}}

QPushButton#dangerBtn {{
    background-color: {C['error_bg']};
    color: {C['error']};
    border: 1px solid {C['error']};
    border-radius: 7px;
    padding: 5px 11px;
    font-size: 12px;
    font-weight: 700;
}}

QPushButton#dangerBtn:hover {{
    background-color: {C['error']};
    color: #FFFFFF;
}}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox,
QSpinBox, QDoubleSpinBox {{
    background-color: {C['input_bg']};
    border: 1px solid {C['border']};
    border-radius: 7px;
    padding: 8px 11px;
    color: {C['text_primary']};
    font-size: 13px;
    selection-background-color: {C['accent']};
    selection-color: {C.get('accent_text', '#FFFFFF')};
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover,
QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {C['border_dark']};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {C['accent']};
    background-color: {C['card_bg']};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 10px;
}}

QComboBox QAbstractItemView {{
    background-color: {C['card_bg']};
    border: 1px solid {C['border']};
    border-radius: 7px;
    color: {C['text_primary']};
    selection-background-color: {C['accent']};
    selection-color: {C.get('accent_text', '#FFFFFF')};
    padding: 4px;
}}

QCheckBox, QRadioButton {{
    color: {C['text_primary']};
    spacing: 8px;
    font-size: 13px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {C['border_dark']};
    border-radius: 5px;
    background-color: {C['input_bg']};
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {C['accent']};
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {C['accent']};
    border-color: {C['accent']};
}}

QTabWidget::pane {{
    border: 1px solid {C['border']};
    border-radius: 8px;
    background-color: {C['card_bg']};
}}

QTabBar::tab {{
    background-color: transparent;
    color: {C['text_secondary']};
    border: none;
    padding: 9px 18px;
    font-size: 12px;
    font-weight: 700;
    border-bottom: 3px solid transparent;
}}

QTabBar::tab:selected {{
    color: {C['accent_dim']};
    border-bottom: 3px solid {C['accent']};
}}

QTabBar::tab:hover {{
    color: {C['text_primary']};
    background-color: {C['hover_bg']};
    border-radius: 7px;
}}

QProgressBar {{
    background-color: {C['progress_track']};
    border: none;
    border-radius: 5px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                      stop:0 {C['accent']},
                                      stop:1 {C['accent_3']});
    border-radius: 5px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {C['border_dark']};
    border-radius: 5px;
    min-height: 34px;
}}

QScrollBar::handle:vertical:hover {{
    background: {C['accent_dim']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
}}

QScrollBar::handle:horizontal {{
    background: {C['border_dark']};
    border-radius: 5px;
    min-width: 34px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {C['accent_dim']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

QListWidget, QTableWidget {{
    background-color: {C['input_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    color: {C['text_primary']};
    outline: none;
}}

QListWidget::item {{
    border-radius: 7px;
    padding: 8px 10px;
}}

QListWidget::item:hover {{
    background-color: {C['hover_bg']};
}}

QListWidget::item:selected, QTableWidget::item:selected {{
    background-color: {C['accent']};
    color: {C.get('accent_text', '#FFFFFF')};
}}

QHeaderView::section {{
    background-color: {C['card_bg']};
    color: {C['text_secondary']};
    border: none;
    border-bottom: 1px solid {C['border']};
    padding: 7px;
    font-weight: 800;
    font-size: 11px;
}}

QMenuBar {{
    background-color: {C['navy']};
    color: {C['text_sidebar']};
    border-bottom: 1px solid {C['navy_border']};
}}

QMenuBar::item:selected {{
    background-color: {C['navy_light']};
    color: {C['white']};
    border-radius: 6px;
}}

QMenu {{
    background-color: {C['card_bg']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 4px;
    color: {C['text_primary']};
}}

QMenu::item {{
    padding: 7px 20px;
    border-radius: 6px;
}}

QMenu::item:selected {{
    background-color: {C['accent']};
    color: {C.get('accent_text', '#FFFFFF')};
}}

QToolTip {{
    background-color: {C['card_bg']};
    color: {C['text_primary']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 11px;
}}

QLabel#tagSuccess {{
    background: {C['success_bg']};
    color: {C['success']};
    border-radius: 5px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 800;
}}

QLabel#tagWarning {{
    background: {C['warning_bg']};
    color: {C['warning']};
    border-radius: 5px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 800;
}}

QLabel#tagInfo {{
    background: {C['info_bg']};
    color: {C['info']};
    border-radius: 5px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 800;
}}

QFrame#dropZone, QFrame#dropZoneActive {{
    background-color: {C['input_bg']};
    border: 2px dashed {C['border_dark']};
    border-radius: 8px;
}}

QFrame#dropZone:hover, QFrame#dropZoneActive {{
    background-color: {C['accent_glow']};
    border-color: {C['accent']};
}}

QLabel#dialogTitle {{
    font-size: 16px;
    font-weight: 800;
    color: {C['text_primary']};
}}

QLabel#dialogSub {{
    font-size: 12px;
    color: {C['text_secondary']};
}}

QSplitter::handle {{
    background-color: {C['border']};
}}

QSplitter::handle:hover {{
    background-color: {C['accent']};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

QSlider::groove:horizontal {{
    height: 5px;
    border-radius: 2px;
    background: {C['progress_track']};
}}

QSlider::handle:horizontal {{
    background: {C['accent']};
    border: none;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}

QSlider::handle:horizontal:hover {{
    background: {C['accent_2']};
}}

QSlider::sub-page:horizontal {{
    background: {C['accent']};
    border-radius: 2px;
}}
"""


_current_theme: str = _saved_theme()
COLORS: dict = dict(_theme_dict(_current_theme))
STYLESHEET: str = _build_qss(COLORS)


def apply_theme(theme: str, app: QApplication | None = None) -> None:
    global _current_theme, COLORS, STYLESHEET

    theme = theme if theme in _THEMES else "light"
    _current_theme = theme
    COLORS.clear()
    COLORS.update(_theme_dict(theme))
    STYLESHEET = _build_qss(COLORS)
    QSettings("BES", "BridgeEngineeringSuite").setValue("ui_theme", theme)

    if app is None:
        app = QApplication.instance()
    if app is None:
        return

    app.setStyle("Fusion")
    app.setPalette(build_palette(theme))
    app.setStyleSheet(STYLESHEET)


def get_stylesheet() -> str:
    return STYLESHEET


def current_theme() -> str:
    return _current_theme
