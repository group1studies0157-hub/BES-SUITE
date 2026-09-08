"""
Unit tests for the Bore Log → DXF integration in Bridge Engineering Suite.

Covers:
  - Data model (BoreholeRecord, SoilLayer, TestRecord)
  - Soil classification (soil_classify)
  - Grid parsing (table_common)
  - DXF builder end-to-end
  - BorelogPanel import and sys.path wiring
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so gui.* and borelog_dxf.* resolve
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_BORELOG_DIR = os.path.join(_ROOT, "bes_borelog")
if _BORELOG_DIR not in sys.path:
    sys.path.insert(0, _BORELOG_DIR)

from borelog_dxf.model import BoreholeRecord, SoilLayer, TestRecord  # noqa: E402
from borelog_dxf.soil_classify import classify, style_for, classify_and_style, HATCH_STYLE  # noqa: E402
from borelog_dxf.table_common import find_header_columns, parse_grid  # noqa: E402
from borelog_dxf.dxf_builder import BoreLogDxfBuilder  # noqa: E402


# ===================================================================
# 1. Data Model Tests
# ===================================================================
class TestSoilLayer(unittest.TestCase):
    def test_thickness(self):
        layer = SoilLayer(0.0, 3.5, "Clay")
        self.assertAlmostEqual(layer.thickness, 3.5)

    def test_thickness_zero(self):
        layer = SoilLayer(2.0, 2.0, "")
        self.assertAlmostEqual(layer.thickness, 0.0)

    def test_description_default(self):
        layer = SoilLayer(0.0, 1.0)
        self.assertEqual(layer.description, "")


class TestTestRecord(unittest.TestCase):
    def test_defaults(self):
        t = TestRecord(5.0)
        self.assertEqual(t.depth, 5.0)
        self.assertEqual(t.note, "")
        self.assertEqual(t.density, "")
        self.assertEqual(t.sample_type, "")

    def test_full_record(self):
        t = TestRecord(3.0, note="N=43", density="V.Dense", sample_type="DS")
        self.assertEqual(t.note, "N=43")
        self.assertEqual(t.density, "V.Dense")
        self.assertEqual(t.sample_type, "DS")


class TestBoreholeRecord(unittest.TestCase):
    def test_total_depth_from_layers(self):
        bh = BoreholeRecord(
            location="BH-01",
            layers=[SoilLayer(0, 5, "Clay"), SoilLayer(5, 12, "Rock")],
        )
        self.assertAlmostEqual(bh.total_depth, 12.0)

    def test_total_depth_from_tests(self):
        bh = BoreholeRecord(
            location="BH-02",
            tests=[TestRecord(3.0), TestRecord(8.5)],
        )
        self.assertAlmostEqual(bh.total_depth, 8.5)

    def test_total_depth_empty(self):
        bh = BoreholeRecord(location="BH-03")
        self.assertAlmostEqual(bh.total_depth, 0.0)

    def test_validate_missing_location(self):
        bh = BoreholeRecord(location="")
        warnings = bh.validate()
        self.assertTrue(any("Missing location" in w for w in warnings))

    def test_validate_no_layers(self):
        bh = BoreholeRecord(location="BH-01")
        warnings = bh.validate()
        self.assertTrue(any("No soil layers" in w for w in warnings))

    def test_validate_no_tests(self):
        bh = BoreholeRecord(
            location="BH-01",
            layers=[SoilLayer(0, 5, "Clay")],
        )
        warnings = bh.validate()
        self.assertTrue(any("No SPT/RQD" in w for w in warnings))

    def test_validate_gap_in_layers(self):
        bh = BoreholeRecord(
            location="BH-01",
            layers=[SoilLayer(0, 3, "Clay"), SoilLayer(5, 8, "Rock")],  # gap 3-5
            tests=[TestRecord(2.0)],
        )
        warnings = bh.validate()
        self.assertTrue(any("Gap/overlap" in w for w in warnings))

    def test_validate_clean(self):
        bh = BoreholeRecord(
            location="BH-01",
            layers=[SoilLayer(0, 5, "Clay"), SoilLayer(5, 10, "Rock")],
            tests=[TestRecord(3.0), TestRecord(7.0)],
        )
        warnings = bh.validate()
        self.assertEqual(warnings, [])

    def test_gwt_default_none(self):
        bh = BoreholeRecord(location="BH-01")
        self.assertIsNone(bh.gwt)


# ===================================================================
# 2. Soil Classification Tests
# ===================================================================
class TestSoilClassify(unittest.TestCase):
    def test_hard_rock(self):
        self.assertEqual(classify("Hard Rock"), "hard_rock")

    def test_disintegrated_rock(self):
        self.assertEqual(classify("Disintegrated Rock"), "weathered_rock")

    def test_weathered_rock(self):
        self.assertEqual(classify("Weathered Rock"), "weathered_rock")

    def test_soft_rock(self):
        self.assertEqual(classify("Soft Rock"), "soft_rock")

    def test_generic_rock(self):
        self.assertEqual(classify("Rock"), "rock")

    def test_boulder(self):
        self.assertEqual(classify("Boulder"), "rock")

    def test_murrum(self):
        self.assertEqual(classify("Murrum"), "rock")

    def test_clay(self):
        self.assertEqual(classify("Clay"), "clay")

    def test_clayey_gravels_dominant_gravel(self):
        # Last significant word "Gravels" → gravel
        self.assertEqual(classify("Clayey Gravels"), "gravel")

    def test_sandy_silt_dominant_silt(self):
        self.assertEqual(classify("Sandy Silt"), "silt")

    def test_sand(self):
        self.assertEqual(classify("Sand"), "sand")

    def test_empty_description(self):
        self.assertEqual(classify(""), "overburden")

    def test_unrecognised_falls_back(self):
        self.assertEqual(classify("FooBarBaz"), "overburden")

    def test_style_for_returns_dict(self):
        style = style_for("Hard Rock")
        self.assertIn("pattern", style)
        self.assertIn("color", style)
        self.assertIn("label", style)

    def test_classify_and_style_tuple(self):
        cat, style = classify_and_style("Clay")
        self.assertEqual(cat, "clay")
        self.assertIs(style, HATCH_STYLE["clay"])

    def test_all_categories_have_hatch_styles(self):
        for cat in ("overburden", "gravel", "sand", "silt", "clay",
                     "weathered_rock", "soft_rock", "rock", "hard_rock"):
            self.assertIn(cat, HATCH_STYLE, f"Missing hatch style for {cat}")


# ===================================================================
# 3. Grid Parsing Tests (table_common)
# ===================================================================
class TestFindHeaderColumns(unittest.TestCase):
    def test_detects_standard_headers(self):
        rows = [
            ["Project X", "", "", "", "", ""],
            ["Br.No. 533", "", "", "", "", ""],
            ["Location Name: BH-01", "", "", "", "", ""],
            ["Started On 01-Jan Ended On 02-Jan", "", "", "", "", ""],
            ["", "", "", "", "", ""],
            ["R.L of Layer", "G.W.T", "", "", "", "Engineering Description",
             "Depth of SPT", "0-15", "15-30", "30-45", "N-Value",
             "Relative Density", "Type of Sample"],
        ]
        cols, header_idx = find_header_columns(rows)
        self.assertEqual(cols["layer_boundary"], 0)
        self.assertEqual(cols["gwt"], 1)
        self.assertEqual(cols["description"], 5)
        self.assertEqual(cols["test_depth"], 6)
        self.assertEqual(header_idx, 5)

    def test_empty_rows(self):
        cols, header_idx = find_header_columns([])
        self.assertEqual(header_idx, -1)
        # Should still return fallback cols
        self.assertIn("description", cols)

    def test_fallback_used_for_missing(self):
        rows = [["Only a description column here"]]
        cols, _ = find_header_columns(rows)
        # Should have fallback values for fields not detected
        self.assertIn("test_depth", cols)


class TestParseGrid(unittest.TestCase):
    def _make_simple_grid(self):
        """Create a minimal but valid bore-log grid."""
        return [
            ["Project Test", "", "", "", "", ""],
            ["Br.No. 001", "", "", "", "", ""],
            ["Location Name: BH-T1", "", "", "", "", ""],
            ["Started 01-Jan Ended 02-Jan", "", "", "", "", ""],
            ["", "", "", "", "", ""],
            # Header row
            ["R.L of Layer", "G.W.T", "", "", "", "Engineering Description",
             "Depth of SPT", "0-15", "15-30", "30-45", "N-Value",
             "Relative Density", "Type of Sample"],
            # Data rows
            ["0.00", "", "", "", "", "Clay", "", "", "", "", "", "", ""],
            ["3.00", "", "", "", "", "Sandy Gravel", "", "", "", "", "", "", ""],
            ["3.00", "", "", "", "", "", "3.00", "8", "12", "15", "20", "Dense", "DS"],
            ["6.00", "4.50", "", "", "", "Rock", "", "", "", "", "", "", ""],
            ["6.00", "", "", "", "", "", "6.00", "15", "20", "25", "43", "Hard", "CS"],
            # Termination
            ["", "", "", "", "", "Bore Hole Terminated at a depth of 6.00 m"],
        ]

    def test_parse_grid_produces_record(self):
        warnings = []
        rows = self._make_simple_grid()
        bh = parse_grid("BH-T1", rows, warnings)
        self.assertIsNotNone(bh)
        self.assertEqual(bh.location, "BH-T1")
        self.assertEqual(bh.project, "Project Test")
        self.assertEqual(bh.br_no, "Br.No. 001")

    def test_parse_grid_extracts_layers(self):
        warnings = []
        rows = self._make_simple_grid()
        bh = parse_grid("BH-T1", rows, warnings)
        self.assertGreaterEqual(len(bh.layers), 1)
        # First layer should start at 0.0
        self.assertAlmostEqual(bh.layers[0].from_depth, 0.0)

    def test_parse_grid_extracts_tests(self):
        warnings = []
        rows = self._make_simple_grid()
        bh = parse_grid("BH-T1", rows, warnings)
        self.assertGreaterEqual(len(bh.tests), 1)
        # Should have N=20 and N=43
        n_values = [t.note for t in bh.tests]
        self.assertTrue(any("N=20" in n for n in n_values))
        self.assertTrue(any("N=43" in n for n in n_values))

    def test_parse_grid_empty_rows(self):
        warnings = []
        bh = parse_grid("empty", [], warnings)
        self.assertIsNone(bh)

    def test_parse_grid_termination_note(self):
        warnings = []
        rows = self._make_simple_grid()
        bh = parse_grid("BH-T1", rows, warnings)
        self.assertIn("Terminated", bh.termination_note)

    def test_parse_grid_gwt_detected(self):
        warnings = []
        rows = self._make_simple_grid()
        bh = parse_grid("BH-T1", rows, warnings)
        self.assertAlmostEqual(bh.gwt, 4.50)


# ===================================================================
# 4. DXF Builder Tests
# ===================================================================
class TestBoreLogDxfBuilder(unittest.TestCase):
    def _make_sample_boreholes(self):
        return [
            BoreholeRecord(
                location="BH-01",
                project="Test Project",
                br_no="001",
                dates="01-Jan to 02-Jan",
                gwt=4.5,
                layers=[
                    SoilLayer(0, 3, "Clay"),
                    SoilLayer(3, 6, "Sandy Gravel"),
                    SoilLayer(6, 10, "Hard Rock"),
                ],
                tests=[
                    TestRecord(3.0, note="N=20", density="Dense", sample_type="DS"),
                    TestRecord(8.0, note="N=50", density="Hard", sample_type="CS"),
                ],
                termination_note="Bore Hole Terminated at a depth of 10.00 m",
            ),
        ]

    def test_builder_invalid_style(self):
        with self.assertRaises(ValueError):
            BoreLogDxfBuilder(style="invalid")

    def test_builder_schematic_default(self):
        b = BoreLogDxfBuilder()
        self.assertEqual(b.style, "schematic")

    def test_builder_detailed(self):
        b = BoreLogDxfBuilder(style="detailed")
        self.assertEqual(b.style, "detailed")

    def test_save_produces_dxf_file(self):
        boreholes = self._make_sample_boreholes()
        builder = BoreLogDxfBuilder(project_line="Test Project", style="schematic")
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
            out_path = f.name
        try:
            builder.save(boreholes, out_path)
            self.assertTrue(os.path.isfile(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)
        finally:
            os.unlink(out_path)

    def test_save_detailed_style(self):
        boreholes = self._make_sample_boreholes()
        builder = BoreLogDxfBuilder(project_line="Test", style="detailed")
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
            out_path = f.name
        try:
            builder.save(boreholes, out_path)
            self.assertTrue(os.path.isfile(out_path))
        finally:
            os.unlink(out_path)

    def test_save_multiple_boreholes(self):
        boreholes = [
            BoreholeRecord(
                location=f"BH-{i:02d}",
                layers=[SoilLayer(0, 5 + i, f"Layer {i}")],
                tests=[TestRecord(3.0, note=f"N={10+i}")],
            )
            for i in range(1, 4)
        ]
        builder = BoreLogDxfBuilder()
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
            out_path = f.name
        try:
            builder.save(boreholes, out_path)
            self.assertTrue(os.path.isfile(out_path))
        finally:
            os.unlink(out_path)

    def test_dxf_file_is_valid(self):
        """Verify the output can be opened by ezdxf without errors."""
        boreholes = self._make_sample_boreholes()
        builder = BoreLogDxfBuilder(project_line="Test")
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
            out_path = f.name
        try:
            builder.save(boreholes, out_path)
            import ezdxf
            doc = ezdxf.readfile(out_path)
            msp = doc.modelspace()
            # Should have at least some entities
            entities = list(msp)
            self.assertGreater(len(entities), 0)
        finally:
            os.unlink(out_path)


# ===================================================================
# 5. Borelog Panel Import & sys.path Tests
# ===================================================================
class TestBorelogPanelImport(unittest.TestCase):
    def test_borelog_dxf_importable(self):
        """Verify borelog_dxf is on sys.path and importable."""
        import borelog_dxf
        self.assertTrue(hasattr(borelog_dxf, "BoreholeRecord"))
        self.assertTrue(hasattr(borelog_dxf, "BoreLogDxfBuilder"))

    def test_panel_importable(self):
        """Verify gui.borelog_panel can be imported."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from gui.borelog_panel import BoreLogPanel
        self.assertTrue(callable(BoreLogPanel))

    def test_main_window_imports_borelog(self):
        """Verify MainWindow loads with BoreLogPanel in the stack."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from gui.main_window import MainWindow
        # MainWindow._PAGE_INFO should mention Bore Log
        page_names = [p[0] for p in MainWindow._PAGE_INFO]
        self.assertIn("Bore Log → DXF", page_names)

    def test_borelog_icon_registered(self):
        """Verify borelog icon is registered in the icon file map."""
        from gui.icons import icon_path
        path = icon_path("borelog")
        self.assertIsNotNone(path, "borelog icon path should not be None")
        self.assertTrue(os.path.isfile(path), f"Icon file missing: {path}")


# ===================================================================
# 6. End-to-End Integration Test
# ===================================================================
class TestEndToEnd(unittest.TestCase):
    def test_full_pipeline(self):
        """Create borehole records → build DXF → verify output is valid DXF."""
        boreholes = [
            BoreholeRecord(
                location="BH-E2E",
                project="Integration Test",
                layers=[
                    SoilLayer(0, 2, "Clay"),
                    SoilLayer(2, 5, "Sandy Gravel"),
                    SoilLayer(5, 8, "Weathered Rock"),
                    SoilLayer(8, 12, "Hard Rock"),
                ],
                tests=[
                    TestRecord(2.0, note="N=15", density="Medium", sample_type="DS"),
                    TestRecord(5.0, note="N=30", density="Dense", sample_type="DS"),
                    TestRecord(10.0, note="N=50+", density="Hard", sample_type="CS"),
                ],
                termination_note="Bore Hole Terminated at a depth of 12.00 m",
                gwt=3.5,
            ),
        ]

        # Validate the data
        for bh in boreholes:
            warnings = bh.validate()
            # Should have no critical warnings (we have location, layers, tests)
            critical = [w for w in warnings if "Missing location" in w or "No soil layers" in w]
            self.assertEqual(critical, [], f"Unexpected critical warnings: {critical}")

        # Build DXF
        builder = BoreLogDxfBuilder(
            project_line="Integration Test — E2E",
            style="schematic",
        )
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
            out_path = f.name
        try:
            builder.save(boreholes, out_path)
            self.assertTrue(os.path.isfile(out_path))
            self.assertGreater(os.path.getsize(out_path), 100)

            # Verify with ezdxf
            import ezdxf
            doc = ezdxf.readfile(out_path)
            msp = doc.modelspace()
            entities = list(msp)
            self.assertGreater(len(entities), 10, "DXF should have many entities")

            # Check layers exist
            layer_names = [lay.dxf.name for lay in doc.layers]
            self.assertIn("BOREHOLE-OUTLINE", layer_names)
            self.assertIn("BOREHOLE-TEXT", layer_names)
        finally:
            os.unlink(out_path)


if __name__ == "__main__":
    unittest.main()
