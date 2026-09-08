"""
bes_cad_knowledge.py — BES AutoCAD/DXF Knowledge Base (Python Reference)

Import this module when working on any DXF/AutoCAD code to get:
  - Layer constants and validation
  - DIMSTYLE configuration
  - Entity creation helpers
  - Dimension repair rules
  - Common pitfalls and solutions

This module grows with every BES session. Add new knowledge as functions/Dicts.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Optional

# ═════════════════════════════════════════════════════════════════════════════
# 1. LAYER CONVENTIONS
# ═════════════════════════════════════════════════════════════════════════════

LAYERS = {
    # BES repair pipeline layers
    "DIM":              {"color": 3,  "purpose": "Rebuilt dimension entities"},
    "_DIM":             {"color": 3,  "purpose": "Rebuilt dimensions (underscore prefix)"},
    "_HATCH_ARCHIVE":   {"color": 253, "purpose": "Archived/deleted hatches", "frozen": True, "locked": True},
    "_NEEDS_REVIEW":    {"color": 6,  "purpose": "Human review markers"},

    # Standard drawing layers
    "GEOMETRY":         {"color": 7,  "purpose": "Structural lines and shapes"},
    "DIMENSIONS":       {"color": 3,  "purpose": "Original dimension lines"},
    "CENTRELINES":      {"color": 1,  "purpose": "Centre lines"},
    "ANNOTATIONS":      {"color": 2,  "purpose": "Labels, notes, titles"},
    "HATCHING":         {"color": 8,  "purpose": "Hatch regions"},
    "ELEVATIONS":       {"color": 3,  "purpose": "RL/FL/BL level markers"},
    "SYMBOLS":          {"color": 6,  "purpose": "Symbols and markers"},
    "BORDER":           {"color": 5,  "purpose": "Drawing border"},
    "TITLEBLOCK":       {"color": 4,  "purpose": "Title block information"},

    # Import-only layers (from extraction DXFs)
    "EXG WORK":         {"color": 3,  "purpose": "Existing work geometry"},
    "PROP.DRAW":        {"color": 4,  "purpose": "Proposed drawing"},
    "EXG TEXT":         {"color": 7,  "purpose": "Existing text"},
}

# Layers that should NEVER receive new entities
FORBIDDEN_LAYERS = {"DEFPOINTS", "0", "LAYER0"}

# Layer prefix convention (underscore = internal/BES-managed)
LAYER_PREFIX_CONVENTION = "_"


def validate_layer(name: str) -> str:
    """Return a safe layer name, rejecting forbidden layers."""
    if name in FORBIDDEN_LAYERS:
        return "GEOMETRY"  # fallback
    return name


def resolve_dim_layer(doc) -> str:
    """Find or create the correct dimension layer in a DXF document.

    Priority: _DIM > DIM > create DIM.
    Never inherit from victim entities.
    """
    for name in ("_DIM", "DIM"):
        if name in doc.layers:
            return name
    # Create DIM layer
    try:
        doc.layers.add("DIM", dxfattribs={"color": 3})
    except Exception:
        pass
    return "DIM"


# ═════════════════════════════════════════════════════════════════════════════
# 2. DIMSTYLE CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

DIMSTYLE_NAME = "BES_REPAIR"

ARROW_STYLES = {
    "oblique":         "_OBLIQUE",           # ← DEFAULT: oblique slashes
    "closed_filled":   "",                   # Filled triangles
    "closed":          "_CLOSED",            # Closed outline arrows
    "architectural":   "_ARCHITECTURAL_TICK",# Slanted tick marks
    "dot":             "_DOT",               # Dot markers
    "none":            "none",               # No arrows
}


def make_dimstyle_attribs(
    char_h: float,
    arrow_style: str = "oblique",
) -> dict:
    """Build DIMSTYLE attributes for BES_REPAIR.

    Args:
        char_h: Drawing's dominant character height in mm
        arrow_style: One of ARROW_STYLES.keys()

    Returns:
        Dict of DXF dimension style attributes
    """
    txt_h = max(150.0, min(400.0, float(char_h)))
    arrow_block = ARROW_STYLES.get(arrow_style, "")

    if arrow_style == "none":
        arrow_sz = 0.0
    elif arrow_style == "architectural":
        arrow_sz = max(60.0, txt_h * 0.40)
    else:
        arrow_sz = max(80.0, txt_h * 0.60)

    return {
        "dimtxt": txt_h,
        "dimasz": arrow_sz,
        "dimexe": max(120.0, txt_h * 0.50),
        "dimexo": min(100.0, txt_h * 0.30),
        "dimgap": max(60.0, txt_h * 0.35),
        "dimlfac": 1.0,
        "dimscale": 1.0,
        "dimdec": 0,
        "dimtad": 1,
        "dimclrd": 256,
        "dimclre": 256,
        "dimclrt": 7,
        "dimblk": arrow_block,
        "dimblk2": arrow_block,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 3. DIMENSION REPAIR RULES
# ═════════════════════════════════════════════════════════════════════════════

# Orthogonality thresholds (degrees)
ORTHOGONALITY_TOLERANCE_H = 7.5    # horizontal: < 7.5° or > 172.5°
ORTHOGONALITY_TOLERANCE_V = 7.5    # vertical: 82.5° - 97.5°

# Dimension text visibility
DIMTXT_MIN_MM = 150.0
DIMTXT_MAX_MM = 400.0

# Dimension spacing
DIM_SPACING_FACTOR = 2.5  # Minimum gap = char_h * this factor

# Value mismatch tolerance
VALUE_MISMATCH_REL = 0.02     # 2% relative tolerance
VALUE_MISMATCH_ABS_MM = 5.0   # 5mm absolute floor

# Search radius for vertex pairing
SNAP_RADIUS_FACTOR = 4.0  # × char height (tightened from 6.0)


def orient_pair(p1, p2):
    """Classify a dimension pair as horizontal, vertical, or aligned.

    Returns:
        ('h', 0.0) for horizontal
        ('v', 90.0) for vertical
        ('a', angle) for non-orthogonal
    """
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ang = math.degrees(math.atan2(dy, dx)) % 180.0
    if ang < ORTHOGONALITY_TOLERANCE_H or ang > (180 - ORTHOGONALITY_TOLERANCE_H):
        return "h", 0.0
    if (90 - ORTHOGONALITY_TOLERANCE_V) < ang < (90 + ORTHOGONALITY_TOLERANCE_V):
        return "v", 90.0
    return "a", ang


def compute_dim_base(p1, p2, orient, ang, char_h, placed_boxes, spacing):
    """Compute dimension line base point perpendicular to geometry.

    For horizontal dims: base is above the line.
    For vertical dims: base is to the right.

    Pushes further out if overlapping already-placed dimensions.
    """
    mid_x = (p1[0] + p2[0]) / 2.0
    mid_y = (p1[1] + p2[1]) / 2.0
    base_offset = char_h * 1.2

    if orient == "v":
        base_x = mid_x + base_offset
        base_y = mid_y
        for (bx0, by0, bx1, by1) in placed_boxes:
            if (by0 - spacing) < base_y < (by1 + spacing) and base_x < (bx1 + spacing):
                base_x = bx1 + spacing
        return (base_x, base_y)
    else:
        base_x = mid_x
        base_y = mid_y + base_offset
        for (bx0, by0, bx1, by1) in placed_boxes:
            if (bx0 - spacing) < base_x < (bx1 + spacing) and base_y < (by1 + spacing):
                base_y = by1 + spacing
        return (base_x, base_y)


def dim_bbox(p1, p2, base, char_h):
    """Rough bounding box of a placed dimension for overlap detection."""
    xs = [p1[0], p2[0], base[0]]
    ys = [p1[1], p2[1], base[1]]
    pad = char_h * 2.0
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


# ═════════════════════════════════════════════════════════════════════════════
# 4. DEBRIS DETECTION WHITELIST
# ═════════════════════════════════════════════════════════════════════════════

DEBRIS_WHITELIST = {
    # Pier / support numbers
    "T0", "T1", "T2", "T3", "T4",
    "P1", "P2", "P3", "P4", "P5",
    "S1", "S2", "S3",
    # Grid marks
    "A", "B", "C", "D", "E", "F",
    # Common abbreviations
    "NOS", "N.T.", "N.S.", "CL",
    # Material call-outs
    "RCC", "PSC", "M.S.", "GR", "SWR",
    # Chainage markers
    "SP", "AP", "IP",
}


def _parse_dim_value_standalone(text: str):
    """Standalone version of parse_dimension_value (no external imports)."""
    import unicodedata
    _NUM_CLEAN_RE = re.compile(r"[^0-9.,+\-]")
    _NUM_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^[+-]?\d+(?:\.\d+)?$")
    _SLOPE_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\s*$")
    _LEVEL_RE = re.compile(r"\b(R\s*[_.]?L|F\s*[_.]?L|B\s*[_.]?L|H\s*F\s*L|RAIL\s+LEVEL"
                           r"|FORMATION|BED\s+LEVEL|HFL)\b", re.IGNORECASE)
    _GRADE_RE = re.compile(r"\b\d+\s*:\s*\d+(?:\s*:\s*\d+)+\b")
    if not text:
        return None
    t = unicodedata.normalize("NFKC", str(text)).strip()
    if _SLOPE_RE.match(t) or _LEVEL_RE.search(t):
        return None
    cleaned = _NUM_CLEAN_RE.sub("", t.split(" ")[0]).lstrip("+")
    if not cleaned or cleaned in {".", "-", ",", "-.", ",."}:
        return None
    if not _NUM_RE.match(cleaned.replace(",", "")):
        if len(cleaned.replace(".", "").replace(",", "").replace("-", "")) < 2:
            return None
    try:
        val = cleaned.replace(",", "")
        return float(val) if any(c.isdigit() for c in val) else None
    except ValueError:
        return None


def _is_annotation_standalone(text: str) -> bool:
    """Standalone version of is_annotation_only (no external imports)."""
    _LEVEL_RE = re.compile(r"\b(R\s*[_.]?L|F\s*[_.]?L|B\s*[_.]?L|H\s*F\s*L|RAIL\s+LEVEL"
                           r"|FORMATION|BED\s+LEVEL|HFL)\b", re.IGNORECASE)
    _GRADE_RE = re.compile(r"\b\d+\s*:\s*\d+(?:\s*:\s*\d+)+\b")
    _SLOPE_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\s*$")
    t = text.strip()
    if not t:
        return False
    return bool(_LEVEL_RE.search(t) or _GRADE_RE.search(t.replace(" ", ""))
                or _SLOPE_RE.match(t))


def is_debris(text: str) -> bool:
    """Check if text is likely OCR debris (not a valid dimension or annotation).

    Returns True if the text should be flagged for review/deletion.
    Self-contained — no imports from core.dxf_repair needed.
    """
    t = text.strip()
    if not t:
        return False

    # Valid dimension value → not debris (but short 1-2 digit numbers are fragments)
    parsed_val = _parse_dim_value_standalone(t)
    if parsed_val is not None:
        # Real bridge dimensions are typically 3+ digits (hundreds of mm)
        # Short numeric fragments like "07", "DL'" are debris
        digits_only = re.sub(r"[^0-9]", "", t)
        if len(digits_only) >= 3:
            return False
        # 1-2 digit numbers could be fragments
        return True

    # Annotation (level/grade/slope) → not debris
    if _is_annotation_standalone(t):
        return False

    # Whitelist check
    clean = t.strip().upper()
    if clean in DEBRIS_WHITELIST:
        return False

    # 4+ alphabetic characters → likely a word (ABUTMENT, PIER, etc.)
    alpha_only = re.sub(r"[^A-Za-z]", "", clean)
    if len(alpha_only) >= 4 and alpha_only.isalpha():
        return False

    # Otherwise → likely debris
    return True


# ═════════════════════════════════════════════════════════════════════════════
# 5. BRIDGE ENGINEERING STANDARDS
# ═════════════════════════════════════════════════════════════════════════════

TRACK_GAUGE_MM = 1676  # Indian broad gauge
DEFAULT_C_C_TRACK_MM = 4070  # Centre-to-centre track distance
LOADING_CLASS = "25T-2008"  # Standard axle loading

LEVEL_ABBREVIATIONS = {
    "RL": "Rail Level",
    "FL": "Formation Level",
    "BL": "Bed Level",
    "HFL": "High Flood Level",
    "NFL": "Normal Flood Level",
    "LWL": "Low Water Level",
}

MATERIAL_ABBREVIATIONS = {
    "RCC": "Reinforced Cement Concrete",
    "PSC": "Pre-stressed Concrete",
    "M.S.": "Mild Steel",
    "GR": "Grade",
    "SWR": "Steel Wire Rope",
}


# ═════════════════════════════════════════════════════════════════════════════
# 6. KNOWLEDGE GROWTH LOG
# ═════════════════════════════════════════════════════════════════════════════

SESSION_LOG = [
    {
        "date": "2026-08-27",
        "topic": "DXF Repair Pipeline Overhaul",
        "learnings": [
            "Distance-maximizing fallback in _pair_from_pool() caused diagonal garbage",
            "Victim layer inheritance placed dimensions on wrong layer",
            "Isolated OCR debris never caught by geometry-proximity detection",
            "Hatch archiving alone doesn't satisfy user requirement (want deletion)",
            "Dimension text needs minimum 150mm to be visible",
            "Dimension lines need perpendicular offset from geometry to avoid overlap",
            "Arrow style configurability needed for different output standards",
        ],
        "impact": "All 10 smoke tests pass, 3 bugs fixed, 2 features added",
    },
]


def log_knowledge(date: str, topic: str, learnings: list[str], impact: str = ""):
    """Add a new knowledge entry to the session log."""
    SESSION_LOG.append({
        "date": date,
        "topic": topic,
        "learnings": learnings,
        "impact": impact,
    })


# ═════════════════════════════════════════════════════════════════════════════
# 7. QUICK REFERENCE FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def get_dimstyle_for_drawing(char_h: float, arrow_style: str = "closed_filled") -> dict:
    """Complete DIMSTYLE setup for a BES repair drawing.

    Usage:
        attribs = get_dimstyle_for_drawing(250.0, "none")
        # Use attribs when creating BES_REPAIR dimstyle
    """
    return make_dimstyle_attribs(char_h, arrow_style)


def validate_dimension_layer(doc) -> str:
    """Ensure the document has a valid dimension layer. Returns layer name."""
    return resolve_dim_layer(doc)


def is_orthogonal(p1, p2) -> bool:
    """Check if a point pair is approximately horizontal or vertical."""
    orient, _ = orient_pair(p1, p2)
    return orient in ("h", "v")


def check_forbidden_layer(layer_name: str) -> bool:
    """Return True if this layer should never receive new entities."""
    return layer_name in FORBIDDEN_LAYERS


if __name__ == "__main__":
    # Quick self-test
    print("BES AutoCAD Knowledge Base loaded")
    print(f"  Layers: {len(LAYERS)} defined")
    print(f"  Arrow styles: {list(ARROW_STYLES.keys())}")
    print(f"  Whitelist tokens: {len(DEBRIS_WHITELIST)}")
    print(f"  Session entries: {len(SESSION_LOG)}")

    # Test orthogonality
    assert orient_pair((0, 0), (100, 0)) == ("h", 0.0)
    assert orient_pair((0, 0), (0, 100)) == ("v", 90.0)
    orient, ang = orient_pair((0, 0), (50, 50))
    assert orient == "a"
    print("  Orthogonality tests: PASS")

    # Test debris detection
    assert not is_debris("1000")
    assert not is_debris("RAIL LEVEL 178.741")
    assert not is_debris("RCC")
    assert is_debris("07")
    assert is_debris("DL'")
    print("  Debris detection tests: PASS")

    print("All self-tests PASSED")
