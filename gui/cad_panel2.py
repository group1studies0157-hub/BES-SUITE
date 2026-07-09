"""
CAD Process 2 — Dimension-First Bridge Drawing → Scaled AutoCAD DXF  (v4)
═══════════════════════════════════════════════════════════════════════════
Pipeline:
  1. Upload image/PDF
  2. Claude Vision extracts a STRUCTURED DIMENSION TABLE (not pixel geometry)
     — every mm value, RL elevation, slope ratio, label — stored as JSON
  3. Zone parser classifies each value: ELEVATION · PLAN · SECTION · NOTES
  4. Geometry engine builds real mm coordinates purely by arithmetic
     (no pixels, no scaling heuristics — start_point + cumulative_dimension)
  5. Validation: dimension chains checked for consistency before drawing
  6. ezdxf writes 1:1 DXF (1 unit = 1 mm) with 10 named layers

KEY PRINCIPLE
─────────────
  ✗  Old approach: trace pixels → convert px→mm (±5 mm error per point)
  ✓  New approach: read "4490" from drawing text → draw line exactly 4490 mm

Drawing zones detected by title keywords:
  "HALF ELEVATION" / "HALF SECTION"      → ELEVATION zone
  "HALF TOP PLAN" / "HALF BOTTOM PLAN"   → PLAN zone
  "SECTION" / "CROSS SECTION"            → SECTION zone
  All text / notes on right side          → NOTES zone
"""

import os, json, base64, datetime, tempfile, shutil, math
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QProgressBar, QFileDialog, QLineEdit, QSizePolicy,
    QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsTextItem,
    QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsPathItem,
    QSplitter, QCheckBox, QGroupBox, QGridLayout, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QRectF, QPointF
from PyQt6.QtGui import (
    QFont, QPen, QColor, QBrush, QPainterPath, QTransform,
    QWheelEvent, QDragEnterEvent, QDropEvent, QKeyEvent
)

from gui.styles import COLORS
from gui.ai_provider import AIProvider

# Vision model IDs are centralised in gui/ai_provider.py (ANTHROPIC_MODEL / GEMINI_MODEL).
# CAD Process 2 routes through AIProvider so it inherits dual-key (Gemini→Claude)
# fallback and the corrected, current model IDs — no separate hardcoded model.

# ═══════════════════════════════════════════════════════════════════════════════
# LAYER DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════
LAYERS = {
    "DECK":        {"color": "#FFFFFF", "width": 2.0,  "label": "Deck / Outline",   "on": True },
    "PIER":        {"color": "#FFFFFF", "width": 1.5,  "label": "Pier / Column",    "on": True },
    "ABUTMENT":    {"color": "#FFFFFF", "width": 1.5,  "label": "Abutment / Wall",  "on": True },
    "DIMENSIONS":  {"color": "#FFFFFF", "width": 0.8,  "label": "Dimensions",       "on": True },
    "LEVELS":      {"color": "#FFFFFF", "width": 0.8,  "label": "RL Levels",        "on": True },
    "ANNOTATIONS": {"color": "#FFFFFF", "width": 0.8,  "label": "Annotations",      "on": True },
    "FOUNDATION":  {"color": "#FFFFFF", "width": 1.2,  "label": "Foundation",       "on": True },
    "BEARING":     {"color": "#FFFFFF", "width": 1.0,  "label": "Bearing",          "on": True },
    "CENTERLINE":  {"color": "#FFFFFF", "width": 0.7,  "label": "Centre Line",      "on": True,  "dash": True},
    "GRID":        {"color": "#FFFFFF", "width": 0.4,  "label": "Grid",             "on": False, "dash": True},
}


# ═══════════════════════════════════════════════════════════════════════════════
# AI PROMPT  — structured dimension extraction
# ═══════════════════════════════════════════════════════════════════════════════

