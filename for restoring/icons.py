"""
Bridge Engineering Suite — Icon Library
Small unicode glyphs for inline UI text, plus real PNG icon assets
(bundled under gui/assets/icons/) used for the sidebar, top bar, and
Home dashboard — generated to match a consistent app-tile style.
"""

import os

ICONS = {
    "settings": "⚙️",
    "extract": "🤖",
    "download": "⬇️",
    "attach": "📎",
    "calculate": "🧮",
    "preview": "👁️",
    "hide": "⬅️",
    "show": "➡️",
    "clear": "✕",
    "info": "ℹ️",
    "warning": "⚠️",
    "error": "❌",
    "success": "✓",
    "close": "✕",
    "menu": "☰",
    "search": "🔍",
    "filter": "⊙",
    "add": "+",
    "delete": "−",
    "edit": "✎",
    "copy": "⎘",
    "paste": "v",
}

def icon(name: str) -> str:
    """Return unicode glyph symbol for inline button/label text."""
    return ICONS.get(name, "•")


# ── Bundled PNG app icons (nav / Home dashboard / top bar) ────────────────
_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")

_ICON_FILES = {
    "home": "home.png",
    "cd": "cd.png",
    "cad": "cad.png",
    "cad2": "cad2.png",
    "gad": "gad.png",
    "hydraulic": "hydraulic.png",
    "kb": "kb.png",
    "settings": "settings.png",
    "quiz": "quiz.png",
    "import": "import.png",
    "codesearch": "codesearch.png",
}


def icon_path(name: str) -> str | None:
    """Return the absolute path to a bundled app-tile PNG, or None if missing."""
    filename = _ICON_FILES.get(name)
    if not filename:
        return None
    path = os.path.join(_ICON_DIR, filename)
    return path if os.path.isfile(path) else None
