"""
tests/test_gad_elevation.py — GAD Generator phase-1 Elevation tests.

Covers:
  * core/cell_sheet.py    — Excel-like formula engine
  * core/gad_elevation.py — the phase-2 elevation drawing rules:
      - BL is datum (y=0), lengths/heights drawn in mm
      - BL line length = 5 x Linear Span
      - FL line at (FL-BL)x1000, RL line at (RL-FL)x1000 above FL
      - all three horizontal lines equal length
      - one vertical central line in the middle crossing all three
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pytest
except ImportError:                      # minimal shim — suite runs w/o pytest
    class _Approx:
        def __init__(self, expected):
            self.expected = float(expected)

        def __eq__(self, actual):
            return math.isclose(float(actual), self.expected, rel_tol=1e-6,
                                abs_tol=1e-9)

        def __repr__(self):
            return f"approx({self.expected})"

    class pytest:                        # noqa: N801 — shim only
        approx = staticmethod(_Approx)

        @staticmethod
        def raises(exc):
            class _Ctx:
                def __enter__(self):
                    return self

                def __exit__(self, et, ev, tb):
                    if et is None:
                        raise AssertionError(f"{exc.__name__} not raised")
                    return issubclass(et, exc)
            return _Ctx()

        @staticmethod
        def main(args):
            return 0

from core.cell_sheet import (
    CellSheet, SheetError, collect_grid, extract_described_values,
    grid_label,
)
from core.gad_elevation import (
    ElevationInput, build_elevation, elevation_from_sheet, values_from_text,
)


# ═════════════════════════════════════════════════════════════════════════════
# cell_sheet — formula engine
# ═════════════════════════════════════════════════════════════════════════════

class TestCellSheet:
    def test_plain_numbers(self):
        sh = CellSheet({"B1": "178.741", "B2": "1000"})
        assert sh.value("B1") == pytest.approx(178.741)
        assert sh.value("B2") == pytest.approx(1000.0)

    def test_arithmetic_formulas(self):
        sh = CellSheet({"A1": "4.25", "B1": "=A1*1000", "C1": "=B1+250",
                        "D1": "=B1/2", "E1": "=B1^2"})
        assert sh.value("B1") == pytest.approx(4250.0)
        assert sh.value("C1") == pytest.approx(4500.0)
        assert sh.value("D1") == pytest.approx(2125.0)
        assert sh.value("E1") == pytest.approx(4250.0 ** 2)

    def test_cell_chain(self):
        sh = CellSheet({"B1": "178.741", "B2": "=B1-0.762", "B3": "=B2-B1"})
        assert sh.value("B2") == pytest.approx(177.979)
        assert sh.value("B3") == pytest.approx(-0.762)

    def test_functions(self):
        sh = CellSheet({"A1": "1", "A2": "2", "A3": "3"})
        assert sh.value("=SUM(A1:A3)") == pytest.approx(6.0)
        assert sh.value("=AVERAGE(A1:A3)") == pytest.approx(2.0)
        assert sh.value("=MIN(A1:A3)") == pytest.approx(1.0)
        assert sh.value("=MAX(A1:A3)") == pytest.approx(3.0)
        assert sh.value("=SUM(A1:A3, 4)") == pytest.approx(10.0)
        assert sh.value("=ABS(-5)") == pytest.approx(5.0)
        assert sh.value("=ROUND(3.14159, 2)") == pytest.approx(3.14)
        assert sh.value("=SQRT(16)") == pytest.approx(4.0)

    def test_if_and_compare(self):
        sh = CellSheet({"A1": "5"})
        assert sh.value("=IF(A1>0, 10, 20)") == pytest.approx(10.0)
        assert sh.value("=IF(A1<0, 10, 20)") == pytest.approx(20.0)
        assert sh.value("=IF(A1=5, 1, 0)") == pytest.approx(1.0)
        assert sh.value("=IF(A1<>5, 1, 0)") == pytest.approx(0.0)
        assert sh.value("=IF(A1>=5, 1, 0)") == pytest.approx(1.0)

    def test_percent(self):
        sh = CellSheet({"A1": "200"})
        assert sh.value("=A1*5%") == pytest.approx(10.0)

    def test_precedence_and_parens(self):
        assert CellSheet().value("=2+3*4") == pytest.approx(14.0)
        assert CellSheet().value("=(2+3)*4") == pytest.approx(20.0)
        assert CellSheet().value("=-2+6") == pytest.approx(4.0)

    def test_circular_reference(self):
        sh = CellSheet({"A1": "=A1+1"})
        with pytest.raises(SheetError):
            sh.value("A1")

    def test_cycle_through_cells(self):
        sh = CellSheet({"A1": "=B1", "B1": "=A1"})
        with pytest.raises(SheetError):
            sh.value("A1")

    def test_bad_formula(self):
        sh = CellSheet({"A1": "=1 +"})
        with pytest.raises(SheetError):
            sh.value("A1")

    def test_unknown_function(self):
        with pytest.raises(SheetError):
            CellSheet().value("=NOSUCHFN(1)")

    def test_text_cell_is_zero(self):
        sh = CellSheet({"A1": "RL:"})
        assert sh.value("A1") == 0.0
        assert sh.value_or_none("A1") is None

    def test_empty_is_zero(self):
        assert CellSheet().value("B2") == 0.0

    def test_value_or_none(self):
        sh = CellSheet({"A1": "", "A2": "3.5", "A3": "=oops"})
        assert sh.value_or_none("A1") is None
        assert sh.value_or_none("A2") == 3.5
        assert sh.value_or_none("A3") is None   # broken formula -> None

    def test_grid_label(self):
        assert grid_label(0, 0) == "A1"
        assert grid_label(1, 0) == "B1"
        assert grid_label(1, 2) == "B3"
        assert grid_label(9, 3) == "J4"

    def test_collect_grid(self):
        grid = [["RL:", "178.741", "", ""],
                ["", "", "", ""],
                ["FL:", "", "177.979", ""],
                ["", "", "", ""]]
        sh = collect_grid(grid)
        assert sh.get_display("A1") == "RL:"
        assert sh.value("B1") == pytest.approx(178.741)
        assert sh.value("C3") == pytest.approx(177.979)


# ═════════════════════════════════════════════════════════════════════════════
# extract_described_values — value sitting against each description
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractDescribedValues:
    def test_value_right_of_label(self):
        sh = CellSheet({"A1": "RL:", "B1": "178.741",
                        "A2": "FL:", "B2": "177.979",
                        "A3": "HFL:", "B3": "176.877",
                        "A4": "BED LEVEL(BL):", "B4": "175.877"})
        vals = extract_described_values(sh, {
            "RL": "RL:", "FL": "FL:", "HFL": "HFL:", "BL": "BED LEVEL(BL):"})
        assert vals["RL"] == pytest.approx(178.741)
        assert vals["FL"] == pytest.approx(177.979)
        assert vals["HFL"] == pytest.approx(176.877)
        assert vals["BL"] == pytest.approx(175.877)

    def test_value_same_cell_as_label(self):
        sh = CellSheet({"A1": "RL: 178.741", "B1": "x"})
        vals = extract_described_values(sh, {"RL": "RL:"})
        assert vals["RL"] == pytest.approx(178.741)

    def test_value_below_label(self):
        sh = CellSheet({"A1": "FL:", "A2": "177.979"})
        vals = extract_described_values(sh, {"FL": "FL:"})
        assert vals["FL"] == pytest.approx(177.979)

    def test_formula_against_label(self):
        sh = CellSheet({"A1": "RL:", "B1": "178.741",
                        "A2": "FL:", "B2": "=B1-0.762"})
        vals = extract_described_values(sh, {"RL": "RL:", "FL": "FL:"})
        assert vals["FL"] == pytest.approx(177.979)

    def test_missing_label(self):
        sh = CellSheet({"A1": "RL:", "B1": "1"})
        vals = extract_described_values(sh, {"HFL": "HFL:"})
        assert vals["HFL"] is None


# ═════════════════════════════════════════════════════════════════════════════
# gad_elevation — input assembly
# ═════════════════════════════════════════════════════════════════════════════

class TestElevationInput:
    def test_derived_geometry(self):
        inp = ElevationInput(rail_level_m=178.741, formation_level_m=177.979,
                             hfl_m=176.877, bed_level_m=175.877,
                             linear_span_m=4.25)
        assert inp.bl_len_mm == pytest.approx(21250.0)   # 5 x 4.25 m
        assert inp.fl_offset_mm == pytest.approx(2102.0)  # (177.979-175.877)*1000
        assert inp.rl_offset_mm == pytest.approx(762.0)   # (178.741-177.979)*1000
        assert inp.validate() == []

    def test_validate_rejects_bad_levels(self):
        inp = ElevationInput(formation_level_m=174.0, bed_level_m=175.877,
                             linear_span_m=4.25)
        errs = inp.validate()
        assert any("FL" in e for e in errs)

    def test_values_from_text(self):
        text = ("EXG. R.L. 181.654\nEXG. F.L 160.311\nHFL: 176.877\n"
                "BED LEVEL(BL): 175.877\nLinear Span: 4.25 m")
        vals = values_from_text(text)
        assert vals["BL"] == pytest.approx(175.877)
        assert vals["HFL"] == pytest.approx(176.877)
        assert vals["Linear Span"] == pytest.approx(4.25)

    def test_elevation_from_sheet(self):
        sh = CellSheet({
            "A1": "RL:", "B1": "178.741",
            "A2": "FL:", "B2": "177.979",
            "A3": "HFL:", "B3": "176.877",
            "A4": "BED LEVEL(BL):", "B4": "175.877",
            "C1": "Linear Span:", "D1": "4.25",
        })
        inp = elevation_from_sheet(sh)
        assert inp.rail_level_m == pytest.approx(178.741)
        assert inp.linear_span_m == pytest.approx(4.25)


# ═════════════════════════════════════════════════════════════════════════════
# gad_elevation — drawing rules (phase 2)
# ═════════════════════════════════════════════════════════════════════════════

SAMPLE = ElevationInput(rail_level_m=178.741, formation_level_m=177.979,
                        hfl_m=176.877, bed_level_m=175.877,
                        linear_span_m=4.25)


def _hlines(ents, layer):
    """Horizontal line entities (y1 == y2) on a layer."""
    return [e for e in ents if e["type"] == "line" and e["layer"] == layer
            and abs(e["y1"] - e["y2"]) < 1e-9]


def _vlines(ents, layer):
    return [e for e in ents if e["type"] == "line" and e["layer"] == layer
            and abs(e["x1"] - e["x2"]) < 1e-9]


class TestBuildElevation:
    def test_three_level_lines_same_length_5x_span(self):
        ents = build_elevation(SAMPLE)
        fl_y = SAMPLE.fl_offset_mm
        rl_y = fl_y + SAMPLE.rl_offset_mm
        for y in (0.0, fl_y, rl_y):
            seg = [e for e in _hlines(ents, "GEOMETRY")
                   if abs(e["y1"] - y) < 1e-6]
            assert seg, f"no horizontal level line at y={y}"
            length = seg[0]["x2"] - seg[0]["x1"]
            assert length == pytest.approx(SAMPLE.bl_len_mm)

    def test_bl_line_at_datum(self):
        ents = build_elevation(SAMPLE)
        assert any(abs(e["y1"]) < 1e-9 for e in _hlines(ents, "GEOMETRY"))

    def test_central_line_crosses_all_three(self):
        ents = build_elevation(SAMPLE)
        fl_y = SAMPLE.fl_offset_mm
        rl_y = fl_y + SAMPLE.rl_offset_mm
        xm = SAMPLE.bl_len_mm / 2.0
        cl = [e for e in _vlines(ents, "CENTRELINES")
              if abs(e["x1"] - xm) < 1e-6 and (e["y2"] - e["y1"]) > 100]
        assert cl, "no vertical central line at mid-span"
        top, bot = max(e["y2"] for e in cl), min(e["y1"] for e in cl)
        for y in (0.0, fl_y, rl_y):
            assert bot < y < top, f"central line misses level y={y}"

    def test_labels_present(self):
        ents = build_elevation(SAMPLE)
        texts = [e["text"] for e in ents if e["type"] == "text"]
        joined = " | ".join(texts)
        assert "CENTRAL LINE" in joined
        assert "Pro. Formation Level" in joined
        assert "B.L." in joined and "175.877" in joined
        assert "R.L." in joined and "178.741" in joined

    def test_offsets_are_in_mm(self):
        ents = build_elevation(SAMPLE)
        texts = [e["text"] for e in ents if e["type"] == "text"]
        assert any("2102" in t for t in texts)    # (FL-BL) x 1000
        assert any("762" in t for t in texts)     # (RL-FL) x 1000
        assert any("21250" in t for t in texts)   # 5 x span

    def test_hfl_line_when_given(self):
        ents = build_elevation(SAMPLE)
        hfl_y = (176.877 - 175.877) * 1000.0
        seg = [e for e in _hlines(ents, "CENTRELINES")
               if abs(e["y1"] - hfl_y) < 1e-6 and (e["x2"] - e["x1"]) > 1000]
        assert seg, "HFL line missing"

    def test_no_hfl_line_when_zero(self):
        inp = ElevationInput(rail_level_m=178.741, formation_level_m=177.979,
                             hfl_m=0.0, bed_level_m=175.877,
                             linear_span_m=4.25)
        ents = build_elevation(inp)
        assert "H.F.L." not in " ".join(
            e["text"] for e in ents if e["type"] == "text")


# ═════════════════════════════════════════════════════════════════════════════
# Full pipeline: generate DXF + LISP + preview PNG
# ═════════════════════════════════════════════════════════════════════════════

class TestGenerateElevation:
    def test_generate_writes_files(self, tmp_path):
        from core.gad_elevation import generate_elevation
        res = generate_elevation(SAMPLE, str(tmp_path), name="T-ELEV")
        for key in ("dxf", "lsp", "preview", "preview_png", "entities"):
            assert key in res
        assert os.path.isfile(res["dxf"])
        assert os.path.isfile(res["lsp"])
        assert os.path.isfile(res["preview"])
        lsp = open(res["lsp"], encoding="utf-8").read()
        assert "BES-GAD-ELEV" in lsp          # custom command name
        assert "(defun c:BES-GAD-ELEV ()" in lsp

    def test_write_lisp_default_command_unchanged(self, tmp_path):
        from core.gad_generator import write_lisp
        p = os.path.join(tmp_path, "x.lsp")
        write_lisp([], str(p), bridge_no="3KK")
        assert "c:BES-GAD" in open(str(p), encoding="utf-8").read()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
