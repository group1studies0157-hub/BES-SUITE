"""
GAD Generator — parametric General Arrangement Drawing creation for AutoCAD.

Inverse of core/param_extractor.py (which reads a GAD and produces parameters):
this module takes a *prompt plus dimensions* (levels, spans, span type) and
produces a complete layer-tagged drawing, written out both as an AutoLISP
script (load in AutoCAD, run BES-GAD) and as a DXF (open directly in any CAD
tool).

Pipeline:  prompt ──► GadInput (AI or offline parse) ──► entities ──► .lsp + .dxf

Views generated (RCC box):  longitudinal section, cross-section, plan,
title block and standard notes.  PSC slab:  elevation, section, plan.
All coordinates are model mm at 1:1; the draftsman plots at the drawing scale.

Layer conventions match the rest of the suite (see cad_engine.py):
GEOMETRY / DIMENSIONS / CENTRELINES / ANNOTATIONS / HATCHING / ELEVATIONS /
SYMBOLS / BORDER / TITLEBLOCK.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from core.gad_standards import (
    FAMILIES, resolve_defaults, detect_family, nearest_catalog_key,
)

# ─────────────────────────────────────────────────────────────────────────────
# Entity model — every drawing primitive is a plain dict so it can be written
# to either DXF (ezdxf) or AutoLISP (entmake) with the same code.
# ─────────────────────────────────────────────────────────────────────────────

Entity = dict


def add_line(ents: list, layer: str, x1: float, y1: float, x2: float, y2: float) -> None:
    ents.append({"type": "line", "layer": layer, "x1": x1, "y1": y1, "x2": x2, "y2": y2})


def add_rect(ents: list, layer: str, x: float, y: float, w: float, h: float) -> None:
    ents.append({"type": "polyline", "layer": layer, "closed": True,
                 "points": [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]})


def add_poly(ents: list, layer: str, pts: list, closed: bool = False) -> None:
    ents.append({"type": "polyline", "layer": layer, "closed": closed, "points": list(pts)})


def add_circle(ents: list, layer: str, x: float, y: float, r: float) -> None:
    ents.append({"type": "circle", "layer": layer, "x": x, "y": y, "r": r})


def add_text(ents: list, layer: str, x: float, y: float, text: str,
             height: float = 350.0, center: bool = True) -> None:
    ents.append({"type": "text", "layer": layer, "x": x, "y": y,
                 "text": str(text), "height": float(height), "center": center})


def add_dim(ents: list, x1: float, x2: float, y: float, value: str,
            layer: str = "DIMENSIONS", above: bool = False) -> None:
    """Linear dimension: witness lines, dim line with end ticks, centred text."""
    d = 900 if above else -900
    add_line(ents, layer, x1, y, x1, y + d)
    add_line(ents, layer, x2, y, x2, y + d)
    add_line(ents, layer, x1, y, x2, y)
    t = 260
    add_line(ents, layer, x1, y, x1 + t, y - t * (1 if above else -1))
    add_line(ents, layer, x1, y, x1 + t, y + t * (1 if above else -1))
    add_line(ents, layer, x2, y, x2 - t, y - t * (1 if above else -1))
    add_line(ents, layer, x2, y, x2 - t, y + t * (1 if above else -1))
    add_text(ents, layer, (x1 + x2) / 2.0, y + (900 if above else -900) - 320 * (1 if above else -1),
             value, height=320, center=True)


def add_level_marker(ents: list, x: float, y: float, label: str,
                     height: float = 350.0) -> None:
    """RL / FL / BL / HFL triangle marker pointing at the level line."""
    add_poly(ents, "SYMBOLS", [(x - 260, y), (x + 260, y), (x, y + 300)], closed=True)
    add_text(ents, "ELEVATIONS", x + 520, y + 140, label, height=height, center=False)


def translate(ents: list, ox: float, oy: float) -> list:
    """Return a copy of entities shifted by (ox, oy) — used to lay out views."""
    out = []
    for e in ents:
        e = dict(e)
        if e["type"] == "line":
            e["x1"] += ox; e["y1"] += oy; e["x2"] += ox; e["y2"] += oy
        elif e["type"] == "polyline":
            e["points"] = [(px + ox, py + oy) for px, py in e["points"]]
        elif e["type"] == "circle":
            e["x"] += ox; e["y"] += oy
        elif e["type"] == "text":
            e["x"] += ox; e["y"] += oy
        out.append(e)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Input model — the vocabulary matches core/param_extractor.py dataclasses so
# values extracted from a GAD can be round-tripped straight back into it.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GadInput:
    bridge_no: str = "XX"
    span_description: str = ""                 # e.g. "(1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX"
    span_type: str = "rcc_box"                 # family — see core/gad_standards.py
    type_key: str = ""                         # catalogue key, e.g. "psc_slab_9.15"
    cells_mm: list = field(default_factory=lambda: [4250, 4500, 4250])   # clear widths / spans
    clear_height_mm: float = 1500.0            # RCC box vent height
    num_tracks: int = 1
    track_centres_mm: float = 0.0              # 0 => single centred track
    rail_level_m: float = 0.0
    formation_level_m: float = 0.0
    bed_level_m: float = 0.0
    hfl_m: float = 0.0
    scour_level_m: float = 0.0                 # 0 => no scour info
    girder_depth_mm: float = 0.0               # slab/girder depth for slab/girder families
    num_girders: int = 0
    top_slab_thk_mm: float = 350.0
    bottom_slab_thk_mm: float = 350.0
    wall_thk_mm: float = 350.0
    wearing_coat_mm: float = 150.0
    levelling_course_mm: float = 150.0
    foundation_depth_mm: float = 1000.0
    barrel_length_mm: float = 0.0              # 0 => computed from cells
    deck_width_mm: float = 0.0                 # 0 => computed from cells
    project: str = ""
    section: str = ""
    division: str = ""
    chainage: str = ""
    loading: str = "25T-2008"
    scale: str = "1:100"
    drawing_no: str = ""
    date: str = ""
    notes: list = field(default_factory=list)  # drawing-specific notes
    standard_notes: list = field(default_factory=list)

    # ── derived geometry ─────────────────────────────────────────────────────
    def barrel_len(self) -> float:
        if self.barrel_length_mm and self.barrel_length_mm > 0:
            return self.barrel_length_mm
        n = len(self.cells_mm)
        if self.span_type == "psc_slab":
            return (self.cells_mm[0] if self.cells_mm else 9150) * (n if n else 1)
        return sum(self.cells_mm) + self.wall_thk_mm * (n + 1)

    def deck_w(self) -> float:
        if self.deck_width_mm and self.deck_width_mm > 0:
            return self.deck_width_mm
        return self.barrel_len() if self.span_type == "rcc_box" else 6200.0

    def stack_height(self) -> float:
        """Total construction height from formation (top of wearing coat) to
        bottom of levelling course."""
        return (self.wearing_coat_mm + self.top_slab_thk_mm +
                self.clear_height_mm + self.bottom_slab_thk_mm +
                self.levelling_course_mm)

    # ── parsing ──────────────────────────────────────────────────────────────
    @staticmethod
    def _span_expr(text: str) -> Optional[tuple]:
        """Recognise '(1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX', '3x4.00x1.30 m RCC
        BOX' or '2x9.15 m PSC slab'. Returns (cells_str, height_m_or_None)."""
        m = re.search(
            r"\(\s*(?P<cells>\d+x\d+(?:\.\d+)?(?:\+\d+x\d+(?:\.\d+)?)*)\s*\)\s*x\s*(?P<h>\d+(?:\.\d+)?)\s*m",
            text, re.I)
        if m:
            return m.group("cells"), float(m.group("h"))
        m = re.search(
            r"(?P<cells>\d+x\d+(?:\.\d+)?)(?:x(?P<h>\d+(?:\.\d+)?))?\s*m"
            r"(?:\s*[A-Za-z ]*)?\b(?:RCC\s*BOX|PSC\s*SLAB|PSC\s*GIRDER|BOX\s*GIRDER|"
            r"STEEL\s*GIRDER|FOOT\s*OVER\s*BRIDGE|FOB)\b",
            text, re.I)
        if m:
            return m.group("cells"), (float(m.group("h")) if m.group("h") else None)
        return None

    @staticmethod
    def _parse_cells(cells_str: str) -> list:
        out = []
        for part in cells_str.split("+"):
            part = part.strip()
            mm = re.match(r"(\d+)x(\d+(?:\.\d+)?)", part)
            if mm:
                n = int(mm.group(1)); w = float(mm.group(2)) * 1000
                out.extend([round(w)] * n)
            else:
                w = re.match(r"(\d+(?:\.\d+)?)", part)
                if w:
                    out.append(round(float(w.group(1)) * 1000))
        return out or [4000]

    @classmethod
    def from_dict(cls, d: dict) -> "GadInput":
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in d.items() if k in known and v is not None}
        inp = cls(**kwargs)
        st = str(inp.span_type or "").lower()
        if st not in FAMILIES:
            inp.span_type = detect_family(str(inp.span_description or ""))
        inp.cells_mm = [int(round(float(c))) for c in (inp.cells_mm or [4000])]
        inp.clear_height_mm = float(inp.clear_height_mm or 0)
        inp.girder_depth_mm = float(inp.girder_depth_mm or 0)
        inp.num_girders = int(inp.num_girders or 0)
        resolve_defaults(inp)
        return inp

    @classmethod
    def from_prompt(cls, text: str) -> "GadInput":
        """Offline, deterministic parse of a free-text prompt. AI parsing
        (from_ai) is preferred when keys are configured; this is the fallback."""
        inp = cls()
        s = text or ""

        expr = cls._span_expr(s)
        if expr:
            cells_str, height_m = expr
            inp.cells_mm = cls._parse_cells(cells_str)
            if height_m:
                inp.clear_height_mm = round(height_m * 1000)
            if inp.span_type == "psc_slab" and inp.clear_height_mm == cls.clear_height_mm:
                inp.clear_height_mm = 0.0  # irrelevant for slabs
        if expr and inp.span_type == "psc_slab" and not inp.span_description:
            inp.span_description = (f"{len(inp.cells_mm)} x {inp.cells_mm[0]/1000:g} m PSC SLAB"
                                    if len(set(inp.cells_mm)) == 1
                                    else "PSC SLAB")

        inp.span_type = detect_family(s)
        if inp.span_type == "rcc_box":
            inp.span_description = (f"({'+'.join(f'1x{c/1000:g}' for c in inp.cells_mm)})"
                                    f"x{inp.clear_height_mm/1000:g} m RCC BOX")

        def _level(pattern, group=1):
            m = re.search(pattern, s, re.I)
            if m:
                try:
                    return float(m.group(group).replace(",", ""))
                except ValueError:
                    return 0.0
            return 0.0

        inp.rail_level_m = _level(r"RAIL\s*(?:LEVEL|RL)?[:=\s]*(\d+(?:\.\d+)?)")
        if not inp.rail_level_m:
            inp.rail_level_m = _level(r"\bRL[:=\s]*(\d+(?:\.\d+)?)")
        inp.formation_level_m = _level(r"FORMATION\s*(?:LEVEL|FL)?[:=\s]*(\d+(?:\.\d+)?)")
        if not inp.formation_level_m:
            inp.formation_level_m = _level(r"\bFL[:=\s]*(\d+(?:\.\d+)?)")
        inp.bed_level_m = _level(r"BED\s*(?:LEVEL|BL)?[:=\s]*(\d+(?:\.\d+)?)")
        if not inp.bed_level_m:
            inp.bed_level_m = _level(r"\bBL[:=\s]*(\d+(?:\.\d+)?)")
        inp.hfl_m = _level(r"\bHFL[:=\s]*(\d+(?:\.\d+)?)")
        inp.scour_level_m = _level(r"(?:MAX\s*)?SCOUR(?:_?LEVEL)?[:=\s]*(\d+(?:\.\d+)?)")

        m = re.search(r"(?:C\s*/\s*C|CENTRE\s*TO\s*CENTRE|TRACK\s*CENTRES?)[^0-9]{0,25}(\d+(?:\.\d+)?)", s, re.I)
        if m:
            try:
                inp.track_centres_mm = float(m.group(1)) * 1000 if "." in m.group(1) else float(m.group(1))
            except ValueError:
                pass

        m = re.search(r"(?:BR(?:IDGE)?\.?\s*NO[.:# ]*|No\.?\s*)([A-Z]{0,4}\d{1,4}[A-Z]{0,3})", s, re.I)
        if m:
            inp.bridge_no = m.group(1).upper()
        else:
            m = re.search(r"^[^\n]{0,30}?(\d+[A-Z]{1,3})\b", s)
            if m:
                inp.bridge_no = m.group(1).upper()

        m = re.search(r"CH(?:AINAGE)?[.:\s]*(\d+(?:\.\d+)?)", s, re.I)
        if m:
            inp.chainage = m.group(1)

        m = re.search(r"(\d{2}T\s*(?:LOADING\s*)?\d{4})", s, re.I)
        if m:
            inp.loading = m.group(1).replace(" ", " ")

        m = re.search(r"SCALE\s*1:(\d+)", s, re.I)
        if m:
            inp.scale = f"1:{m.group(1)}"

        m = re.search(r"([A-Z][A-Z ]{4,60}SECTION)", s)
        if m:
            inp.section = m.group(1).strip()
        m = re.search(r"([A-Z][A-Z ]{4,60}DIVISION)", s)
        if m:
            inp.division = m.group(1).strip()

        m = re.search(r"(\d+(?:\.\d+)?)\s*[mM]\s*(?:PSC\s*SLAB|PSC\s*GIRDER|BOX\s*GIRDER|STEEL\s*GIRDER|FOOT\s*OVER\s*BRIDGE|FOB)", s, re.I)
        if m and inp.span_type in ("psc_slab", "psc_girder", "box_girder", "steel_girder", "fob") and expr is None:
            inp.cells_mm = [round(float(m.group(1)) * 1000)]
            inp.span_description = f"{m.group(1)} m {inp.span_type.upper().replace('_', ' ')}"

        if not inp.standard_notes:
            inp.standard_notes = list(DEFAULT_STANDARD_NOTES)
        resolve_defaults(inp)
        return inp

    @classmethod
    def from_ai(cls, text: str, ai: Any) -> "GadInput":
        """Ask the configured AI provider to fill the structured schema, then
        fall back to the offline parser if anything fails."""
        system = (
            "You are an expert in Indian Railways bridge General Arrangement Drawings (GADs). "
            "Convert the user's prompt into a structured parameter object for parametric GAD "
            "generation. Return ONLY a single valid JSON object, no prose, no markdown fences. "
            "The JSON must match exactly this schema:\n" +
            json.dumps(_AI_SCHEMA_EXAMPLE) +
            "\nRules: cells_mm is the list of clear vent widths (RCC box) or span lengths (slab/girder) "
            "in millimetres. Levels are in metres (RL/FL/BL/HFL). span_type must be one of: "
            "'rcc_box', 'psc_slab', 'psc_girder', 'box_girder', 'steel_girder', 'fob' — pick it from "
            "the prompt text (RCC box / PSC slab / PSC girder / box girder / steel girder / foot over "
            "bridge). Convert metric text like '4.25 m' to 4250 mm. If a value is not mentioned, use null."
        )
        try:
            raw = ai.chat(system, text, max_tokens=2000)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(raw[start:end + 1])
                return cls.from_dict(data)
        except Exception:
            pass
        return cls.from_prompt(text)


