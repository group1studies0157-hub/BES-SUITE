"""
Bridge Engineering Suite — Futuristic Premium Dark Design System
═══════════════════════════════════════════════════════════════════
Deep graphite/charcoal surfaces with glowing cyan→violet gradient accents,
glassy translucent cards, thin luminous borders, and a single Segoe UI
typography ramp applied globally through QSS.

Themes: "graphite" is the dark flagship (default); the other five keep their
light identities, harmonized through the same radii / typography / gradients.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QLabel

DEFAULT_THEME = "graphite"

# Bump when the default theme experience changes: installs whose saved
# ui_theme_generation is older are migrated to DEFAULT_THEME exactly once.
_THEME_GENERATION = 4

THEME_NAMES = {
    "graphite": "Graphite",
    "studio": "Studio",
    "ocean": "Ocean",
    "sunset": "Ember",
    "forest": "Meadow",
    "royal": "Prism",
}

THEME_SWATCHES = {
    "graphite": ("#0F172A", "#22D3EE"),
    "studio": ("#2563EB", "#0891B2"),
    "ocean": ("#0284C7", "#10B981"),
    "sunset": ("#EA580C", "#DC2626"),
    "forest": ("#22C55E", "#84CC16"),
    "royal": ("#7C3AED", "#EC4899"),
}

# Typography — one family stack, one size ramp (Qt QSS takes integer px).
FONT_DISPLAY = "'Segoe UI Variable Display', 'Segoe UI Variable', 'Segoe UI', -apple-system, 'Helvetica Neue', Arial, sans-serif"
FONT_TEXT = "'Segoe UI Variable Text', 'Segoe UI Variable', 'Segoe UI', -apple-system, 'Helvetica Neue', Arial, sans-serif"
FONT_MONO = "'Cascadia Mono', 'Consolas', 'SF Mono', Monaco, monospace"
# Ramp: micro 10 · caption 11 · body 12 · section 15 · title 17 · hero 22


_THEMES = {
    "graphite": {
        # Flagship — deep charcoal-blue shell, glowing cyan→violet accents.
        # True dark: every surface token is dark and every text token is light,
        # so the whole UI re-inks proportionally when Graphite is active.
        "bg_primary": "#0F172A",
        "bg_secondary": "#1B2540",
        "bg_tertiary": "#16203A",
        "sidebar_bg": "#0B1120",
        "text_primary": "#E8EEF9",
        "text_secondary": "#B4C2D9",
        "text_tertiary": "#7C8CA8",
        "text_inverted": "#0B1120",   # dark ink on glowing accent fills
        "border": "#2A3650",
        "border_subtle": "#232E48",
        "input_bg": "#141D33",
        "input_border": "#33415E",
        "card_bg": "#141D33",
        "card_border": "#26334F",
        "hover_bg": "#1C2942",
        "active_bg": "#24314E",
        "disabled_bg": "#161F35",
        "disabled_text": "#5D6B85",
        "accent": "#22D3EE",
        "accent_dim": "#0E9BBE",
        "accent_light": "#5EE1F5",
        "accent_lighter": "#8FEAF9",
        "accent_bg": "rgba(34,211,238,0.14)",
        "accent_2": "#8B5CF6",
        "accent_3": "#A78BFA",
        "success": "#34D399",
        "success_bg": "rgba(52,211,153,0.14)",
        "warning": "#FBBF24",
        "warning_bg": "rgba(251,191,36,0.14)",
        "error": "#F87171",
        "error_bg": "rgba(248,113,113,0.14)",
        "info": "#38BDF8",
        "info_bg": "rgba(56,189,248,0.14)",
        # Glass surfaces
        "glass_bg": "rgba(20,29,51,0.86)",
        "glass_border": "rgba(148,180,220,0.14)",
        # Legacy tokens — 'navy' must stay DARK: it is also used as ink on
        # light chips (e.g. find-highlight text) in every theme.
        "navy": "#0B1120",
        "navy_light": "#16213A",
        "navy_border": "#33415E",
        "sidebar_top": "#0A1A33",
        "sidebar_bottom": "#0E2A52",
        "accent_glow": "rgba(34,211,238,0.20)",
        "accent_text": "#0B1120",
        "white": "#FFFFFF",
        "off_white": "#E8EEF9",
        "panel_grad_1": "#141D33",
        "panel_grad_2": "#0F172A",
        "text_muted": "#7C8CA8",
        "text_sidebar": "#C7D4EA",
        "border_dark": "#3A4A6B",
        "progress_track": "#232E48",
        "settings_bg": "#0F172A",
        "settings_row": "#141D33",
    },
    "studio": {
        # Light — clean, bright, premium
        "bg_primary": "#FFFFFF",
        "bg_secondary": "#F9FAFB",
        "bg_tertiary": "#F3F4F6",
        "sidebar_bg": "#FFFFFF",
        "text_primary": "#111827",
        "text_secondary": "#4B5563",
        "text_tertiary": "#9CA3AF",
        "text_inverted": "#FFFFFF",
        "border": "#E5E7EB",
        "border_subtle": "#F3F4F6",
        "input_bg": "#FFFFFF",
        "input_border": "#D1D5DB",
        "card_bg": "#FFFFFF",
        "card_border": "#E5E7EB",
        "hover_bg": "#F9FAFB",
        "active_bg": "#F3F4F6",
        "disabled_bg": "#F9FAFB",
        "disabled_text": "#D1D5DB",
        "accent": "#2563EB",
        "accent_dim": "#1E40AF",
        "accent_light": "#3B82F6",
        "accent_lighter": "#60A5FA",
        "accent_bg": "rgba(37,99,235,0.1)",
        "accent_2": "#0891B2",
        "accent_3": "#7C3AED",
        "success": "#059669",
        "success_bg": "rgba(5,150,105,0.1)",
        "warning": "#D97706",
        "warning_bg": "rgba(217,119,6,0.1)",
        "error": "#DC2626",
        "error_bg": "rgba(220,38,38,0.1)",
        "info": "#2563EB",
        "info_bg": "rgba(37,99,235,0.1)",
        # Glass surfaces
        "glass_bg": "rgba(255,255,255,0.82)",
        "glass_border": "rgba(17,24,39,0.08)",
        # Legacy
        "navy": "#111827",
        "navy_light": "#F3F4F6",
        "navy_border": "#D1D5DB",
        "sidebar_top": "#FFFFFF",
        "sidebar_bottom": "#FFFFFF",
        "accent_dim": "#1E40AF",
        "accent_glow": "rgba(37,99,235,0.15)",
        "accent_text": "#FFFFFF",
        "white": "#FFFFFF",
        "off_white": "#F9FAFB",
        "panel_grad_1": "#FFFFFF",
        "panel_grad_2": "#F9FAFB",
        "text_muted": "#9CA3AF",
        "text_sidebar": "#4B5563",
        "border_dark": "#D1D5DB",
        "progress_track": "#E5E7EB",
        "settings_bg": "#FFFFFF",
        "settings_row": "#F9FAFB",
    },
    "ocean": {
        "bg_primary": "#F0F9FF",
        "bg_secondary": "#F8FCFD",
        "bg_tertiary": "#EFF6FF",
        "sidebar_bg": "#FFFFFF",
        "text_primary": "#0C2340",
        "text_secondary": "#0E7490",
        "text_tertiary": "#7BA3B0",
        "text_inverted": "#FFFFFF",
        "border": "#BFDBFE",
        "border_subtle": "#EFF6FF",
        "input_bg": "#FFFFFF",
        "input_border": "#93C5FD",
        "card_bg": "#FFFFFF",
        "card_border": "#BFDBFE",
        "hover_bg": "#EFF6FF",
        "active_bg": "#DBEAFE",
        "disabled_bg": "#F8FCFD",
        "disabled_text": "#93C5FD",
        "accent": "#0284C7",
        "accent_dim": "#0369A1",
        "accent_light": "#0EA5E9",
        "accent_lighter": "#38BDF8",
        "accent_bg": "rgba(2,132,199,0.1)",
        "accent_2": "#10B981",
        "accent_3": "#06B6D4",
        "success": "#059669",
        "success_bg": "rgba(5,150,105,0.1)",
        "warning": "#D97706",
        "warning_bg": "rgba(217,119,6,0.1)",
        "error": "#DC2626",
        "error_bg": "rgba(220,38,38,0.1)",
        "info": "#0284C7",
        "info_bg": "rgba(2,132,199,0.1)",
        # Glass surfaces
        "glass_bg": "rgba(255,255,255,0.82)",
        "glass_border": "rgba(2,132,199,0.14)",
        # Legacy
        "navy": "#0C2340",
        "navy_light": "#EFF6FF",
        "navy_border": "#93C5FD",
        "sidebar_top": "#FFFFFF",
        "sidebar_bottom": "#FFFFFF",
        "accent_dim": "#0369A1",
        "accent_glow": "rgba(2,132,199,0.12)",
        "accent_text": "#FFFFFF",
        "white": "#F0F9FF",
        "off_white": "#F8FCFD",
        "panel_grad_1": "#FFFFFF",
        "panel_grad_2": "#F8FCFD",
        "text_muted": "#7BA3B0",
        "text_sidebar": "#0E7490",
        "border_dark": "#93C5FD",
        "progress_track": "#BFDBFE",
        "settings_bg": "#FFFFFF",
        "settings_row": "#F8FCFD",
    },
    "sunset": {
        "bg_primary": "#FFF8F5",
        "bg_secondary": "#FFFCFA",
        "bg_tertiary": "#FFF5F0",
        "sidebar_bg": "#FFFFFF",
        "text_primary": "#5A2817",
        "text_secondary": "#B45309",
        "text_tertiary": "#CA8A04",
        "text_inverted": "#FFFFFF",
        "border": "#FBCFE8",
        "border_subtle": "#FFF5F0",
        "input_bg": "#FFFFFF",
        "input_border": "#FED7AA",
        "card_bg": "#FFFFFF",
        "card_border": "#FBCFE8",
        "hover_bg": "#FFF5F0",
        "active_bg": "#FEE2E2",
        "disabled_bg": "#FFFCFA",
        "disabled_text": "#FECACA",
        "accent": "#EA580C",
        "accent_dim": "#C2410C",
        "accent_light": "#F97316",
        "accent_lighter": "#FB923C",
        "accent_bg": "rgba(234,88,12,0.1)",
        "accent_2": "#DC2626",
        "accent_3": "#F59E0B",
        "success": "#16A34A",
        "success_bg": "rgba(22,163,74,0.1)",
        "warning": "#EA580C",
        "warning_bg": "rgba(234,88,12,0.1)",
        "error": "#DC2626",
        "error_bg": "rgba(220,38,38,0.1)",
        "info": "#EA580C",
        "info_bg": "rgba(234,88,12,0.1)",
        # Glass surfaces
        "glass_bg": "rgba(255,255,255,0.82)",
        "glass_border": "rgba(234,88,12,0.14)",
        # Legacy
        "navy": "#5A2817",
        "navy_light": "#FFF5F0",
        "navy_border": "#FED7AA",
        "sidebar_top": "#FFFFFF",
        "sidebar_bottom": "#FFFFFF",
        "accent_dim": "#C2410C",
        "accent_glow": "rgba(234,88,12,0.12)",
        "accent_text": "#FFFFFF",
        "white": "#FFF8F5",
        "off_white": "#FFFCFA",
        "panel_grad_1": "#FFFFFF",
        "panel_grad_2": "#FFFCFA",
        "text_muted": "#CA8A04",
        "text_sidebar": "#B45309",
        "border_dark": "#FED7AA",
        "progress_track": "#FBCFE8",
        "settings_bg": "#FFFFFF",
        "settings_row": "#FFFCFA",
    },
    "forest": {
        "bg_primary": "#F0FDF4",
        "bg_secondary": "#F7FEFC",
        "bg_tertiary": "#DFFCF0",
        "sidebar_bg": "#FFFFFF",
        "text_primary": "#15290C",
        "text_secondary": "#166534",
        "text_tertiary": "#65A30D",
        "text_inverted": "#FFFFFF",
        "border": "#BBF7D0",
        "border_subtle": "#DFFCF0",
        "input_bg": "#FFFFFF",
        "input_border": "#86EFAC",
        "card_bg": "#FFFFFF",
        "card_border": "#BBF7D0",
        "hover_bg": "#DFFCF0",
        "active_bg": "#CCFBF1",
        "disabled_bg": "#F7FEFC",
        "disabled_text": "#86EFAC",
        "accent": "#16A34A",
        "accent_dim": "#15803D",
        "accent_light": "#22C55E",
        "accent_lighter": "#4ADE80",
        "accent_bg": "rgba(22,163,74,0.1)",
        "accent_2": "#84CC16",
        "accent_3": "#10B981",
        "success": "#16A34A",
        "success_bg": "rgba(22,163,74,0.1)",
        "warning": "#CA8A04",
        "warning_bg": "rgba(202,138,4,0.1)",
        "error": "#DC2626",
        "error_bg": "rgba(220,38,38,0.1)",
        "info": "#0284C7",
        "info_bg": "rgba(2,132,199,0.1)",
        # Glass surfaces
        "glass_bg": "rgba(255,255,255,0.82)",
        "glass_border": "rgba(22,163,74,0.14)",
        # Legacy
        "navy": "#15290C",
        "navy_light": "#DFFCF0",
        "navy_border": "#86EFAC",
        "sidebar_top": "#FFFFFF",
        "sidebar_bottom": "#FFFFFF",
        "accent_dim": "#15803D",
        "accent_glow": "rgba(22,163,74,0.12)",
        "accent_text": "#FFFFFF",
        "white": "#F0FDF4",
        "off_white": "#F7FEFC",
        "panel_grad_1": "#FFFFFF",
        "panel_grad_2": "#F7FEFC",
        "text_muted": "#65A30D",
        "text_sidebar": "#166534",
        "border_dark": "#86EFAC",
        "progress_track": "#BBF7D0",
        "settings_bg": "#FFFFFF",
        "settings_row": "#F7FEFC",
    },
    "royal": {
        "bg_primary": "#FAF8FF",
        "bg_secondary": "#FDF5FF",
        "bg_tertiary": "#F3E8FF",
        "sidebar_bg": "#FFFFFF",
        "text_primary": "#5B21B6",
        "text_secondary": "#7E22CE",
        "text_tertiary": "#A855F7",
        "text_inverted": "#FFFFFF",
        "border": "#E9D5FF",
        "border_subtle": "#F3E8FF",
        "input_bg": "#FFFFFF",
        "input_border": "#D8B4FE",
        "card_bg": "#FFFFFF",
        "card_border": "#E9D5FF",
        "hover_bg": "#F3E8FF",
        "active_bg": "#E9D5FF",
        "disabled_bg": "#FDF5FF",
        "disabled_text": "#D8B4FE",
        "accent": "#7C3AED",
        "accent_dim": "#6D28D9",
        "accent_light": "#A855F7",
        "accent_lighter": "#C084FC",
        "accent_bg": "rgba(124,58,237,0.1)",
        "accent_2": "#EC4899",
        "accent_3": "#22D3EE",
        "success": "#10B981",
        "success_bg": "rgba(16,185,129,0.1)",
        "warning": "#F59E0B",
        "warning_bg": "rgba(245,158,11,0.1)",
        "error": "#EF4444",
        "error_bg": "rgba(239,68,68,0.1)",
        "info": "#7C3AED",
        "info_bg": "rgba(124,58,237,0.1)",
        # Glass surfaces
        "glass_bg": "rgba(255,255,255,0.82)",
        "glass_border": "rgba(124,58,237,0.14)",
        # Legacy
        "navy": "#5B21B6",
        "navy_light": "#F3E8FF",
        "navy_border": "#D8B4FE",
        "sidebar_top": "#FFFFFF",
        "sidebar_bottom": "#FFFFFF",
        "accent_dim": "#6D28D9",
        "accent_glow": "rgba(124,58,237,0.12)",
        "accent_text": "#FFFFFF",
        "white": "#FAF8FF",
        "off_white": "#FDF5FF",
        "panel_grad_1": "#FFFFFF",
        "panel_grad_2": "#FDF5FF",
        "text_muted": "#A855F7",
        "text_sidebar": "#7E22CE",
        "border_dark": "#D8B4FE",
        "progress_track": "#E9D5FF",
        "settings_bg": "#FFFFFF",
        "settings_row": "#FDF5FF",
    },
}


def _theme_dict(theme: str) -> dict:
    return _THEMES.get(theme, _THEMES[DEFAULT_THEME])


def _saved_theme() -> str:
    """Saved preference, migrating installs older than the redesign to Graphite once."""
    s = QSettings("BES", "BridgeEngineeringSuite")
    try:
        gen = int(s.value("ui_theme_generation", 0) or 0)
    except (TypeError, ValueError):
        gen = 0
    saved = s.value("ui_theme", "")
    if not saved or gen < _THEME_GENERATION:
        return DEFAULT_THEME
    return saved if saved in _THEMES else DEFAULT_THEME


def build_palette(theme: str) -> QPalette:
    p = QPalette()
    c = QColor
    C = _theme_dict(theme)

    bg = C["bg_primary"]
    base = C["card_bg"]
    alt = C["hover_bg"]
    text = C["text_primary"]
    muted = C["text_tertiary"]
    button = C["bg_secondary"]
    highlight = C["accent"]
    highlighted_text = C.get("text_inverted", "#FFFFFF")

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
        QPalette.ColorRole.LinkVisited: C["accent_2"],
        QPalette.ColorRole.Mid: C["border"],
        QPalette.ColorRole.Midlight: alt,
        QPalette.ColorRole.Dark: C["border_dark"],
        QPalette.ColorRole.Shadow: C["bg_primary"],
        QPalette.ColorRole.BrightText: C["error"],
        QPalette.ColorRole.Light: C["white"],
        QPalette.ColorRole.PlaceholderText: muted,
    }

    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, color in roles.items():
            p.setColor(group, role, c(color))

    disabled_roles = dict(roles)
    disabled_roles[QPalette.ColorRole.WindowText] = C["disabled_text"]
    disabled_roles[QPalette.ColorRole.ButtonText] = C["disabled_text"]
    disabled_roles[QPalette.ColorRole.Text] = C["disabled_text"]
    for role, color in disabled_roles.items():
        p.setColor(QPalette.ColorGroup.Disabled, role, c(color))

    return p


def _qg(c1: str, c2: str, vertical: bool = False) -> str:
    """Two-stop qlineargradient fragment (diagonal by default)."""
    x2, y2 = ("0", "1") if vertical else ("1", "0")
    return f"qlineargradient(x1:0,y1:0,x2:{x2},y2:{y2},stop:0 {c1},stop:1 {c2})"


def _build_qss(C: dict) -> str:
    """Futuristic premium QSS: glass cards, gradient primaries, neon focus, 12px radii."""
    grad = _qg
    return f"""
