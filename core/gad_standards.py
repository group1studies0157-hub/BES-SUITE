"""
GAD span-type catalogue.

Seed data comes from the standard documentation / reference GAD set
(H:\\OFFICE WORK\\Standard documentation\\RDSO DRAWINGS and F:\\Project B\\completed):
RCC boxes, PSC slabs (3.05 / 6.1 / 9.15 / 12.2 m), PSC / box / steel girders,
and foot-over-bridges. Each entry carries engineering *defaults* (depths, deck
widths, thicknesses) plus the standard-drawing reference to quote in notes.

Values are sensible Indian-Railways order-of-magnitude defaults — edit freely
to match your section's approved standard drawings. The generator applies them
only where the user has not given an explicit value, so a prompt always wins.
"""

from __future__ import annotations

from typing import Optional

# family -> view template used by the generator
FAMILY_RCC_BOX = "rcc_box"
FAMILY_PSC_SLAB = "psc_slab"
FAMILY_PSC_GIRDER = "psc_girder"
FAMILY_BOX_GIRDER = "box_girder"
FAMILY_STEEL_GIRDER = "steel_girder"
FAMILY_FOB = "fob"

FAMILIES = (FAMILY_RCC_BOX, FAMILY_PSC_SLAB, FAMILY_PSC_GIRDER,
            FAMILY_BOX_GIRDER, FAMILY_STEEL_GIRDER, FAMILY_FOB)

SPAN_TYPES: dict = {
    # ── RCC box (vent) ─────────────────────────────────────────────────────
    "rcc_box": {
        "key": "rcc_box", "family": FAMILY_RCC_BOX,
        "label": "RCC Box (vent)",
        "rdso_ref": "",
        "slab_thk_mm": 350, "wall_thk_mm": 350,
        "deck_width_mm": 6200, "default_clear_height_mm": 1500,
        "notes": ["RCC BOX AS PER DESIGN.",
                  "WEEP HOLES & BACK FILLING BEHIND ABUTMENT AND RETURNS AS PER STANDARD DRAWING."],
    },
    # ── PSC slabs ──────────────────────────────────────────────────────────
    "psc_slab_3.05": {
        "key": "psc_slab_3.05", "family": FAMILY_PSC_SLAB, "label": "PSC Slab 3.05 m",
        "rdso_ref": "RDSO B-10221 (3.05 m 25T PSC slab)",
        "girder_depth_mm": 450, "deck_width_mm": 6200,
        "notes": ["SUPERSTRUCTURE AS PER RDSO DRG. RDSO B-10221 (3.05 m 25T PSC SLAB)."],
    },
    "psc_slab_6.1": {
        "key": "psc_slab_6.1", "family": FAMILY_PSC_SLAB, "label": "PSC Slab 6.1 m",
        "rdso_ref": "RDSO B-10221R (6.1 m pre-tensioned PSC slab)",
        "girder_depth_mm": 550, "deck_width_mm": 6200,
        "notes": ["SUPERSTRUCTURE AS PER RDSO DRG. RDSO B-10221R (6.1 m PRE-TENSIONED PSC SLAB)."],
    },
    "psc_slab_9.15": {
        "key": "psc_slab_9.15", "family": FAMILY_PSC_SLAB, "label": "PSC Slab 9.15 m",
        "rdso_ref": "9.15 m post-tensioned PSC slab (RDSO)",
        "girder_depth_mm": 700, "deck_width_mm": 6200,
        "notes": ["SUPERSTRUCTURE AS PER RDSO 9.15 m POST-TENSIONED PSC SLAB DRAWING."],
    },
    "psc_slab_12.2": {
        "key": "psc_slab_12.2", "family": FAMILY_PSC_SLAB, "label": "PSC Slab 12.2 m",
        "rdso_ref": "RDSO B-10361 (12.2 m PSC slab)",
        "girder_depth_mm": 850, "deck_width_mm": 6200,
        "notes": ["SUPERSTRUCTURE AS PER RDSO DRG. RDSO B-10361 (12.2 m PSC SLAB)."],
    },
    # ── PSC girders ────────────────────────────────────────────────────────
    "psc_girder_12.2": {
        "key": "psc_girder_12.2", "family": FAMILY_PSC_GIRDER, "label": "PSC Girder 12.2 m",
        "rdso_ref": "RDSO PSC girder (12.2 m)",
        "girder_depth_mm": 1250, "deck_width_mm": 6200, "num_girders": 2,
        "notes": ["SUPERSTRUCTURE AS PER RDSO PSC GIRDER DRAWING."],
    },
    "psc_girder_18.3": {
        "key": "psc_girder_18.3", "family": FAMILY_PSC_GIRDER, "label": "PSC Girder 18.3 m",
        "rdso_ref": "RDSO PSC girder (18.3 m)",
        "girder_depth_mm": 1600, "deck_width_mm": 6200, "num_girders": 2,
        "notes": ["SUPERSTRUCTURE AS PER RDSO PSC GIRDER DRAWING."],
    },
    "psc_girder_24.4": {
        "key": "psc_girder_24.4", "family": FAMILY_PSC_GIRDER, "label": "PSC Girder 24.4 m",
        "rdso_ref": "RDSO PSC girder (24.4 m)",
        "girder_depth_mm": 2000, "deck_width_mm": 6200, "num_girders": 3,
        "notes": ["SUPERSTRUCTURE AS PER RDSO PSC GIRDER DRAWING."],
    },
    # ── Box girder ─────────────────────────────────────────────────────────
    "box_girder_24.4": {
        "key": "box_girder_24.4", "family": FAMILY_BOX_GIRDER, "label": "Box Girder 24.4 m",
        "rdso_ref": "RDSO B-10270 (24.4 m 25T box girder)",
        "girder_depth_mm": 2500, "deck_width_mm": 6200, "num_girders": 1,
        "notes": ["SUPERSTRUCTURE AS PER RDSO DRG. RDSO B-10270 (24.4 m 25T BOX GIRDER)."],
    },
    # ── Steel girders ──────────────────────────────────────────────────────
    "steel_girder_18.3": {
        "key": "steel_girder_18.3", "family": FAMILY_STEEL_GIRDER, "label": "Steel Girder 18.3 m",
        "rdso_ref": "RDSO steel girder (18.3 m)",
        "girder_depth_mm": 1800, "deck_width_mm": 6200, "num_girders": 2,
        "notes": ["SUPERSTRUCTURE AS PER RDSO STEEL GIRDER DRAWING (PLATE/COMPOSITE GIRDER)."],
    },
    "steel_girder_24.4": {
        "key": "steel_girder_24.4", "family": FAMILY_STEEL_GIRDER, "label": "Steel Girder 24.4 m",
        "rdso_ref": "RDSO steel girder (24.4 m)",
        "girder_depth_mm": 2400, "deck_width_mm": 6200, "num_girders": 2,
        "notes": ["SUPERSTRUCTURE AS PER RDSO STEEL GIRDER DRAWING (PLATE/COMPOSITE GIRDER)."],
    },
    # ── Foot over bridge ───────────────────────────────────────────────────
    "fob": {
        "key": "fob", "family": FAMILY_FOB, "label": "Foot Over Bridge (FOB)",
        "rdso_ref": "RDSO FOB standard drawing",
        "girder_depth_mm": 450, "deck_width_mm": 2400,
        "notes": ["FOB DECK AND STAIRS AS PER RDSO FOB STANDARD DRAWING.",
                  "HANDRAILS 1.2 m HIGH ON BOTH SIDES."],
    },
}

