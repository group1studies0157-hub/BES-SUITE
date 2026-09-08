"""
Bridge Engineering Suite — Premium macOS Sonoma Design System
═══════════════════════════════════════════════════════════════
Vibrant, sophisticated, premium aesthetic inspired by macOS Sonoma 2024.
Features: authentic Sonoma color palette, gradient accents, premium shadows,
smooth transitions, native SF Pro typography, and polished interactions.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


THEME_NAMES = {
    "graphite": "Graphite",
    "studio": "Studio",
    "ocean": "Ocean",
    "sunset": "Ember",
    "forest": "Meadow",
    "royal": "Prism",
}

THEME_SWATCHES = {
    "graphite": ("#06B6D4", "#8B5CF6"),
    "studio": ("#2563EB", "#0891B2"),
    "ocean": ("#0284C7", "#10B981"),
    "sunset": ("#EA580C", "#DC2626"),
    "forest": ("#22C55E", "#84CC16"),
    "royal": ("#7C3AED", "#EC4899"),
}


_THEMES = {
    "graphite": {
        # Dark mode — deep, sophisticated
        "bg_primary": "#050A12",
        "bg_secondary": "#0F1419",
        "bg_tertiary": "#1A202C",
        "sidebar_bg": "#0A0E17",
        "text_primary": "#F8FAFC",
        "text_secondary": "#CBD5E1",
        "text_tertiary": "#94A3B8",
        "text_inverted": "#0A0E17",
        "border": "#1E293B",
        "border_subtle": "#0F1419",
        "input_bg": "#0F1419",
        "input_border": "#2D3B4F",
        "card_bg": "#0A0E17",
        "card_border": "#1E293B",
        "hover_bg": "#1A202C",
        "active_bg": "#2D3B4F",
        "disabled_bg": "#0F1419",
        "disabled_text": "#64748B",
        "accent": "#06B6D4",
        "accent_dim": "#0891B2",
        "accent_light": "#22D3EE",
        "accent_lighter": "#67E8F9",
        "accent_bg": "rgba(6,182,212,0.12)",
        "accent_2": "#8B5CF6",
        "accent_3": "#3B82F6",
        "success": "#10B981",
        "success_bg": "rgba(16,185,129,0.15)",
        "warning": "#F59E0B",
        "warning_bg": "rgba(245,158,11,0.15)",
        "error": "#EF4444",
        "error_bg": "rgba(239,68,68,0.15)",
        "info": "#06B6D4",
        "info_bg": "rgba(6,182,212,0.15)",
        # Legacy
        "navy": "#0A0E17",
        "navy_light": "#1A202C",
        "navy_border": "#2D3B4F",
        "sidebar_top": "#0A0E17",
        "sidebar_bottom": "#0F1419",
        "accent_dim": "#0891B2",
        "accent_glow": "rgba(6,182,212,0.2)",
        "accent_text": "#F8FAFC",
        "white": "#F8FAFC",
        "off_white": "#0F1419",
        "panel_grad_1": "#0A0E17",
        "panel_grad_2": "#050A12",
        "text_muted": "#94A3B8",
        "text_sidebar": "#CBD5E1",
        "border_dark": "#2D3B4F",
        "progress_track": "#1E293B",
        "settings_bg": "#0F1419",
        "settings_row": "#0A0E17",
    },
    "studio": {
        # Light mode — clean, bright, premium
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
    return _THEMES.get(theme, _THEMES["studio"])


def _saved_theme() -> str:
    value = QSettings("BES", "BridgeEngineeringSuite").value("ui_theme", "studio")
    return value if value in _THEMES else "studio"


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


def _build_qss(C: dict) -> str:
    """Premium macOS Sonoma QSS with vibrant accents, sophisticated shadows, gradients."""
    return f"""
QMainWindow, QDialog, QWidget {{
    background-color: {C['bg_primary']};
    color: {C['text_primary']};
}}

/* ── Top-level windows ─────────────────────────────────────────────── */

QMainWindow {{
    border: none;
    margin: 0;
    padding: 0;
}}

