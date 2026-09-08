"""
run_all.py — Phase 0–4 orchestrator with per-view checkpointing.

    from core.dxf_repair.run_all import run_repair
    summary = run_repair("extracted.dxf", "original_scan.tif", "./out",
                         progress_cb=print)

Outputs (all inside ``out_dir``; inputs are NEVER modified):
    repaired.dxf / repaired.phase2.dxf / repaired.phase3.dxf   checkpoints
    calibration.json        fitted transform(s)
    change_log.json         every correction, before/after + confidence
    side_by_side.png        repaired render vs source scan
    validation_report.md    entity counts + phase summaries
    needs_review_index.json + _review/*.png crops for low-confidence items
    README.txt              how to re-run on another sheet
"""

from __future__ import annotations

import os
import shutil
import time

from core.dxf_repair import ARCHIVE_LAYER, REVIEW_LAYER
from core.dxf_repair.common import (
    ChangeLog, archive_hatch_entities, bucket_counts, ensure_layer,
)
from core.dxf_repair.calibrate import Calibration, calibrate
from core.dxf_repair.fix_dimensions import repair_dimensions
from core.dxf_repair.fix_shapes import repair_shapes
from core.dxf_repair import validate as V


def _load_doc(dxf_path):
    """ezdxf load with the recover path first (extraction DXFs are dirty)."""
    try:
        from ezdxf import recover
        doc, auditor = recover.readfile(dxf_path)
        if auditor.has_errors:
            audit_txt = "; ".join(str(e) for e in auditor.errors[:3])
            return doc, f"recovered (audit notes: {audit_txt})"
        return doc, "recovered-clean"
    except Exception:                  # noqa: BLE001 — fall back to strict loader
        import ezdxf
        return ezdxf.readfile(dxf_path), "strict"


def _readme_text() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "README.md")
    if os.path.isfile(src):
        try:
            with open(src, "r", encoding="utf-8") as fh:
                return fh.read()
        except Exception:              # noqa: BLE001
            pass
    return ("BES DXF Repair — see docs in repository: core/dxf_repair/README.md")


