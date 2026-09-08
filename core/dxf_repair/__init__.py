"""
BES — AutoCAD DXF Corruption Repair Pipeline (Railway Bridge GAD)
=================================================================

Repairs an automated raster→vector DXF extraction of a scanned railway
bridge General Arrangement Drawing:

Phase 0/1  calibrate.py        bucket split, hatch archival, image↔DXF
                               affine calibration (calibration.json)
Phase 2    fix_dimensions.py   corrupt dimension audit → ground-truth OCR +
                               vision cross-check → true associative
                               DIMENSION entities (one shared DIMSTYLE)
Phase 3    fix_shapes.py       rectangle/circle loop rebuild on original layers
Phase 4    validate.py         renders, side-by-side diff, change_log.json,
                               needs_review crops, entity-count report

Single entry point:

    from core.dxf_repair.run_all import run_repair
    summary = run_repair("extracted.dxf", "original_scan.tif", "./out")

Original files are never modified; every output goes to ``out_dir``.
"""

from __future__ import annotations

ARCHIVE_LAYER = "_HATCH_ARCHIVE"      # frozen/locked hatch archive layer
REVIEW_LAYER = "_NEEDS_REVIEW"        # magenta markers for human review
DIMSTYLE_NAME = "BES_REPAIR"          # single shared DIMSTYLE for all rebuilds

__version__ = "1.0.0"

__all__ = [
    "ARCHIVE_LAYER",
    "REVIEW_LAYER",
    "DIMSTYLE_NAME",
    "run_repair",
]


def run_repair(*args, **kwargs):
    """Lazy re-export so importing this package stays cheap."""
    from core.dxf_repair.run_all import run_repair as _fn

    return _fn(*args, **kwargs)
