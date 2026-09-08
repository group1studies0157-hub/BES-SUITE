"""
Parameter Extraction Module
GAD Review System — Indian Railways Bridge Drawing Review
---------------------------------------------------------
Calls Claude API to intelligently extract structured parameters
from the raw text extracted from a GAD PDF.
"""

import json
import re
import anthropic
from dataclasses import dataclass, field, asdict
from typing import Optional
from gui.grs.core.pdf_ingestor import GADText


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class HydraulicParams:
    design_discharge_m3s: Optional[float] = None
    hfl_m: Optional[float] = None
    lwl_m: Optional[float] = None
    existing_linear_waterway_m: Optional[float] = None
    proposed_linear_waterway_m: Optional[float] = None
    required_waterway_area_m2: Optional[float] = None
    proposed_waterway_area_m2: Optional[float] = None
    velocity_ms: Optional[float] = None
    freeboard_required_m: Optional[float] = None
    freeboard_provided_m: Optional[float] = None
    vertical_clearance_required_mm: Optional[float] = None
    vertical_clearance_provided_mm: Optional[float] = None
    vc_required_mm_computed: Optional[float] = None   # deterministic table lookup
    vc_computation_note: Optional[str] = None         # explanation of the lookup
    navigable: Optional[bool] = None
    scour_levels_individual: Optional[bool] = None   # True if individually computed
    max_scour_level_m: Optional[float] = None


@dataclass
class GeometricParams:
    num_spans: Optional[int] = None
    span_length_m: Optional[float] = None
    span_arrangement: Optional[str] = None          # e.g. "15 × 18.30 m"
    effective_span_m: Optional[float] = None
    overall_span_m: Optional[float] = None
    rail_level_m: Optional[float] = None
    formation_level_m: Optional[float] = None
    bed_level_m: Optional[float] = None
    bog_m: Optional[float] = None                   # Bottom of Girder
    tobb_m: Optional[float] = None                  # Top of Bridge Beam
    bobb_m: Optional[float] = None
    bearing_type: Optional[str] = None
    deck_width_m: Optional[float] = None
    track_centres_m: Optional[float] = None
    wearing_coat_thickness_mm: Optional[float] = None


@dataclass
class MaterialParams:
    psc_girder_grade: Optional[str] = None          # e.g. "M-50"
    substructure_concrete_grade: Optional[str] = None
    pile_concrete_grade: Optional[str] = None
    wearing_coat_grade: Optional[str] = None
    levelling_course_grade: Optional[str] = None
    reinforcement_grade: Optional[str] = None       # e.g. "Fe-500"
    bearing_specification: Optional[str] = None
    pitching_specification: Optional[str] = None
    exposure_condition: Optional[str] = None
    seismic_zone: Optional[str] = None
    loading_standard: Optional[str] = None


@dataclass
class DrawingMetadata:
    bridge_number: Optional[str] = None
    chainage: Optional[str] = None
    section: Optional[str] = None
    division: Optional[str] = None
    zone: Optional[str] = None
    drawing_number: Optional[str] = None
    revision: Optional[str] = None
    date: Optional[str] = None
    authority_of_work: Optional[str] = None
    river_name: Optional[str] = None
    bridge_type: Optional[str] = None              # PSC / RCC / Steel etc.
    project_type: Optional[str] = None             # New line / Doubling / Gauge conv.


@dataclass
class ChecklistFlags:
    """
    Boolean flags used by the Rule Engine.
    Each flag maps to a rule check parameter.
    Claude sets these based on reading the drawing notes.
    """
    # Foundation
    foundation_design_finalised: Optional[bool] = None
    pile_load_test_noted: Optional[bool] = None
    pile_integrity_test_noted: Optional[bool] = None
    pile_concrete_grade_correct: Optional[bool] = None
    bed_block_dimensions_shown: Optional[bool] = None
    pedestal_dimensions_consistent: Optional[bool] = None
    foundation_level_vs_scour_checked: Optional[bool] = None

    # Superstructure
    psc_girder_rdso_reference: Optional[str] = None   # The actual ref no. if found
    bearing_type_confirmed: Optional[bool] = None
    bearing_reference_drawing: Optional[str] = None
    wearing_coat_annotated: Optional[bool] = None
    transition_slab_shown: Optional[bool] = None

    # Material specs
    substructure_concrete_spec_correct: Optional[bool] = None
    wearing_coat_concrete_spec: Optional[bool] = None
    levelling_course_spec: Optional[bool] = None
    reinforcement_grade_correct: Optional[bool] = None
    exposure_condition_stated: Optional[bool] = None

    # Protection works
    pitching_shown_complete: Optional[bool] = None
    inter_bridge_drainage_shown: Optional[bool] = None
    weep_holes_specified: Optional[bool] = None

    # OHE / Track
    ohe_pedestal_shown: Optional[bool] = None
    track_centre_dimensioned: Optional[bool] = None
    guard_rail_noted: Optional[bool] = None
    crs_permission_note: Optional[bool] = None

    # Drawing completeness
    drawing_number_complete: Optional[bool] = None
    signature_block_complete: Optional[bool] = None
    open_comments_resolved: Optional[bool] = None
    l_section_esp_referenced: Optional[bool] = None
    completion_drawing_note: Optional[bool] = None
    soundness_certificate_noted: Optional[bool] = None
    dimension_callouts_correct: Optional[bool] = None