_AI_SCHEMA_EXAMPLE = {
    "bridge_no": "3KK",
    "span_description": "(1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX",
    "span_type": "rcc_box",
    "cells_mm": [4250, 4500, 4250],
    "clear_height_mm": 1500,
    "num_tracks": 2,
    "track_centres_mm": 9450,
    "rail_level_m": 178.741,
    "formation_level_m": 177.979,
    "bed_level_m": 175.877,
    "hfl_m": 176.877,
    "top_slab_thk_mm": 350,
    "bottom_slab_thk_mm": 350,
    "wall_thk_mm": 350,
    "wearing_coat_mm": 150,
    "levelling_course_mm": 150,
    "foundation_depth_mm": 1000,
    "barrel_length_mm": 0,
    "deck_width_mm": 0,
    "project": "PROPOSED DOUBLING BETWEEN DORNAKAL - BHADRACHALAM ROAD STATIONS",
    "section": "DORNAKAL - BHADRACHALAM ROAD SECTION",
    "division": "SECUNDERABAD DIVISION",
    "chainage": "17178.982",
    "loading": "25T-2008",
    "scale": "1:100",
    "drawing_no": "",
    "date": "",
    "notes": [],
}

DEFAULT_STANDARD_NOTES = [
    "ALL THE DIMENSIONS ARE IN mm AND THE DRAWING SHALL NOT BE SCALED.",
    "RCC BOX AS PER DESIGN.",
    "WEEP HOLES & BACK FILLING BEHIND ABUTMENT AND RETURNS AS PER STANDARD DRAWING.",
    "BACK FILL MATERIAL AS PER CLAUSE 7.5 OF IRS BRIDGE SUB-STRUCTURE CODE 2013 (REVISED) WITH LATEST ACS.",
    "DEPTH OF FOUNDATION SHOWN IN THIS DRAWING IS TENTATIVE; THE ACTUAL DEPTH SHALL BE DECIDED BY ENGINEER-IN-CHARGE.",
    "MAX. FOUNDATION PRESSURE SHOWN TO BE ENSURED BY ENGINEER AT SITE.",
    "LEGEND: EXISTING WORKS SHOWN IN BLACK, PROPOSED WORKS IN RED, DISMANTLING IN DOTTED YELLOW.",
]