# Family keyword detection for free-text prompts (checked in this order).
FAMILY_KEYWORDS = [
    ("fob", r"\bFOB\b|FOOT\s*OVER"),
    ("box_girder", r"BOX\s*GIRDER"),
    ("steel_girder", r"STEEL\s*GIRDER"),
    ("psc_girder", r"PSC\s*GIRDER|PRESTRESSED\s*GIRDER"),
    ("psc_slab", r"PSC\s*SLAB"),
    ("rcc_box", r"RCC\s*BOX|\bBOX\b|\bCULVERT\b"),
]


def detect_family(text: str) -> str:
    """Pick the span family from a free-text prompt."""
    import re
    for family, pattern in FAMILY_KEYWORDS:
        if re.search(pattern, text, re.I):
            return family
    return FAMILY_RCC_BOX


def nearest_catalog_key(family: str, span_m: float) -> Optional[str]:
    """Closest catalogue entry for a family + first span length (metres)."""
    cands = [(k, v) for k, v in SPAN_TYPES.items() if v["family"] == family]
    if not cands:
        return None
    if family == FAMILY_RCC_BOX:
        return "rcc_box"
    if family == FAMILY_FOB:
        return "fob"
    best, best_d = None, None
    for k, v in cands:
        label = v.get("label", "")
        m = __import__("re").search(r"(\d+(?:\.\d+)?)\s*m", label)
        if not m:
            continue
        d = abs(float(m.group(1)) - span_m)
        if best_d is None or d < best_d:
            best, best_d = k, d
    return best


def resolve_defaults(inp) -> None:
    """Fill engineering defaults from the catalogue where the user gave none.
    Mutates the GadInput in place. Prompt values always win."""
    if not inp.cells_mm:
        inp.cells_mm = [4000]
    family = inp.span_type if inp.span_type in FAMILIES else detect_family(
        str(inp.span_description))
    inp.span_type = family

    span_m = (inp.cells_mm[0] or 4000) / 1000.0
    key = inp.type_key or nearest_catalog_key(family, span_m)
    cat = SPAN_TYPES.get(key) if key else None
    if cat is None and family == FAMILY_RCC_BOX:
        cat = SPAN_TYPES["rcc_box"]
    if cat is None:
        return

    if not inp.type_key:
        inp.type_key = cat["key"]
    if inp.girder_depth_mm <= 0 and cat.get("girder_depth_mm"):
        inp.girder_depth_mm = cat["girder_depth_mm"]
    if inp.deck_width_mm <= 0 and cat.get("deck_width_mm"):
        inp.deck_width_mm = cat["deck_width_mm"]
    if inp.num_girders <= 0 and cat.get("num_girders"):
        inp.num_girders = cat["num_girders"]
    if inp.clear_height_mm <= 0 and cat.get("default_clear_height_mm"):
        inp.clear_height_mm = cat["default_clear_height_mm"]
    if inp.top_slab_thk_mm <= 0 and cat.get("slab_thk_mm"):
        inp.top_slab_thk_mm = cat["slab_thk_mm"]
    if inp.bottom_slab_thk_mm <= 0 and cat.get("slab_thk_mm"):
        inp.bottom_slab_thk_mm = cat["slab_thk_mm"]
    if inp.wall_thk_mm <= 0 and cat.get("wall_thk_mm"):
        inp.wall_thk_mm = cat["wall_thk_mm"]
    for note in cat.get("notes", []):
        if note not in inp.standard_notes:
            inp.standard_notes.append(note)
