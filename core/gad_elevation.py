"""
core/gad_elevation.py — GAD "Elevation" phase-1 view builder
═══════════════════════════════════════════════════════════════

First of the GAD Generator's phase-wise builders (Elevation / Plan / Section /
Wing & Return Wall / Square Return).  Everything is driven by five user
values, entered in the GUI's 10x4 excel-like grid (with formulas) or extracted
from an uploaded Excel / PDF / image:

    RL            rail level, metres          (e.g. 178.741)
    FL            formation level, metres     (e.g. 177.979)
    HFL           high flood level, metres    (e.g. 176.877)
    Linear Span   span in metres              (e.g. 4.25  -> 4250 mm)
    BL            bed level, metres           (e.g. 175.877)  ← datum

Drawing rules (from the user's step-by-step spec):

  * BL is the datum: y = 0 at bed level.
  * Units: levels are entered in metres, but every drawn height / length /
    dimension appears in millimetres (metres x 1000).
  * Draw a horizontal BL line at datum.  Length = 5 x Linear Span (mm).
  * Draw the "Pro. Formation Level" line at offset (FL - BL) x 1000 above BL.
  * Draw the RL line at offset (RL - FL) x 1000 above the FL line.
  * All three horizontal lines are the same length (= BL line length).
  * Draw one vertical line in the middle intersecting all three lines,
    labelled "CENTRAL LINE".
  * Label each line with its description and the level value.

Outputs the same entity-dict model as core/gad_generator.py so the standard
writers (write_dxf / write_lisp / render_png) can be reused directly.
"""

from __future__ import annotations

import base64
import io
import math
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

from core.cell_sheet import CellSheet, extract_described_values

# ─────────────────────────────────────────────────────────────────────────────
# Input model
# ─────────────────────────────────────────────────────────────────────────────

# Output key -> label spellings accepted in the sheet / extraction prompts.
LEVEL_FIELDS: Dict[str, str] = {
    "RL": "RL:",
    "FL": "FL:",
    "HFL": "HFL:",
    "Linear Span": "Linear Span:",
    "BL": "BED LEVEL(BL):",
}

_LABEL_ALIASES: Dict[str, tuple] = {
    "RL": ("RL", "RAIL LEVEL", "RAILLEVEL", "EXGRL", "EXG R L"),
    "FL": ("FL", "FORMATION LEVEL", "FORMATIONLEVEL", "PROFORMATIONLEVEL",
           "PRO FORMATION LEVEL", "PROPOSED FORMATION LEVEL"),
    "HFL": ("HFL", "H F L", "HIGH FLOOD LEVEL", "HIGHFLOODLEVEL"),
    "Linear Span": ("LINEARSPAN", "LINEAR SPAN", "SPAN", "LINEARSPANM", "SPANM"),
    "BL": ("BL", "BEDLEVEL", "BED LEVEL", "BEDLEVELBL", "BEDLEVELBL"),
}


@dataclass
class ElevationInput:
    """The five numbers the elevation needs (levels m, span m)."""
    rail_level_m: float = 0.0
    formation_level_m: float = 0.0
    hfl_m: float = 0.0
    bed_level_m: float = 0.0
    linear_span_m: float = 0.0
    bridge_no: str = ""                 # optional, for the title
    notes: list = field(default_factory=list)

    # ── geometry (mm, BL datum = 0) ──────────────────────────────────────────
    @property
    def bl_len_mm(self) -> float:
        """Length of the BL/FL/RL horizontal lines = 5 x Linear Span."""
        return 5.0 * self.linear_span_m * 1000.0

    @property
    def fl_offset_mm(self) -> float:
        """(FL - BL) x 1000 — height of FL line above BL line."""
        return (self.formation_level_m - self.bed_level_m) * 1000.0

    @property
    def rl_offset_mm(self) -> float:
        """(RL - FL) x 1000 — height of RL line above FL line."""
        return (self.rail_level_m - self.formation_level_m) * 1000.0

    def validate(self) -> list:
        errs = []
        if self.linear_span_m <= 0:
            errs.append("Linear Span must be > 0 (metres).")
        if self.bed_level_m == 0:
            errs.append("BED LEVEL(BL) is required — it is the datum.")
        if self.formation_level_m <= self.bed_level_m:
            errs.append("FL must be above BL ((FL-BL) x 1000 draws the FL line).")
        if self.rail_level_m <= self.formation_level_m:
            errs.append("RL must be above FL ((RL-FL) x 1000 draws the RL line).")
        if self.hfl_m and self.hfl_m >= self.rail_level_m:
            errs.append("HFL is above RL — check the values.")
        return errs