# ─────────────────────────────────────────────────────────────────────────────
# Geometry templates
# ─────────────────────────────────────────────────────────────────────────────

def _rcc_box_views(inp: GadInput, ents: list, sec_ox: float) -> None:
    cells, n = inp.cells_mm, len(inp.cells_mm)
    wt, ts, bs = inp.wall_thk_mm, inp.top_slab_thk_mm, inp.bottom_slab_thk_mm
    wc, lc = inp.wearing_coat_mm, inp.levelling_course_mm
    ch = inp.clear_height_mm
    total_w = inp.barrel_len()
    fd = inp.foundation_depth_mm

    bed_y = 0.0
    rail_y = (inp.rail_level_m - inp.bed_level_m) * 1000 if inp.rail_level_m and inp.bed_level_m else 3000.0
    form_y = (inp.formation_level_m - inp.bed_level_m) * 1000 if inp.formation_level_m and inp.bed_level_m else rail_y - 800.0
    hfl_y = (inp.hfl_m - inp.bed_level_m) * 1000 if inp.hfl_m and inp.bed_level_m else None
    scour_y = (inp.scour_level_m - inp.bed_level_m) * 1000 if inp.scour_level_m and inp.bed_level_m else None

    box_top = form_y - wc if form_y else (rail_y - 800 - wc)
    box_bottom = box_top - (ts + ch + bs + lc)

    # Foundation goes below bed, and below scour when scour is given.
    if scour_y is not None and scour_y < 0:
        fd = max(fd, -scour_y)
    fbottom = bed_y - fd

    def wall_x(i: int) -> float:
        """x of the left face of wall i (0..n)."""
        return i * wt + sum(cells[:i])

    # ── longitudinal section ────────────────────────────────────────────────
    # bed / ground
    add_line(ents, "HATCHING", -4200, bed_y, total_w + 4200, bed_y)
    add_line(ents, "HATCHING", -4200, bed_y - 300, total_w + 4200, bed_y - 300)
    for x in range(-4200, int(total_w) + 4200, 1200):
        add_line(ents, "HATCHING", x, bed_y, x - 300, bed_y - 300)

    # HFL line + scour line + foundation level
    if hfl_y is not None:
        add_line(ents, "CENTRELINES", -4200, hfl_y, total_w + 4200, hfl_y)
    if scour_y is not None and scour_y < 0:
        add_line(ents, "CENTRELINES", -4200, scour_y, total_w + 4200, scour_y)
    add_line(ents, "CENTRELINES", -4200, fbottom, total_w + 4200, fbottom)

    # PCC / foundation (levels-driven: from box bottom / bed down to foundation level)
    f_top = min(box_bottom, bed_y)
    add_rect(ents, "HATCHING", -900, fbottom, total_w + 1800, f_top - fbottom)
    if box_bottom > bed_y:
        add_rect(ents, "HATCHING", -600, bed_y, total_w + 1200, box_bottom - bed_y)  # earth fill

    # box
    add_rect(ents, "GEOMETRY", 0, box_top - ts, total_w, ts)                  # top slab
    add_rect(ents, "GEOMETRY", 0, box_bottom + lc, total_w, bs)               # bottom slab
    add_rect(ents, "GEOMETRY", 0, box_top, total_w, wc)                       # wearing coat
    add_rect(ents, "GEOMETRY", 0, box_bottom, total_w, lc)                    # levelling course
    for i in range(n + 1):
        x = wall_x(i)
        add_line(ents, "GEOMETRY", x, box_bottom + lc + bs, x, box_top - ts)  # walls

    # return walls + coping (outside the barrel at both ends)
    rw_h = max(box_top, rail_y - 1200)
    for ex in (0, total_w):
        sign = -1 if ex == 0 else 1
        x0 = ex - 2600 if ex == 0 else ex          # wall outer face
        add_rect(ents, "GEOMETRY", x0, bed_y, 2600, rw_h - bed_y)
        add_rect(ents, "GEOMETRY", x0 - 150, rw_h - 150, 2600 + 300, 150)  # coping
        add_line(ents, "HATCHING", x0, rw_h, x0 + sign * 3600, box_top + 400)  # backfill slope

    # pitching + toe wall
    for ex in (0, total_w):
        sign = -1 if ex == 0 else 1
        x0 = ex + sign * 2600
        add_line(ents, "HATCHING", x0, bed_y, x0 + sign * 5200, bed_y - 2600)  # 2:1 slope
        add_rect(ents, "GEOMETRY", x0 + sign * 5200 - sign * 300, bed_y - 2200, 900, 2200)

    # rail / formation lines
    add_line(ents, "CENTRELINES", -3800, rail_y, total_w + 3800, rail_y)
    add_line(ents, "CENTRELINES", -3800, form_y, total_w + 3800, form_y)

    # level markers
    add_level_marker(ents, -4200, rail_y, f"RL: {inp.rail_level_m:.3f}")
    add_level_marker(ents, -4200, form_y, f"FL: {inp.formation_level_m:.3f}")
    add_level_marker(ents, -4200, bed_y, f"BL: {inp.bed_level_m:.3f}")
    if hfl_y is not None:
        fb = (form_y - hfl_y) / 1000.0 if form_y else 0.0
        lbl = f"HFL: {inp.hfl_m:.3f}" + (f"   F.B. = {fb:.3f} m" if fb > 0 else "")
        add_level_marker(ents, -4200, hfl_y, lbl)
    if scour_y is not None and scour_y < 0:
        add_level_marker(ents, -4200, scour_y, f"MAX SCOUR: {inp.scour_level_m:.3f}")
    add_level_marker(ents, -4200, fbottom, f"FOUNDATION LEVEL: {(inp.bed_level_m or 0) - fd / 1000.0:.3f}")

    # dimensions
    add_dim(ents, 0, total_w, bed_y - 1500, f"{round(total_w)}")
    x = 0.0
    for c in cells:
        add_dim(ents, x + wt, x + wt + c, bed_y - 2200, f"{round(c)}")
        x += wt + c
    add_dim(ents, 0, total_w, box_top - ts - ch - 1200, f"CLEAR HT {round(ch)}", above=False)
    # construction height stack (right side)
    sx = total_w + 2200
    stack = [(wc, "WEARING COAT"), (ts, "TOP SLAB"), (ch, "CLEAR HEIGHT"),
             (bs, "BOTTOM SLAB"), (lc, "LEVELLING COURSE")]
    yy = box_top
    for thk, name in stack:
        add_line(ents, "DIMENSIONS", sx, yy - thk, sx + 900, yy - thk)
        add_line(ents, "DIMENSIONS", sx, yy, sx + 900, yy)
        add_line(ents, "DIMENSIONS", sx, yy - thk, sx, yy)
        add_text(ents, "ANNOTATIONS", sx + 1200, yy - thk / 2, f"{name} {round(thk)}", height=280, center=False)
        yy -= thk

    # ── cross-section (half) ─────────────────────────────────────────────────
    sec = []
    deck = inp.deck_w()
    add_rect(sec, "GEOMETRY", 0, box_top - ts, deck, ts)
    add_rect(sec, "GEOMETRY", 0, box_bottom + lc, deck, bs)
    add_rect(sec, "GEOMETRY", 0, box_top, deck, wc)
    add_rect(sec, "GEOMETRY", 0, box_bottom, deck, lc)
    for i in range(n + 1):
        x = i * wt + sum(cells[:i])
        add_line(sec, "GEOMETRY", x, box_bottom + lc + bs, x, box_top - ts)
    add_line(sec, "HATCHING", 0, bed_y, deck, bed_y)
    add_line(sec, "CENTRELINES", 0, form_y, deck, form_y)
    add_line(sec, "CENTRELINES", 0, rail_y, deck, rail_y)

    # track (multi-track aware)
    tc = inp.track_centres_mm or 0
    if inp.num_tracks > 1 and tc:
        centres = [deck / 2 + (i - (inp.num_tracks - 1) / 2) * tc for i in range(inp.num_tracks)]
    else:
        centres = [deck / 2]
    for c in centres:
        add_line(sec, "CENTRELINES", c, rail_y - 2600, c, rail_y)
        add_line(sec, "SYMBOLS", c - 1100, rail_y, c + 1100, rail_y)          # rail foot
        add_line(sec, "SYMBOLS", c - 700, rail_y - 172, c + 700, rail_y - 172)
        add_line(sec, "SYMBOLS", c - 1250, rail_y - 382, c + 1250, rail_y - 382)  # sleeper
    if len(centres) > 1:
        add_dim(sec, centres[0], centres[1], rail_y + 1500, f"C/C {round(tc)}", above=True)

    add_level_marker(sec, deck + 1400, rail_y, f"RL: {inp.rail_level_m:.3f}")
    add_level_marker(sec, deck + 1400, form_y, f"FL: {inp.formation_level_m:.3f}")
    add_level_marker(sec, deck + 1400, bed_y, f"BL: {inp.bed_level_m:.3f}")
    add_dim(sec, 0, deck, bed_y - 1500, f"DECK WIDTH {round(deck)}")
    add_dim(sec, 0, deck, box_top - ts - ch - 1200, f"CLEAR HT {round(ch)}")
    if inp.num_tracks > 1 and tc:
        add_dim(sec, centres[0], centres[1], rail_y + 1500, f"C/C {round(tc)}", above=True)
    x = 0.0
    for c in cells:
        add_dim(sec, x + wt, x + wt + c, box_bottom - 2200, f"{round(c)}")
        x += wt + c
    add_text(sec, "ANNOTATIONS", deck / 2, box_bottom - 3200,
             "SECTION THROUGH BOX", height=350, center=True)

    # ── plan (half plan top / bottom) ────────────────────────────────────────
    plan = []
    add_rect(plan, "GEOMETRY", 0, 0, total_w, deck)                      # box outline
    for i in range(1, n):
        x = wall_x(i)
        add_line(plan, "GEOMETRY", x, 0, x, deck)
    tc2 = inp.track_centres_mm or 0
    if inp.num_tracks > 1 and tc2:
        ctrs = [deck / 2 + (i - (inp.num_tracks - 1) / 2) * tc2 for i in range(inp.num_tracks)]
    else:
        ctrs = [deck / 2]
    for c in ctrs:
        add_line(plan, "CENTRELINES", -2600, c, total_w + 2600, c)
    for ex in (0, total_w):
        sign = -1 if ex == 0 else 1
        x0 = ex - 2600 if ex == 0 else ex
        add_rect(plan, "GEOMETRY", x0, -600, 2600, deck + 1200)  # returns
        add_poly(plan, "HATCHING",
                 [(ex + sign * 2600, -2600), (ex + sign * 7800, -2600),
                  (ex + sign * 7800, 0), (ex + sign * 2600, 0)], closed=True)         # pitching
    add_poly(plan, "SYMBOLS", [(total_w / 2 - 1600, deck + 1600),
                               (total_w / 2 - 1600, deck + 700),
                               (total_w / 2 + 1600, deck + 700)], closed=True)
    add_poly(plan, "SYMBOLS", [(total_w / 2 - 1200, deck + 700),
                               (total_w / 2 + 1200, deck + 700),
                               (total_w / 2, deck - 100)], closed=True)
    add_text(plan, "ANNOTATIONS", total_w / 2, deck + 2400, "FLOW", height=350, center=True)
    add_dim(plan, 0, total_w, -3200, f"BARREL LENGTH {round(total_w)}")
    add_dim(plan, -3200, -3200, 0, "", above=True)
    add_text(plan, "ANNOTATIONS", total_w / 2, -4500, "PLAN", height=350, center=True)

    # lay out views: longitudinal at origin, section right of the title block,
    # plan below
    plan_oy = -14500
    ents.extend(translate(sec, sec_ox, 0))
    ents.extend(translate(plan, 0, plan_oy))
    ents.extend(translate(sec, sec_ox, plan_oy))


