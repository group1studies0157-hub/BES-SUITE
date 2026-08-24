"""
borelog_dxf - convert bore-log Excel/PDF reports into AutoCAD DXF
"BORE HOLE DETAILS (NOT TO SCALE)" sheets.

Public entry points:
    borelog_dxf.parser_xls.parse_workbook(path) -> (boreholes, warnings)
    borelog_dxf.parser_pdf.parse_pdf(path)       -> (boreholes, warnings)
    borelog_dxf.dxf_builder.BoreLogDxfBuilder().save(boreholes, out_path)

    python -m borelog_dxf.cli input.xls -o output.dxf     # CLI
    python -m borelog_dxf.gui                              # desktop app
"""
from .model import BoreholeRecord, SoilLayer, TestRecord
from .dxf_builder import BoreLogDxfBuilder

__all__ = ["BoreholeRecord", "SoilLayer", "TestRecord", "BoreLogDxfBuilder"]
__version__ = "1.0.0"
