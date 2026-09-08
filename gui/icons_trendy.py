"""
Bridge Engineering Suite — Trendy macOS-Style Icons
Modern emoji symbols inspired by SF Symbols
"""

ICONS = {
    # Main actions
    "extract": "🤖",
    "calculate": "⚙️",
    "download": "⬇️",
    "attach": "📎",
    "preview": "👁️",
    
    # Navigation
    "hide": "⬅️",
    "show": "➡️",
    "expand": "⬆️",
    "collapse": "⬇️",
    
    # States
    "success": "✓",
    "error": "✕",
    "warning": "⚠️",
    "info": "ℹ️",
    "clear": "🗑️",
    
    # Settings & menu
    "settings": "⚙️",
    "menu": "☰",
    "close": "✕",
    "search": "🔍",
    
    # Data management
    "add": "➕",
    "delete": "➖",
    "edit": "✎",
    "copy": "⎘",
    "paste": "v",
    
    # Special
    "scour": "💧",
    "knowledge": "📚",
    "cad": "📐",
    "gad": "📋",
    "hydraulic": "〰️",
}

def icon(name: str) -> str:
    """Return trendy icon symbol for button/label."""
    return ICONS.get(name, "•")

def button_text(label: str, icon_name: str = None) -> str:
    """Generate button text with icon and label."""
    if not icon_name:
        return label
    return f"{icon(icon_name)}  {label}"