def _psc_slab_views(inp: GadInput, ents: list, sec_ox: float) -> None:
    """Simple PSC slab / girder: elevation (span(s) on abutments/pier), section, plan."""
    span = (inp.cells_mm[0] if inp.cells_mm else 9150)
    n = len(inp.cells_mm) or 1
    slab = inp.girder_depth_mm or max(500.0, span / 13.0)
    wc = inp.wearing_coat_mm
    deck = inp.deck_w()

    bed_y = 0.0
    rail_y = (inp.rail_level_m - inp.bed_level_m) * 1000 if inp.rail_level_m and inp.bed_level_m else 3000.0
    form_y = (inp.formation_level_m - inp.bed_level_m) * 1000 if inp.formation_level_m and inp.bed_level_m else rail_y - 800.0
    hfl_y = (inp.hfl_m - inp.bed_level_m) * 1000 if inp.hfl_m and inp.bed_level_m else None
    slab_top = form_y - wc if form_y else (rail_y - 900)
    total = span * n

    # ── elevation ────────────────────────────────────────────────────────────
    add_line(ents, "HATCHING", -4000, bed_y, total + 4000, bed_y)
    add_rect(ents, "HATCHING", -500, bed_y - 800, total + 1000, 800)
    if hfl_y is not None:
        add_line(ents, "CENTRELINES", -4000, hfl_y, total + 4000, hfl_y)
    add_rect(ents, "GEOMETRY", 0, slab_top - slab, total, slab)          # slab
    add_rect(ents, "GEOMETRY", 0, slab_top, total, wc)                   # wearing coat
    for i in range(n + 1):
        x = i * span
        if i == 0 or i == n:
            w, h = 1500, slab_top - bed_y                                # abutment
        else:
            w, h = 1200, slab_top - bed_y                                # pier
        add_rect(ents, "GEOMETRY", x - w / 2, bed_y, w, h)
        add_rect(ents, "SYMBOLS", x - 400, slab_top - slab, 800, 250)    # bearing
    add_line(ents, "CENTRELINES", -3600, rail_y, total + 3600, rail_y)
    add_line(ents, "CENTRELINES", -3600, form_y, total + 3600, form_y)
    add_level_marker(ents, -4000, rail_y, f"RL: {inp.rail_level_m:.3f}")
    add_level_marker(ents, -4000, form_y, f"FL: {inp.formation_level_m:.3f}")
    add_level_marker(ents, -4000, bed_y, f"BL: {inp.bed_level_m:.3f}")
    if hfl_y is not None:
        add_level_marker(ents, -4000, hfl_y, f"HFL: {inp.hfl_m:.3f}")
    add_dim(ents, 0, total, bed_y - 1500, f"OVERALL {round(total)}")
    for i in range(n):
        add_dim(ents, i * span, (i + 1) * span, bed_y - 2200, f"{round(span)}")
    add_text(ents, "ANNOTATIONS", total / 2, slab_top - slab - 1600, "ELEVATION", height=350)

    # ── section ──────────────────────────────────────────────────────────────
    sec = []
    add_rect(sec, "GEOMETRY", 0, slab_top - slab, deck, slab)
    add_rect(sec, "GEOMETRY", 0, slab_top, deck, wc)
    add_line(sec, "HATCHING", 0, bed_y, deck, bed_y)
    add_line(sec, "CENTRELINES", 0, form_y, deck, form_y)
    add_line(sec, "CENTRELINES", 0, rail_y, deck, rail_y)
    c = deck / 2
    add_line(sec, "CENTRELINES", c, rail_y - 2600, c, rail_y)
    add_line(sec, "SYMBOLS", c - 1100, rail_y, c + 1100, rail_y)
    add_line(sec, "SYMBOLS", c - 1250, rail_y - 382, c + 1250, rail_y - 382)
    add_level_marker(sec, deck + 1400, rail_y, f"RL: {inp.rail_level_m:.3f}")
    add_level_marker(sec, deck + 1400, form_y, f"FL: {inp.formation_level_m:.3f}")
    add_level_marker(sec, deck + 1400, bed_y, f"BL: {inp.bed_level_m:.3f}")
    add_dim(sec, 0, deck, bed_y - 1500, f"DECK WIDTH {round(deck)}")
    add_text(sec, "ANNOTATIONS", deck / 2, slab_top - slab - 1600, "SECTION", height=350)

    # ── plan ─────────────────────────────────────────────────────────────────
    plan = []
    add_rect(plan, "GEOMETRY", 0, 0, total, deck)
    add_line(plan, "CENTRELINES", -2600, deck / 2, total + 2600, deck / 2)
    for i in range(n + 1):
        x = i * span
        if i == 0 or i == n:
            add_rect(plan, "GEOMETRY", x - 750, -600, 1500, deck + 1200)
        else:
            add_rect(plan, "GEOMETRY", x - 600, -400, 1200, deck + 800)
    add_dim(plan, 0, total, -3200, f"OVERALL {round(total)}")
    add_text(plan, "ANNOTATIONS", total / 2, -4500, "PLAN", height=350)

    plan_oy = -14500
    ents.extend(translate(sec, sec_ox, 0))
    ents.extend(translate(plan, 0, plan_oy))
    ents.extend(translate(sec, sec_ox, plan_oy))


