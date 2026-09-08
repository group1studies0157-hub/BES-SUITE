"""
validate.py — Phase 4: validation loop.

Renders the repaired DXF back to raster (matplotlib backend when installed,
guaranteed PIL fallback otherwise), produces a side-by-side diff against the
source scan, and emits the final reports:

    * entity-count table per bucket (before/after)
    * change_log.json            (written by run_all from the ChangeLog)
    * needs_review index         (magenta flags + crop evidence)
"""

from __future__ import annotations

import math
import os

import numpy as np

from core.dxf_repair import ARCHIVE_LAYER, REVIEW_LAYER
from core.dxf_repair.common import bucket_counts, polyline_points


def _msp_bbox(msp):
    pts = []
    for e in msp.query("*"):
        if e.dxftype() == "CIRCLE":
            c, r = e.dxf.center, e.dxf.radius
            pts += [(c.x - r, c.y - r), (c.x + r, c.y + r)]
        else:
            for p in polyline_points(e):
                pts.append(p)
    if not pts:
        return (0.0, 0.0, 1000.0, 1000.0)
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def render_dxf_png(msp, out_path, width_px=2400, bg="#FFFFFF",
                   fg=(30, 30, 30)) -> str:
    """
    Fast PIL rasteriser of the model space (lines/polylines/circles/text).
    Used when matplotlib is unavailable; matplotlib's ezdxf drawing add-on is
    preferred when present (see _render_with_matplotlib).
    """
    if _render_with_matplotlib(msp, out_path, width_px=width_px, bg=bg):
        return out_path

    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = _msp_bbox(msp)
    w = max(x1 - x0, 1.0)
    h = max(y1 - y0, 1.0)
    H = max(int(width_px * h / w), 100)
    pad = int(width_px * 0.02)
    img = Image.new("RGB", (width_px + 2 * pad, H + 2 * pad), "white")
    drw = ImageDraw.Draw(img)

    def T(p):
        px = pad + (float(p[0]) - x0) / w * width_px
        py = img.height - pad - (float(p[1]) - y0) / h * H
        return (px, py)

    for e in msp.query("*"):
        layer = getattr(e.dxf, "layer", "")
        color = "black"
        try:
            if layer in (REVIEW_LAYER,):
                color = (255, 0, 255)
            elif layer == DIMENSIONS_LAYER:
                color = (0, 130, 0)
        except Exception:              # noqa: BLE001
            pass
        t = e.dxftype()
        try:
            if t == "LINE":
                drw.line([T(e.dxf.start), T(e.dxf.end)], fill=color, width=1)
            elif t == "LWPOLYLINE":
                pp = [T(p) for p in e.get_points("xy")]
                if bool(getattr(e.dxf, "closed", False)) and len(pp) > 2:
                    pp.append(pp[0])
                if len(pp) >= 2:
                    drw.line(pp, fill=color, width=1)
            elif t == "POLYLINE":
                pp = [T((v.dxf.location.x, v.dxf.location.y))
                      for v in e.vertices]
                if len(pp) >= 2:
                    drw.line(pp, fill=color, width=1)
            elif t in ("CIRCLE", "ARC"):
                cx, cy = T(e.dxf.center)
                rr = float(e.dxf.radius) / w * width_px
                bbox_ = [cx - rr, cy - rr, cx + rr, cy + rr]
                if t == "CIRCLE":
                    drw.ellipse(bbox_, outline=color, width=1)
            elif t in ("TEXT", "MTEXT"):
                pos = getattr(e.dxf, "insert", None) or \
                    getattr(e.dxf, "define_point", None)
                if pos is not None:
                    hh = float(getattr(e.dxf, "char_height", None)
                               or getattr(e.dxf, "height", 200.0))
                    ph = hh / w * width_px
                    txt = str(getattr(e, "plain_text", lambda: "")())
                    txt = txt or str(getattr(e.dxf, "text", ""))
                    if txt:
                        fsize = max(8, int(ph))
                        try:
                            from PIL import ImageFont
                            font = ImageFont.load_default(fsize)
                        except Exception:   # noqa: BLE001
                            font = None
                        drw.text(T(pos), txt[:60], fill=color, font=font)
        except Exception:              # noqa: BLE001 — rendering must never abort
            continue
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path)
    return out_path


DIMENSIONS_LAYER = "DIMENSIONS"


