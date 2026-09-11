"""
core/cad_knowledge.py — runtime knowledge pack for BES drawing tools
═══════════════════════════════════════════════════════════════════

Distilled from .agents/skills/autocad_drawing_standards.md (NCS layer model,
ezdxf dimensioning docs, Lee Mac LISP conventions, RDSO/GAD practice).

Used by:
  - CAD Process   (core/cad_engine.py)      -> build_vision_rules_block()
  - CAD Process 2 (gui/cad_panel2.py)       -> extract_rules_block()
  - GAD Generator (core/gad_generator.py)   -> gad_rules_block()

NOT used by bore log (gui/borelog_panel.py, borelog_dxf/*) — deliberately.
"""

from __future__ import annotations

# ── Layer model (ACI colours) — §2 of the standards file ────────────────────
LAYER_MODEL = {
    "GEOMETRY":    7,
    "DIMENSIONS":  3,
    "CENTRELINES": 1,
    "ANNOTATIONS": 2,
    "LEVELS":      3,
    "SYMBOLS":     6,
    "BORDER":      5,
    "TITLEBLOCK":  4,
}

# ── Text size ladder (plot-mm at 1:100 -> model-mm factors) — §3 ────────────
TEXT_LADDER = {
    "title": 500.0,   # 5.0 mm plot
    "note":  300.0,   # 3.0 mm
    "dim":   250.0,   # 2.5 mm
    "level": 250.0,
}
TEXT_MIN_PLOT_MM = 2.5
TEXT_MAX_FRACTIONS = {"dim": 0.025, "note": 0.020, "title": 0.015}
TEXT_STYLE = "STANDARD"
TEXT_MIN_MM, TEXT_MAX_DIM_MM, TEXT_MAX_TITLE_MM = 2.5, 50.0, 35.0

# ── Dimension rules — §4 ─────────────────────────────────────────────────────
CHAIN_TOLERANCE_MM = 1.0          # sum(segments) vs overall
CHAIN_OFFSET_FRAC = 0.01          # dim line offset from geometry (× extent)
CHAIN_PITCH_FACTORS = 4.0         # chain pitch in text heights
TICK_TO_TEXT = 0.8                # oblique tick size vs text height

# ── Hatch patterns — §5 (soil / concrete / materials) ───────────────────────
HATCH_PATTERNS = {
    "earth":         {"pattern": "EARTH",    "angle": 45, "spacing_frac": 1 / 300},
    "steel":         {"pattern": "ANSI31",   "angle": 45, "spacing_frac": 1 / 600},
    "mass_concrete": {"pattern": "AR-CONC",  "angle": 0,  "spacing_frac": 1 / 100},
    "brick":         {"pattern": "ANSI37",   "angle": 45, "spacing_frac": 1 / 200},
    "rubble":        {"pattern": "GRAVEL",   "angle": 0,  "spacing_frac": 1 / 150},
    "sand":          {"pattern": "AR-SAND",  "angle": 0,  "spacing_frac": 1 / 150},
    "water":         {"pattern": "AR-RSHKE", "angle": 0,  "spacing_frac": 1 / 150},
    "generic":       {"pattern": "NET",      "angle": 0,  "spacing_frac": 1 / 200},
}
HATCH_LAYER = "HATCHING"          # ACI 8 — every hatch lives here
RCC_GAD_HATCH = False              # RCC/PSC superstructure stays unhatched in GAD views

# ── RDSO catalogue quick refs — §7 (canonical list in core/gad_standards.py) ─
RDSO_REFS = {
    "psc_slab_3.05":  "RDSO B-10221 (3.05 m 25T PSC slab)",
    "psc_slab_6.1":   "RDSO B-10221R (6.1 m pre-tensioned PSC slab)",
    "notes order":    "superstructure, substructure, materials, drainage, approaches, general",
    "title order":    "BRIDGE NO / DESCRIPTION / PROJECT-SECTION-DIVISION / CHAINAGE / LOADING / SCALE / DRG NO / DATE",
}


def build_vision_rules_block() -> str:
    """Rules block for CAD Process's VISION_PROMPT (image -> geometry JSON)."""
    return (
        "\n\nDRAWING STANDARDS (from BES AutoCAD standards knowledge):\n"
        "1. 1:1 model space in millimetres; scale annotations only.\n"
        "2. Assign every entity to a layer from this table:\n"
        + "".join(f"     - {n} (colour {c})\n" for n, c in LAYER_MODEL.items())
        + "3. Text: dim 2.5 mm plot-min (<=0.025 of extent), notes 3.0 mm "
          "(<=0.020), title 5.0 mm (<=0.015); style STANDARD, left-justified notes.\n"
        "4. Dimension chains must be complete: sum of segments == overall (+/-1 mm). "
        "Read every chain number — never sum or skip members.\n"
        "5. mm for dimensions; levels (RL/HFL/BL/FRL) in metres, 3 decimals.\n"
        "6. Annotation/leader geometry belongs on ANNOTATIONS, not GEOMETRY.\n"
        "7. If the bridge type matches an RDSO standard drawing, report its "
        "reference (e.g. 'RDSO B-10221') in the notes field.\n"
        + hatch_rules_block()
    )