/* ── Global stage ──────────────────────────────────────────────── */

QMainWindow, QDialog, QWidget {{
    background-color: {C['bg_primary']};
    color: {C['text_primary']};
    font-family: {FONT_TEXT};
    font-size: 12px;
}}

QMainWindow {{
    border: none;
    margin: 0;
    padding: 0;
}}

QDialog {{
    border: 1px solid {C['card_border']};
    background-color: {C['bg_primary']};
}}

#contentShell {{
    background-color: {C['bg_primary']};
}}

#contentArea {{
    background: transparent;
}}

/* ── Sidebar & Navigation ──────────────────────────────────────── */

#sidebarContainer {{
    background-color: {C['sidebar_bg']};
    border-right: 1px solid {C['border_subtle']};
}}

QPushButton#sidebarButton {{
    background-color: transparent;
    color: {C['text_secondary']};
    border: none;
    border-radius: 10px;
    padding: 9px 10px;
    margin: 2px 6px;
    font-family: {FONT_TEXT};
    font-size: 11px;
    font-weight: 500;
    text-align: left;
}}

QPushButton#sidebarButton:hover {{
    background-color: {C['hover_bg']};
    color: {C['text_primary']};
}}

QPushButton#sidebarButton:checked {{
    background-color: {C['accent_bg']};
    color: {C['accent_light']};
    font-weight: 600;
}}