def _render_with_matplotlib(msp, out_path, width_px=2400, bg="#FFFFFF") -> bool:
    """Higher-fidelity path; silently skipped when mpl/ezdxf add-on missing."""
    try:
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:                  # noqa: BLE001
        return False
    try:
        fig = plt.figure(figsize=(min(30.0, width_px / 300.0),
                                  min(30.0, width_px / 300.0)))
        ax = fig.add_axes([0, 0, 1, 1])
        ctx = RenderContext(msp.doc)
        out = MatplotlibBackend(ax)
        Frontend(ctx, out).draw_layout(msp, finalize=True)
        fig.savefig(out_path, dpi=300, facecolor=bg)
        plt.close(fig)
        return True
    except Exception:                  # noqa: BLE001
        try:
            plt.close("all")
        except Exception:              # noqa: BLE001
            pass
        return False


def side_by_side(render_png, source_image_path, out_png, max_height=1800):
    """Repair render next to the original scan for the human eyeball pass."""
    from PIL import Image
    a = Image.open(render_png).convert("RGB")
    try:
        from core.dxf_repair.calibrate import load_image
        src = load_image(source_image_path)
        b = Image.fromarray(src[:, :, ::-1])
    except Exception:                  # noqa: BLE001
        b = None
    if b is not None:
        target_h = min(max_height, min(a.height, b.height))
        scale_a = target_h / max(a.height, 1)
        scale_b = target_h / max(b.height, 1)
        a = a.resize((max(int(a.width * scale_a), 1), target_h))
        b = b.resize((max(int(b.width * scale_b), 1), target_h))
        canvas = Image.new("RGB", (a.width + b.width + 24, target_h),
                           (240, 240, 240))
        canvas.paste(a, (0, 0))
        canvas.paste(b, (a.width + 24, 0))
    else:
        canvas = a
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    canvas.save(out_png)
    return out_png


def entity_report(msp_before_counts: dict, msp) -> dict:
    after = bucket_counts(msp.query("*"))
    return {"before": msp_before_counts, "after": after}


def review_index(log, out_dir) -> dict:
    items = log.needs_review
    for i, rec in enumerate(items):
        rec.setdefault("index", i + 1)
    if items:
        import json as _json
        path = os.path.join(out_dir, "needs_review_index.json")
        with open(path, "w", encoding="utf-8") as fh:
            _json.dump(items, fh, indent=2)
        return {"count": len(items), "path": path}
    return {"count": 0, "path": ""}


def build_final_report(run_meta, phase2_res, phase3_res, counts, calib,
                       review_info):
    p2 = (phase2_res or {}).get("stats", {})
    p3 = (phase3_res or {}).get("stats", {})
    lines = [
        "# BES DXF Repair — validation report",
        "",
        f"Source DXF   : {run_meta.get('source_dxf','')}",
        f"Source image : {run_meta.get('source_image','')}",
        f"Calibration  : {calib.kind} | quality={calib.quality} "
        f"| max residual {calib.residual_max_mm:.1f} mm",
        f"Duration     : {run_meta.get('seconds', 0):.1f} s",
        "",
        "## Entity buckets (before → after)",
        "| bucket | before | after |",
        "|---|---|---|",
    ]
    keys = sorted(set(counts["before"]) | set(counts["after"]))
    for k in keys:
        if k == "TOTAL":
            continue
        lines.append(f"| {k} | {counts['before'].get(k, 0)} "
                     f"| {counts['after'].get(k, 0)} |")
    lines.append(f"| **TOTAL** | {counts['before'].get('TOTAL', 0)} "
                 f"| **{counts['after'].get('TOTAL', 0)}** |")
    lines += [
        "",
        "## Phase 2 — dimensions",
        f"rebuilt associative : {p2.get('rebuilt', 0)}",
        f"text-annotation fallbacks : {p2.get('annotation_fallback', 0)}",
        f"flagged NEEDS_REVIEW : {p2.get('needs_review', 0)}",
        "",
        "## Phase 3 — shapes",
        f"rectangles rebuilt : {p3.get('rects_rebuilt', 0)}",
        f"circles rebuilt : {p3.get('circles_rebuilt', 0)}",
        f"duplicate outlines removed : {p3.get('duplicates_removed', 0)}",
        "",
        "## Human review",
        f"NEEDS_REVIEW items : {review_info.get('count', 0)} "
        f"({review_info.get('path') or 'none'})",
        "",
        ("NOTE: hatch entities were archived untouched on frozen layer "
         f"{ARCHIVE_LAYER}; their count is intentionally unchanged."),
    ]
    return "\n".join(lines)


def write_report(report_md_path, text) -> str:
    with open(report_md_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return report_md_path