def _girder_views(inp: GadInput, ents: list, sec_ox: float) -> None:
    """PSC / box / steel girder family: deck slab on girders between supports."""
    span = (inp.cells_mm[0] if inp.cells_mm else 9150)
    n = len(inp.cells_mm) or 1
    gd = inp.girder_depth_mm or max(1000.0, span / 10.0)
    deck_slab = 300.0
    wc = inp.wearing_coat_mm
    ng = max(1, inp.num_girders or 2)
    deck = inp.deck_w()

    bed_y = 0.0
    rail_y = (inp.rail_level_m - inp.bed_level_m) * 1000 if inp.rail_level_m and inp.bed_level_m else 3000.0
    form_y = (inp.formation_level_m - inp.bed_level_m) * 1000 if inp.formation_level_m and inp.bed_level_m else rail_y - 900.0
    hfl_y = (inp.hfl_m - inp.bed_level_m) * 1000 if inp.hfl_m and inp.bed_level_m else None
    slab_top = form_y - wc if form_y else (rail_y - 900)
    girder_bottom = slab_top - deck_slab - gd
    total = span * n

    # ── elevation ────────────────────────────────────────────────────────────
    add_line(ents, "HATCHING", -4000, bed_y, total + 4000, bed_y)
    add_rect(ents, "HATCHING", -500, bed_y - 1000, total + 1000, 1000)
    if hfl_y is not None:
        add_line(ents, "CENTRELINES", -4000, hfl_y, total + 4000, hfl_y)
    add_rect(ents, "GEOMETRY", 0, slab_top, total, wc)                      # wearing coat
    add_rect(ents, "GEOMETRY", 0, slab_top - deck_slab, total, deck_slab)   # deck slab
    for i in range(n):
        gx = i * span + 350
        add_rect(ents, "GEOMETRY", gx, girder_bottom, gd, gd)               # girder
        add_rect(ents, "SYMBOLS", gx - 250, slab_top - deck_slab, 500, 200)  # bearing
    for i in range(n + 1):
        x = i * span
        if i == 0 or i == n:
            w, h = 1600, slab_top - bed_y                                    # abutment
        else:
            w, h = 1300, slab_top - bed_y                                    # pier
        add_rect(ents, "GEOMETRY", x - w / 2, bed_y, w, h)
    add_line(ents, "CENTRELINES", -3600, rail_y, total + 3600, rail_y)
    add_line(ents, "CENTRELINES", -3600, form_y, total + 3600, form_y)
    add_level_marker(ents, -4000, rail_y, f"RL: {inp.rail_level_m:.3f}")
    add_level_marker(ents, -4000, form_y, f"FL: {inp.formation_level_m:.3f}")
    add_level_marker(ents, -4000, bed_y, f"BL: {inp.bed_level_m:.3f}")
    if hfl_y is not None:
        add_level_marker(ents, -4000, hfl_y, f"HFL: {inp.hfl_m:.3f}")
    add_dim(ents, 0, total, bed_y - 1500, f"OVERALL {round(total)}")
    for i in range(n):
        add_dim(ents, i * span, (i + 1) * span, bed_y - 2200, f"{round(span)}")
    add_dim(ents, 0, total, slab_top - deck_slab - gd - 1400, f"GIRDER DEPTH {round(gd)}", above=False)
    add_text(ents, "ANNOTATIONS", total / 2, girder_bottom - 1900, "ELEVATION", height=350)

    # ── section ──────────────────────────────────────────────────────────────
    sec = []
    add_rect(sec, "GEOMETRY", 0, slab_top, deck, wc)
    add_rect(sec, "GEOMETRY", 0, slab_top - deck_slab, deck, deck_slab)
    for j in range(ng):
        gx = deck * (j + 1) / (ng + 1) - 220
        add_rect(sec, "GEOMETRY", gx, girder_bottom, 440, gd)
    add_line(sec, "HATCHING", 0, bed_y, deck, bed_y)
    add_line(sec, "CENTRELINES", 0, form_y, deck, form_y)
    add_line(sec, "CENTRELINES", 0, rail_y, deck, rail_y)
    c = deck / 2
    add_line(sec, "CENTRELINES", c, rail_y - 2600, c, rail_y)
    add_line(sec, "SYMBOLS", c - 1100, rail_y, c + 1100, rail_y)
    add_line(sec, "SYMBOLS", c - 1250, rail_y - 382, c + 1250, rail_y - 382)
    add_level_marker(sec, deck + 1400, rail_y, f"RL: {inp.rail_level_m:.3f}")
    add_level_marker(sec, deck + 1400, form_y, f"FL: {inp.formation_level_m:.3f}")
    add_level_marker(sec, deck + 1400, bed_y, f"BL: {inp.bed_level_m:.3f}")
    add_dim(sec, 0, deck, bed_y - 1500, f"DECK WIDTH {round(deck)}")
    add_text(sec, "ANNOTATIONS", deck / 2, girder_bottom - 1900, "SECTION", height=350)

    # ── plan ────────────────────────────────────────────────────────────────
    plan = []
    add_rect(plan, "GEOMETRY", 0, 0, total, deck)
    for j in range(ng):
        gy = deck * (j + 1) / (ng + 1)
        add_line(plan, "CENTRELINES", 0, gy, total, gy)
    for i in range(n + 1):
        x = i * span
        if i == 0 or i == n:
            add_rect(plan, "GEOMETRY", x - 800, -700, 1600, deck + 1400)
        else:
            add_rect(plan, "GEOMETRY", x - 650, -500, 1300, deck + 1000)
    add_dim(plan, 0, total, -3400, f"OVERALL {round(total)}")
    add_text(plan, "ANNOTATIONS", total / 2, -4700, "PLAN", height=350)

    plan_oy = -14500
    ents.extend(translate(sec, sec_ox, 0))
    ents.extend(translate(plan, 0, plan_oy))
    ents.extend(translate(sec, sec_ox, plan_oy))