@dataclass
class ExtractedParams:
    """Complete set of parameters extracted from a GAD."""
    hydraulic: HydraulicParams = field(default_factory=HydraulicParams)
    geometric: GeometricParams = field(default_factory=GeometricParams)
    material: MaterialParams = field(default_factory=MaterialParams)
    metadata: DrawingMetadata = field(default_factory=DrawingMetadata)
    flags: ChecklistFlags = field(default_factory=ChecklistFlags)
    raw_ai_response: str = ""
    extraction_notes: list[str] = field(default_factory=list)


# ── Extraction Prompt ─────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """You are a specialised AI assistant for reviewing Indian Railways bridge 
General Arrangement Drawings (GADs). You have deep knowledge of:
- IRS Bridge Rules 2014 (Revised)
- IRS Concrete Bridge Code (CBC) 2014
- IRS Bridge Substructure & Foundation Code 2013
- IR Bridge Manual (IRBM) 2024
- IRPWM 2019
- RDSO guidelines for bridge components

Your task is to extract ALL relevant parameters from the text of a GAD PDF that has been 
provided to you. The text may be imperfect (OCR artifacts, merged words, missing spaces) 
because it comes from CAD-generated PDFs.

You must extract parameters and return them as a single valid JSON object.
Be conservative — if you are not sure of a value, set it to null rather than guessing.
For boolean flags, true means "confirmed present and correct", false means "explicitly absent 
or wrong", null means "cannot determine from available text".

Return ONLY the JSON object, no explanatory text before or after."""


def build_extraction_prompt(gad: GADText) -> str:
    """Build the user prompt for parameter extraction."""

    # Prepare a condensed version of the text for the API call
    # (full text may exceed context; we send the most relevant parts)
    sections = []

    sections.append("=== FULL TEXT (first 4000 chars) ===")
    sections.append(gad.full_text[:4000])

    if gad.title_block:
        sections.append("\n=== TITLE BLOCK ===")
        sections.append(gad.title_block[:1500])

    if gad.notes_section:
        sections.append("\n=== GENERAL NOTES ===")
        sections.append(gad.notes_section[:2000])

    if gad.levels_table:
        sections.append("\n=== LEVELS / HYDRAULIC DATA ===")
        sections.append(gad.levels_table[:1500])

    if len(gad.pages) > 1:
        sections.append("\n=== LAST PAGE TEXT ===")
        sections.append(gad.pages[-1][:2000])

    text_for_api = "\n".join(sections)

    prompt = f"""Please extract all available parameters from this Indian Railways bridge GAD text.

{text_for_api}

Return a JSON object with EXACTLY this structure (use null for unknown values):

{{
  "metadata": {{
    "bridge_number": null,
    "chainage": null,
    "section": null,
    "division": null,
    "zone": null,
    "drawing_number": null,
    "revision": null,
    "date": null,
    "authority_of_work": null,
    "river_name": null,
    "bridge_type": null,
    "project_type": null
  }},
  "hydraulic": {{
    "design_discharge_m3s": null,
    "hfl_m": null,
    "lwl_m": null,
    "existing_linear_waterway_m": null,
    "proposed_linear_waterway_m": null,
    "required_waterway_area_m2": null,
    "proposed_waterway_area_m2": null,
    "velocity_ms": null,
    "freeboard_required_m": null,
    "freeboard_provided_m": null,
    "vertical_clearance_required_mm": null,
    "vertical_clearance_provided_mm": null,
    "navigable": null,
    "scour_levels_individual": null,
    "max_scour_level_m": null
  }},
  "geometric": {{
    "num_spans": null,
    "span_length_m": null,
    "span_arrangement": null,
    "effective_span_m": null,
    "overall_span_m": null,
    "rail_level_m": null,
    "formation_level_m": null,
    "bed_level_m": null,
    "bog_m": null,
    "tobb_m": null,
    "bobb_m": null,
    "bearing_type": null,
    "deck_width_m": null,
    "track_centres_m": null,
    "wearing_coat_thickness_mm": null
  }},
  "material": {{
    "psc_girder_grade": null,
    "substructure_concrete_grade": null,
    "pile_concrete_grade": null,
    "wearing_coat_grade": null,
    "levelling_course_grade": null,
    "reinforcement_grade": null,
    "bearing_specification": null,
    "pitching_specification": null,
    "exposure_condition": null,
    "seismic_zone": null,
    "loading_standard": null
  }},
  "flags": {{
    "foundation_design_finalised": null,
    "pile_load_test_noted": null,
    "pile_integrity_test_noted": null,
    "pile_concrete_grade_correct": null,
    "bed_block_dimensions_shown": null,
    "pedestal_dimensions_consistent": null,
    "foundation_level_vs_scour_checked": null,
    "psc_girder_rdso_reference": null,
    "bearing_type_confirmed": null,
    "bearing_reference_drawing": null,
    "wearing_coat_annotated": null,
    "transition_slab_shown": null,
    "substructure_concrete_spec_correct": null,
    "wearing_coat_concrete_spec": null,
    "levelling_course_spec": null,
    "reinforcement_grade_correct": null,
    "exposure_condition_stated": null,
    "pitching_shown_complete": null,
    "inter_bridge_drainage_shown": null,
    "weep_holes_specified": null,
    "ohe_pedestal_shown": null,
    "track_centre_dimensioned": null,
    "guard_rail_noted": null,
    "crs_permission_note": null,
    "drawing_number_complete": null,
    "signature_block_complete": null,
    "open_comments_resolved": null,
    "l_section_esp_referenced": null,
    "completion_drawing_note": null,
    "soundness_certificate_noted": null,
    "dimension_callouts_correct": null
  }},
  "extraction_notes": []
}}