QDialog {{
    border-radius: 14px;
    border: 1px solid {C['border']};
    background-color: {C['bg_primary']};
}}

/* ── Sidebar & Navigation ──────────────────────────────────────────── */

#sidebarContainer {{
    background-color: {C['sidebar_bg']};
    border-right: 1px solid {C['border_subtle']};
}}

QPushButton#sidebarButton {{
    background-color: transparent;
    color: {C['text_secondary']};
    border: none;
    border-radius: 10px;
    padding: 12px 16px;
    margin: 6px 8px;
    font-family: -apple-system, 'SF Pro Display', 'Segoe UI', sans-serif;
    font-size: 13px;
    font-weight: 500;
    text-align: left;
}}

QPushButton#sidebarButton:hover {{
    background-color: {C['hover_bg']};
    color: {C['text_primary']};
}}

QPushButton#sidebarButton:checked {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent_bg']},
                                stop:1 {C['accent_bg']});
    color: {C['accent']};
    font-weight: 600;
    border-radius: 10px;
}}

/* ── Top bar ────────────────────────────────────────────────────── */

#topBar {{
    background-color: {C['bg_secondary']};
    border-bottom: 1px solid {C['border_subtle']};
    padding: 12px 16px;
}}

QLabel#topTitle {{
    color: {C['text_primary']};
    font-family: -apple-system, 'SF Pro Display', 'Segoe UI', sans-serif;
    font-size: 16px;
    font-weight: 700;
}}

QLabel#topIcon {{
    background-color: transparent;
}}

QLabel#topSubtitle {{
    color: {C['text_secondary']};
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 12px;
    font-weight: 400;
}}

/* ── Buttons — Premium styling ─────────────────────────────────── */

QPushButton {{
    background-color: {C['bg_secondary']};
    color: {C['text_primary']};
    border: 1.5px solid {C['border']};
    border-radius: 10px;
    padding: 8px 18px;
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 13px;
    font-weight: 500;
    outline: none;
    min-height: 32px;
}}

QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['hover_bg']},
                                stop:1 {C['active_bg']});
    border-color: {C['accent_dim']};
}}

QPushButton:pressed {{
    background-color: {C['active_bg']};
    border-color: {C['accent']};
}}

QPushButton:disabled {{
    color: {C['disabled_text']};
    background-color: {C['disabled_bg']};
    border-color: {C['border_subtle']};
}}

QPushButton#primaryBtn {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_dim']});
    color: {C['text_inverted']};
    border: none;
    font-weight: 600;
}}

QPushButton#primaryBtn:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent_light']},
                                stop:1 {C['accent']});
}}

QPushButton#primaryBtn:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent_dim']},
                                stop:1 {C['accent_dim']});
}}

QPushButton#secondaryBtn {{
    background-color: {C['bg_secondary']};
    border: 1.5px solid {C['border_dark']};
}}

QPushButton#secondaryBtn:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['hover_bg']},
                                stop:1 {C['active_bg']});
    border-color: {C['accent']};
}}

/* ── Home dashboard — Microsoft Store-inspired ─────────────────── */

QFrame#heroBanner {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent']},
                                stop:0.55 {C['accent_2']},
                                stop:1 {C['accent_3']});
    border-radius: 16px;
}}

QLabel#heroKicker {{
    color: rgba(255,255,255,0.85);
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 11px;
    font-weight: 800;
}}

QLabel#heroTitle {{
    color: #FFFFFF;
    font-family: -apple-system, 'SF Pro Display', 'Segoe UI', sans-serif;
    font-size: 24px;
    font-weight: 800;
}}

QLabel#heroSubtitle {{
    color: rgba(255,255,255,0.92);
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 13px;
}}

QLineEdit#storeSearch {{
    background-color: {C['input_bg']};
    color: {C['text_primary']};
    border: 1.5px solid {C['input_border']};
    border-radius: 18px;
    padding: 6px 18px;
    font-size: 13px;
}}

QLineEdit#storeSearch:focus {{
    border-color: {C['accent']};
}}