QPushButton#settingsBtn {{
    background-color: transparent;
    color: {C['text_secondary']};
    border: none;
    border-radius: 10px;
    padding: 9px 10px;
    margin: 2px 6px;
    font-family: {FONT_TEXT};
    font-size: 11px;
    font-weight: 500;
    text-align: left;
}}

QPushButton#settingsBtn:hover {{
    background-color: {C['hover_bg']};
    color: {C['text_primary']};
}}

QPushButton#settingsBtn:checked {{
    background-color: {C['accent_bg']};
    color: {C['accent_light']};
    font-weight: 600;
}}

QPushButton#pinButton {{
    background-color: transparent;
    color: {C['text_tertiary']};
    border: none;
    border-radius: 5px;
    font-size: 9px;
    font-weight: 600;
}}

QPushButton#pinButton:hover {{
    background-color: {C['hover_bg']};
    color: {C['accent']};
}}

QFrame#brandCard {{
    background: {grad(C['sidebar_top'], C['sidebar_bottom'], vertical=True)};
    border: 1px solid {C['glass_border']};
    border-radius: 12px;
}}

QLabel#appMark {{
    background: {grad(C['accent'], C['accent_2'])};
    color: {C['text_inverted']};
    border-radius: 8px;
    font-size: 14px;
    font-weight: 800;
}}