In extraction_notes, list any ambiguities, items that need manual verification,
or important observations you noticed during extraction (max 10 items)."""

    return prompt


# ── API Call ──────────────────────────────────────────────────────────────────

def extract_parameters(gad: GADText, api_key: str = "", gemini_key: str = "") -> ExtractedParams:
    """
    Call the AI provider to extract structured parameters from GAD text.
    Tries Gemini first (free tier) and falls back to Claude automatically
    via AIProvider.dual() — same dual-key logic used elsewhere in the app.

    Backward compatible: existing callers passing only `api_key` (the
    Claude key) keep working exactly as before; Gemini is simply skipped
    if no gemini_key is supplied.

    Parameters
    ----------
    gad         : GADText
    api_key     : str  — Anthropic Claude key (fallback provider)
    gemini_key  : str  — Google Gemini key (tried first, if provided)
    """
    from gui.ai_provider import AIProvider

    prompt = build_extraction_prompt(gad)

    provider = AIProvider.dual(gemini_key=gemini_key, claude_key=api_key)
    raw_response = provider.chat(EXTRACTION_SYSTEM_PROMPT, prompt, max_tokens=2000)

    # Parse JSON response
    params = ExtractedParams()
    params.raw_ai_response = raw_response

    try:
        # Strip any accidental markdown fences
        clean = re.sub(r'```json|```', '', raw_response).strip()
        data = json.loads(clean)

        # Map to dataclasses
        if "hydraulic" in data:
            params.hydraulic = HydraulicParams(**{
                k: v for k, v in data["hydraulic"].items()
                if k in HydraulicParams.__dataclass_fields__
            })
        if "geometric" in data:
            params.geometric = GeometricParams(**{
                k: v for k, v in data["geometric"].items()
                if k in GeometricParams.__dataclass_fields__
            })
        if "material" in data:
            params.material = MaterialParams(**{
                k: v for k, v in data["material"].items()
                if k in MaterialParams.__dataclass_fields__
            })
        if "metadata" in data:
            params.metadata = DrawingMetadata(**{
                k: v for k, v in data["metadata"].items()
                if k in DrawingMetadata.__dataclass_fields__
            })
        if "flags" in data:
            params.flags = ChecklistFlags(**{
                k: v for k, v in data["flags"].items()
                if k in ChecklistFlags.__dataclass_fields__
            })
        if "extraction_notes" in data:
            params.extraction_notes = data["extraction_notes"]

    except (json.JSONDecodeError, TypeError) as e:
        params.extraction_notes.append(f"JSON parse error: {e}. Manual review of raw response needed.")

    # ── Deterministic VC cross-check ────────────────────────────────────────
    # Compute VC required from the IRS Bridge Rules discharge table, independent
    # of whatever value the AI extracted from the drawing text. This catches
    # cases where the GAD states a VC that doesn't match its own discharge value.
    try:
        from gui.grs.core.vc_lookup import compute_vc_required_mm
        discharge = params.hydraulic.design_discharge_m3s
        if discharge is not None:
            vc_computed, vc_note = compute_vc_required_mm(discharge)
            params.hydraulic.vc_required_mm_computed = vc_computed
            params.hydraulic.vc_computation_note = vc_note
    except Exception as e:
        params.extraction_notes.append(f"VC table lookup failed: {e}")

    return params


def params_to_dict(params: ExtractedParams) -> dict:
    """Convert ExtractedParams to a plain dict for storage/display."""
    return asdict(params)