def _fob_views(inp: GadInput, ents: list, sec_ox: float) -> None:
    """Foot over bridge: elevated walkway deck on abutments with handrails."""
    span = (inp.cells_mm[0] if inp.cells_mm else 9150)
    n = len(inp.cells_mm) or 1
    deck_w = inp.deck_w() or 2400
    deck_thk = 150.0
    rail_h = 1200.0
    total = span * n

    bed_y = 0.0
    rail_y = (inp.rail_level_m - inp.bed_level_m) * 1000 if inp.rail_level_m and inp.bed_level_m else 5000.0
    deck_top = rail_y - 2500 if rail_y else 4000.0   # walkway below rail level

    # elevation
    add_line(ents, "HATCHING", -3000, bed_y, total + 3000, bed_y)
    add_rect(ents, "GEOMETRY", 0, deck_top - deck_thk, total, deck_thk)
    for i in range(n + 1):
        x = i * span
        w = 1200 if (i == 0 or i == n) else 900
        add_rect(ents, "GEOMETRY", x - w / 2, bed_y, w, deck_top - bed_y)
    # handrails
    for x in range(0, int(total) + 1, 2000):
        add_line(ents, "SYMBOLS", x, deck_top, x, deck_top + rail_h)
    add_line(ents, "SYMBOLS", 0, deck_top + rail_h, total, deck_top + rail_h)
    add_level_marker(ents, -3200, deck_top, f"DECK RL: {(inp.rail_level_m - 2.5) if inp.rail_level_m else 0:.3f}")
    add_level_marker(ents, -3200, bed_y, f"BL: {inp.bed_level_m:.3f}")
    add_dim(ents, 0, total, bed_y - 1500, f"OVERALL {round(total)}")
    for i in range(n):
        add_dim(ents, i * span, (i + 1) * span, bed_y - 2200, f"{round(span)}")
    add_text(ents, "ANNOTATIONS", total / 2, deck_top + rail_h + 900, "FOB - ELEVATION", height=350)

    # section
    sec = []
    add_rect(sec, "GEOMETRY", 0, deck_top - deck_thk, deck_w, deck_thk)
    add_line(sec, "SYMBOLS", 0, deck_top, 0, deck_top + rail_h)
    add_line(sec, "SYMBOLS", deck_w, deck_top, deck_w, deck_top + rail_h)
    add_line(sec, "SYMBOLS", -150, deck_top + rail_h, deck_w + 150, deck_top + rail_h)
    add_line(sec, "HATCHING", 0, bed_y, deck_w, bed_y)
    add_dim(sec, 0, deck_w, bed_y - 1500, f"DECK WIDTH {round(deck_w)}")
    add_text(sec, "ANNOTATIONS", deck_w / 2, deck_top + rail_h + 900, "SECTION", height=350)

    # plan
    plan = []
    add_rect(plan, "GEOMETRY", 0, 0, total, deck_w)
    for i in range(n + 1):
        x = i * span
        if i == 0 or i == n:
            add_rect(plan, "GEOMETRY", x - 600, -400, 1200, deck_w + 800)
        else:
            add_rect(plan, "GEOMETRY", x - 450, -300, 900, deck_w + 600)
    add_dim(plan, 0, total, -3200, f"OVERALL {round(total)}")
    add_text(plan, "ANNOTATIONS", total / 2, -4500, "PLAN", height=350)

    plan_oy = -14500
    ents.extend(translate(sec, sec_ox, 0))
    ents.extend(translate(plan, 0, plan_oy))
    ents.extend(translate(sec, sec_ox, plan_oy))