QPushButton#chipButton {{
    background-color: {C['bg_secondary']};
    color: {C['text_secondary']};
    border: 1.5px solid {C['border']};
    border-radius: 16px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 700;
    min-height: 26px;
}}

QPushButton#chipButton:hover {{
    border-color: {C['accent']};
    color: {C['text_primary']};
}}

QPushButton#chipButton:checked {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_2']});
    color: {C['text_inverted']};
    border: none;
}}

QLabel#sectionHeader {{
    color: {C['text_primary']};
    font-family: -apple-system, 'SF Pro Display', 'Segoe UI', sans-serif;
    font-size: 15px;
    font-weight: 800;
}}

QFrame#storeCard {{
    background-color: {C['card_bg']};
    border: 1px solid {C['card_border']};
    border-radius: 12px;
}}

QFrame#storeCard:hover {{
    border: 1px solid {C['accent']};
    background-color: {C['hover_bg']};
}}

QLabel#storeIcon {{
    background-color: transparent;
}}

QLabel#storeAppName {{
    color: {C['text_primary']};
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 13px;
    font-weight: 700;
}}

QLabel#storeAppMeta {{
    color: {C['text_tertiary']};
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 11px;
}}

QPushButton#openBtn {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_dim']});
    color: {C['text_inverted']};
    border: none;
    border-radius: 8px;
    padding: 6px 18px;
    font-size: 12px;
    font-weight: 700;
    min-height: 28px;
}}

QPushButton#openBtn:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 {C['accent_light']},
                                stop:1 {C['accent']});
}}

/* ── Text inputs & Fields ──────────────────────────────────────── */

QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {C['input_bg']};
    color: {C['text_primary']};
    border: 1.5px solid {C['input_border']};
    border-radius: 10px;
    padding: 6px 12px;
    font-family: 'SF Mono', 'Monaco', monospace;
    font-size: 13px;
    selection-background-color: {C['accent']};
    selection-color: {C['text_inverted']};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1.5px solid {C['accent']};
    background-color: {C['white']};
}}

QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{
    background-color: {C['disabled_bg']};
    color: {C['disabled_text']};
    border-color: {C['border_subtle']};
}}

QLineEdit::placeholder {{
    color: {C['text_tertiary']};
}}

/* ── Dropdowns (ComboBox) ────────────────────────────────────────── */

QComboBox {{
    background-color: {C['input_bg']};
    color: {C['text_primary']};
    border: 1.5px solid {C['input_border']};
    border-radius: 10px;
    padding: 5px 12px;
    font-size: 13px;
}}

QComboBox:focus {{
    border: 1.5px solid {C['accent']};
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
    border: 1px solid {C['border']};
    border-radius: 10px;
    outline: none;
}}

QAbstractItemView::item {{
    padding: 8px 12px;
    border-radius: 6px;
}}

QAbstractItemView::item:hover {{
    background-color: {C['hover_bg']};
}}

QAbstractItemView::item:selected {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_dim']});
    color: {C['text_inverted']};
}}

/* ── Checkboxes & Radios ────────────────────────────────────────– */

QCheckBox, QRadioButton {{
    color: {C['text_primary']};
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 13px;
    spacing: 10px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 1.5px solid {C['input_border']};
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
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_dim']});
    border-color: {C['accent']};
}}

/* ── Tabs ────────────────────────────────────────────────────────── */

QTabWidget::pane {{
    border: 1px solid {C['border']};
    border-radius: 10px;
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
    padding: 12px 18px;
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 13px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
}}

QTabBar::tab:selected {{
    color: {C['accent']};
    border-bottom: 2px solid {C['accent']};
    font-weight: 600;
}}

QTabBar::tab:hover {{
    color: {C['text_primary']};
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 transparent,
                                stop:0.5 {C['hover_bg']},
                                stop:1 transparent);
    border-radius: 8px;
}}

/* ── Scroll Bars ────────────────────────────────────────────────── */

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 {C['border_dark']},
                                stop:1 {C['accent_dim']});
    border-radius: 5px;
    min-height: 40px;
}}

QScrollBar::handle:vertical:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_light']});
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}