QLabel#logoLabel {{
    color: {C['text_primary']};
    font-family: {FONT_DISPLAY};
    font-size: 14px;
    font-weight: 800;
}}

QLabel#subLabel {{
    color: {C['text_tertiary']};
    font-size: 9px;
}}

QLabel#navLabel {{
    color: {C['text_tertiary']};
    font-size: 10px;
    font-weight: 700;
    padding-left: 4px;
    background: transparent;
}}

QLabel#versionLabel {{
    color: {C['text_tertiary']};
    font-size: 9px;
}}

/* ── Top bar ───────────────────────────────────────────────────── */

QFrame#sidebar {{
    background-color: {C['sidebar_bg']};
    border-right: 1px solid {C['border_subtle']};
}}

QFrame#sidebar QLabel {{
    background: transparent;
}}

QFrame#sidebar QLabel#navLabel {{
    color: {C['text_sidebar']};
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1px;
    padding-left: 6px;
}}

QFrame#sidebar QLabel#logoLabel {{
    color: {C['text_sidebar']};
    font-family: {FONT_DISPLAY};
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 0.5px;
}}

QFrame#sidebar QLabel#subLabel {{
    color: {C['text_sidebar']};
    font-size: 9px;
    font-weight: 600;
    border-bottom: 2px solid {grad(C['accent'], C['accent_2'])};
    padding-bottom: 2px;
}}

QFrame#sidebar QLabel#sideTagline {{
    color: {C['text_sidebar']};
    font-size: 7px;
    font-weight: 500;
    letter-spacing: 0.5px;
}}

QFrame#sidebar QLabel#versionLabel {{
    color: {C['text_sidebar']};
    font-size: 9px;
}}

QFrame#sidebar QLabel#sideStatus {{
    color: {C['success']};
    font-size: 10px;
    font-weight: 700;
}}

QFrame#sidebar QPushButton#sidebarButton,
QFrame#sidebar QPushButton#settingsBtn {{
    background-color: transparent;
    color: {C['text_sidebar']};
    border: none;
    border-radius: 10px;
    padding: 9px 10px;
    margin: 2px 4px;
    font-size: 11px;
    font-weight: 600;
    text-align: left;
}}

QFrame#sidebar QPushButton#sidebarButton:hover,
QFrame#sidebar QPushButton#settingsBtn:hover {{
    background-color: {C['hover_bg']};
    color: {C['text_primary']};
}}

QFrame#sidebar QPushButton#sidebarButton:checked,
QFrame#sidebar QPushButton#settingsBtn:checked {{
    background-color: {C['accent']};
    color: {C['text_inverted']};
    font-weight: 700;
}}

QFrame#sidebar QPushButton#pinButton {{
    color: {C['text_sidebar']};
}}

#topBar {{
    background-color: {C['card_bg']};
    border-bottom: 1px solid {C['border_subtle']};
    /* spacing is owned by the layout's contentsMargins in _build_top_bar;
       QSS padding would stack on top of it and squeeze panel controls */
    padding: 0px;
}}

QLabel#topTitle {{
    color: {C['text_primary']};
    font-family: {FONT_DISPLAY};
    font-size: 17px;
    font-weight: 700;
    background: transparent;
}}

QLabel#topSubtitle {{
    color: {C['text_secondary']};
    font-size: 12px;
    font-weight: 400;
    background: transparent;
}}

QLabel#panelTitle {{
    font-family: {FONT_DISPLAY};
    font-size: 15px;
    font-weight: 600;
    background: transparent;
}}

QLabel#panelSubtitle {{
    color: {C['text_secondary']};
    font-size: 11px;
    background: transparent;
}}

/* ── Buttons ───────────────────────────────────────────────────── */

QPushButton {{
    background-color: {C['bg_secondary']};
    color: {C['text_primary']};
    border: 1px solid {C['border']};
    border-radius: 10px;
    padding: 8px 16px;
    font-family: {FONT_TEXT};
    font-size: 12px;
    font-weight: 600;
    outline: none;
    min-height: 30px;
}}

QPushButton:hover {{
    background-color: {C['hover_bg']};
    border-color: {C['accent_dim']};
    color: {C['text_primary']};
}}

QPushButton:pressed {{
    background-color: {C['active_bg']};
    border-color: {C['accent']};
}}

QPushButton:focus {{
    border-color: {C['accent']};
}}

QPushButton:disabled {{
    color: {C['disabled_text']};
    background-color: {C['disabled_bg']};
    border-color: {C['border_subtle']};
}}

QPushButton#primaryBtn {{
    background: {grad(C['accent'], C['accent_2'])};
    color: {C['text_inverted']};
    border: 1px solid {C['glass_border']};
    font-weight: 700;
}}

QPushButton#primaryBtn:hover {{
    background: {grad(C['accent_light'], C['accent'])};
    border-color: {C['accent_light']};
}}

QPushButton#primaryBtn:pressed {{
    background: {grad(C['accent_dim'], C['accent_dim'])};
    border-color: {C['accent_dim']};
}}

QPushButton#secondaryBtn {{
    background-color: {C['bg_secondary']};
    border: 1px solid {C['border_dark']};
}}