def _dynamic_notes(inp: GadInput) -> list:
    """Engineering-rule notes derived from the dynamic levels."""
    out = []
    if inp.scour_level_m and inp.bed_level_m and inp.scour_level_m < inp.bed_level_m:
        out.append(f"MAX SCOUR LEVEL: {inp.scour_level_m:.3f} m — FOUNDATION SHALL BE TAKEN BELOW SCOUR.")
    if inp.hfl_m and inp.formation_level_m:
        fb = inp.formation_level_m - inp.hfl_m
        out.append(f"FREE BOARD PROVIDED: {fb:.3f} m (FL - HFL)." if fb > 0
                   else f"WARNING: FORMATION BELOW HFL — FREE BOARD NOT PROVIDED ({fb:.3f} m).")
    if inp.span_type == "rcc_box" and inp.formation_level_m and inp.bed_level_m:
        avail = (inp.formation_level_m - inp.bed_level_m) * 1000
        stack = inp.stack_height()
        if stack > avail:
            out.append(f"WARNING: BOX STACK {round(stack)} mm EXCEEDS DEPTH BELOW FORMATION "
                       f"{round(avail)} mm — CHECK BOX HEIGHT / LEVELS.")
    if inp.type_key:
        out.append(f"SPAN TYPE: {inp.type_key.upper().replace('_', ' ')}.")
    return out


def _title_block(inp: GadInput, ents: list) -> None:
    """Standard drawing title block, bottom-right of the sheet."""
    x0, y0, w, h = 30000, 0, 11000, 7600
    add_rect(ents, "BORDER", x0, y0, w, h)
    rows = [
        ("GENERAL ARRANGEMENT DRAWING", 900),
        (f"BRIDGE No. {inp.bridge_no}", 600),
        (inp.span_description or (inp.span_type.upper().replace("_", " ")), 500),
        (inp.project or "", 450),
        (f"SECTION: {inp.section}" if inp.section else "", 450),
        (f"DIVISION: {inp.division}" if inp.division else "", 450),
        (f"CHAINAGE: {inp.chainage} m" if inp.chainage else "", 450),
        (f"SCALE {inp.scale}      LOADING: {inp.loading}", 450),
        (f"DRAWING No: {inp.drawing_no}" if inp.drawing_no else "", 450),
        (f"DATE: {inp.date}" if inp.date else "", 450),
        ("APPROVED BY: ______________________    DRAWN BY: ______________________", 400),
    ]
    yy = y0 + h - 500
    for label, size in rows:
        if label:
            add_text(ents, "TITLEBLOCK", x0 + w / 2, yy, label, height=size)
        yy -= 640


def _notes(inp: GadInput, ents: list) -> None:
    """Standard + drawing-specific + dynamic (levels-derived) notes."""
    notes = list(DEFAULT_STANDARD_NOTES if not inp.standard_notes else inp.standard_notes)
    notes = notes + inp.notes + _dynamic_notes(inp)
    x, y, gap = 1200, 27500, 700
    add_text(ents, "ANNOTATIONS", x, y + 300, "NOTES:", height=500, center=False)
    for i, note in enumerate(notes):
        add_text(ents, "ANNOTATIONS", x, y - (i + 1) * gap, f"{i+1}. {note}", height=380, center=False)


def _add_border(ents: list) -> None:
    """Wrap every drawing with a border sized to its own content, so any
    combination of levels / spans / family fits the sheet at 1:1."""
    xs, ys = [], []
    for e in ents:
        if e["type"] == "line":
            xs += [e["x1"], e["x2"]]; ys += [e["y1"], e["y2"]]
        elif e["type"] == "polyline":
            xs += [p[0] for p in e["points"]]; ys += [p[1] for p in e["points"]]
        elif e["type"] == "circle":
            xs += [e["x"] - e["r"], e["x"] + e["r"]]; ys += [e["y"] - e["r"], e["y"] + e["r"]]
        elif e["type"] == "text":
            xs += [e["x"]]; ys += [e["y"]]
    if not xs:
        add_rect(ents, "BORDER", 0, 0, 1000, 1000)
        return
    m = 2200
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    add_rect(ents, "BORDER", x0 - m, y0 - m, (x1 - x0) + 2 * m, (y1 - y0) + 2 * m)


def build_entities(inp: GadInput) -> list:
    resolve_defaults(inp)
    ents: list = []
    total = inp.barrel_len()
    deck = inp.deck_w()
    # Cross-section sits clear of the title block (x 30000..41000).
    sec_ox = max(total + 6000, 43000)
    if inp.span_type in ("psc_girder", "box_girder", "steel_girder"):
        _girder_views(inp, ents, sec_ox)
    elif inp.span_type == "fob":
        _fob_views(inp, ents, sec_ox)
    elif inp.span_type == "psc_slab":
        _psc_slab_views(inp, ents, sec_ox)
    else:
        _rcc_box_views(inp, ents, sec_ox)
    _title_block(inp, ents)
    _notes(inp, ents)
    _add_border(ents)
    return ents


# ─────────────────────────────────────────────────────────────────────────────
# Writers — DXF (ezdxf) and AutoLISP (entmake)
# ─────────────────────────────────────────────────────────────────────────────

LAYER_DEFS = [
    ("GEOMETRY", 7, "Structural lines and shapes"),
    ("DIMENSIONS", 3, "Dimension lines and values"),
    ("CENTRELINES", 1, "Centre lines"),
    ("ANNOTATIONS", 2, "Labels, notes, titles"),
    ("HATCHING", 8, "Hatch / fill region outlines"),
    ("ELEVATIONS", 3, "RL/FL/BL level markers"),
    ("SYMBOLS", 6, "Symbols and markers"),
    ("BORDER", 5, "Drawing border"),
    ("TITLEBLOCK", 4, "Title block information"),
]

_ACI = {"GEOMETRY": 7, "DIMENSIONS": 3, "CENTRELINES": 1, "ANNOTATIONS": 2,
        "HATCHING": 8, "ELEVATIONS": 3, "SYMBOLS": 6, "BORDER": 5, "TITLEBLOCK": 4}


def write_dxf(ents: list, path: str) -> None:
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    for name, color, _desc in LAYER_DEFS:
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    msp = doc.modelspace()
    for e in ents:
        layer = e["layer"]
        try:
            if e["type"] == "line":
                msp.add_line((e["x1"], e["y1"]), (e["x2"], e["y2"]), dxfattribs={"layer": layer})
            elif e["type"] == "polyline":
                msp.add_lwpolyline(e["points"], close=e.get("closed", False),
                                   dxfattribs={"layer": layer})
            elif e["type"] == "circle":
                msp.add_circle((e["x"], e["y"]), e["r"], dxfattribs={"layer": layer})
            elif e["type"] == "text":
                t = msp.add_text(e["text"], dxfattribs={"layer": layer, "height": e["height"]})
                if e.get("center"):
                    t.set_placement((e["x"], e["y"]), align=TextEntityAlignment.MIDDLE_CENTER)
                else:
                    t.set_placement((e["x"], e["y"]), align=TextEntityAlignment.LEFT)
        except Exception:
            continue
    doc.saveas(path)