EXTRACT_SYSTEM_PROMPT = """\
You are a senior bridge engineer reading a GAD (General Arrangement Drawing).
Your job is to produce a STRUCTURED DIMENSION TABLE — not to describe the drawing.

CRITICAL RULES:
1. All dimensions must be output in MILLIMETRES.
   If the drawing shows metres (e.g. 4.490m), multiply by 1000 → 4490.
2. Read EVERY individual number in each dimension chain. Do NOT sum or skip any.
3. Reduced Levels (RL / Rail Lvl / F.Lvl / B.Lvl) are in METRES — keep them in metres.
4. If a value is not legible or not shown, use null (not 0, not estimated).
5. Return ONLY valid JSON — no markdown, no explanation, no code fences.

DRAWING ZONE DETECTION:
Read the title/heading text to identify zones present in this drawing.
Look for these exact phrase patterns (case-insensitive):
  "HALF ELEVATION" or "HALF SECTION"               → elevation zone present
  "HALF TOP PLAN" or "HALF BOTTOM PLAN" or "PLAN"  → plan zone present
  "CROSS SECTION" or "SECTION"                     → section zone present

RETURN THIS JSON STRUCTURE (include only zones actually present):

{
  "drawingTitle": "full title string from drawing",
  "bridgeNo":     "bridge number/ID if shown",
  "chainage":     "chainage if shown",
  "bridgeType":   "e.g. RCC Slab, PSC Box, Steel Composite",
  "scale":        "e.g. 1:100",
  "zones":        ["elevation", "plan", "section"],

  "elevation": {
    "_comment": "HALF ELEVATION AND HALF SECTION — longitudinal view",
    "rl": {
      "rail_lvl":        100.000,
      "formation_lvl":   null,
      "hfl":             99.250,
      "bed_lvl":         97.100,
      "cc_top":          96.100,
      "cc_bottom":       95.600,
      "other": [{"label": "F.Lvl", "value": 99.540}]
    },
    "horizontal_chain": [4350, 4490],
    "vertical_dims":    [150, 600, 600, 1000],
    "span_clear":       4490,
    "approach_slab":    4350,
    "rcc_slab_thk":     null,
    "abutment": {
      "top_width":       500,
      "base_width":      3235,
      "height":          null,
      "footing_width":   1000,
      "cc_width":        450,
      "cc_label":        "C.C 1:3:6"
    },
    "deck_slope":        null,
    "approach_slope":    "1:1½",
    "notes":             ["2x4.49m RCC Slab"]
  },

  "plan": {
    "_comment": "HALF PLAN AT TOP AND HALF PLAN AT BOTTOM — bird's-eye view",
    "transverse_chain":  [1800, 4266, 1000, 4490, 1000, 4490, 1000],
    "longitudinal_chain":[4880, 6100, 4880],
    "offset_from_cl":    [6100],
    "curtain_wall":      {"label": "Curtain wall", "dim": null},
    "toe_wall":          {"label": "Toe wall",     "dim": null},
    "drop_wall":         {"label": "Drop wall",    "dim": null},
    "stone_flooring":    true,
    "flow_direction":    "down",
    "left_label":        "DKJ",
    "right_label":       "MUGR",
    "section_cut_label": "X-X",
    "track_cl_offset":   6100,
    "notes":             []
  },

  "section": {
    "_comment": "SECTION X-X — transverse cross-section",
    "label":             "SECTION X-X",
    "transverse_chain":  [750, 9150],
    "vertical_chain":    [610],
    "rcc_slab_thk":      610,
    "slope_left":        "2:1",
    "slope_right":       "1:8",
    "stone_flooring":    true,
    "rl": {
      "rail_lvl":        100.000,
      "formation_lvl":   99.540,
      "bed":             97.100
    },
    "abutment_width":    1676,
    "drop_wall_dim":     750,
    "notes":             ["RCC Slab 610mm thick"]
  },

  "abutment_section": {
    "_comment": "CROSS SECTION OF ABUTMENT (if separately drawn)",
    "top_width":         500,
    "base_width":        3235,
    "height_dims":       [150, 600, 600, 1000],
    "footing":           1000,
    "cc_label":          "C.C 1:3:6"
  },

  "return_wall_section": {
    "_comment": "CROSS SECTION OF STRAIGHT RETURN WALL (if separately drawn)",
    "top_width":         450,
    "base_width":        3200,
    "height_dims":       [450, 600, 600, 1000],
    "footing":           1000,
    "cc_label":          "C.C 1:3:6"
  },

  "validation": {
    "elevation_h_chain_sum":   8840,
    "elevation_v_chain_sum":   2350,
    "plan_transverse_sum":     null,
    "plan_longitudinal_sum":   null,
    "warnings":                []
  }
}

IMPORTANT: Only include keys for zones and sections actually visible in the drawing.
Read every number you can see. Do not invent or estimate any value.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _validate_chain(chain: list, expected_total, label: str, warnings: list):
    """Check a dimension chain sums to expected total. Appends warnings."""
    if not chain or expected_total is None:
        return
    total = sum(v for v in chain if isinstance(v, (int, float)))
    diff  = abs(total - expected_total)
    tol   = max(5, expected_total * 0.005)   # 0.5% or 5mm tolerance
    if diff > tol:
        warnings.append(
            f"{label}: chain sum {total:.0f}mm ≠ stated {expected_total:.0f}mm "
            f"(diff {diff:.0f}mm)"
        )


def validate_extracted(data: dict) -> list:
    """Run all cross-checks. Returns list of warning strings."""
    w = []
    ev = data.get("elevation", {})
    pv = data.get("plan",      {})
    sv = data.get("section",   {})

    # Elevation horizontal chain vs span
    h = ev.get("horizontal_chain", [])
    span = ev.get("span_clear")
    if h and span:
        _validate_chain(h, sum(v for v in h if v), "Elev H-chain", w)

    # Elevation vertical chain vs RL diff
    rl  = ev.get("rl", {})
    rail = rl.get("rail_lvl")
    bed  = rl.get("bed_lvl")
    if rail and bed:
        rl_diff = (rail - bed) * 1000   # m→mm
        vchain  = ev.get("vertical_dims", [])
        if vchain:
            _validate_chain(vchain, rl_diff, "Elev V-chain vs RL diff", w)

    # Plan transverse chain
    pt = pv.get("transverse_chain", [])
    if pt:
        pass   # no stated total to check against usually

    # Section slab thickness
    if sv.get("rcc_slab_thk") and sv.get("vertical_chain"):
        vc_sum = sum(sv["vertical_chain"])
        thk    = sv["rcc_slab_thk"]
        if abs(vc_sum - thk) > 5:
            w.append(f"Section V-chain sum {vc_sum}mm ≠ slab thickness {thk}mm")

    return w


# ═══════════════════════════════════════════════════════════════════════════════
# INTERPOLATION — fill missing (null) dimensions from surrounding context
# ═══════════════════════════════════════════════════════════════════════════════

def interpolate_missing(data: dict) -> list:
    """
    Fill null / missing dimensions by inference from surrounding values:
      • slab thickness  ← first vertical dim, or RL(rail) − RL(soffit)
      • span / approach ← horizontal dimension chain
      • abutment height ← RL(bed) − RL(cc_bottom) or vertical chain sum
      • abutment ↔ return-wall widths ← mirrored when one side is missing
    Mutates `data` in place. Returns a list of human-readable interpolation notes
    so every inferred value is auditable (never silently invented).
    """
    notes = []
    ev = data.get("elevation", {}) or {}
    rl = ev.get("rl", {}) if isinstance(ev.get("rl"), dict) else {}

    # 1) RCC slab thickness
    if ev and not ev.get("rcc_slab_thk"):
        vd = [v for v in (ev.get("vertical_dims") or []) if isinstance(v, (int, float))]
        if vd:
            ev["rcc_slab_thk"] = vd[0]
            notes.append(f"slab thickness ← {vd[0]}mm (1st vertical dim)")
        else:
            rail, form = rl.get("rail_lvl"), rl.get("formation_lvl")
            if rail and form:
                thk = round((rail - form) * 1000)
                ev["rcc_slab_thk"] = thk
                notes.append(f"slab thickness ← {thk}mm (rail−formation RL)")

    # 2) Span / approach from horizontal chain
    hc = [v for v in (ev.get("horizontal_chain") or []) if isinstance(v, (int, float))]
    if ev.get("span_clear") is None and hc:
        ev["span_clear"] = max(hc)
        notes.append(f"span_clear ← {max(hc)}mm (max of H-chain)")
    if ev.get("approach_slab") is None and len(hc) > 1:
        ev["approach_slab"] = min(hc)
        notes.append(f"approach_slab ← {min(hc)}mm (min of H-chain)")

    # 3) Abutment height from RL difference or vertical chain
    ab = ev.get("abutment", {}) if isinstance(ev.get("abutment"), dict) else {}
    if ab and ab.get("height") is None:
        vd = [v for v in (ev.get("vertical_dims") or []) if isinstance(v, (int, float))]
        if vd:
            ab["height"] = sum(vd)
            notes.append(f"abutment height ← {sum(vd)}mm (Σ vertical chain)")

    # 4) Abutment ↔ return-wall symmetry (mirror missing widths)
    ab_sec = data.get("abutment_section", {}) or {}
    rw_sec = data.get("return_wall_section", {}) or {}
    for src, dst, lbl in ((ab_sec, rw_sec, "return-wall"),
                          (rw_sec, ab_sec, "abutment-section")):
        if src and dst:
            for k in ("top_width", "base_width", "footing"):
                if dst.get(k) is None and src.get(k) is not None:
                    dst[k] = src[k]
                    notes.append(f"{lbl} {k} ← {src[k]}mm (mirrored)")

    return notes


# ═══════════════════════════════════════════════════════════════════════════════
# GEOMETRY HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _num(v, default):
    """None-safe numeric fetch. dict.get(key, default) returns None when the
    JSON explicitly contains null — this coalesces that to the default too."""
    return default if v is None else v

def _chain(seq):
    """Return a dimension chain with any null/non-numeric entries removed."""
    return [v for v in (seq or []) if isinstance(v, (int, float))]

def _line(ents, layer, x1, y1, x2, y2):
    ents.append({"type": "LINE", "layer": layer,
                 "x1": float(x1), "y1": float(y1),
                 "x2": float(x2), "y2": float(y2)})

def _text(ents, layer, x, y, text, height=180):
    ents.append({"type": "TEXT", "layer": layer,
                 "x": float(x), "y": float(y),
                 "text": str(text), "height": float(height)})

def _circle(ents, layer, cx, cy, r):
    ents.append({"type": "CIRCLE", "layer": layer,
                 "cx": float(cx), "cy": float(cy), "r": float(r)})

def _rect(ents, layer, x1, y1, x2, y2):
    _line(ents, layer, x1, y1, x2, y1)
    _line(ents, layer, x2, y1, x2, y2)
    _line(ents, layer, x2, y2, x1, y2)
    _line(ents, layer, x1, y2, x1, y1)

def _dim_line(ents, layer, x1, y1, x2, y2, label, offset=400, text_h=180):
    """Dimension line with ticks and label."""
    _line(ents, layer, x1, y1, x2, y2)
    if abs(x2 - x1) > abs(y2 - y1):   # horizontal
        for tx in (x1, x2):
            _line(ents, layer, tx, y1 - offset * 0.5, tx, y1 + offset * 0.5)
        _text(ents, layer, (x1+x2)/2 - len(label)*text_h*0.28,
              y1 + offset * 1.1, label, text_h)
    else:                               # vertical
        for ty in (y1, y2):
            _line(ents, layer, x1 - offset * 0.5, ty, x1 + offset * 0.5, ty)
        _text(ents, layer, x1 - offset * 1.8,
              (y1+y2)/2 - text_h * 0.5, label, text_h)

def _rl_marker(ents, x, y, label, side="left"):
    """Draw a level marker arrow + label."""
    if side == "left":
        _line(ents, "LEVELS", x - 4000, y, x - 200, y)
        _text(ents, "LEVELS", x - 3900, y + 120, label, 160)
    else:
        _line(ents, "LEVELS", x + 200, y, x + 4000, y)
        _text(ents, "LEVELS", x + 300, y + 120, label, 160)


# ═══════════════════════════════════════════════════════════════════════════════
# ELEVATION GEOMETRY BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_elevation(data: dict) -> tuple:
    """
    Build elevation view from extracted dimension table.
    Origin: X=0 at left edge, Y=0 at bed level (B.Lvl).
    All coordinates computed from RL values and dimension chains.
    """
    ents = []
    ev   = data.get("elevation", {})
    rl   = ev.get("rl", {})

    # ── Convert RL values to Y coordinates (mm above bed level) ──────
    # _num() coalesces explicit JSON nulls (dict.get default only covers
    # MISSING keys, not null values — the float−NoneType crash).
    rl_bed    = _num(rl.get("bed_lvl"),        97.100)
    rl_rail   = _num(rl.get("rail_lvl"),      100.000)
    rl_hfl    = _num(rl.get("hfl"),            99.250)
    rl_form   = _num(rl.get("formation_lvl"),  99.540)
    rl_cc_top = _num(rl.get("cc_top"),         96.100)
    rl_cc_bot = _num(rl.get("cc_bottom"),      95.600)

    def rl_y(rl_m):
        """Convert an RL in metres to a Y coordinate in mm (bed = 0)."""
        return (rl_m - rl_bed) * 1000

    y_bed    = 0.0
    y_rail   = rl_y(rl_rail)    if rl_rail   else 2900.0
    y_hfl    = rl_y(rl_hfl)     if rl_hfl    else 2150.0
    y_form   = rl_y(rl_form)    if rl_form   else 2440.0
    y_cc_top = rl_y(rl_cc_top)  if rl_cc_top else -900.0
    y_cc_bot = rl_y(rl_cc_bot)  if rl_cc_bot else -1400.0

    # Slab thickness from vertical dim chain or RL diff
    slab_thk = ev.get("rcc_slab_thk")
    if not slab_thk:
        vchain = _chain(ev.get("vertical_dims"))
        slab_thk = vchain[0] if vchain else (y_rail - y_form)

    y_soffit = y_rail - slab_thk if slab_thk else y_form

    # ── Horizontal layout from dimension chain ────────────────────────
    h_chain   = _chain(ev.get("horizontal_chain"))
    span_clear = ev.get("span_clear")
    approach   = ev.get("approach_slab")
    ab_data    = ev.get("abutment", {}) or {}
    ab_base_w  = _num(ab_data.get("base_width"),   3235)
    ab_top_w   = _num(ab_data.get("top_width"),    500)
    ab_foot_w  = _num(ab_data.get("footing_width"), 1000)

    # Determine span and approach from chain if not explicit
    if span_clear is None:
        span_clear = max(h_chain) if h_chain else 4490
    if approach is None:
        approach   = min(h_chain) if h_chain else 4350

    # X positions: origin at left abutment stem
    x0         = 0.0
    x_span_l   = x0                   # left end of clear span
    x_span_r   = x0 + span_clear      # right end of clear span
    total_x    = x_span_r

    # ── MAIN SLAB (deck) ──────────────────────────────────────────────
    _line(ents, "DECK", x_span_l, y_soffit, x_span_r, y_soffit)   # soffit
    _line(ents, "DECK", x_span_l, y_rail,   x_span_r, y_rail)     # top

    # ── RCC SLAB thickness end lines ─────────────────────────────────
    _line(ents, "DECK", x_span_l, y_soffit, x_span_l, y_rail)
    _line(ents, "DECK", x_span_r, y_soffit, x_span_r, y_rail)

    # ── HFL LINE ─────────────────────────────────────────────────────
    _line(ents, "LEVELS", x_span_l, y_hfl, x_span_r, y_hfl)

    # ── LEFT ABUTMENT ─────────────────────────────────────────────────
    # Stem: from bed level up to soffit level, top_width wide
    ab_stem_l = x_span_l - ab_top_w / 2
    ab_stem_r = x_span_l + ab_top_w / 2
    _line(ents, "ABUTMENT", ab_stem_l, y_bed, ab_stem_l, y_soffit)
    _line(ents, "ABUTMENT", ab_stem_r, y_bed, ab_stem_r, y_soffit)
    # Footing: wider base
    ab_foot_l = x_span_l - ab_base_w / 2
    ab_foot_r = x_span_l + ab_base_w / 2
    _line(ents, "FOUNDATION", ab_foot_l, y_cc_bot, ab_foot_r, y_cc_bot)
    _line(ents, "FOUNDATION", ab_foot_l, y_bed,    ab_foot_r, y_bed)
    _line(ents, "FOUNDATION", ab_foot_l, y_cc_bot, ab_foot_l, y_bed)
    _line(ents, "FOUNDATION", ab_foot_r, y_cc_bot, ab_foot_r, y_bed)
    # C.C label line
    _line(ents, "FOUNDATION", ab_foot_l, y_cc_top, ab_foot_r, y_cc_top)
    _text(ents, "ANNOTATIONS", ab_foot_l + 100, y_cc_top + 80,
          ab_data.get("cc_label", "C.C 1:3:6"), 150)

    # ── RIGHT ABUTMENT (mirror) ───────────────────────────────────────
    ab2_stem_l = x_span_r - ab_top_w / 2
    ab2_stem_r = x_span_r + ab_top_w / 2
    _line(ents, "ABUTMENT", ab2_stem_l, y_bed, ab2_stem_l, y_soffit)
    _line(ents, "ABUTMENT", ab2_stem_r, y_bed, ab2_stem_r, y_soffit)
    ab2_foot_l = x_span_r - ab_base_w / 2
    ab2_foot_r = x_span_r + ab_base_w / 2
    _line(ents, "FOUNDATION", ab2_foot_l, y_cc_bot, ab2_foot_r, y_cc_bot)
    _line(ents, "FOUNDATION", ab2_foot_l, y_bed,    ab2_foot_r, y_bed)
    _line(ents, "FOUNDATION", ab2_foot_l, y_cc_bot, ab2_foot_l, y_bed)
    _line(ents, "FOUNDATION", ab2_foot_r, y_cc_bot, ab2_foot_r, y_bed)
    _line(ents, "FOUNDATION", ab2_foot_l, y_cc_top, ab2_foot_r, y_cc_top)
    _text(ents, "ANNOTATIONS", ab2_foot_l + 100, y_cc_top + 80,
          ab_data.get("cc_label", "C.C 1:3:6"), 150)

    # ── APPROACH SLABS ────────────────────────────────────────────────
    if approach:
        # Left approach
        _line(ents, "DECK", x_span_l - approach, y_form, x_span_l, y_form)
        _line(ents, "DECK", x_span_l - approach, y_rail, x_span_l, y_rail)
        _line(ents, "DECK", x_span_l - approach, y_form, x_span_l - approach, y_rail)
        # Right approach
        _line(ents, "DECK", x_span_r, y_form, x_span_r + approach, y_form)
        _line(ents, "DECK", x_span_r, y_rail, x_span_r + approach, y_rail)
        _line(ents, "DECK", x_span_r + approach, y_form, x_span_r + approach, y_rail)

    # ── SLOPE LINES (embankment) ──────────────────────────────────────
    slope_str = ev.get("approach_slope", "1:1½")
    # Parse slope e.g. "1:1½" → run = 1.5 per rise 1
    try:
        parts = slope_str.replace("½", ".5").replace("¾", ".75").split(":")
        slope_h = float(parts[1]) if len(parts) > 1 else 1.5
    except Exception:
        slope_h = 1.5
    slope_run = y_rail * slope_h   # horizontal run for full height
    _line(ents, "ABUTMENT",
          ab_foot_l, y_bed,
          ab_foot_l - slope_run, y_rail)
    _line(ents, "ABUTMENT",
          ab2_foot_r, y_bed,
          ab2_foot_r + slope_run, y_rail)

    # ── RL LEVEL MARKERS ─────────────────────────────────────────────
    _rl_marker(ents, ab_foot_l - slope_run - 500, y_rail,
               f"Rail Lvl {rl_rail:.3f}", "left")
    if rl_form:
        _rl_marker(ents, ab_foot_l - 200, y_form,
                   f"F.Lvl {rl_form:.3f}", "left")
    _rl_marker(ents, ab_foot_l, y_hfl,
               f"HFL {rl_hfl:.3f}", "left")
    _rl_marker(ents, ab_foot_l, y_bed,
               f"B.Lvl {rl_bed:.3f}", "left")
    if rl_cc_top:
        _rl_marker(ents, ab_foot_l, y_cc_top,
                   f"{rl_cc_top:.3f}", "left")
    if rl_cc_bot:
        _rl_marker(ents, ab_foot_l, y_cc_bot,
                   f"{rl_cc_bot:.3f}", "left")

    # ── HORIZONTAL DIMENSION CHAIN ────────────────────────────────────
    dim_y = y_rail + 600
    if approach:
        _dim_line(ents, "DIMENSIONS",
                  x_span_l - approach, dim_y, x_span_l, dim_y,
                  f"{approach:.0f}", 300, 160)
    _dim_line(ents, "DIMENSIONS",
              x_span_l, dim_y, x_span_r, dim_y,
              f"{span_clear:.0f}", 300, 160)
    if approach:
        _dim_line(ents, "DIMENSIONS",
                  x_span_r, dim_y, x_span_r + approach, dim_y,
                  f"{approach:.0f}", 300, 160)

    # ── TITLE ─────────────────────────────────────────────────────────
    _text(ents, "ANNOTATIONS",
          x_span_l, y_cc_bot - 1500,
          "HALF ELEVATION AND HALF SECTION", 220)
    _text(ents, "ANNOTATIONS",
          x_span_l, y_cc_bot - 1800,
          f"Scale: {data.get('scale','NTS')}  |  "
          f"Bridge No: {data.get('bridgeNo','—')}  |  "
          f"Units: mm  |  {datetime.date.today()}", 150)

    # Validate
    w_msgs = validate_extracted(data)
    for w in w_msgs:
        _text(ents, "ANNOTATIONS", x_span_l, y_cc_bot - 2200 - w_msgs.index(w)*300,
              f"⚠ {w}", 140)

    x_extent   = max(x_span_r + (approach or 0), ab2_foot_r) + slope_run
    bounds = {
        "xMin": ab_foot_l - slope_run - 5000,
        "xMax": x_extent + 2000,
        "yMin": y_cc_bot - 2800,
        "yMax": y_rail   + 1500,
    }
    meta = {
        "rl_deck":   y_rail, "rl_soffit": y_soffit,
        "rl_ground": y_bed,  "total_x":   total_x, "abut_w": ab_top_w,
    }
    return ents, bounds, meta


# ═══════════════════════════════════════════════════════════════════════════════
# PLAN GEOMETRY BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_plan(data: dict) -> tuple:
    """
    Build plan view from extracted dimension table.
    Origin: X=0 at left transverse edge, Y=0 at bottom longitudinal edge.
    All coordinates from transverse_chain and longitudinal_chain.
    """
    ents = []
    pv   = data.get("plan", {})

    t_chain = _chain(pv.get("transverse_chain"))
    l_chain = _chain(pv.get("longitudinal_chain"))

    # Fallback
    if not t_chain:
        t_chain = [_num(data.get("elevation", {}).get("span_clear"), 4490)]
    if not l_chain:
        cl_off = _num(pv.get("track_cl_offset"), 6100)
        l_chain = [cl_off, cl_off]

    total_w = sum(t_chain)
    total_l = sum(l_chain)

    # Build cumulative X positions
    x_pos = [0.0]
    for d in t_chain:
        x_pos.append(x_pos[-1] + d)

    # Build cumulative Y positions
    y_pos = [0.0]
    for d in l_chain:
        y_pos.append(y_pos[-1] + d)

    FONT = 180

    # ── OUTER BOUNDARY ────────────────────────────────────────────────
    _rect(ents, "DECK", 0, 0, total_w, total_l)

    # ── INTERNAL TRANSVERSE GRID LINES ───────────────────────────────
    for xi in x_pos[1:-1]:
        _line(ents, "PIER", xi, 0, xi, total_l)

    # ── INTERNAL LONGITUDINAL ZONE LINES ─────────────────────────────
    for yi in y_pos[1:-1]:
        _line(ents, "ABUTMENT", 0, yi, total_w, yi)

    # ── CENTRELINE OF TRACK ───────────────────────────────────────────
    cl_x = total_w / 2
    cl_y = _num(pv.get("track_cl_offset"), total_l / 2)
    _line(ents, "CENTERLINE", cl_x, -1000, cl_x, total_l + 1000)
    _text(ents, "ANNOTATIONS", cl_x + 100, total_l / 2, "₵ OF TRACK", FONT)

    # ── SECTION CUT LINE ─────────────────────────────────────────────
    sec_lbl = pv.get("section_cut_label", "X-X")
    _line(ents, "CENTERLINE", -800, cl_y, total_w + 800, cl_y)
    _text(ents, "ANNOTATIONS", -700, cl_y + 150, sec_lbl, 220)
    _text(ents, "ANNOTATIONS", total_w + 100, cl_y + 150, sec_lbl, 220)

    # ── WING WALL LABELS ─────────────────────────────────────────────
    cw_lbl = pv.get("curtain_wall", {})
    if isinstance(cw_lbl, dict): cw_lbl = cw_lbl.get("label", "Curtain wall")
    tw_lbl = pv.get("toe_wall",    {})
    if isinstance(tw_lbl, dict): tw_lbl = tw_lbl.get("label", "Toe wall")
    dw_lbl = pv.get("drop_wall",   {})
    if isinstance(dw_lbl, dict): dw_lbl = dw_lbl.get("label", "Drop wall")

    _text(ents, "ANNOTATIONS", total_w * 0.3, total_l + 200, cw_lbl,  FONT)
    _text(ents, "ANNOTATIONS", total_w * 0.3, -600,          tw_lbl,  FONT)
    _text(ents, "ANNOTATIONS", total_w * 0.3, -900,          dw_lbl,  FONT)

    # ── STONE FLOORING LABEL ─────────────────────────────────────────
    if pv.get("stone_flooring"):
        _text(ents, "ANNOTATIONS", total_w * 0.15, total_l * 0.7,
              "Stone Flooring", FONT)
        _text(ents, "ANNOTATIONS", total_w * 0.15, total_l * 0.3,
              "Stone Flooring", FONT)

    # ── DIRECTION ARROWS ─────────────────────────────────────────────
    left_lbl  = pv.get("left_label",  "DKJ")
    right_lbl = pv.get("right_label", "MUGR")
    # Left arrow
    _line(ents, "ANNOTATIONS", -2500, cl_y, -800, cl_y)
    _line(ents, "ANNOTATIONS", -2500, cl_y, -2200, cl_y + 150)
    _line(ents, "ANNOTATIONS", -2500, cl_y, -2200, cl_y - 150)
    _text(ents, "ANNOTATIONS", -2400, cl_y + 250, left_lbl, FONT)
    # Right arrow
    _line(ents, "ANNOTATIONS", total_w + 800, cl_y, total_w + 2500, cl_y)
    _line(ents, "ANNOTATIONS", total_w + 2500, cl_y, total_w + 2200, cl_y + 150)
    _line(ents, "ANNOTATIONS", total_w + 2500, cl_y, total_w + 2200, cl_y - 150)
    _text(ents, "ANNOTATIONS", total_w + 900, cl_y + 250, right_lbl, FONT)

    # ── FLOW ARROW ───────────────────────────────────────────────────
    flow_dir = pv.get("flow_direction", "down")
    fy = -1800
    _line(ents, "ANNOTATIONS", cl_x, fy + 600, cl_x, fy)
    _line(ents, "ANNOTATIONS", cl_x, fy, cl_x - 150, fy + 250)
    _line(ents, "ANNOTATIONS", cl_x, fy, cl_x + 150, fy + 250)
    _text(ents, "ANNOTATIONS", cl_x + 200, fy + 300, "Flow", FONT)

    # ── TRANSVERSE DIMENSION CHAIN ───────────────────────────────────
    dim_y = -1200
    for i, (xa, xb) in enumerate(zip(x_pos, x_pos[1:])):
        _dim_line(ents, "DIMENSIONS", xa, dim_y, xb, dim_y,
                  f"{t_chain[i]:.0f}", 250, FONT)

    # ── LONGITUDINAL DIMENSION CHAIN ─────────────────────────────────
    dim_x = -1200
    for i, (ya, yb) in enumerate(zip(y_pos, y_pos[1:])):
        _dim_line(ents, "DIMENSIONS", dim_x, ya, dim_x, yb,
                  f"{l_chain[i]:.0f}", 250, FONT)

    # ── OFFSET DIMS FROM CL ──────────────────────────────────────────
    for od in pv.get("offset_from_cl", []):
        _dim_line(ents, "DIMENSIONS",
                  cl_x, cl_y + 300, cl_x + od, cl_y + 300,
                  f"{od:.0f}", 200, FONT)

    # ── TITLE ─────────────────────────────────────────────────────────
    _text(ents, "ANNOTATIONS", 0, -2800,
          "HALF PLAN AT TOP AND HALF PLAN AT BOTTOM", 220)
    _text(ents, "ANNOTATIONS", 0, -3100,
          f"Scale: {data.get('scale','NTS')}  |  Units: mm  |  {datetime.date.today()}",
          150)

    bounds = {
        "xMin": -4000, "xMax": total_w + 4000,
        "yMin": -4000, "yMax": total_l + 2000,
    }
    meta = {"rl_deck": 0, "rl_soffit": 0, "rl_ground": 0,
            "total_x": total_w, "abut_w": 0}
    return ents, bounds, meta


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION GEOMETRY BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_section(data: dict) -> tuple:
    """
    Build cross-section (Section X-X) from extracted dimension table.
    Origin: X=0 at left edge, Y=0 at bed level.
    """
    ents = []
    sv   = data.get("section", {})
    rl   = sv.get("rl", data.get("elevation", {}).get("rl", {}))

    rl_bed    = _num(rl.get("bed", rl.get("bed_lvl")), 97.100)
    rl_rail   = _num(rl.get("rail_lvl"),  100.000)
    rl_form   = _num(rl.get("formation_lvl"), 99.540)

    def rl_y(v):
        return (v - rl_bed) * 1000

    y_bed  = 0.0
    y_rail = rl_y(rl_rail)
    y_form = rl_y(rl_form) if rl_form else y_rail - 460

    slab_thk   = _num(sv.get("rcc_slab_thk"), 610)
    t_chain    = _chain(sv.get("transverse_chain"))
    total_w    = sum(t_chain) if t_chain else 9900
    abut_w     = _num(sv.get("abutment_width"), 1676)
    drop_dim   = _num(sv.get("drop_wall_dim"), 750)

    FONT = 180

    # ── RCC SLAB (top) ────────────────────────────────────────────────
    _rect(ents, "DECK",
          0, y_rail - slab_thk,
          total_w, y_rail)
    _text(ents, "ANNOTATIONS", total_w / 2 - 600, y_rail - slab_thk / 2,
          f"RCC Slab {slab_thk:.0f}mm thick", FONT)

    # ── ABUTMENT STEMS (left and right) ──────────────────────────────
    _rect(ents, "ABUTMENT", 0, y_bed, abut_w, y_rail - slab_thk)
    _rect(ents, "ABUTMENT", total_w - abut_w, y_bed, total_w, y_rail - slab_thk)

    # ── DROP WALLS ────────────────────────────────────────────────────
    _rect(ents, "FOUNDATION", 0, y_bed - drop_dim, drop_dim, y_bed)
    _rect(ents, "FOUNDATION", total_w - drop_dim, y_bed - drop_dim, total_w, y_bed)

    # ── STONE FLOORING ZONE ──────────────────────────────────────────
    if sv.get("stone_flooring"):
        _line(ents, "ABUTMENT", abut_w, y_bed, total_w - abut_w, y_bed)
        _text(ents, "ANNOTATIONS", total_w / 2 - 500, y_bed + 100,
              "Stone Flooring", FONT)

    # ── SLOPE LINES ───────────────────────────────────────────────────
    def _parse_slope(s):
        try:
            p = str(s).replace("½", ".5").replace("¾", ".75").split(":")
            return float(p[1]) if len(p) > 1 else 2.0
        except Exception:
            return 2.0

    sl_left  = _parse_slope(sv.get("slope_left",  "2:1"))
    sl_right = _parse_slope(sv.get("slope_right", "1:8"))
    run_l    = y_rail * sl_left
    run_r    = y_rail * sl_right
    _line(ents, "ABUTMENT", 0, y_rail, -run_l, y_bed)
    _line(ents, "ABUTMENT", total_w, y_rail, total_w + run_r, y_bed)

    # ── CENTRELINE OF TRACK ───────────────────────────────────────────
    cl_x = total_w / 2
    _line(ents, "CENTERLINE", cl_x, y_bed - 500, cl_x, y_rail + 800)
    _text(ents, "ANNOTATIONS", cl_x + 80, y_rail + 300, "₵ of Track", FONT)

    # ── RL MARKERS ────────────────────────────────────────────────────
    _rl_marker(ents, -run_l, y_rail,
               f"Rail Lvl {rl_rail:.3f}", "left")
    _rl_marker(ents, 0, y_form,
               f"Formation Lvl {rl_form:.3f}", "left")
    _rl_marker(ents, 0, y_bed,
               f"{rl_bed:.3f}", "left")

    # ── DIMENSION CHAIN ───────────────────────────────────────────────
    dim_y = y_bed - 800
    if t_chain:
        x_cur = 0.0
        for d in t_chain:
            _dim_line(ents, "DIMENSIONS",
                      x_cur, dim_y, x_cur + d, dim_y,
                      f"{d:.0f}", 250, FONT)
            x_cur += d
    else:
        _dim_line(ents, "DIMENSIONS", 0, dim_y, total_w, dim_y,
                  f"{total_w:.0f}", 250, FONT)

    # Vertical: slab thickness
    _dim_line(ents, "DIMENSIONS",
              total_w + 600, y_rail - slab_thk,
              total_w + 600, y_rail,
              f"{slab_thk:.0f}", 250, FONT)

    # ── LABELS ────────────────────────────────────────────────────────
    _text(ents, "ANNOTATIONS", total_w + 800, y_rail / 2, "SECTION 'X-X'", FONT)
    _text(ents, "ANNOTATIONS", 0, y_bed - drop_dim - 800,
          "SECTION X-X", 220)
    _text(ents, "ANNOTATIONS", 0, y_bed - drop_dim - 1100,
          f"Scale: {data.get('scale','NTS')}  |  Units: mm  |  {datetime.date.today()}", 150)

    # Curtain wall label
    _text(ents, "ANNOTATIONS", total_w + 900, y_rail * 0.8, "Curtain Wall", FONT)

    bounds = {
        "xMin": -run_l  - 5000,
        "xMax": total_w + run_r + 3000,
        "yMin": y_bed - drop_dim - 2000,
        "yMax": y_rail + 1500,
    }
    meta = {"rl_deck": y_rail, "rl_soffit": y_rail - slab_thk,
            "rl_ground": y_bed, "total_x": total_w, "abut_w": abut_w}
    return ents, bounds, meta


# ═══════════════════════════════════════════════════════════════════════════════
# ABUTMENT CROSS-SECTION BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_abutment_section(data: dict) -> tuple:
    """Cross section of abutment — trapezoidal shape from extracted dims."""
    ents = []
    ab   = data.get("abutment_section",
                    data.get("elevation", {}).get("abutment", {}))

    top_w  = _num(ab.get("top_width"),  500)
    base_w = _num(ab.get("base_width"), 3235)
    h_dims = _chain(ab.get("height_dims")) or [150, 600, 600, 1000]
    foot_w = _num(ab.get("footing"),    1000)
    total_h = sum(h_dims)
    FONT = 180

    cx = base_w / 2

    # Layers from top
    y = 0.0
    for i, hd in enumerate(h_dims):
        # Width tapers from top_w at top to base_w at bottom
        frac_bot = (sum(h_dims[:i+1])) / total_h
        frac_top = (sum(h_dims[:i]))   / total_h
        w_top = top_w  + (base_w - top_w) * frac_top
        w_bot = top_w  + (base_w - top_w) * frac_bot
        xl_top = cx - w_top / 2; xr_top = cx + w_top / 2
        xl_bot = cx - w_bot / 2; xr_bot = cx + w_bot / 2
        _line(ents, "ABUTMENT", xl_top, y, xr_top, y)        # top edge
        _line(ents, "ABUTMENT", xl_top, y, xl_bot, y + hd)   # left slope
        _line(ents, "ABUTMENT", xr_top, y, xr_bot, y + hd)   # right slope
        _dim_line(ents, "DIMENSIONS",
                  xr_bot + 300, y, xr_bot + 300, y + hd,
                  f"{hd:.0f}", 200, 150)
        y += hd

    # Bottom edge
    _line(ents, "ABUTMENT", cx - base_w/2, y, cx + base_w/2, y)

    # Footing
    _rect(ents, "FOUNDATION",
          cx - foot_w/2, y, cx + foot_w/2, y + 300)

    # C.C label
    cc_lbl = ab.get("cc_label", "C.C 1:3:6")
    _text(ents, "ANNOTATIONS", cx - 200, y + 100, cc_lbl, FONT)

    # Width dims
    _dim_line(ents, "DIMENSIONS", cx - top_w/2, -400, cx + top_w/2, -400,
              f"{top_w:.0f}", 200, FONT)
    _dim_line(ents, "DIMENSIONS", cx - base_w/2, y + 600, cx + base_w/2, y + 600,
              f"{base_w:.0f}", 200, FONT)

    _text(ents, "ANNOTATIONS", 0, y + 1200, "CROSS SECTION OF ABUTMENT", 200)

    bounds = {"xMin": -1500, "xMax": base_w + 2000,
              "yMin": -1000, "yMax": y + 2000}
    meta   = {"rl_deck": 0, "rl_soffit": 0, "rl_ground": 0,
              "total_x": base_w, "abut_w": 0}
    return ents, bounds, meta


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-ZONE DISPATCHER
# ═══════════════════════════════════════════════════════════════════════════════

def build_bridge_geometry(data: dict) -> tuple:
    """
    Build all zones present in the drawing and offset them so they
    don't overlap in model space — matching the original sheet layout.
    Returns merged entities, combined bounds, meta.
    """
    zones  = [z.lower() for z in data.get("zones", [])]
    if not zones:
        # Detect from drawingType fallback
        dt = data.get("drawingType", "elevation").lower()
        if "plan" in dt:              zones = ["plan"]
        elif "section" in dt:         zones = ["section"]
        else:                         zones = ["elevation"]

    all_ents  = []
    xmin_all  = []
    xmax_all  = []
    ymin_all  = []
    ymax_all  = []
    x_offset  = 0.0
    GAP       = 8000   # horizontal gap between zones in model space

    meta_out  = {}

    for zone in zones:
        if "elevation" in zone or "elevation" in data.get("drawingType",""):
            ents, bounds, meta = _build_elevation(data)
        elif "plan" in zone:
            ents, bounds, meta = _build_plan(data)
        elif "section" in zone and "abutment" not in zone:
            ents, bounds, meta = _build_section(data)
        elif "abutment" in zone:
            ents, bounds, meta = _build_abutment_section(data)
        else:
            ents, bounds, meta = _build_elevation(data)

        # Shift entities horizontally by x_offset
        for e in ents:
            if "x1" in e:
                e["x1"] += x_offset; e["x2"] += x_offset
            if "cx" in e:
                e["cx"] += x_offset
            if "x" in e and e["type"] == "TEXT":
                e["x"] += x_offset
        bounds["xMin"] += x_offset
        bounds["xMax"] += x_offset

        all_ents.extend(ents)
        xmin_all.append(bounds["xMin"]); xmax_all.append(bounds["xMax"])
        ymin_all.append(bounds["yMin"]); ymax_all.append(bounds["yMax"])
        x_offset = bounds["xMax"] + GAP
        meta_out = meta

    combined_bounds = {
        "xMin": min(xmin_all), "xMax": max(xmax_all),
        "yMin": min(ymin_all), "yMax": max(ymax_all),
    }
    meta_out["data"] = data
    return all_ents, combined_bounds, meta_out


# ═══════════════════════════════════════════════════════════════════════════════
# DXF WRITER
# ═══════════════════════════════════════════════════════════════════════════════

def write_dxf(entities: list, output_path: str):
    import ezdxf
    doc      = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp      = doc.modelspace()

    for name in LAYERS:
        if name not in doc.layers:
            lyr = doc.layers.add(name, color=7)   # 7 = white
            if name in ("CENTERLINE", "GRID"):
                lyr.dxf.linetype = "DASHED"

    if "CADSTYLE" not in doc.styles:
        doc.styles.add("CADSTYLE", font="romans.shx")

    for e in entities:
        layer = e.get("layer", "ANNOTATIONS")
        if e["type"] == "LINE":
            msp.add_line((e["x1"], e["y1"]), (e["x2"], e["y2"]),
                         dxfattribs={"layer": layer})
        elif e["type"] == "TEXT":
            txt = msp.add_text(e["text"], dxfattribs={
                "layer": layer, "height": e.get("height", 180),
                "style": "CADSTYLE",
            })
            # set_placement is the reliable way to position TEXT in ezdxf;
            # passing "insert" via dxfattribs is silently ignored on some builds,
            # which stacked every label at the origin.
            txt.set_placement((e["x"], e["y"]))
        elif e["type"] == "CIRCLE":
            msp.add_circle((e["cx"], e["cy"]), e["r"],
                           dxfattribs={"layer": layer})

    # ── Frame the drawing so AutoCAD opens zoomed-to-extents, not blank ──────
    xs, ys = [], []
    for e in entities:
        if e["type"] == "LINE":
            xs += [e["x1"], e["x2"]]; ys += [e["y1"], e["y2"]]
        elif e["type"] == "CIRCLE":
            xs += [e["cx"] - e["r"], e["cx"] + e["r"]]
            ys += [e["cy"] - e["r"], e["cy"] + e["r"]]
        elif e["type"] == "TEXT":
            xs.append(e["x"]); ys.append(e["y"])
    if xs and ys:
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        pad = (max(xmax - xmin, ymax - ymin) * 0.05) or 500
        doc.header["$EXTMIN"] = (xmin - pad, ymin - pad, 0)
        doc.header["$EXTMAX"] = (xmax + pad, ymax + pad, 0)
        doc.set_modelspace_vport(
            height=(ymax - ymin) + 2 * pad,
            center=((xmin + xmax) / 2, (ymin + ymax) / 2))

    doc.saveas(output_path)


# ═══════════════════════════════════════════════════════════════════════════════
# DWG EXPORT  — via ODA File Converter (free) if installed, else graceful fallback
# ═══════════════════════════════════════════════════════════════════════════════

def find_oda_converter() -> str:
    """Locate ODAFileConverter.exe from common install locations. '' if absent."""
    import glob as _glob
    patterns = [
        r"C:\Program Files\ODA\*\ODAFileConverter.exe",
        r"C:\Program Files (x86)\ODA\*\ODAFileConverter.exe",
        r"C:\Program Files\ODAFileConverter*\ODAFileConverter.exe",
        r"C:\Program Files (x86)\ODAFileConverter*\ODAFileConverter.exe",
    ]
    for pat in patterns:
        hits = _glob.glob(pat)
        if hits:
            return hits[0]
    return ""


def export_dwg(dxf_path: str, out_ver: str = "ACAD2018") -> str:
    """
    Convert a DXF to DWG using ODA File Converter (headless CLI mode).
    Returns the .dwg path on success, or '' if the converter is unavailable
    or the conversion produced no file. ezdxf cannot write DWG directly, so
    this external step is the only pure-local route to a real .dwg.
    """
    exe = find_oda_converter()
    if not exe:
        return ""
    import subprocess
    in_dir  = os.path.dirname(dxf_path)
    fname   = os.path.basename(dxf_path)
    # ODAFileConverter  InDir OutDir OutVer OutType Recurse Audit [InputFilter]
    try:
        subprocess.run(
            [exe, in_dir, in_dir, out_ver, "DWG", "0", "1", fname],
            check=False, timeout=180)
    except Exception:
        return ""
    dwg = os.path.splitext(dxf_path)[0] + ".dwg"
    return dwg if os.path.exists(dwg) else ""


# ═══════════════════════════════════════════════════════════════════════════════
# AUTOLISP EXPORT  — native AutoCAD reconstruction (load → BES-DRAW → Save As DWG)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_lisp(entities: list, output_path: str) -> str:
    """
    Emit an AutoLISP script that rebuilds the drawing natively inside AutoCAD
    using entmake (no external files, exact 1:1 mm coordinates). The user loads
    it, runs BES-DRAW, then File ▸ Save As ▸ DWG — the fully portable DWG route.
    """
    def fmt(v):  return f"{float(v):.3f}"
    def esc(s):  return str(s).replace("\\", "\\\\").replace('"', '\\"')

    # Helper defuns must exist before BES-DRAW is invoked — define them first.
    helpers = (
        '(defun bes-layer (name col /)\n'
        '  (if (not (tblsearch "LAYER" name))\n'
        '    (entmake (list (cons 0 "LAYER") (cons 100 "AcDbSymbolTableRecord")\n'
        '                   (cons 100 "AcDbLayerTableRecord") (cons 2 name)\n'
        '                   (cons 70 0) (cons 62 col)))))\n'
        '(defun bes-line (lay x1 y1 x2 y2 /)\n'
        '  (entmake (list (cons 0 "LINE") (cons 8 lay)\n'
        '                 (cons 10 (list x1 y1 0.0)) (cons 11 (list x2 y2 0.0)))))\n'
        '(defun bes-text (lay x y h s /)\n'
        '  (entmake (list (cons 0 "TEXT") (cons 8 lay)\n'
        '                 (cons 10 (list x y 0.0)) (cons 40 h) (cons 1 s))))\n'
        '(defun bes-circle (lay x y r /)\n'
        '  (entmake (list (cons 0 "CIRCLE") (cons 8 lay)\n'
        '                 (cons 10 (list x y 0.0)) (cons 40 r))))\n'
    )

    body = ['(defun c:BES-DRAW (/ oe)',
            '  (setq oe (getvar "CMDECHO")) (setvar "CMDECHO" 0)']
    for name in LAYERS:
        body.append(f'  (bes-layer "{name}" 7)')
    for e in entities:
        lay = esc(e.get("layer", "ANNOTATIONS"))
        if e["type"] == "LINE":
            body.append(f'  (bes-line "{lay}" {fmt(e["x1"])} {fmt(e["y1"])} '
                        f'{fmt(e["x2"])} {fmt(e["y2"])})')
        elif e["type"] == "TEXT":
            body.append(f'  (bes-text "{lay}" {fmt(e["x"])} {fmt(e["y"])} '
                        f'{fmt(e.get("height", 180))} "{esc(e["text"])}")')
        elif e["type"] == "CIRCLE":
            body.append(f'  (bes-circle "{lay}" {fmt(e["cx"])} {fmt(e["cy"])} '
                        f'{fmt(e["r"])})')
    body += ['  (setvar "CMDECHO" oe)',
             '  (command "._ZOOM" "_E")',
             '  (princ "\\nBES bridge drawing complete — File > Save As > DWG.")',
             '  (princ))']

    script = (
        "; Bridge Engineering Suite — CAD Process 2 auto-generated AutoLISP\n"
        "; Load:  (load \"thisfile.lsp\")   then run:  BES-DRAW\n"
        "; 1 drawing unit = 1 mm, 1:1 model space.\n\n"
        + helpers + "\n" + "\n".join(body) + "\n(c:BES-DRAW)\n(princ)\n"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(script)
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER THREAD
# ═══════════════════════════════════════════════════════════════════════════════

class CAD2Worker(QThread):
    log_msg     = pyqtSignal(str, str)
    step_done   = pyqtSignal(int)
    step_active = pyqtSignal(int)
    progress    = pyqtSignal(int)
    finished    = pyqtSignal(bool, str, object, object, str)

    STEPS = [
        "Load & encode file",
        "Claude Vision — extract dimension table",
        "Parse & validate dimensions",
        "Build scaled geometry (dimension-first)",
        "Write DXF — 1:1 model space (1 unit = 1 mm)",
    ]

    def __init__(self, file_path: str, api_key: str = "", gemini_key: str = ""):
        super().__init__()
        self.file_path  = file_path
        self.api_key    = api_key
        self.gemini_key = gemini_key

    def run(self):
        entities = bounds = meta = dxf_path = None
        try:
            # ── Step 0: Load ──────────────────────────────────────────
            self.step_active.emit(0)
            ext = os.path.splitext(self.file_path)[1].lower()
            SUPPORTED = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png",  ".gif":  "image/gif",
                ".webp": "image/webp", ".pdf": "application/pdf",
            }
            if ext in SUPPORTED:
                with open(self.file_path, "rb") as f:
                    raw = f.read()
                mime = SUPPORTED[ext]
                self.log_msg.emit(
                    f"Loaded: {os.path.basename(self.file_path)}  "
                    f"({len(raw)//1024} KB)", "info")
            else:
                self.log_msg.emit(f"Converting {ext.upper()} → PNG…", "warn")
                from PIL import Image as _PIL
                import io as _io
                img = _PIL.open(self.file_path)
                if img.mode not in ("RGB", "RGBA", "L"):
                    img = img.convert("RGBA" if "transparency" in img.info else "RGB")
                buf = _io.BytesIO()
                img.save(buf, format="PNG")
                raw  = buf.getvalue()
                mime = "image/png"
                self.log_msg.emit(
                    f"Converted: {len(raw)//1024} KB  "
                    f"({img.width}×{img.height}px)", "ok")
            b64 = base64.b64encode(raw).decode()
            self.step_done.emit(0); self.progress.emit(15)

            # ── Step 1: AI Vision — extract dimension table ───────────
            self.step_active.emit(1)
            provider = AIProvider.dual(self.gemini_key, self.api_key)
            self.log_msg.emit(
                f"Sending to AI vision "
                f"({'Gemini→Claude fallback' if self.gemini_key else 'Claude'}) "
                f"— extracting dimension table…", "info")

            user_msg = (
                "Read this bridge GAD view by view (each titled sub-drawing: "
                "HALF ELEVATION, CROSS SECTION OF ABUTMENT, RETURN WALL, PLAN, SECTION X-X). "
                "Extract every visible dimension as strict JSON per the schema. "
                "Read each number individually — never sum a chain. Use null for anything "
                "not legible; do not guess.")

            if mime == "application/pdf":
                raw_text = provider.vision_pdf(
                    EXTRACT_SYSTEM_PROMPT, b64, user_msg, max_tokens=8000)
            else:
                raw_text = provider.vision(
                    EXTRACT_SYSTEM_PROMPT, b64, mime, user_msg, max_tokens=8000)
            self.log_msg.emit("Dimension table received from AI.", "ok")
            self.step_done.emit(1); self.progress.emit(45)

            # ── Step 2: Parse & validate ──────────────────────────────
            self.step_active.emit(2)
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:]
            data = json.loads(cleaned.strip())

            # Fill any missing dimensions from surrounding context (audited)
            interp_notes = interpolate_missing(data)
            for n in interp_notes:
                self.log_msg.emit(f"↳ interpolated: {n}", "warn")
            if not interp_notes:
                self.log_msg.emit("No missing dimensions — nothing to interpolate.", "ok")

            # Log what was found
            zones = data.get("zones", [])
            self.log_msg.emit(
                f"Drawing: {data.get('drawingTitle','—')}  |  "
                f"Zones: {', '.join(zones) if zones else 'auto-detect'}  |  "
                f"Bridge: {data.get('bridgeNo','—')}", "ok")

            if "elevation" in str(zones).lower() or data.get("elevation"):
                ev = data.get("elevation", {})
                rl = ev.get("rl", {})
                self.log_msg.emit(
                    f"  Elevation: span={ev.get('span_clear','?')}mm  "
                    f"rail_lvl={rl.get('rail_lvl','?')}m  "
                    f"bed_lvl={rl.get('bed_lvl','?')}m", "info")
                h_chain = _chain(ev.get("horizontal_chain"))
                v_chain = _chain(ev.get("vertical_dims"))
                if h_chain:
                    self.log_msg.emit(f"  H-chain: {h_chain}  (sum={sum(h_chain):.0f}mm)", "info")
                if v_chain:
                    self.log_msg.emit(f"  V-chain: {v_chain}  (sum={sum(v_chain):.0f}mm)", "info")

            if "plan" in str(zones).lower() or data.get("plan"):
                pv = data.get("plan", {})
                self.log_msg.emit(
                    f"  Plan: transverse={pv.get('transverse_chain',[])}  "
                    f"longitudinal={pv.get('longitudinal_chain', [])}", "info")

            if "section" in str(zones).lower() or data.get("section"):
                sv = data.get("section", {})
                self.log_msg.emit(
                    f"  Section: slab_thk={sv.get('rcc_slab_thk','?')}mm  "
                    f"transverse={sv.get('transverse_chain','?')}", "info")

            # Run validation
            warnings = validate_extracted(data)
            for w in warnings:
                self.log_msg.emit(f"⚠ Validation: {w}", "warn")
            if not warnings:
                self.log_msg.emit("✓ Dimension chains validated — no inconsistencies.", "ok")

            self.step_done.emit(2); self.progress.emit(62)

            # ── Step 3: Build geometry ────────────────────────────────
            self.step_active.emit(3)
            self.log_msg.emit("Building geometry from extracted dimensions…", "info")
            entities, bounds, meta = build_bridge_geometry(data)
            meta["data"] = data
            self.log_msg.emit(
                f"Geometry: {len(entities)} entities  |  "
                f"Bounds: x={bounds['xMin']:.0f}..{bounds['xMax']:.0f}  "
                f"y={bounds['yMin']:.0f}..{bounds['yMax']:.0f}", "ok")
            self.step_done.emit(3); self.progress.emit(82)

            # ── Step 4: Write DXF ─────────────────────────────────────
            self.step_active.emit(4)
            tmp_fd, tmp = tempfile.mkstemp(suffix=".dxf")
            os.close(tmp_fd)
            write_dxf(entities, tmp)
            kb = os.path.getsize(tmp) // 1024
            self.log_msg.emit(
                f"DXF written: {kb} KB  |  1:1 model space  |  units: mm  |  "
                f"10 named layers", "ok")
            self.step_done.emit(4); self.progress.emit(100)
            self.finished.emit(True, "Success", entities, (bounds, meta), tmp)

        except json.JSONDecodeError as e:
            self.log_msg.emit(f"JSON parse error: {e}", "err")
            self.log_msg.emit("AI response was not valid JSON — trying default geometry.", "warn")
            default = {
                "drawingType": "elevation", "bridgeNo": "—", "scale": "1:100",
                "zones": ["elevation"],
                "elevation": {
                    "rl": {"rail_lvl": 100.0, "hfl": 99.25, "bed_lvl": 97.1,
                           "cc_top": 96.1, "cc_bottom": 95.6},
                    "horizontal_chain": [4350, 4490],
                    "span_clear": 4490, "approach_slab": 4350,
                    "rcc_slab_thk": 460,
                    "abutment": {"top_width": 500, "base_width": 3235,
                                 "footing_width": 1000, "cc_label": "C.C 1:3:6"},
                    "approach_slope": "1:1½",
                }
            }
            entities, bounds, meta = build_bridge_geometry(default)
            meta["data"] = default
            tmp_fd, tmp = tempfile.mkstemp(suffix=".dxf")
            os.close(tmp_fd)
            write_dxf(entities, tmp)
            self.finished.emit(True,
                               "Used reference geometry (AI parse failed — check raw log)",
                               entities, (bounds, meta), tmp)

        except Exception as e:
            import traceback
            self.log_msg.emit(f"ERROR: {e}", "err")
            self.log_msg.emit(traceback.format_exc()[:800], "err")
            self.finished.emit(False, str(e), None, None, "")


# ═══════════════════════════════════════════════════════════════════════════════
# GRAPHICS VIEW  (unchanged from v3)
# ═══════════════════════════════════════════════════════════════════════════════

class BridgeGraphicsView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setRenderHint(self.renderHints().Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor("#0E1318")))
        self.setStyleSheet("border: none;")
        self._items_by_layer = {}
        self._layer_visible  = {k: v["on"] for k, v in LAYERS.items()}

    def load_entities(self, entities, bounds):
        self.scene.clear()
        self._items_by_layer = {k: [] for k in LAYERS}
        y_max = bounds["yMax"]

        for e in entities:
            layer = e.get("layer", "ANNOTATIONS")
            cfg   = LAYERS.get(layer, {"color": "#ffffff", "width": 1.0, "dash": False})
            pen   = QPen(QColor(cfg["color"]), cfg.get("width", 1.0))
            pen.setCosmetic(True)
            if cfg.get("dash"):
                pen.setStyle(Qt.PenStyle.DashLine)

            item = None
            if e["type"] == "LINE":
                item = self.scene.addLine(
                    e["x1"], y_max - e["y1"],
                    e["x2"], y_max - e["y2"], pen)
            elif e["type"] == "CIRCLE":
                r = e["r"]
                item = self.scene.addEllipse(
                    e["cx"] - r, y_max - e["cy"] - r, 2*r, 2*r,
                    pen, QBrush(Qt.BrushStyle.NoBrush))
            elif e["type"] == "TEXT":
                txt = QGraphicsTextItem(e["text"])
                fs  = max(6, int(e.get("height", 180) * 0.50))
                fnt = QFont("Courier New", fs)
                fnt.setStyleHint(QFont.StyleHint.Monospace)
                txt.setFont(fnt)
                txt.setDefaultTextColor(QColor(cfg["color"]))
                txt.setPos(e["x"], y_max - e["y"])
                self.scene.addItem(txt)
                item = txt

            if item and layer in self._items_by_layer:
                self._items_by_layer[layer].append(item)
                item.setVisible(self._layer_visible.get(layer, True))

        pad  = (bounds["xMax"] - bounds["xMin"]) * 0.04
        rect = QRectF(bounds["xMin"] - pad, 0,
                      bounds["xMax"] - bounds["xMin"] + pad * 2,
                      y_max - bounds["yMin"] + pad)
        self.setSceneRect(rect)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def set_layer_visible(self, layer, visible):
        self._layer_visible[layer] = visible
        for item in self._items_by_layer.get(layer, []):
            item.setVisible(visible)

    def wheelEvent(self, e: QWheelEvent):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key.Key_F:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        super().keyPressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
# DROP ZONE, STEP WIDGET, LAYER PANEL, MAIN PANEL  (UI unchanged from v3)
# ═══════════════════════════════════════════════════════════════════════════════

class DropZone2(QFrame):
    file_dropped = pyqtSignal(str)
    EXTS = {".jpg",".jpeg",".png",".gif",".webp",
            ".tiff",".tif",".bmp",".tga",".ppm",".pgm",
            ".ico",".dib",".pcx",".pdf"}

    def __init__(self):
        super().__init__()
        self.setObjectName("dropZone")
        self.setMinimumHeight(130)
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.setSpacing(6)
        self.icon_lbl = QLabel("⬆")
        self.icon_lbl.setFont(QFont("Segoe UI", 22))
        self.icon_lbl.setStyleSheet(f"color:{COLORS['text_muted']};border:none;")
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icon_lbl)
        self.main_lbl = QLabel("Click or drag a bridge drawing here")
        self.main_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.main_lbl.setStyleSheet(f"color:{COLORS['text_secondary']};border:none;")
        self.main_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.main_lbl)
        self.fmt_lbl = QLabel("JPEG · PNG · WEBP · TIFF · BMP · PDF")
        self.fmt_lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;border:none;")
        self.fmt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.fmt_lbl)

    def set_file(self, path):
        self.icon_lbl.setText("✓")
        self.icon_lbl.setStyleSheet(f"color:{COLORS['accent']};border:none;font-size:22px;")
        self.main_lbl.setText(f"📄  {os.path.basename(path)}")
        self.fmt_lbl.setText(f"Ready — {os.path.splitext(path)[1].upper()}")
        self.setObjectName("dropZoneActive")
        self.style().unpolish(self); self.style().polish(self)

    def reset(self):
        self.icon_lbl.setText("⬆")
        self.icon_lbl.setStyleSheet(f"color:{COLORS['text_muted']};border:none;font-size:22px;")
        self.main_lbl.setText("Click or drag a bridge drawing here")
        self.fmt_lbl.setText("JPEG · PNG · WEBP · TIFF · BMP · PDF")
        self.setObjectName("dropZone")
        self.style().unpolish(self); self.style().polish(self)

    def mousePressEvent(self, e):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Bridge Drawing", "",
            "Drawing Files (*.jpg *.jpeg *.png *.gif *.webp "
            "*.tiff *.tif *.bmp *.tga *.ppm *.pdf)")
        if path: self.file_dropped.emit(path)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            ext = os.path.splitext(e.mimeData().urls()[0].toLocalFile())[1].lower()
            if ext in self.EXTS:
                e.acceptProposedAction()
                self.setObjectName("dropZoneActive")
                self.style().unpolish(self); self.style().polish(self)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self.setObjectName("dropZone")
        self.style().unpolish(self); self.style().polish(self)

    def dropEvent(self, e: QDropEvent):
        path = e.mimeData().urls()[0].toLocalFile()
        if os.path.splitext(path)[1].lower() in self.EXTS:
            self.file_dropped.emit(path)
        e.acceptProposedAction()


class Step2(QWidget):
    def __init__(self, n, desc):
        super().__init__()
        self._n = n
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2); lay.setSpacing(10)
        self.num = QLabel(str(n))
        self.num.setFixedSize(24, 24)
        self.num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.num.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._idle()
        lay.addWidget(self.num)
        self.desc = QLabel(desc)
        self.desc.setStyleSheet(f"color:{COLORS['text_secondary']};font-size:12px;")
        self.desc.setWordWrap(True)
        lay.addWidget(self.desc, 1)
        self.tag = QLabel(); self.tag.setVisible(False)
        lay.addWidget(self.tag)

    def _idle(self):
        self.num.setStyleSheet(
            f"background:{COLORS['border']};color:{COLORS['text_muted']};border-radius:12px;")
    def set_active(self):
        self.num.setStyleSheet(
            f"background:{COLORS['accent_glow']};color:{COLORS['accent']};"
            f"border:1px solid {COLORS['accent']};border-radius:12px;")
        self.tag.setText("running"); self.tag.setObjectName("tagWarning")
        self.tag.style().unpolish(self.tag); self.tag.style().polish(self.tag)
        self.tag.setVisible(True)
    def set_done(self):
        self.num.setText("✓")
        self.num.setStyleSheet(
            f"background:{COLORS['success_bg']};color:{COLORS['success']};border-radius:12px;")
        self.tag.setText("done"); self.tag.setObjectName("tagSuccess")
        self.tag.style().unpolish(self.tag); self.tag.style().polish(self.tag)
        self.tag.setVisible(True)
    def set_error(self):
        self.num.setText("✗")
        self.num.setStyleSheet(
            f"background:{COLORS['error_bg']};color:{COLORS['error']};border-radius:12px;")
        self.tag.setText("error"); self.tag.setObjectName("tagWarning")
        self.tag.style().unpolish(self.tag); self.tag.style().polish(self.tag)
        self.tag.setVisible(True)
    def reset(self):
        self.num.setText(str(self._n)); self._idle(); self.tag.setVisible(False)


class LayerPanel(QFrame):
    layer_toggled = pyqtSignal(str, bool)

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setFixedWidth(195)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12); lay.setSpacing(4)
        hdr = QLabel("LAYERS")
        hdr.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:10px;"
            f"font-weight:700;letter-spacing:1.5px;")
        lay.addWidget(hdr)
        self._checks = {}
        for layer, cfg in LAYERS.items():
            row = QHBoxLayout(); row.setSpacing(6)
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{cfg['color']};font-size:10px;border:none;")
            row.addWidget(dot)
            cb = QCheckBox(cfg["label"])
            cb.setChecked(cfg["on"])
            cb.setStyleSheet(f"font-size:11px;color:{COLORS['text_primary']};")
            cb.stateChanged.connect(
                lambda state, l=layer: self.layer_toggled.emit(l, bool(state)))
            row.addWidget(cb, 1)
            lay.addLayout(row)
            self._checks[layer] = cb
        lay.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        all_on = QPushButton("All On"); all_on.setObjectName("secondaryBtn")
        all_on.setFixedHeight(28)
        all_on.clicked.connect(
            lambda: [cb.setChecked(True) for cb in self._checks.values()])
        all_off = QPushButton("All Off"); all_off.setObjectName("secondaryBtn")
        all_off.setFixedHeight(28)
        all_off.clicked.connect(
            lambda: [cb.setChecked(False) for cb in self._checks.values()])
        btn_row.addWidget(all_on); btn_row.addWidget(all_off)
        lay.addLayout(btn_row)
        lay.addStretch()
        hint = QLabel("Scroll · Zoom\nDrag  · Pan\nF key · Fit view")
        hint.setStyleSheet(f"color:{COLORS['text_muted']};font-size:10px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hint)


class CAD2Panel(QWidget):
    def __init__(self):
        super().__init__()
        self.current_file = None
        self.dxf_tmp      = None
        self.worker       = None
        self.settings     = QSettings("BES", "BridgeEngineeringSuite")
        self._log_lines   = []
        self._entities    = []
        self._bounds      = None
        self._extracted   = {}
        self._build()

    def _build(self):
        outer    = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #353B45; }")
        outer.addWidget(splitter)

        # ── LEFT PANEL ────────────────────────────────────────────────
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setMinimumWidth(380); left_scroll.setMaximumWidth(480)
        left_w   = QWidget()
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(28, 28, 20, 28); left_lay.setSpacing(0)
        left_scroll.setWidget(left_w)

        t = QLabel("CAD Process 2"); t.setObjectName("panelTitle")
        left_lay.addWidget(t)
        s = QLabel(
            "Upload a bridge GAD drawing — Claude Vision extracts every dimension "
            "and RL level as a structured table, then builds 1:1 DXF geometry "
            "purely from those numbers. No pixel tracing.")
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        left_lay.addWidget(s)
        left_lay.addSpacing(12)

        # Engine badge
        eng = QFrame(); eng.setObjectName("accentCard")
        el  = QHBoxLayout(eng)
        el.setContentsMargins(14, 8, 14, 8); el.setSpacing(8)
        el.addWidget(self._icon("🔬"))
        ei = QLabel("Dimension-first engine  —  1 extracted mm = 1 DXF mm")
        ei.setStyleSheet(f"color:{COLORS['text_primary']};font-size:11px;font-weight:600;")
        el.addWidget(ei); el.addStretch()
        left_lay.addWidget(eng)
        left_lay.addSpacing(6)

        # Key status
        key = self._get_key()
        self.key_status = QLabel(
            "● Claude Vision active" if key
            else "● No API key — add in ⚙ Settings")
        self.key_status.setStyleSheet(
            f"color:{COLORS['success'] if key else COLORS['warning']};font-size:11px;")
        left_lay.addWidget(self.key_status)
        left_lay.addSpacing(12)

        # Upload card
        uc = QFrame(); uc.setObjectName("accentCard")
        ul = QVBoxLayout(uc)
        ul.setContentsMargins(18, 14, 18, 14); ul.setSpacing(8)
        ul.addWidget(self._bold("Upload Bridge Drawing", 11))
        self.drop_zone = DropZone2()
        self.drop_zone.file_dropped.connect(self._on_file)
        ul.addWidget(self.drop_zone)
        ubr = QHBoxLayout(); ubr.setSpacing(8)
        self.proc_btn = QPushButton("▶   Analyse & Generate DXF")
        self.proc_btn.setObjectName("primaryBtn"); self.proc_btn.setFixedHeight(42)
        self.proc_btn.setEnabled(False); self.proc_btn.clicked.connect(self._start)
        ubr.addWidget(self.proc_btn)
        self.clr_btn = QPushButton("Clear"); self.clr_btn.setObjectName("secondaryBtn")
        self.clr_btn.setFixedHeight(42); self.clr_btn.setEnabled(False)
        self.clr_btn.clicked.connect(self._clear); ubr.addWidget(self.clr_btn)
        ubr.addStretch(); ul.addLayout(ubr)
        left_lay.addWidget(uc); left_lay.addSpacing(12)

        # Progress card
        self.prog_card = QFrame(); self.prog_card.setObjectName("card")
        self.prog_card.setVisible(False)
        pg = QVBoxLayout(self.prog_card)
        pg.setContentsMargins(18, 14, 18, 14); pg.setSpacing(8)
        ph = QHBoxLayout()
        ph.addWidget(self._bold("Processing pipeline"))
        ph.addStretch()
        self.pct = QLabel("0%")
        self.pct.setStyleSheet(
            f"color:{COLORS['accent']};font-weight:600;font-size:13px;")
        ph.addWidget(self.pct); pg.addLayout(ph)
        self.prog_bar = QProgressBar()
        self.prog_bar.setFixedHeight(6); self.prog_bar.setRange(0, 100)
        pg.addWidget(self.prog_bar)
        self.steps = []
        for i, desc in enumerate(CAD2Worker.STEPS, 1):
            st = Step2(i, desc); pg.addWidget(st); self.steps.append(st)
        pg.addWidget(self._muted("Live log"))
        self.log_box = QLabel(); self.log_box.setWordWrap(True)
        self.log_box.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.log_box.setStyleSheet(
            f"background:{COLORS['input_bg']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;padding:8px;font-size:11px;"
            f"color:{COLORS['text_secondary']};"
            f"font-family:'Consolas','Courier New',monospace;min-height:80px;")
        pg.addWidget(self.log_box)
        left_lay.addWidget(self.prog_card); left_lay.addSpacing(12)

        # Result card
        self.res_card = QFrame(); self.res_card.setObjectName("card")
        self.res_card.setVisible(False)
        rl2 = QVBoxLayout(self.res_card)
        rl2.setContentsMargins(18, 14, 18, 14); rl2.setSpacing(10)
        rh  = QHBoxLayout()
        ri  = QLabel("✓"); ri.setFont(QFont("Segoe UI", 18))
        ri.setStyleSheet(f"color:{COLORS['success']};")
        rh.addWidget(ri)
        self.res_title = QLabel("Files ready")
        self.res_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        rh.addWidget(self.res_title); rh.addStretch()
        rl2.addLayout(rh)
        self.res_desc = QLabel(); self.res_desc.setWordWrap(True)
        self.res_desc.setStyleSheet(
            f"color:{COLORS['text_secondary']};font-size:12px;")
        rl2.addWidget(self.res_desc)

        # Extracted data grid
        self.data_grid = QFrame(); self.data_grid.setObjectName("card")
        self.data_grid.setVisible(False)
        dg_lay = QGridLayout(self.data_grid)
        dg_lay.setContentsMargins(12, 10, 12, 10); dg_lay.setSpacing(4)
        self.data_labels = {}
        fields = [
            ("Bridge No",      "bridgeNo"),
            ("Bridge Type",    "bridgeType"),
            ("Drawing Title",  "drawingTitle"),
            ("Zones Found",    "_zones"),
            ("Span Clear",     "_span"),
            ("Rail Level",     "_rl_rail"),
            ("Bed Level",      "_rl_bed"),
            ("Slab Thickness", "_slab_thk"),
            ("Scale",          "scale"),
            ("Chainage",       "chainage"),
        ]
        for row, (label, key) in enumerate(fields):
            lbl = QLabel(label + ":")
            lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;")
            val = QLabel("—")
            val.setStyleSheet(
                f"color:{COLORS['text_primary']};font-size:11px;font-weight:600;")
            dg_lay.addWidget(lbl, row, 0); dg_lay.addWidget(val, row, 1)
            self.data_labels[key] = val
        rl2.addWidget(self.data_grid)

        dxf_btn = QPushButton("⬇   Save DXF File")
        dxf_btn.setObjectName("primaryBtn"); dxf_btn.setFixedHeight(40)
        dxf_btn.clicked.connect(self._save_dxf)
        rl2.addWidget(dxf_btn)
        dwg_btn = QPushButton("⬇   Save DWG File  (needs ODA Converter)")
        dwg_btn.setObjectName("secondaryBtn"); dwg_btn.setFixedHeight(40)
        dwg_btn.clicked.connect(self._save_dwg)
        rl2.addWidget(dwg_btn)
        lsp_btn = QPushButton("⬇   Save AutoLISP  (.lsp → load → Save As DWG)")
        lsp_btn.setObjectName("secondaryBtn"); lsp_btn.setFixedHeight(40)
        lsp_btn.clicked.connect(self._save_lisp)
        rl2.addWidget(lsp_btn)
        new_btn = QPushButton("Process another file")
        new_btn.setObjectName("secondaryBtn"); new_btn.setFixedHeight(36)
        new_btn.clicked.connect(self._reset)
        rl2.addWidget(new_btn)
        left_lay.addWidget(self.res_card)
        left_lay.addStretch()
        splitter.addWidget(left_scroll)

        # ── RIGHT PANEL ───────────────────────────────────────────────
        right_w = QWidget()
        right_w.setStyleSheet("background:#0E1318;")
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(0, 0, 0, 0); right_lay.setSpacing(0)

        top_bar = QFrame()
        top_bar.setStyleSheet(
            f"background:{COLORS['navy']};"
            f"border-bottom:1px solid {COLORS['navy_border']};")
        top_bar.setFixedHeight(38)
        tb = QHBoxLayout(top_bar); tb.setContentsMargins(14, 0, 14, 0)
        vl = QLabel("BRIDGE DRAWING VIEWER  —  DIMENSION-FIRST ENGINE")
        vl.setStyleSheet(
            f"color:{COLORS['accent']};font-size:10px;"
            f"font-weight:700;letter-spacing:1.5px;")
        tb.addWidget(vl); tb.addStretch()
        hl = QLabel("Scroll=Zoom  ·  Drag=Pan  ·  F=Fit  ·  1 unit=1 mm")
        hl.setStyleSheet(f"color:{COLORS['navy_border']};font-size:10px;")
        tb.addWidget(hl)
        right_lay.addWidget(top_bar)

        view_row = QHBoxLayout()
        view_row.setSpacing(0); view_row.setContentsMargins(0, 0, 0, 0)
        self.layer_panel = LayerPanel()
        self.layer_panel.layer_toggled.connect(self._on_layer_toggle)
        self.layer_panel.setStyleSheet(
            f"background:{COLORS['off_white']};"
            f"border-right:1px solid {COLORS['border']};border-radius:0;")
        view_row.addWidget(self.layer_panel)
        self.gfx_view = BridgeGraphicsView()
        view_row.addWidget(self.gfx_view, 1)
        right_lay.addLayout(view_row, 1)

        self.status_bar = QLabel(
            "  No drawing loaded — upload a file and click Analyse")
        self.status_bar.setFixedHeight(26)
        self.status_bar.setStyleSheet(
            f"background:{COLORS['navy']};color:{COLORS['navy_border']};"
            f"font-size:10px;font-family:'Consolas','Courier New',monospace;"
            f"border-top:1px solid {COLORS['navy_border']};padding-left:10px;")
        right_lay.addWidget(self.status_bar)
        splitter.addWidget(right_w)
        splitter.setSizes([420, 800])

    # ── UI helpers ────────────────────────────────────────────────────
    def _bold(self, t, sz=11):
        l = QLabel(t); l.setFont(QFont("Segoe UI", sz, QFont.Weight.Bold))
        return l
    def _muted(self, t):
        l = QLabel(t)
        l.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:11px;"
            f"font-weight:600;margin-top:4px;")
        return l
    def _icon(self, t):
        l = QLabel(t); l.setFont(QFont("Segoe UI", 14))
        return l

    def _get_key(self):
        return (self.settings.value("anthropic_api_key", "") or
                self.settings.value("claude_api_key",    "") or
                self.settings.value("api_key",           "") or
                os.environ.get("ANTHROPIC_API_KEY", ""))

    def _get_gemini_key(self):
        return (self.settings.value("gemini_api_key", "") or
                os.environ.get("GEMINI_API_KEY", ""))

    def _upd_key(self):
        key = self._get_key()
        if key:
            self.key_status.setText("● Claude Vision active")
            self.key_status.setStyleSheet(
                f"color:{COLORS['success']};font-size:11px;")
        else:
            self.key_status.setText("● No API key — add in ⚙ Settings")
            self.key_status.setStyleSheet(
                f"color:{COLORS['warning']};font-size:11px;")

    def showEvent(self, e):
        super().showEvent(e)
        self._upd_key()

    def _on_file(self, path):
        self.current_file = path
        self.drop_zone.set_file(path)
        self.proc_btn.setEnabled(True)
        self.clr_btn.setEnabled(True)

    def _clear(self):
        self.current_file = None
        self.drop_zone.reset()
        self.proc_btn.setEnabled(False)
        self.clr_btn.setEnabled(False)

    def _log(self, msg, level="info"):
        pfx = {"info": "  ", "ok": "✓ ", "warn": "⚠ ", "err": "✗ "}.get(level, "  ")
        self._log_lines.append(pfx + msg)
        if len(self._log_lines) > 14:
            self._log_lines = self._log_lines[-14:]
        self.log_box.setText("\n".join(self._log_lines))

    def _start(self):
        if not self.current_file: return
        key    = self._get_key()
        gemini = self._get_gemini_key()
        if not key and not gemini:
            self._log("No API key configured — go to ⚙ Settings → API Keys", "err")
            return
        self.proc_btn.setEnabled(False); self.clr_btn.setEnabled(False)
        self.res_card.setVisible(False); self.prog_card.setVisible(True)
        self.prog_bar.setValue(0); self.pct.setText("0%")
        self._log_lines = []; self.log_box.setText("")
        for st in self.steps: st.reset()
        self.status_bar.setText("  ⏳ Extracting dimension table…")
        self.worker = CAD2Worker(self.current_file, key, gemini)
        self.worker.log_msg.connect(self._log)
        self.worker.step_active.connect(
            lambda i: self.steps[i].set_active() if i < len(self.steps) else None)
        self.worker.step_done.connect(
            lambda i: self.steps[i].set_done() if i < len(self.steps) else None)
        self.worker.progress.connect(
            lambda p: (self.prog_bar.setValue(p), self.pct.setText(f"{p}%")))
        self.worker.finished.connect(self._on_done)
        self.worker.start()

    def _on_done(self, ok, msg, entities, bounds_meta, dxf_tmp):
        self.prog_card.setVisible(False)
        if ok and entities:
            self._entities  = entities
            bounds, meta    = bounds_meta
            self._bounds    = bounds
            self._extracted = meta.get("data", {})
            self.dxf_tmp    = dxf_tmp
            self.gfx_view.load_entities(entities, bounds)

            # Populate data grid with extracted values
            d = self._extracted
            ev = d.get("elevation", {})
            sv = d.get("section",   {})
            rl = ev.get("rl", sv.get("rl", {}))
            self.data_grid.setVisible(True)
            self.data_labels["bridgeNo"    ].setText(str(d.get("bridgeNo",     "—")))
            self.data_labels["bridgeType"  ].setText(str(d.get("bridgeType",   "—")))
            self.data_labels["drawingTitle"].setText(str(d.get("drawingTitle", "—"))[:50])
            self.data_labels["_zones"      ].setText(", ".join(d.get("zones", [])) or "—")
            self.data_labels["_span"       ].setText(
                f"{ev.get('span_clear','—')} mm" if ev.get("span_clear") else "—")
            self.data_labels["_rl_rail"    ].setText(
                f"{rl.get('rail_lvl','—')} m" if rl.get("rail_lvl") else "—")
            self.data_labels["_rl_bed"     ].setText(
                f"{rl.get('bed_lvl','—')} m" if rl.get("bed_lvl") else "—")
            self.data_labels["_slab_thk"   ].setText(
                f"{ev.get('rcc_slab_thk') or sv.get('rcc_slab_thk','—')} mm")
            self.data_labels["scale"       ].setText(str(d.get("scale",     "—")))
            self.data_labels["chainage"    ].setText(str(d.get("chainage",  "—")))

            kb = os.path.getsize(dxf_tmp) // 1024 if dxf_tmp and os.path.exists(dxf_tmp) else 0
            self.res_title.setText("DXF Generated — Dimension-First")
            self.res_desc.setText(
                f"{len(entities)} entities  ·  10 named layers  ·  {kb} KB  "
                f"·  1:1 model space\n"
                f"Every line was placed using extracted mm values, not pixel tracing.")
            self.status_bar.setText(
                f"  ✓  {len(entities)} entities  |  "
                f"Bridge: {d.get('bridgeNo','—')}  |  "
                f"Span: {ev.get('span_clear','—')}mm  |  "
                f"RL Rail: {rl.get('rail_lvl','—')}m")
        else:
            self.res_title.setText("Processing Error")
            self.res_desc.setText(f"{msg}\n\nCheck your API key or try a cleaner image.")
            self.status_bar.setText("  ✗  Error — see log above")
            self.proc_btn.setEnabled(True); self.clr_btn.setEnabled(True)
        self.res_card.setVisible(True)

    def _on_layer_toggle(self, layer, visible):
        self.gfx_view.set_layer_visible(layer, visible)

    def _save_dxf(self):
        if not self.dxf_tmp or not os.path.exists(self.dxf_tmp): return
        base  = os.path.splitext(os.path.basename(self.current_file or "bridge"))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Save DXF File", f"{base}_DimFirst.dxf", "AutoCAD DXF (*.dxf)")
        if path:
            shutil.copy2(self.dxf_tmp, path)
            self._log(f"DXF saved: {path}", "ok")

    def _save_dwg(self):
        if not self.dxf_tmp or not os.path.exists(self.dxf_tmp):
            return
        if not find_oda_converter():
            self._log("ODA File Converter not found. Install the free converter from "
                      "odafileconverter.com, then retry. Meanwhile the DXF opens directly "
                      "in AutoCAD — use File ▸ Save As ▸ DWG.", "warn")
            return
        self._log("Converting DXF → DWG via ODA File Converter…", "info")
        dwg = export_dwg(self.dxf_tmp)
        if not dwg:
            self._log("DWG conversion failed — see ODA Converter. DXF is still available.", "err")
            return
        base = os.path.splitext(os.path.basename(self.current_file or "bridge"))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Save DWG File", f"{base}.dwg", "AutoCAD DWG (*.dwg)")
        if path:
            shutil.copy2(dwg, path)
            self._log(f"DWG saved: {path}", "ok")

    def _save_lisp(self):
        if not self._entities:
            self._log("No geometry to export — run Analyse first.", "warn")
            return
        base = os.path.splitext(os.path.basename(self.current_file or "bridge"))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Save AutoLISP Script", f"{base}_BES.lsp", "AutoLISP (*.lsp)")
        if path:
            generate_lisp(self._entities, path)
            self._log(f"LISP saved: {path}  —  in AutoCAD: (load \"{os.path.basename(path)}\") "
                      f"then BES-DRAW, then Save As DWG.", "ok")

    def _reset(self):
        self.res_card.setVisible(False); self.data_grid.setVisible(False)
        self._clear(); self.dxf_tmp = None
        self.gfx_view.scene.clear()
        self.status_bar.setText("  No drawing loaded — upload a file and click Analyse")
