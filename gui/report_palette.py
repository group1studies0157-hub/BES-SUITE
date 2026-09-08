"""Fixed print palettes for PDF report exports (theme-independent).

These are output-document colors, deliberately decoupled from the UI theme
so printed engineering reports look identical regardless of the active app
skin. Shared by hydraulic_panel and scour_panel (values unchanged from the
original per-panel definitions).
"""

from reportlab.lib import colors as rc

TEAL = rc.HexColor("#006666")
LGREY = rc.HexColor("#f5f5f5")
MGREY = rc.HexColor("#dddddd")
GREEN = rc.HexColor("#006400")
AMBER = rc.HexColor("#b8860b")

# Paragraph / note text greys
DARK_TEXT = rc.HexColor("#444")
MUTE_TEXT = rc.HexColor("#555")
REFS_TEXT = rc.HexColor("#333")

# Table row tints
ROW_TINT = rc.HexColor("#e0f5ef")
OK_BG = rc.HexColor("#f0fff8")
FAIL_BG = rc.HexColor("#fff0f0")