def _lisp_esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def write_lisp(ents: list, path: str, bridge_no: str = "") -> None:
    """Emit AutoLISP that rebuilds the drawing natively in AutoCAD via entmake.
    Load the file and run (BES-GAD)."""
    L = []
    a = L.append
    a("; ═══════════════════════════════════════════════════════════════")
    a("; Bridge Engineering Suite v2.0 — GAD Generator (parametric)")
    a(f"; Bridge No. : {bridge_no}")
    a("; Generated  : parametric template — do not hand-edit geometry")
    a("; Units      : mm at 1:1 — plot at the drawing scale")
    a("; USAGE      : load this file in AutoCAD, then type: BES-GAD")
    a("; ═══════════════════════════════════════════════════════════════")
    a("(defun BES-GAD-LAYER (name col /)")
    a('  (if (not (tblsearch "LAYER" name))')
    a("    (entmake (list (cons 0 \"LAYER\") (cons 100 \"AcDbSymbolTableRecord\")")
    a("                   (cons 100 \"AcDbLayerTableRecord\") (cons 2 name)")
    a("                   (cons 70 0) (cons 62 col))))")
    a(")")
    a("(defun BES-GAD-LINE (la x1 y1 x2 y2 /)")
    a('  (entmake (list (cons 0 "LINE") (cons 8 la)')
    a("                  (cons 10 (list x1 y1 0.0)) (cons 11 (list x2 y2 0.0)))))")
    a("(defun BES-GAD-PLINE (la pts closed /)")
    a('  (entmake (append (list (cons 0 "LWPOLYLINE") (cons 100 "AcDbEntity")')
    a('                       (cons 100 "AcDbPolyline") (cons 8 la) (cons 90 (length pts)))')
    a("                  (mapcar (function (lambda (p) (cons 10 p))) pts)")
    a('                  (list (cons 70 (if closed 1 0))))))')
    a("(defun BES-GAD-CIRC (la x y r /)")
    a('  (entmake (list (cons 0 "CIRCLE") (cons 8 la)')
    a("                  (cons 10 (list x y 0.0)) (cons 40 r))))")
    a("(defun BES-GAD-TEXT (la x y h s /)")
    a('  (entmake (list (cons 0 "TEXT") (cons 8 la) (cons 10 (list x y 0.0))')
    a("                  (cons 40 h) (cons 1 s))))")
    a("(defun BES-GAD-DRAW (/ i e pts)")
    a("  (BES-GAD-LAYER \"GEOMETRY\" 7)   (BES-GAD-LAYER \"DIMENSIONS\" 3)")
    a("  (BES-GAD-LAYER \"CENTRELINES\" 1)(BES-GAD-LAYER \"ANNOTATIONS\" 2)")
    a("  (BES-GAD-LAYER \"HATCHING\" 8)   (BES-GAD-LAYER \"ELEVATIONS\" 3)")
    a("  (BES-GAD-LAYER \"SYMBOLS\" 6)    (BES-GAD-LAYER \"BORDER\" 5)")
    a('  (BES-GAD-LAYER "TITLEBLOCK" 4)')
    for e in ents:
        layer = e["layer"]
        if e["type"] == "line":
            a(f'  (BES-GAD-LINE "{layer}" {e["x1"]:.2f} {e["y1"]:.2f} {e["x2"]:.2f} {e["y2"]:.2f})')
        elif e["type"] == "polyline":
            pts = " ".join(f"(list {x:.2f} {y:.2f})" for x, y in e["points"])
            a(f'  (setq pts (list {pts}))')
            a(f'  (BES-GAD-PLINE "{layer}" pts {("T" if e.get("closed") else "nil")})')
        elif e["type"] == "circle":
            a(f'  (BES-GAD-CIRC "{layer}" {e["x"]:.2f} {e["y"]:.2f} {e["r"]:.2f})')
        elif e["type"] == "text":
            a(f'  (BES-GAD-TEXT "{layer}" {e["x"]:.2f} {e["y"]:.2f} {e["height"]:.2f} "{_lisp_esc(e["text"])}")')
    a("  (princ \"\\nGAD drawn — check layers, then plot at scale.\")")
    a("  (princ)")
    a(")")
    a("(defun c:BES-GAD () (BES-GAD-DRAW))")
    a("(princ \"\\nGAD Generator loaded — type BES-GAD to draw.\")")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Preview rendering — lightweight PIL rasteriser so the app can show the
# drawing without any CAD application (rendered straight from the entity
# model; no DXF round-trip required).
# ─────────────────────────────────────────────────────────────────────────────

_PREVIEW_COLORS = {
    "GEOMETRY": (0, 0, 0), "DIMENSIONS": (0, 130, 0), "CENTRELINES": (180, 30, 30),
    "ANNOTATIONS": (140, 110, 0), "HATCHING": (120, 120, 120), "ELEVATIONS": (0, 130, 0),
    "SYMBOLS": (180, 0, 180), "BORDER": (0, 0, 200), "TITLEBLOCK": (0, 120, 140),
}


def render_png(ents: list, path: Optional[str] = None, width_px: int = 2200,
               margin: int = 80) -> bytes:
    """Rasterise generated entities to a PNG (white sheet, layer colours).
    Returns PNG bytes; writes the file too when *path* is given."""
    from PIL import Image, ImageDraw, ImageFont

    xs, ys = [], []
    for e in ents:
        if e["type"] == "line":
            xs += [e["x1"], e["x2"]]; ys += [e["y1"], e["y2"]]
        elif e["type"] == "polyline":
            xs += [p[0] for p in e["points"]]; ys += [p[1] for p in e["points"]]
        elif e["type"] == "circle":
            xs += [e["x"] - e["r"], e["x"] + e["r"]]; ys += [e["y"] - e["r"], e["y"] + e["r"]]
        elif e["type"] == "text":
            xs += [e["x"]]; ys += [e["y"]]
    if not xs:
        xs, ys = [0, 1000], [0, 1000]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    span = max(x1 - x0, y1 - y0, 1)
    s = (width_px - 2 * margin) / span
    H = int((y1 - y0) * s + 2 * margin)
    W = int((x1 - x0) * s + 2 * margin)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    def P(x: float, y: float):
        return (int((x - x0) * s + margin), int(H - ((y - y0) * s + margin)))

    try:
        font = ImageFont.load_default(size=max(10, int(350 * s * 0.9)))
    except TypeError:  # very old Pillow without scalable default font
        font = None

    for e in ents:
        col = _PREVIEW_COLORS.get(e["layer"], (0, 0, 0))
        try:
            if e["type"] == "line":
                d.line([P(e["x1"], e["y1"]), P(e["x2"], e["y2"])], fill=col, width=1)
            elif e["type"] == "polyline":
                pts = [P(*p) for p in e["points"]]
                if e.get("closed") and len(pts) > 2:
                    pts.append(pts[0])
                d.line(pts, fill=col, width=1, joint="curve")
            elif e["type"] == "circle":
                cx, cy = P(e["x"], e["y"])
                r = int(e["r"] * s)
                d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=1)
            elif e["type"] == "text":
                tx, ty = P(e["x"], e["y"])
                d.text((tx, ty), e["text"], fill=col, font=font,
                       anchor="mm" if e.get("center") else "lm")
        except Exception:
            continue
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    if path:
        with open(path, "wb") as fh:
            fh.write(data)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate(inp: GadInput, out_dir: str, name: Optional[str] = None) -> dict:
    """Build the drawing and write .dxf + .lsp. Returns output info dict."""
    resolve_defaults(inp)
    os.makedirs(out_dir, exist_ok=True)
    base = name or f"{inp.bridge_no or 'GAD'}-GAD"
    dxf_path = os.path.join(out_dir, f"{base}.dxf")
    lsp_path = os.path.join(out_dir, f"{base}.lsp")
    preview_path = os.path.join(out_dir, f"{base}-preview.png")
    ents = build_entities(inp)
    write_dxf(ents, dxf_path)
    write_lisp(ents, lsp_path, bridge_no=inp.bridge_no)
    counts: dict = {}
    for e in ents:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    preview_png = render_png(ents, preview_path, width_px=2400)
    return {"dxf": dxf_path, "lsp": lsp_path, "preview": preview_path,
            "preview_png": preview_png, "entities": counts, "total": len(ents),
            "input": asdict(inp)}