QPushButton#secondaryBtn:hover {{
    background-color: {C['hover_bg']};
    border-color: {C['accent']};
    color: {C['text_primary']};
}}

/* ── Text inputs & Fields — neon focus ─────────────────────────── */

QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {C['input_bg']};
    color: {C['text_primary']};
    border: 1px solid {C['input_border']};
    border-radius: 10px;
    padding: 9px 12px;
    font-family: {FONT_MONO};
    font-size: 12px;
    selection-background-color: {C['accent']};
    selection-color: {C['text_inverted']};
    min-height: 30px;
}}

QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{
    border-color: {C['border_dark']};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {C['accent']};
    background-color: {C['input_bg']};
}}

QPlainTextEdit, QTextEdit {{
    font-family: {FONT_TEXT};
}}

QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{
    background-color: {C['disabled_bg']};
    color: {C['disabled_text']};
    border-color: {C['border_subtle']};
}}

/* ── Dropdowns (ComboBox) ──────────────────────────────────────── */

QComboBox {{
    background-color: {C['input_bg']};
    color: {C['text_primary']};
    border: 1px solid {C['input_border']};
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 12px;
    min-height: 30px;
}}

QComboBox:hover {{
    border-color: {C['border_dark']};
}}

QComboBox:focus {{
    border: 1px solid {C['accent']};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border: none;
    background: transparent;
}}

QAbstractItemView {{
    background-color: {C['card_bg']};
    color: {C['text_primary']};
    border: 1px solid {C['card_border']};
    border-radius: 10px;
    outline: none;
    selection-background-color: {C['active_bg']};
    selection-color: {C['accent_light']};
}}

QAbstractItemView::item {{
    padding: 8px 12px;
    border-radius: 6px;
}}

QAbstractItemView::item:hover {{
    background-color: {C['hover_bg']};
}}

QAbstractItemView::item:selected {{
    background-color: {C['active_bg']};
    color: {C['accent_light']};
}}

/* ── Checkboxes & Radios ───────────────────────────────────────── */

QCheckBox, QRadioButton {{
    color: {C['text_primary']};
    font-family: {FONT_TEXT};
    font-size: 12px;
    spacing: 10px;
    background: transparent;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {C['input_border']};
    border-radius: 6px;
    background-color: {C['input_bg']};
}}

QRadioButton::indicator {{
    border-radius: 9px;
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {C['accent']};
    background-color: {C['accent_bg']};
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {grad(C['accent'], C['accent_2'])};
    border-color: {C['accent']};
}}

/* ── Tabs ──────────────────────────────────────────────────────── */

QTabWidget::pane {{
    border: 1px solid {C['card_border']};
    border-radius: 12px;
    background-color: {C['card_bg']};
    top: -1px;
}}

QTabBar {{
    background-color: transparent;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {C['text_secondary']};
    border: none;
    padding: 11px 16px;
    font-family: {FONT_TEXT};
    font-size: 12px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
}}

QTabBar::tab:selected {{
    color: {C['accent']};
    border-bottom: 2px solid {C['accent']};
    font-weight: 700;
}}

QTabBar::tab:hover {{
    color: {C['text_primary']};
    background-color: {C['hover_bg']};
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}

/* ── Scroll Bars — slim, luminous ──────────────────────────────── */

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px 0;
}}

QScrollBar::handle:vertical {{
    background-color: {C['border_dark']};
    border-radius: 4px;
    min-height: 40px;
}}

QScrollBar::handle:vertical:hover {{
    background: {grad(C['accent'], C['accent_2'], vertical=True)};
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0 2px;
}}

QScrollBar::handle:horizontal {{
    background-color: {C['border_dark']};
    border-radius: 4px;
    min-width: 40px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {grad(C['accent'], C['accent_2'])};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
    background: none;
    border: none;
}}

QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    border: none;
}}

/* ── Tables & Lists ────────────────────────────────────────────── */

QTableWidget, QListWidget {{
    background-color: {C['input_bg']};
    alternate-background-color: {C['bg_secondary']};
    border: 1px solid {C['card_border']};
    border-radius: 12px;
    color: {C['text_primary']};
    outline: none;
    gridline-color: {C['border_subtle']};
}}

QTableWidget::item {{
    padding: 8px;
    border-radius: 6px;
}}

QTableWidget::item:hover, QListWidget::item:hover {{
    background-color: {C['hover_bg']};
}}

QTableWidget::item:selected, QListWidget::item:selected {{
    background-color: {C['active_bg']};
    color: {C['accent_light']};
}}

QHeaderView::section {{
    background-color: {C['bg_secondary']};
    color: {C['text_secondary']};
    border: none;
    border-bottom: 1px solid {C['card_border']};
    padding: 10px 12px;
    font-family: {FONT_TEXT};
    font-size: 11px;
    font-weight: 700;
}}

/* ── Progress Bar ──────────────────────────────────────────────── */

QProgressBar {{
    background-color: {C['progress_track']};
    border: none;
    border-radius: 7px;
    text-align: center;
    color: transparent;
    min-height: 7px;
}}

QProgressBar::chunk {{
    background: {grad(C['accent'], C['accent_2'])};
    border-radius: 7px;
}}

/* ── Menus ─────────────────────────────────────────────────────── */

QMenuBar {{
    background-color: {C['bg_primary']};
    color: {C['text_primary']};
    border-bottom: 1px solid {C['border_subtle']};
    padding: 4px;
}}

QMenuBar::item:selected {{
    background-color: {C['hover_bg']};
    border-radius: 8px;
}}

QMenu {{
    background-color: {C['card_bg']};
    border: 1px solid {C['card_border']};
    border-radius: 12px;
    padding: 6px;
    color: {C['text_primary']};
}}

QMenu::item {{
    padding: 9px 20px;
    border-radius: 8px;
    font-family: {FONT_TEXT};
    font-size: 12px;
}}

QMenu::item:selected {{
    background-color: {C['active_bg']};
    color: {C['accent_light']};
}}

/* ── Tool Tips ─────────────────────────────────────────────────── */

QToolTip {{
    background-color: {C['bg_tertiary']};
    color: {C['text_primary']};
    border: 1px solid {C['glass_border']};
    border-radius: 8px;
    padding: 8px 12px;
    font-family: {FONT_TEXT};
    font-size: 11px;
}}

/* ── Frames & Panels — glass ───────────────────────────────────── */

QFrame {{
    border: none;
    background-color: transparent;
}}

QFrame#card {{
    background-color: {C['glass_bg']};
    border: 1px solid {C['glass_border']};
    border-radius: 12px;
    padding: 14px;
}}

QFrame#dropZone {{
    background-color: {C['input_bg']};
    border: 2px dashed {C['border_dark']};
    border-radius: 12px;
}}