def run_repair(extracted_dxf: str, original_scan: str, out_dir: str,
               ai_provider=None, control_points=None,
               progress_cb=None, arrow_style="oblique") -> dict:
    t0 = time.time()

    def say(msg):
        if progress_cb:
            progress_cb(msg)

    extracted_dxf = os.path.abspath(extracted_dxf)
    original_scan = os.path.abspath(original_scan)
    out_dir = os.path.abspath(out_dir) or out_dir
    os.makedirs(out_dir, exist_ok=True)
    log = ChangeLog()
    summary = {"out_dir": out_dir, "steps": [], "errors": []}

    if not os.path.isfile(extracted_dxf):
        raise FileNotFoundError(extracted_dxf)
    if not os.path.isfile(original_scan):
        raise FileNotFoundError(original_scan)

    # ── Phase 0: work only on copies ────────────────────────────────────────
    work_copy = os.path.join(out_dir, "_work_extracted.dxf")
    shutil.copy2(extracted_dxf, work_copy)
    doc, how = _load_doc(work_copy)
    say(f"phase 0: loaded working copy ({how})")
    msp = doc.modelspace()
    before_counts = bucket_counts(msp.query("*"))
    say("phase 0: buckets @start "
        + ", ".join(f"{k}={v}" for k, v in sorted(before_counts.items())))

    archived = archive_hatch_entities(doc, msp, progress_cb=say)
    ensure_layer(doc, ARCHIVE_LAYER, color=253, frozen=True, locked=True)
    ensure_layer(doc, REVIEW_LAYER, color=6)

    # User request: remove all hatches entirely from the drawing.
    # After archiving them (moved to _HATCH_ARCHIVE), delete them outright
    # so the repaired DXF has zero hatch entities.
    deleted_hatches = 0
    for e in list(msp.query("*")):
        if getattr(e.dxf, "layer", "") == ARCHIVE_LAYER:
            try:
                msp.delete_entity(e)
                deleted_hatches += 1
            except Exception:          # noqa: BLE001
                continue
    if deleted_hatches:
        say(f"phase 0: deleted {deleted_hatches} hatch entities entirely")

    doc.saveas(os.path.join(out_dir, "repaired.phase0.dxf"))
    summary["steps"].append({"phase": 0, "archived_hatches": archived,
                              "deleted_hatches": deleted_hatches})

    # ── Phase 1: image ⇄ DXF calibration ───────────────────────────────────
    geometry_entities = [e for e in msp.query("*")
                         if getattr(e.dxf, "layer", "") != ARCHIVE_LAYER]
    calib: Calibration = calibrate(original_scan, geometry_entities,
                                   control_points=control_points,
                                   progress_cb=say)
    calib_path = os.path.join(out_dir, "calibration.json")
    calib.save(calib_path)
    log.warn(f"calibration quality={calib.quality} "
             f"(max residual {calib.residual_max_mm:.1f} mm)")
    summary["steps"].append({"phase": 1, "quality": calib.quality,
                             "residual_max_mm": round(calib.residual_max_mm, 2),
                             "json": calib_path})


    def save_phase(name):
        pth = os.path.join(out_dir, name)
        doc.saveas(pth)
        return pth

    # ── Phase 2: dimensions ────────────────────────────────────────────────
    say("phase 2: dimension audit & rebuild …")
    p2 = {}
    try:
        p2 = repair_dimensions(doc, msp, original_scan, calib, log, out_dir,
                               ai_provider=ai_provider, progress_cb=say,
                               arrow_style=arrow_style)
        summary["steps"].append({"phase": 2, **p2.get("stats", {})})
    except Exception as exc:           # noqa: BLE001 — keep going, report it
        err = f"phase 2 error: {exc}"
        summary["errors"].append(err)
        say(err)
    save_phase("repaired.phase2.dxf")

    # ── Phase 3: shapes ────────────────────────────────────────────────────
    say("phase 3: shape audit & rebuild …")
    p3 = {}
    try:
        p3 = repair_shapes(doc, msp, original_scan, calib, log, out_dir,
                           dim_endpoints=p2.get("dim_endpoints", []),
                           progress_cb=say)
        summary["steps"].append({"phase": 3, **p3.get("stats", {})})
    except Exception as exc:           # noqa: BLE001
        err = f"phase 3 error: {exc}"
        summary["errors"].append(err)
        say(err)
    p3_ckpt = save_phase("repaired.phase3.dxf")


    # ── Final save + Phase 4 validation artifacts ──────────────────────────
    final_dxf = os.path.join(out_dir, "repaired.dxf")
    doc.saveas(final_dxf)
    change_log_path = log.save(os.path.join(out_dir, "change_log.json"))

    say("phase 4: rendering & diff …")
    render_png = ""
    sbs_png = ""
    try:
        render_png = V.render_dxf_png(msp, os.path.join(out_dir,
                                                        "repaired_render.png"))
        sbs_png = V.side_by_side(render_png, original_scan,
                                 os.path.join(out_dir, "side_by_side.png"))
    except Exception as exc:           # noqa: BLE001
        summary["errors"].append(f"render skipped: {exc}")

    after_counts = bucket_counts(msp.query("*"))
    counts = {"before": before_counts, "after": after_counts}
    review_info = V.review_index(log, out_dir)
    try:
        report_md = V.build_final_report(
            {"source_dxf": extracted_dxf, "source_image": original_scan,
             "seconds": time.time() - t0},
            p2, p3, counts, calib, review_info)
        V.write_report(os.path.join(out_dir, "validation_report.md"), report_md)
    except Exception as exc:           # noqa: BLE001
        summary["errors"].append(f"report failed: {exc}")

    readme_path = os.path.join(out_dir, "README.txt")
    try:
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write(_readme_text())
    except Exception:                  # noqa: BLE001
        pass

    review_count = review_info.get("count", 0)
    p2s = p2.get("stats", {}) if isinstance(p2, dict) else {}
    p3s = p3.get("stats", {}) if isinstance(p3, dict) else {}
    summary.update({
        "dxf": final_dxf,
        "checkpoint2": os.path.join(out_dir, "repaired.phase2.dxf"),
        "checkpoint3": p3_ckpt,
        "change_log": change_log_path,
        "calibration": calib_path,
        "side_by_side": sbs_png,
        "render": render_png,
        "review_index": review_info.get("path"),
        "needs_review": review_count,
        "counts_after": {k: v for k, v in sorted(after_counts.items())
                         if k != "TOTAL"},
        "totals": {
            "dims_rebuilt": p2s.get("rebuilt", 0),
            "annotations_fixed": p2s.get("annotation_fallback", 0),
            "shapes_fixed": (p3s.get("rects_rebuilt", 0)
                             + p3s.get("circles_rebuilt", 0)),
            "hatches_archived": archived,
            "entities_before": before_counts.get("TOTAL", 0),
            "entities_after": after_counts.get("TOTAL", 0),
        },
        "seconds": round(time.time() - t0, 1),
    })
    say(f"done: repaired.dxf written · {review_count} item(s) need review"
        if review_count else "done: no items required human review")
    return summary