# ─────────────────────────────────────────────────────────────────────────────
# Sheet -> ElevationInput
# ─────────────────────────────────────────────────────────────────────────────

def elevation_from_sheet(sheet: CellSheet) -> ElevationInput:
    """Resolve the five values from the 10x4 grid.

    The value that matters is whatever sits against each description — same
    cell after the text, the cell to the right, or (for compact layouts) the
    cell directly below.  Formulas are honoured via CellSheet.
    """
    vals = extract_described_values(sheet, LEVEL_FIELDS)
    return ElevationInput(
        rail_level_m=float(vals.get("RL") or 0.0),
        formation_level_m=float(vals.get("FL") or 0.0),
        hfl_m=float(vals.get("HFL") or 0.0),
        bed_level_m=float(vals.get("BL") or 0.0),
        linear_span_m=float(vals.get("Linear Span") or 0.0),
    )


# ─────────────────────────────────────────────────────────────────────────────
# File upload -> raw text -> ElevationInput  (Excel / PDF / image)
# ─────────────────────────────────────────────────────────────────────────────

def read_file_text(path: str) -> str:
    """Best-effort extraction of text from .xlsx/.xls/.csv/.pdf/.txt.

    Images and anything binary are returned empty — those go through the AI
    vision path instead (see extract_values_ai).
    """
    ext = (path.rsplit(".", 1)[-1] if "." in path else "").lower()
    if ext in ("xlsx", "xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        lines = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                if any(c.strip() for c in cells):
                    lines.append(" | ".join(cells).strip(" |"))
        return "\n".join(lines)
    if ext == "xls":
        import xlrd
        book = xlrd.open_workbook(path)
        lines = []
        for si in range(book.nsheets):
            sh = book.sheet_by_index(si)
            for r in range(sh.nrows):
                cells = [str(sh.cell_value(r, c)) for c in range(sh.ncols)]
                if any(c.strip() for c in cells):
                    lines.append(" | ".join(cells).strip(" |"))
        return "\n".join(lines)
    if ext == "csv" or ext == "txt":
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if ext == "pdf":
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(path)
            return "\n".join(page.get_text() for page in doc)
        except Exception:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return "\n".join((p.extract_text() or "") for p in pdf.pages)
    return ""


_LEVEL_RE_TMPL = r"(?:{aliases})\s*[:=\s]\s*(-?\d+(?:\.\d+)?)"


def values_from_text(text: str) -> Dict[str, Optional[float]]:
    """Regex-extract the five values from raw text (Excel dump / PDF text)."""
    out: Dict[str, Optional[float]] = {
        "RL": None, "FL": None, "HFL": None, "Linear Span": None, "BL": None,
    }
    if not text:
        return out

    def grab(*aliases: str) -> Optional[float]:
        # longest alias first so 'BED LEVEL(BL)' wins over 'BL'
        for a in sorted(aliases, key=len, reverse=True):
            m = re.search(_LEVEL_RE_TMPL.format(aliases=a), text, re.I)
            if m:
                return float(m.group(1))
        return None

    out["RL"] = grab(r"RL", r"RAIL LEVEL", r"EXG\.?\s?R\.?\s?L\.?")
    out["FL"] = grab(r"FL", r"FORMATION LEVEL", r"PRO\.?\s?FORMATION LEVEL")
    out["HFL"] = grab(r"HFL", r"HIGH FLOOD LEVEL")
    out["BL"] = grab(r"BED LEVEL\s*\(?BL\)?", r"BED LEVEL", r"(?<!F)(?<!H)(?<!R)BL")
    m = re.search(r"(?:LINEAR\s*SPAN|SPAN)\s*[:=\s]\s*(\d+(?:\.\d+)?)\s*(?:m\b)?",
                  text, re.I)
    if m:
        out["Linear Span"] = float(m.group(1))
    return out


def elevation_from_file(path: str) -> tuple:
    """Extract the five values from an Excel/CSV/PDF file.

    Returns (ElevationInput, warnings: list[str])."""
    text = read_file_text(path)
    if not text.strip():
        return ElevationInput(), ["No readable text found in the file — "
                                  "enter the values in the grid instead."]
    vals = values_from_text(text)
    missing = [k for k, v in vals.items() if v is None]
    inp = ElevationInput(
        rail_level_m=vals["RL"] or 0.0,
        formation_level_m=vals["FL"] or 0.0,
        hfl_m=vals["HFL"] or 0.0,
        bed_level_m=vals["BL"] or 0.0,
        linear_span_m=vals["Linear Span"] or 0.0,
    )
    warns = []
    if missing:
        warns.append("Not found in file: " + ", ".join(missing)
                     + " — fill them in the grid.")
    return inp, warns


def extract_values_ai(path: str, ai: Any) -> tuple:
    """AI vision path for images/scans (and stubborn PDFs).

    Returns (values dict, warnings)."""
    ext = (path.rsplit(".", 1)[-1] if "." in path else "").lower()
    system = (
        "You extract bridge survey values from drawings, tables or scans. "
        "Return ONLY a JSON object with keys 'RL', 'FL', 'HFL', 'Linear Span', "
        "'BL' — all numbers: levels in metres, Linear Span in metres. Use null "
        "when a value is not present. No prose, no markdown fences."
    )
    user = ("Read the rail level (RL), formation level (FL), high flood level "
            "(HFL), linear span and bed level (BL). Return the JSON object.")
    data = None
    if ext in ("png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"):
        from PIL import Image
        img = Image.open(path)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        raw = ai.vision(system, b64, "image/png", user, max_tokens=500)
    else:
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        raw = ai.vision_pdf(system, b64, user, max_tokens=500)
    try:
        import json
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(raw[start:end + 1])
    except Exception:
        data = None
    if not isinstance(data, dict):
        return ({"RL": None, "FL": None, "HFL": None,
                 "Linear Span": None, "BL": None},
                ["AI could not read the values — enter them in the grid."])

    def num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    vals = {k: num(data.get(k)) for k in
            ("RL", "FL", "HFL", "Linear Span", "BL")}
    missing = [k for k, v in vals.items() if v is None]
    warns = (["AI could not read: " + ", ".join(missing)
              + " — fill them in the grid."] if missing else [])
    return vals, warns


# ─────────────────────────────────────────────────────────────────────────────
# Entity helpers (same model as core/gad_generator.py)
# ─────────────────────────────────────────────────────────────────────────────

def _line(ents, layer, x1, y1, x2, y2):
    ents.append({"type": "line", "layer": layer,
                 "x1": x1, "y1": y1, "x2": x2, "y2": y2})


def _text(ents, layer, x, y, text, height=300.0, center=True):
    ents.append({"type": "text", "layer": layer, "x": x, "y": y,
                 "text": str(text), "height": float(height), "center": center})


def _level_marker(ents, x, y, label, height=300.0):
    """Triangle marker pointing up at the level line + label to the left."""
    pts = [(x - 240, y), (x + 240, y), (x, y + 280)]
    ents.append({"type": "polyline", "layer": "SYMBOLS", "closed": True,
                 "points": pts})
    _text(ents, "ELEVATIONS", x - 420, y + 150, label, height=height,
          center=False)


def _vertical_dim(ents, x, y1, y2, value):
    """Vertical dimension with ticks + value text beside the line."""
    t = 200
    _line(ents, "DIMENSIONS", x, y1, x + t, y1 + t)
    _line(ents, "DIMENSIONS", x, y1, x - t, y1 + t)
    _line(ents, "DIMENSIONS", x, y2, x + t, y2 - t)
    _line(ents, "DIMENSIONS", x, y2, x - t, y2 - t)
    _text(ents, "DIMENSIONS", x + 320, (y1 + y2) / 2.0, value, height=280,
          center=False)


# ─────────────────────────────────────────────────────────────────────────────
# The phase-2 elevation builder
# ─────────────────────────────────────────────────────────────────────────────

TEXT_H = 300.0          # label text height (mm)
TICK = 400.0            # end-tick extension of horizontal lines


def build_elevation(inp: ElevationInput) -> list:
    """Build the phase-2 elevation entities (BL datum, mm at 1:1)."""
    ents: list = []

    bl_len = inp.bl_len_mm                 # 5 x Linear Span (mm)
    fl_y = inp.fl_offset_mm                # (FL - BL) x 1000
    rl_y = fl_y + inp.rl_offset_mm         # (RL - FL) x 1000 above FL
    hfl_y = (inp.hfl_m - inp.bed_level_m) * 1000.0 if inp.hfl_m else None

    x0, x1 = 0.0, bl_len
    xm = bl_len / 2.0

    # ── 1. BL line at datum ─────────────────────────────────────────────────
    _line(ents, "GEOMETRY", x0, 0.0, x1, 0.0)
    for ex in (x0, x1):
        _line(ents, "SYMBOLS", ex, 0.0, ex - TICK if ex == x1 else ex, 0.0)
    _level_marker(ents, x0, 0.0, f"B.L. {inp.bed_level_m:.3f}")

    # ── 2. Pro. Formation Level line at (FL-BL)x1000 ────────────────────────
    _line(ents, "GEOMETRY", x0, fl_y, x1, fl_y)
    _level_marker(ents, x0, fl_y, f"Pro. Formation Level {inp.formation_level_m:.3f}")

    # ── 3. RL line at (RL-FL)x1000 above FL ─────────────────────────────────
    _line(ents, "GEOMETRY", x0, rl_y, x1, rl_y)
    _level_marker(ents, x0, rl_y, f"R.L. {inp.rail_level_m:.3f}")

    # ── HFL line (when provided) — dashed look via CENTRELINES layer ────────
    if hfl_y is not None and hfl_y < rl_y:
        _line(ents, "CENTRELINES", x0, hfl_y, x1, hfl_y)
        _level_marker(ents, x0, hfl_y, f"H.F.L. {inp.hfl_m:.3f}")

    # ── 4. Central line in the middle, crossing all three lines ─────────────
    over = max(1200.0, (rl_y - 0.0) * 0.10)
    under = max(1200.0, fl_y * 0.25 if fl_y else 1200.0)
    _line(ents, "CENTRELINES", xm, -under, xm, rl_y + over)
    _text(ents, "ANNOTATIONS", xm + 300, rl_y + over + TEXT_H * 1.4,
          "CENTRAL LINE", height=TEXT_H, center=False)

    # ── vertical offset dimensions (right end, in mm) ────────────────────────
    dx = x1 + 1400
    _line(ents, "DIMENSIONS", dx, 0.0, dx, rl_y)          # extension line
    if fl_y:
        _vertical_dim(ents, dx, 0.0, fl_y, f"{round(fl_y)}")
    if inp.rl_offset_mm:
        _vertical_dim(ents, dx + 900, fl_y, rl_y, f"{round(inp.rl_offset_mm)}")
    # overall RL above BL
    _vertical_dim(ents, dx + 1800, 0.0, rl_y, f"{round(rl_y)}")

    # ── horizontal span dimension under the BL line (mm) ────────────────────
    dy = -under - 1200
    t = 260
    _line(ents, "DIMENSIONS", x0, dy, x1, dy)
    for xx in (x0, x1):
        _line(ents, "DIMENSIONS", xx, dy, xx, dy + 900)
        _line(ents, "DIMENSIONS", xx, dy, xx - t, dy + t)
        _line(ents, "DIMENSIONS", xx, dy, xx + t, dy + t)
    _text(ents, "DIMENSIONS", xm, dy + 300,
          f"5 x {inp.linear_span_m:g} m = {round(bl_len)}", height=320)

    # ── title ────────────────────────────────────────────────────────────────
    title = "ELEVATION"
    if inp.bridge_no:
        title = f"ELEVATION — BRIDGE NO {inp.bridge_no}"
    _text(ents, "ANNOTATIONS", xm, rl_y + over + TEXT_H * 3.2, title,
          height=450)

    return ents


# ─────────────────────────────────────────────────────────────────────────────
# Public generate() — reuses the standard writers from core/gad_generator
# ─────────────────────────────────────────────────────────────────────────────

def generate_elevation(inp: ElevationInput, out_dir: str,
                       name: Optional[str] = None) -> dict:
    """Build the elevation and write .dxf + .lsp + preview .png."""
    import os

    from core.gad_generator import render_png, write_dxf, write_lisp

    os.makedirs(out_dir, exist_ok=True)
    base = name or (f"{inp.bridge_no or 'GAD'}-Elevation")
    ents = build_elevation(inp)
    dxf_path = os.path.join(out_dir, f"{base}.dxf")
    lsp_path = os.path.join(out_dir, f"{base}.lsp")
    png_path = os.path.join(out_dir, f"{base}-preview.png")
    write_dxf(ents, dxf_path)
    write_lisp(ents, lsp_path, bridge_no=inp.bridge_no or "GAD",
               command_name="BES-GAD-ELEV")
    counts: Dict[str, int] = {}
    for e in ents:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return {"dxf": dxf_path, "lsp": lsp_path, "preview": png_path,
            "preview_png": render_png(ents, png_path, width_px=2400),
            "entities": counts, "total": len(ents),
            "input": asdict(inp)}


if __name__ == "__main__":
    # Self-test with the sample values from the user's reference drawing
    demo = ElevationInput(rail_level_m=178.741, formation_level_m=177.979,
                          hfl_m=176.877, bed_level_m=175.877,
                          linear_span_m=4.25)
    assert abs(demo.bl_len_mm - 21250.0) < 1e-6
    assert abs(demo.fl_offset_mm - 2102.0) < 1e-6
    assert abs(demo.rl_offset_mm - 762.0) < 1e-6
    ents = build_elevation(demo)
    lines = [e for e in ents if e["type"] == "line"]
    texts = {e["text"] for e in ents if e["type"] == "text"}
    # three level lines share the same length
    for y in (0.0, demo.fl_offset_mm, demo.fl_offset_mm + demo.rl_offset_mm):
        seg = [e for e in lines if e["layer"] == "GEOMETRY"
               and abs(e["y1"] - y) < 1e-6 and abs(e["y2"] - y) < 1e-6]
        assert seg and abs(seg[0]["x2"] - seg[0]["x1"] - 21250.0) < 1e-6, y
    # central line crosses the middle
    cl = [e for e in lines if e["layer"] == "CENTRELINES"
          and abs((e["x1"] + e["x2"]) / 2 - 10625.0) < 1e-6
          and abs(e["y1"] - e["y2"]) > 1]
    assert cl, "central line missing"
    assert any("CENTRAL LINE" in t for t in texts)
    assert any("Pro. Formation Level" in t for t in texts)
    errs = demo.validate()
    assert not errs, errs
    print(f"gad_elevation self-test PASSED ({len(ents)} entities)")