QFrame#dropZone:hover {{
    background-color: {C['accent_bg']};
    border: 2px dashed {C['accent']};
    border-radius: 12px;
}}

/* ── Home dashboard — hero, chips, store cards ─────────────────── */

QFrame#heroBanner {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent_dim']},
                                stop:0.48 {C['accent']},
                                stop:1 {C['accent_2']});
    border: 1px solid {C['glass_border']};
    border-radius: 16px;
}}

QFrame#heroBanner QLabel {{
    background: transparent;
}}

QFrame#heroBanner QLabel#heroKicker {{
    font-size: 10px;
    font-weight: 800;
}}

QFrame#heroBanner QLabel#heroTitle {{
    font-family: {FONT_DISPLAY};
    font-size: 22px;
    font-weight: 800;
}}

QFrame#heroBanner QLabel#heroSubtitle {{
    font-size: 12px;
    font-weight: 500;
}}

QLineEdit#storeSearch {{
    background-color: {C['glass_bg']};
    border: 1px solid {C['glass_border']};
    border-radius: 12px;
    padding: 10px 14px;
    font-family: {FONT_TEXT};
    font-size: 12px;
}}

QLineEdit#storeSearch:focus {{
    border: 1px solid {C['accent']};
}}

QPushButton#chipButton {{
    background-color: transparent;
    color: {C['text_secondary']};
    border: 1px solid {C['border']};
    border-radius: 13px;
    padding: 5px 14px;
    font-size: 11px;
    font-weight: 600;
    min-height: 0;
}}

QPushButton#chipButton:hover {{
    border-color: {C['accent_dim']};
    color: {C['text_primary']};
}}

QPushButton#chipButton:checked {{
    background-color: {C['accent']};
    color: {C['text_inverted']};
    border: 1px solid {C['accent']};
    font-weight: 700;
}}

QLabel#sectionHeader {{
    font-family: {FONT_DISPLAY};
    font-size: 15px;
    font-weight: 700;
    background: transparent;
}}

QFrame#storeCard {{
    background-color: {C['glass_bg']};
    border: 1px solid {C['glass_border']};
    border-radius: 14px;
}}

QFrame#storeCard:hover {{
    background-color: {C['hover_bg']};
    border: 1px solid {C['accent_dim']};
}}

QLabel#storeAppName {{
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}

QLabel#storeAppMeta {{
    color: {C['text_muted']};
    font-size: 11px;
    background: transparent;
}}

QPushButton#openBtn {{
    background: {grad(C['accent'], C['accent_2'])};
    color: {C['text_inverted']};
    border: 1px solid {C['glass_border']};
    border-radius: 10px;
    font-size: 12px;
    font-weight: 700;
    padding: 6px 12px;
    min-height: 0;
}}

QPushButton#openBtn:hover {{
    background: {grad(C['accent_light'], C['accent'])};
    border-color: {C['accent_light']};
}}

QPushButton#openBtn:pressed {{
    background: {grad(C['accent_dim'], C['accent_dim'])};
}}

/* ── New Home dashboard (redesign) ─────────────────────────────── */

QFrame#topBar QLineEdit#topSearch {{
    background-color: {C['input_bg']};
    color: {C['text_primary']};
    border: 1px solid {C['input_border']};
    border-radius: 17px;
    padding: 7px 14px;
    font-family: {FONT_TEXT};
    font-size: 11px;
}}

QFrame#topBar QLineEdit#topSearch:focus {{
    border: 1px solid {C['accent']};
}}

QLabel#topTagline {{
    color: {C['accent']};
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1px;
    background: transparent;
}}

QLabel#topTagline QLabel {{
    background: transparent;
}}

QPushButton#topIconBtn {{
    background-color: {C['input_bg']};
    color: {C['text_secondary']};
    border: 1px solid {C['input_border']};
    border-radius: 17px;
    padding: 0px;
    min-height: 34px;
    min-width: 34px;
    max-width: 34px;
}}

QPushButton#topIconBtn:hover {{
    background-color: {C['hover_bg']};
    border-color: {C['accent_dim']};
    color: {C['accent_light']};
}}

QFrame#profileChip {{
    background-color: {C['input_bg']};
    border: 1px solid {C['input_border']};
    border-radius: 17px;
}}

QLabel#avatarLabel {{
    background: {grad(C['accent'], C['accent_2'])};
    color: {C['text_inverted']};
    border-radius: 14px;
    font-size: 11px;
    font-weight: 800;
}}

QLabel#profileName {{
    color: {C['text_primary']};
    font-size: 11px;
    font-weight: 700;
    background: transparent;
}}

QLabel#profileSub {{
    color: {C['text_tertiary']};
    font-size: 9px;
    background: transparent;
}}

QPushButton#profileChevron {{
    background: transparent;
    color: {C['text_secondary']};
    border: none;
    padding: 0px;
    min-height: 0px;
}}

/* Hero — photo painted by HeroBanner; QSS only styles the overlays */
QFrame#homeHero {{
    background-color: {C['navy']};
    border: 1px solid {C['card_border']};
    border-radius: 16px;
}}

QFrame#homeHero QLabel {{
    /* no forced color: let heroKicker/heroTitle/heroSubtitle follow the theme;
       heroFeature and heroQuoteTitle set their own (white on dark surfaces) */
    background: transparent;
}}

QLabel#heroKicker {{
    /* fixed ink: the hero paints a permanent white wash over the photo, so
       its headline stays dark in every theme */
    color: #0E2C50;
    font-size: 20px;
    font-weight: 800;
}}

QLabel#heroTitle {{
    color: #0E2C50;
    font-family: {FONT_DISPLAY};
    font-size: 28px;
    font-weight: 800;
}}

QLabel#heroSubtitle {{
    color: #42566E;
    font-size: 12px;
    font-weight: 500;
}}

QLabel#heroFeature {{
    color: #FFFFFF;
    font-size: 11px;
    font-weight: 700;
    background: transparent;
    border: none;
    padding: 0px;
}}

QFrame#heroQuote {{
    background: rgba(8,28,52,0.34);
    border: 1px solid rgba(255,255,255,0.20);
    border-radius: 14px;
}}

QLabel#heroQuoteTitle {{
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 700;
}}

QLabel#heroQuoteBody {{
    color: #D8E8F7;
    font-size: 11px;
}}

QPushButton#heroArrowBtn {{
    background: rgba(255,255,255,0.14);
    color: #FFFFFF;
    border: 1px solid rgba(255,255,255,0.22);
    border-radius: 15px;
    min-height: 30px;
    min-width: 30px;
    max-width: 30px;
    padding: 0px;
}}

