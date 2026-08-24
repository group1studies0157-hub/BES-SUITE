"""
CLI: convert one or more Excel/PDF bore-log reports to DXF without the GUI.

Usage:
    python -m borelog_dxf.cli 533.xls -o 533_BoreHole_Details.dxf
    python -m borelog_dxf.cli report.pdf -o out.dxf --ocr-dpi 400
    python -m borelog_dxf.cli *.xls --out-dir converted/
"""
from __future__ import annotations
import argparse
import os
import sys

from .model import BoreholeRecord
from .dxf_builder import BoreLogDxfBuilder


def _parse_one(path: str, ocr_dpi: int) -> tuple[list[BoreholeRecord], list[str]]:
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xls', '.xlsx'):
        from .parser_xls import parse_workbook
        return parse_workbook(path)
    elif ext == '.pdf':
        from .parser_pdf import parse_pdf
        return parse_pdf(path, ocr_dpi=ocr_dpi)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert bore-log Excel/PDF reports to a DXF bore-log sheet.")
    ap.add_argument('inputs', nargs='+', help="Input .xls/.xlsx/.pdf file(s)")
    ap.add_argument('-o', '--output', help="Output DXF path (only valid for a single input file)")
    ap.add_argument('--out-dir', help="Directory to write DXF files into (for multiple inputs)")
    ap.add_argument('--combine', action='store_true',
                     help="Combine all boreholes from all input files into a single DXF sheet")
    ap.add_argument('--ocr-dpi', type=int, default=300, help="DPI used when OCR-ing scanned PDF pages")
    ap.add_argument('--project-line', default=None, help="Override the project title line printed on the sheet")
    ap.add_argument('--style', choices=['schematic', 'detailed'], default='schematic',
                     help="'schematic' (default): clean profile + labels only, matches the "
                          "standard GAD bore-log sheet look. 'detailed': every depth/SPT/RQD "
                          "value printed next to the column, for working/QC drawings.")
    ap.add_argument('-q', '--quiet', action='store_true', help="Suppress warnings")
    args = ap.parse_args(argv)

    if args.output and len(args.inputs) > 1 and not args.combine:
        ap.error("--output can only be used with a single input file unless --combine is set")

    all_boreholes: list[BoreholeRecord] = []
    exit_code = 0

    for path in args.inputs:
        if not os.path.exists(path):
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            exit_code = 1
            continue
        try:
            boreholes, warnings = _parse_one(path, args.ocr_dpi)
        except Exception as e:
            print(f"ERROR: failed to parse {path}: {e}", file=sys.stderr)
            exit_code = 1
            continue

        if not args.quiet:
            for w in warnings:
                print(f"WARNING [{os.path.basename(path)}] {w}", file=sys.stderr)
        print(f"{path}: parsed {len(boreholes)} borehole(s) "
              f"({', '.join(b.location for b in boreholes)})")

        if args.combine:
            all_boreholes.extend(boreholes)
            continue

        if not boreholes:
            print(f"  -> skipped (no usable data)", file=sys.stderr)
            exit_code = 1
            continue

        out_path = args.output
        if not out_path:
            base = os.path.splitext(os.path.basename(path))[0]
            out_dir = args.out_dir or os.path.dirname(path) or '.'
            out_path = os.path.join(out_dir, f"{base}_BoreHole_Details.dxf")

        project_line = args.project_line or (boreholes[0].project if boreholes[0].project else "")
        builder = BoreLogDxfBuilder(project_line=project_line, style=args.style)
        builder.save(boreholes, out_path)
        print(f"  -> {out_path}")

    if args.combine:
        if not all_boreholes:
            print("ERROR: no boreholes parsed from any input file", file=sys.stderr)
            return 1
        out_path = args.output or (os.path.join(args.out_dir, "Combined_BoreHole_Details.dxf")
                                    if args.out_dir else "Combined_BoreHole_Details.dxf")
        project_line = args.project_line or (all_boreholes[0].project if all_boreholes[0].project else "")
        builder = BoreLogDxfBuilder(project_line=project_line, style=args.style)
        builder.save(all_boreholes, out_path)
        print(f"Combined {len(all_boreholes)} borehole(s) -> {out_path}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