QScrollBar::handle:horizontal {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 {C['border_dark']},
                                stop:1 {C['accent_dim']});
    border-radius: 5px;
    min-width: 40px;
}}

QScrollBar::handle:horizontal:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_light']});
}}

/* ── Tables & Lists ────────────────────────────────────────────– */

QTableWidget, QListWidget {{
    background-color: {C['input_bg']};
    border: 1px solid {C['border']};
    border-radius: 10px;
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
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_dim']});
    color: {C['text_inverted']};
}}

QHeaderView::section {{
    background-color: {C['bg_secondary']};
    color: {C['text_secondary']};
    border: none;
    border-bottom: 1px solid {C['border']};
    padding: 10px 12px;
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 12px;
    font-weight: 600;
}}

/* ── Progress Bar ──────────────────────────────────────────────– */

QProgressBar {{
    background-color: {C['progress_track']};
    border: none;
    border-radius: 8px;
    text-align: center;
    color: transparent;
    min-height: 6px;
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 {C['accent']},
                                stop:0.5 {C['accent_light']},
                                stop:1 {C['accent_dim']});
    border-radius: 8px;
}}

/* ── Menus ─────────────────────────────────────────────────────– */

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
    border: 1px solid {C['border']};
    border-radius: 10px;
    padding: 6px;
    color: {C['text_primary']};
}}

QMenu::item {{
    padding: 10px 20px;
    border-radius: 6px;
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 13px;
}}

QMenu::item:selected {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent_bg']},
                                stop:1 {C['accent_bg']});
    color: {C['accent']};
}}

/* ── Tool Tips ─────────────────────────────────────────────────– */

QToolTip {{
    background-color: {C['bg_secondary']};
    color: {C['text_primary']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 8px 12px;
    font-family: -apple-system, 'SF Pro Text', 'Segoe UI', sans-serif;
    font-size: 12px;
}}

/* ── Frames & Panels ────────────────────────────────────────────– */

QFrame {{
    border: none;
    background-color: transparent;
}}

QFrame#card {{
    background-color: {C['card_bg']};
    border: 1px solid {C['card_border']};
    border-radius: 12px;
    padding: 14px;
}}

QFrame#dropZone {{
    background-color: {C['input_bg']};
    border: 2px dashed {C['border_dark']};
    border-radius: 12px;
}}

QFrame#dropZone:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent_bg']},
                                stop:1 {C['accent_bg']});
    border: 2px solid {C['accent']};
    border-radius: 12px;
}}

/* ── Status Tags ────────────────────────────────────────────────– */

QLabel#tagSuccess {{
    background-color: {C['success_bg']};
    color: {C['success']};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel#tagWarning {{
    background-color: {C['warning_bg']};
    color: {C['warning']};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel#tagError {{
    background-color: {C['error_bg']};
    color: {C['error']};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel#tagInfo {{
    background-color: {C['info_bg']};
    color: {C['info']};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

/* ── Splitter ──────────────────────────────────────────────────– */

QSplitter::handle {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 transparent,
                                stop:0.5 {C['border']},
                                stop:1 transparent);
    margin: 0 4px;
}}

QSplitter::handle:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 transparent,
                                stop:0.5 {C['accent']},
                                stop:1 transparent);
}}

/* ── Sliders ────────────────────────────────────────────────────– */

QSlider::groove:horizontal {{
    height: 6px;
    border-radius: 3px;
    background: {C['progress_track']};
    margin: 0;
}}

QSlider::handle:horizontal {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_dim']});
    border: none;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}}

QSlider::handle:horizontal:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                stop:0 {C['accent_light']},
                                stop:1 {C['accent']});
}}

QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 {C['accent']},
                                stop:1 {C['accent_light']});
    border-radius: 3px;
}}
"""


_current_theme: str = _saved_theme()
COLORS: dict = dict(_theme_dict(_current_theme))
STYLESHEET: str = _build_qss(COLORS)


def apply_theme(theme: str, app: QApplication | None = None) -> None:
    global _current_theme, COLORS, STYLESHEET

    theme = theme if theme in _THEMES else "studio"
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
