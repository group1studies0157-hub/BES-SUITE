# BES DXF Repair Pipeline (Railway Bridge GAD)

Repairs a corrupted raster→vector AutoCAD DXF extraction of a scanned
railway-bridge General Arrangement Drawing against its source scan.

## Run from Python

```python
from core.dxf_repair.run_all import run_repair

summary = run_repair(
    "extracted.dxf",          # corrupted vision-extraction output
    "original_scan.tif",      # full-resolution source scan (.tif/.png/.jpg/.pdf)
    "./repair_out",           # everything lands here; inputs stay untouched
    # control_points=[[img_x, img_y, dxf_x, dxf_y], …],  # optional manual fit
    progress_cb=print,
)
print(summary["dxf"], summary["totals"])
```

## Re-run on a different bridge sheet

Nothing is hardcoded to one sheet's coordinates:

1. **Automatic calibration**, tried in two stages:
   - **Per-axis matcher** — matches scan-axis ink peaks to dominant parallel
     line bands of the DXF independently per axis (no shared X/Y scale assumed).
     Works when the sheet has a clean dimension/grid structure.
   - **Sheet-frame fit (fallback)** — if the per-axis matcher can't reach a
     consensus, the drawn page's outer ink frame is affinely mapped onto the
     DXF model extent. This covers the common GAD case where the source image
     is a straight render of the model (uniform scale) but the structural
     lines are too sparse/unevenly spaced for peak matching. It is accepted
     only when the fit is stable (correct orientation, near-uniform scale,
     page-frame fills most of the image) and is reported in the change log as
     `mode: auto-frame`.
2. If both automatic stages are rejected (`calibration.json → quality` absent /
   "poor" or an explicit "supply control_points" error), fall back to
   **6–10 explicit control points** through `control_points=[[img_x,img_y,dxf_x,dxf_y], …]`
   (pier centrelines, abutment corners, title-block corners work well) and
   re-run — phase checkpoints make that cheap:

```python
run_repair("extracted.dxf", "scan.tif", "out", control_points=[...])
```

3. Each phase writes `repaired.phaseN.dxf`; you can re-run only later phases by
   loading the checkpoint and calling the phase modules directly.

## What it fixes

| Corruption | Repair |
|---|---|
| Fragmented / garbage / missing dimension text | Ground-truth OCR (Tesseract psm 7 + whitelist) cross-checked by AI vision; rebuilt as **true associative DIMENSION** entities (`<text>` never overridden ⇒ value always re-derived from geometry, scale-proof) with ONE shared DIMSTYLE `BES_REPAIR` |
| Level/grade callouts (RL/FL/BL/HFL, 1:2:4) | Clean MTEXT annotation fallback — never faked as dimensions |
| Unclosed/non-orthogonal rectangles | Single closed `LWPOLYLINE`, exact corners, size verified vs scan via contours, original layer/colour preserved |
| Jagged pseudo-circles | Single `CIRCLE` (Kasa fit + optional Hough refinement), original layer/colour preserved |
| Duplicate overlapping outlines | Best copy kept, duplicates deleted |
| Hatch bloat | All HATCH/SOLID moved once to frozen+locked `_HATCH_ARCHIVE`, excluded from every analysis loop, visuals untouched |

Everything ambiguous goes to **NEEDS_REVIEW**: bright magenta flags on layer
`_NEEDS_REVIEW` inside the DXF plus `_review/item_*.png` crops and
`needs_review_index.json`. The pipeline **never silently guesses** a number.

## Deliverables produced per run

| File | Content |
|---|---|
| `repaired.dxf` | corrected drawing (plus `.phase0/2/3.dxf` checkpoints) |
| `calibration.json` | fitted transform(s), quality + residuals |
| `change_log.json` | every correction: old → new, confidence, method |
| `side_by_side.png` | repaired render next to the original scan |
| `validation_report.md` | entity-count table + phase summaries |
| `needs_review_index.json`, `_review/*.png` | human-review evidence pack |

## Honest limitation (associativity note)

Rebuilt dimensions are real DIMENSION entities whose definition points are
snapped to actual geometry vertices and whose text is left as `<>`
(measurement = geometry). Nudging a defpoint or STRETCHing geometry in
AutoCAD updates the displayed value automatically. Native osnap-level ACAD
association records (ACID networks) cannot be written by the ezdxf library;
if your approval workflow requires them, run `DIMREASSOC`/`DIMDISASSOCIATE`
once in AutoCAD — geometry values will not change.
