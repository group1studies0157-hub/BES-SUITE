#!/usr/bin/env python3
"""
Batch GAD Generator — Bridge Engineering Suite.

Generate GAD drafts for MANY bridges from a single spreadsheet. Each row is a
bridge: a free-text `prompt` (same format as generate_gad.py: spans, levels,
span type, tracks) plus optional override columns for anything the prompt
misses — perfect for feeding per-bridge dynamic levels.

Columns (header names, case-insensitive; `prompt` is required):

    prompt                bridge description, e.g.
                          "3KK: (1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX, RL 178.741,
                           FL 177.979, BL 175.877, HFL 176.877, 2 tracks C/C 9450"
    bridge_no             output folder / file name override
    span_type             family override: rcc_box | psc_slab | psc_girder |
                          box_girder | steel_girder | fob
    cells_mm              comma-separated clear widths / spans in mm
    clear_height_mm       RCC box vent height (mm)
    rail_level_m          dynamic levels (metres)
    formation_level_m
    bed_level_m
    hfl_m
    scour_level_m
    num_tracks
    track_centres_mm
    deck_width_mm
    section / division / chainage / loading / scale / project

Example:
    python batch_gad.py bridges.csv --out ./generated --json
    python batch_gad.py bridges.xlsx --offline

Use --sample to write an empty bridges.csv template first.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.gad_generator import GadInput, generate  # noqa: E402

_INT_FIELDS = {"cells_mm", "clear_height_mm", "num_tracks", "track_centres_mm",
               "deck_width_mm"}
_FLOAT_FIELDS = {"rail_level_m", "formation_level_m", "bed_level_m", "hfl_m",
                 "scour_level_m"}
_STR_FIELDS = {"bridge_no", "span_type", "section", "division", "chainage",
               "loading", "scale", "project", "span_description", "type_key"}

SAMPLE_ROWS = [
    ["prompt",
     "3KK: (1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX, RL 178.741, FL 177.979, "
     "BL 175.877, HFL 176.877, max scour 174.5, 2 tracks C/C 9450"],
    ["2x9.15 m PSC slab, RL 112.25, FL 111.15, BL 108.2, HFL 109.4"],
    ["1x18.3 m PSC girder, RL 122.5, FL 121.4, BL 117.0, HFL 118.5"],
    ["1x15.0 m FOB, RL 118.0, BL 111.0"],
]


def _read_rows(path: str) -> list:
    if path.lower().endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            sys.exit("openpyxl is required for .xlsx input: pip install openpyxl")
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = [[str(c).strip() if c is not None else "" for c in row]
                for row in ws.iter_rows(values_only=True)]
        return [r for r in rows if any(r)]
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.reader(fh) if any(c.strip() for c in r)]


def apply_overrides(inp: GadInput, row: dict) -> None:
    for k, v in row.items():
        if k not in _INT_FIELDS and k not in _FLOAT_FIELDS and k not in _STR_FIELDS:
            continue
        if v == "":
            continue
        try:
            if k in _INT_FIELDS:
                if k == "cells_mm":
                    vals = [int(round(float(x))) for x in v.split(",") if x.strip()]
                    if vals:
                        setattr(inp, k, vals)
                else:
                    setattr(inp, k, int(round(float(v))))
            elif k in _FLOAT_FIELDS:
                setattr(inp, k, float(v))
            else:
                setattr(inp, k, v)
        except ValueError:
            print(f"    [warn] skipping bad value for {k} = {v!r}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch GAD generation from CSV/XLSX")
    ap.add_argument("input", help="CSV or XLSX file of bridges (see module docstring)")
    ap.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "BES_GAD_Output"),
                    help="Output root folder (default: ~/BES_GAD_Output)")
    ap.add_argument("--ai", action="store_true",
                    help="Use the AI provider to parse prompts (default: deterministic offline parser)")
    ap.add_argument("--json", action="store_true", help="Dump per-bridge parsed params")
    ap.add_argument("--sample", action="store_true",
                    help="Write a sample bridges.csv and exit")
    args = ap.parse_args()

    if args.sample:
        with open("bridges.csv", "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(SAMPLE_ROWS)
        print("Wrote bridges.csv — edit it and re-run batch_gad.py bridges.csv")
        return 0

    rows = _read_rows(args.input)
    if not rows:
        sys.exit("no data rows found")
    header = [h.strip().lower().replace(" ", "_") for h in rows[0]]
    data = [dict(zip(header, [c.strip() for c in r])) for r in rows[1:]]
    if "prompt" not in header:
        sys.exit("the spreadsheet needs a 'prompt' column (see --sample)")

    ai = None
    if args.ai:
        ck = os.environ.get("ANTHROPIC_API_KEY", "")
        gk = os.environ.get("GEMINI_API_KEY", "")
        if ck or gk:
            try:
                from gui.ai_provider import AIProvider
                ai = AIProvider.dual(gemini_key=gk, claude_key=ck)
            except Exception:
                ai = None
        if ai is None:
            print("[warn] --ai given but no API keys found — using the offline parser "
                  "(set ANTHROPIC_API_KEY/GEMINI_API_KEY)", file=sys.stderr)

    ok = fail = 0
    for i, row in enumerate(data, start=2):
        prompt = row.get("prompt", "").strip()
        if not prompt:
            print(f"[{i}] skipped (empty prompt)")
            continue
        try:
            inp = GadInput.from_ai(prompt, ai) if ai is not None else GadInput.from_prompt(prompt)
            apply_overrides(inp, row)
            bridge = inp.bridge_no or f"bridge-{i}"
            out_dir = os.path.join(args.out, bridge)
            res = generate(inp, out_dir)
            if args.json:
                with open(os.path.join(out_dir, f"{bridge}-params.json"), "w",
                          encoding="utf-8") as fh:
                    json.dump(res["input"], fh, indent=2)
            print(f"[{i}] {bridge:<10} {inp.span_type:<12} "
                  f"cells={inp.cells_mm} RL={inp.rail_level_m:g} FL={inp.formation_level_m:g} "
                  f"BL={inp.bed_level_m:g} -> {out_dir}")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}] FAILED: {exc}", file=sys.stderr)
            traceback.print_exc(limit=2, file=sys.stderr)
            fail += 1

    print(f"\nDone: {ok} generated, {fail} failed -> {os.path.abspath(args.out)}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