QPushButton#heroArrowBtn:hover {{
    background: rgba(255,255,255,0.28);
}}

/* SEARCH TOOLBAR */
QFrame#searchToolbar {{
    background-color: {C['glass_bg']};
    border: 1px solid {C['glass_border']};
    border-radius: 16px;
}}

QLineEdit#homeSearch {{
    background-color: {C['input_bg']};
    color: {C['text_primary']};
    border: 1px solid {C['input_border']};
    border-radius: 12px;
    padding: 10px 14px;
    font-family: {FONT_TEXT};
    font-size: 12px;
}}

QLineEdit#homeSearch:focus {{
    border: 1px solid {C['accent']};
}}

QLabel#searchHint {{
    color: {C['text_tertiary']};
    font-size: 10px;
    background: {C['input_bg']};
    border: 1px solid {C['input_border']};
    border-radius: 6px;
    padding: 3px 7px;
}}

/* SECTION HEADERS */
QLabel#sectionTitle {{
    font-family: {FONT_DISPLAY};
    font-size: 16px;
    font-weight: 700;
    background: transparent;
}}

QPushButton#viewAllBtn {{
    background: transparent;
    color: {C['accent']};
    border: none;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 4px;
    min-height: 0px;
}}

QPushButton#viewAllBtn:hover {{
    color: {C['accent_light']};
}}

/* TOOL CARDS */
QFrame#toolCard {{
    background-color: {C['card_bg']};
    border: 1px solid {C['card_border']};
    border-radius: 16px;
}}

QFrame#toolCard:hover {{
    background-color: {C['hover_bg']};
    border: 1px solid {C['accent_dim']};
}}

QLabel#toolTitle {{
    color: {C['text_primary']};
    font-size: 14px;
    font-weight: 700;
    background: transparent;
}}

QLabel#toolDesc {{
    color: {C['text_secondary']};
    font-size: 11px;
    background: transparent;
}}

QLabel#toolStep {{
    color: {C['text_tertiary']};
    font-size: 9px;
    font-weight: 600;
    background: transparent;
}}

QPushButton#learnBtn {{
    background: transparent;
    color: {C['text_tertiary']};
    border: none;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 4px;
    min-height: 0px;
}}

QPushButton#learnBtn:hover {{
    color: {C['accent_light']};
}}

QPushButton#openBtn {{
    background-color: {C['accent']};
    color: {C['text_inverted']};
    border: none;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 700;
    padding: 7px 16px;
    min-height: 0px;
}}

QPushButton#openBtn:hover {{
    background-color: {C['accent_light']};
}}

QPushButton#openBtn:pressed {{
    background-color: {C['accent_dim']};
}}

QPushButton#starBtn {{
    background: transparent;
    color: {C['text_tertiary']};
    border: none;
    padding: 0px;
    min-height: 0px;
}}

QPushButton#starBtn:hover {{
    color: {C['warning']};
}}

QFrame#toolThumb {{
    background: {C['bg_tertiary']};
    border: 1px solid {C['border_subtle']};
    border-radius: 10px;
}}

/* RIGHT RAIL */
QFrame#railCard {{
    background-color: {C['card_bg']};
    border: 1px solid {C['card_border']};
    border-radius: 16px;
}}

QFrame#greetingCard {{
    background-color: {C['card_bg']};
    border: 1px solid {C['card_border']};
    border-radius: 14px;
}}

QFrame#greetingCard QLabel {{
    color: {C['text_primary']};
    background: transparent;
}}

QLabel#greetingName {{
    font-size: 15px;
    font-weight: 800;
}}

QLabel#greetingSub {{
    color: {C['text_tertiary']};
    font-size: 9px;
}}

QLabel#dateLabel {{
    color: {C['text_primary']};
    font-size: 10px;
    font-weight: 700;
    background: transparent;
}}

QLabel#greetingTime {{
    color: {C['accent']};
    font-family: {FONT_DISPLAY};
    font-size: 15px;
    font-weight: 800;
    background: transparent;
}}

QFrame#dateBox {{
    background-color: {C['bg_tertiary']};
    border: 1px solid {C['border_subtle']};
    border-radius: 10px;
}}

QFrame#railSection {{
    background-color: {C['card_bg']};
    border: 1px solid {C['card_border']};
    border-radius: 14px;
}}

QLabel#railHeader {{
    color: {C['text_primary']};
    font-family: {FONT_DISPLAY};
    font-size: 14px;
    font-weight: 800;
    background: transparent;
}}

QLabel#quickLinkName {{
    color: {C['text_secondary']};
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}}

QFrame#systemStatusCard {{
    background-color: {C['card_bg']};
    border: 1px solid {C['card_border']};
    border-radius: 14px;
}}

QLabel#systemStatusTitle {{
    color: {C['text_primary']};
    font-size: 12px;
    font-weight: 800;
    background: transparent;
}}

QLabel#systemStatusSub {{
    color: {C['success']};
    font-size: 10px;
    font-weight: 700;
    background: transparent;
}}

QLabel#secureTitle {{
    color: {C['text_primary']};
    font-size: 11px;
    font-weight: 700;
    background: transparent;
}}

QLabel#secureSub {{
    color: {C['text_tertiary']};
    font-size: 9px;
    background: transparent;
}}

QFrame#projectRow {{
    background-color: transparent;
    border: none;
    border-radius: 10px;
}}

QFrame#projectRow:hover {{
    background-color: {C['hover_bg']};
}}

QFrame#quickLinkRow {{
    background-color: transparent;
    border: none;
    border-top: 1px solid {C['border_subtle']};
    border-radius: 0px;
}}

QFrame#quickLinkRow:hover {{
    background-color: {C['hover_bg']};
}}

QLabel#projectName {{
    color: {C['text_primary']};
    font-size: 12px;
    font-weight: 700;
    background: transparent;
}}

QLabel#projectMeta {{
    color: {C['text_tertiary']};
    font-size: 10px;
    background: transparent;
}}

QLabel#quickLinkGlyph {{
    color: {C['accent']};
    background: transparent;
}}

/* AI / INTELLIGENCE BAND */
QFrame#aiBand {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 {C['navy']},
                                stop:1 #17549E);
    border: none;
    border-radius: 14px;
}}

QFrame#aiBand QLabel {{
    color: #FFFFFF;
    background: transparent;
}}

QFrame#aiBandChip {{
    background: rgba(255,255,255,0.14);
    border: 1px solid rgba(255,255,255,0.30);
    border-radius: 12px;
}}

QLabel#aiBandChipText {{
    color: #FFFFFF;
    font-family: {FONT_DISPLAY};
    font-size: 14px;
    font-weight: 800;
    background: transparent;
}}

QLabel#aiBandKicker {{
    font-size: 14px;
    font-weight: 800;
}}