def extract_rules_block() -> str:
    """Rules block for CAD Process 2's EXTRACT/OBSERVE/VERIFY prompts."""
    return (
        "\n\nBES DRAWING STANDARDS:\n"
        "1. Dimensions in MILLIMETRES; levels (RL/HFL/BL/FRL) in metres, 3 decimals.\n"
        "2. Read EVERY number in each dimension chain — never sum, skip or average. "
        "Chains must close: sum(segments) == overall within 1 mm; if a chain does not "
        "close, report the raw values and flag the mismatch.\n"
        "3. Quote the RDSO standard-drawing reference when the bridge type matches "
        "the catalogue (e.g. psc_slab_6.1 -> 'RDSO B-10221R').\n"
        "4. Zones: identify HALF ELEVATION / HALF SECTION, HALF TOP/BOTTOM PLAN, "
        "CROSS SECTION exactly as drawn.\n"
    )


def gad_rules_block() -> str:
    """Rules block for GAD Generator's from_ai() system prompt."""
    return (
        "\nDrawing standards: dimensions in mm, levels in metres (3 decimals). "
        "Dimension chains must close within 1 mm — if the prompt gives segments "
        "plus an overall length, verify they reconcile; if not, prefer the "
        "segments and note the mismatch in 'notes'. Quote the RDSO reference for "
        "the span type from the standard catalogue (psc_slab_3.05 -> RDSO B-10221, "
        "psc_slab_6.1 -> RDR B-10221R, psc_slab_12.2 -> RDSO B-10361)."
    )


def hatch_rules_block() -> str:
    """Pattern vocabulary + section-lining rules (standards §5) for tools that
    emit hatches — currently CAD Process's vision extraction."""
    vocab = ", ".join(
        f"{mat}={d['pattern']}" for mat, d in HATCH_PATTERNS.items())
    return (
        "HATCHING RULES:\n"
        f"- Use ONLY these standard AutoCAD patterns: {vocab}.\n"
        "- Earth/soil in section -> EARTH at 45°; structural steel -> tight "
        "ANSI31 at 45°; mass concrete -> sparse AR-CONC; brick -> ANSI37; "
        "rubble -> GRAVEL; sand -> AR-SAND; water -> AR-RSHKE.\n"
        "- RCC/PSC superstructure in GAD views is NOT hatched — plain outline "
        "plus concrete-grade note.\n"
        "- Adjacent hatched parts alternate 45°/135° so their joint stays readable.\n"
        "- Hatch scale derives from the drawing extent (EARTH ~extent/300, "
        "ANSI31 ~extent/600), never a fixed magic number.\n"
        f"- Every hatch region sits on the {HATCH_LAYER} layer; never hatch "
        "over text, dimensions or level markers.\n"
    )


# ── Shared repair helper — §4 chain-completeness rule ───────────────────────
def repair_dimension_chain(segments: list[float], overall: float | None,
                           tol: float = CHAIN_TOLERANCE_MM) -> list[float]:
    """Redistribute the residual when a dimension chain does not close.

    Follows §4 of the standards: the chain sum must equal the overall within
    tolerance. Residuals are spread proportionally; the input list is not
    mutated. Returns segments unchanged when `overall` is None or already
    consistent.
    """
    if not segments or overall is None or overall <= 0:
        return list(segments)
    residual = overall - sum(segments)
    if abs(residual) <= tol:
        return list(segments)
    total = sum(segments)
    if total <= 0:
        return list(segments)
    k = overall / total
    fixed = [s * k for s in segments]
    # absorb float noise into the longest segment
    fixed[int(max(range(len(fixed)), key=lambda i: fixed[i]))] += overall - sum(fixed)
    return fixed


__all__ = [
    "LAYER_MODEL", "TEXT_LADDER", "TEXT_STYLE", "RDSO_REFS",
    "HATCH_PATTERNS", "HATCH_LAYER", "RCC_GAD_HATCH",
    "build_vision_rules_block", "extract_rules_block", "gad_rules_block",
    "hatch_rules_block", "repair_dimension_chain",
]
