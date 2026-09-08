#!/usr/bin/env python3
"""
Headless GAD Generator — Bridge Engineering Suite.

Turn a prompt with dimensions into a draft General Arrangement Drawing:

    python generate_gad.py "3KK: (1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX, \
RL 178.741, FL 177.979, BL 175.877, HFL 176.877, 2 tracks C/C 9450, 25T-2008"

Outputs  <bridge>-GAD.dxf  (open in AutoCAD/BricsCAD, save as DWG)
and      <bridge>-GAD.lsp  (load in AutoCAD, type BES-GAD)

If ANTHROPIC_API_KEY / GEMINI_API_KEY are set the prompt is parsed with the
AI provider first (structured fill-in); otherwise a deterministic offline
parser is used. Use --offline to force the local parser.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.gad_generator import GadInput, generate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate a parametric GAD (AutoLISP + DXF) from a prompt with dimensions."
    )
    ap.add_argument("prompt", nargs="?", default="", help="Bridge description, e.g. "
                    "'3KK: (1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX, RL 178.741, FL 177.979, "
                    "BL 175.877, HFL 176.877, 2 tracks C/C 9450, 25T-2008'. "
                    "If omitted, the prompt is read from stdin.")
    ap.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "BES_GAD_Output"),
                    help="Output folder (default: ~/BES_GAD_Output)")
    ap.add_argument("--offline", action="store_true",
                    help="Force the deterministic offline parser (no AI call)")
    ap.add_argument("--name", default="", help="Output file base name "
                    "(default: <bridge_no>-GAD)")
    ap.add_argument("--json", action="store_true",
                    help="Also dump the parsed input parameters as <name>-params.json")
    args = ap.parse_args()

    prompt = args.prompt.strip()
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        ap.error("no prompt given (pass it as an argument or pipe it on stdin)")

    inp = None
    ai = None
    if not args.offline:
        ck = os.environ.get("ANTHROPIC_API_KEY", "")
        gk = os.environ.get("GEMINI_API_KEY", "")
        if ck or gk:
            try:
                from gui.ai_provider import AIProvider
                ai = AIProvider.dual(gemini_key=gk, claude_key=ck)
            except Exception:
                ai = None
        if ai is None and not args.offline:
            print("[warn] no API keys found — using the offline parser. "
                  "Set ANTHROPIC_API_KEY/GEMINI_API_KEY or pass --offline.", file=sys.stderr)
    if ai is not None:
        inp = GadInput.from_ai(prompt, ai)
        print(f"[ai] parsed with {ai.provider}", file=sys.stderr)
    else:
        inp = GadInput.from_prompt(prompt)
        print("[offline] parsed with deterministic regex parser", file=sys.stderr)

    res = generate(inp, args.out, name=args.name or None)
    print(f"Bridge No.    : {inp.bridge_no}")
    print(f"Span type     : {inp.span_type}")
    print(f"Spans / cells : {', '.join(str(c) for c in inp.cells_mm)} mm")
    print(f"RL / FL / BL  : {inp.rail_level_m:g} / {inp.formation_level_m:g} / {inp.bed_level_m:g} m")
    if inp.hfl_m:
        print(f"HFL           : {inp.hfl_m:g} m")
    print(f"Entities      : {res['total']} ({', '.join(f'{k}={v}' for k, v in res['entities'].items())})")
    print(f"DXF           : {res['dxf']}")
    print(f"AutoLISP      : {res['lsp']}")
    if args.json:
        params_path = os.path.join(args.out, f"{os.path.splitext(os.path.basename(res['dxf']))[0]}-params.json")
        with open(params_path, "w", encoding="utf-8") as fh:
            json.dump(res["input"], fh, indent=2)
        print(f"Params        : {params_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