QLabel#aiBandTitle {{
    font-family: {FONT_DISPLAY};
    font-size: 19px;
    font-weight: 800;
}}

QLabel#aiBandSub {{
    color: #C9DCF2;
    font-size: 11px;
}}

QPushButton#aiBandBtn {{
    background: #DCEBFB;
    color: {C['navy']};
    border: none;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 700;
    padding: 9px 18px;
}}

QPushButton#aiBandBtn:hover {{
    background: #EAF3FD;
}}

/* FOOTER BAR */
QFrame#footerBar {{
    background-color: {C['bg_secondary']};
    border-top: 1px solid {C['border_subtle']};
}}

QLabel#footerText {{
    color: {C['text_tertiary']};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
    background: transparent;
}}

QLabel#footerStatus {{
    color: {C['success']};
    font-size: 10px;
    font-weight: 700;
    background: transparent;
}}

QLabel#statusDot {{
    background: {C['success']};
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}}

QLabel#footerSecure {{
    color: {C['text_tertiary']};
    font-size: 10px;
    background: transparent;
}}

/* SIDEBAR (extra) */
QLabel#sideTagline {{
    color: {C['text_tertiary']};
    font-size: 8px;
    background: transparent;
}}

QLabel#sideStatus {{
    color: {C['success']};
    font-size: 10px;
    font-weight: 700;
    background: transparent;
}}

/* Sidebar promo — cable-stayed photo painted in code; QSS keeps it transparent */
QFrame#sidePromo {{
    background-color: transparent;
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 14px;
}}

QFrame#sidePromo QLabel {{
    color: #FFFFFF;
    background: transparent;
}}

QLabel#sidePromoTitle {{
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1px;
}}

/* Tool-card icon tile + AI badge */
QFrame#toolIconTile {{
    background-color: {C['card_bg']};
    border: 1px solid {C['border']};
    border-radius: 12px;
}}

QLabel#aiBadge {{
    background-color: #DDEBFB;
    color: #1D4F8F;
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 9px;
    font-weight: 700;
}}

/* ── Settings rows & dividers ──────────────────────────────────── */

QWidget#settingsRow {{
    background-color: {C['settings_row']};
    border: 1px solid {C['border_subtle']};
    border-radius: 12px;
}}

QWidget#settingsRow:hover {{
    background-color: {C['hover_bg']};
    border-color: {C['glass_border']};
}}

QFrame#divider {{
    background-color: {C['border_subtle']};
    max-height: 1px;
    border: none;
}}

/* ── Status Tags ───────────────────────────────────────────────── */

QLabel#tagSuccess {{
    background-color: {C['success_bg']};
    color: {C['success']};
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel#tagWarning {{
    background-color: {C['warning_bg']};
    color: {C['warning']};
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel#tagError {{
    background-color: {C['error_bg']};
    color: {C['error']};
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel#tagInfo {{
    background-color: {C['info_bg']};
    color: {C['info']};
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

/* ── Splitter ──────────────────────────────────────────────────── */

QSplitter::handle {{
    background-color: {C['border_subtle']};
    margin: 0 4px;
}}

QSplitter::handle:hover {{
    background-color: {C['accent_dim']};
}}

/* ── Sliders ───────────────────────────────────────────────────── */

QSlider::groove:horizontal {{
    height: 6px;
    border-radius: 3px;
    background: {C['progress_track']};
    margin: 0;
}}

QSlider::handle:horizontal {{
    background: {grad(C['accent'], C['accent_2'])};
    border: none;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}}

QSlider::handle:horizontal:hover {{
    background: {grad(C['accent_lighter'], C['accent'])};
}}

QSlider::sub-page:horizontal {{
    background: {grad(C['accent'], C['accent_2'])};
    border-radius: 3px;
}}
"""


_current_theme: str = _saved_theme()
COLORS: dict = dict(_theme_dict(_current_theme))
STYLESHEET: str = _build_qss(COLORS)


def apply_theme(theme: str, app: QApplication | None = None) -> None:
    global _current_theme, COLORS, STYLESHEET

    theme = theme if theme in _THEMES else DEFAULT_THEME
    _current_theme = theme
    COLORS.clear()
    COLORS.update(_theme_dict(theme))
    STYLESHEET = _build_qss(COLORS)
    s = QSettings("BES", "BridgeEngineeringSuite")
    s.setValue("ui_theme", theme)
    s.setValue("ui_theme_generation", _THEME_GENERATION)

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


# ── Shared widget-style helpers (read COLORS live → theme-fresh) ─────────


def shade(color: str, factor: float) -> str:
    """Lighten (factor > 1) or darken (factor < 1) a token color; returns hex.

    QSS cannot derive hover/pressed variants, so buttons that need them
    compute shades from live theme tokens at construction time.
    """
    c = QColor(color)
    if not c.isValid():
        return color
    if factor >= 1.0:
        f = min(factor - 1.0, 1.0)
        r = c.red() + (255 - c.red()) * f
        g = c.green() + (255 - c.green()) * f
        b = c.blue() + (255 - c.blue()) * f
    else:
        f = max(factor, 0.0)
        r, g, b = c.red() * f, c.green() * f, c.blue() * f
    return f"#{int(round(r)):02X}{int(round(g)):02X}{int(round(b)):02X}"


def card_frame(radius: int = 14, pad: int | None = None) -> str:
    """QSS string for a glassy elevated card surface."""
    pad_s = f"padding:{pad}px;" if pad else ""
    return (f"background-color:{COLORS['glass_bg']};"
            f"border:1px solid {COLORS['glass_border']};"
            f"border-radius:{radius}px;{pad_s}")


def section_label(text: str, size: int = 15, color_key: str = "text_primary") -> QLabel:
    """Bold section heading (ramp: 15px semibold)."""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{COLORS[color_key]};font-size:{size}px;"
                      f"font-weight:600;background:transparent;")
    return lbl


def muted_label(text: str, size: int = 11) -> QLabel:
    """Muted hint/caption label."""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:{size}px;"
                      "background:transparent;")
    return lbl


_STATUS_KEYS = {
    "success": ("success_bg", "success"),
    "warning": ("warning_bg", "warning"),
    "error": ("error_bg", "error"),
    "info": ("info_bg", "info"),
}


def status_label(text: str, kind: str = "info", size: int = 11) -> QLabel:
    """Pill status chip: kind in success/warning/error/info."""
    bg_k, fg_k = _STATUS_KEYS.get(kind, _STATUS_KEYS["info"])
    lbl = QLabel(text)
    lbl.setStyleSheet(f"background-color:{COLORS[bg_k]};color:{COLORS[fg_k]};"
                      f"border-radius:8px;padding:4px 10px;"
                      f"font-size:{size}px;font-weight:600;")
    return lbl
