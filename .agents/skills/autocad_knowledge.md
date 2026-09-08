# AutoCAD & DXF Knowledge Base — Bridge Engineering Suite (BES)

> **Purpose:** Living reference for every AutoCAD/DXF operation in BES.
> Every new bug fix, feature, or standard discovery should be appended here.
> Load this file when working on any `.dxf`, `.dwg`, AutoLISP, or CAD-related code.

---

## 1. DXF Entity Reference (ezdxf)

### Entity Types We Use

| Entity | ezfxf type | Purpose in BES |
|--------|-----------|----------------|
| LINE | `msp.add_line(start, end)` | Structural edges, dimension witnesses |
| LWPOLYLINE | `msp.add_lwpolyline(pts, is_closed)` | Rectangles, polygons, borders |
| POLYLINE | `msp.add_polyline(pts)` | Complex multi-segment geometry |
| CIRCLE | `msp.add_circle(center, radius)` | Piers, bolts, holes |
| ARC | `msp.add_arc(center, radius, start, end)` | Haunches, curves |
| MTEXT | `msp.add_mtext(text)` | Annotations, notes, levels |
| TEXT | `msp.add_text(text)` | Simple labels |
| DIMENSION | `msp.add_linear_dim()` / `add_aligned_dim()` | Associative dimensions |
| HATCH | `msp.add_hatch()` | Fill patterns (archived/deleted in BES) |
| INSERT | `msp.add_blockref()` | Reusable blocks |
| LEADER | `msp.add_leader()` | Callout leaders |

### Critical ezdxf Patterns

```python
import ezdxf
from ezdxf import recover

# Always use recover for dirty extraction DXFs
doc, auditor = recover.readfile("extracted.dxf")
if auditor.has_errors:
    # Log but continue — most extraction DXFs have minor issues
    pass

msp = doc.modelspace()

# Entity lifecycle — deleted entities lose .dxf attribute
# ALWAYS check entity_alive() before accessing .dxf
def entity_alive(entity):
    return bool(getattr(entity, "is_alive", True)) and hasattr(entity, "dxf")

# Querying entities
for e in msp.query("DIMENSION"):
    layer = getattr(e.dxf, "layer", "")
    text = getattr(e.dxf, "text", "")

# Saving
doc.saveas("output.dxf")  # NEVER modify the source file
```

### Dimension Entity Anatomy

```python
# DIMENSION has these key attributes:
e.dxf.defpoint      # Dimension line location (base point)
e.dxf.defpoint2     # Extension origin 1
e.dxf.defpoint3     # Extension origin 2
e.dxf.text          # Displayed text ("<>" = geometry-derived)
e.dxf.dimtype       # 0=linear, 1=aligned, 2=angular, 3=diameter, 4=radius
e.dxf.dimstyle      # Style name reference
e.dxf.layer         # Layer name

# Creating associative dimensions (ezdxf >=1.x)
override = msp.add_linear_dim(
    base=(x, y),           # dimension line location
    p1=start_point,        # extension origin 1
    p2=end_point,          # extension origin 2
    angle=0,               # 0=horizontal, 90=vertical
    dimstyle="BES_REPAIR",
    dxfattribs={"layer": "DIM"}
)
renderer = override.render()
ent = renderer.dimension    # the actual DIMENSION entity
```

---

## 2. BES Layer Conventions

| Layer Name | Color | Purpose | Status |
|-----------|-------|---------|--------|
| `DIM` / `_DIM` | 3 (green) | Rebuilt dimension entities | Active |
| `_HATCH_ARCHIVE` | 253 | Archived hatches | Frozen/Locked |
| `_NEEDS_REVIEW` | 6 (magenta) | Human review markers | Active |
| `GEOMETRY` | 7 (white) | Structural lines/shapes | Active |
| `DIMENSIONS` | 3 | Original dimension lines | Active |
| `CENTRELINES` | 1 (red) | Centre lines | Active |
| `ANNOTATIONS` | 2 (yellow) | Labels, notes | Active |
| `HATCHING` | 8 | Hatch regions | Active |
| `ELEVATIONS` | 3 | RL/FL/BL markers | Active |
| `SYMBOLS` | 6 | Symbols/markers | Active |
| `BORDER` | 5 | Drawing border | Active |
| `TITLEBLOCK` | 4 | Title block | Active |
| `DEFPOINTS` | — | AutoCAD definition points | Never use |
| `EXG WORK` | 3 | Existing work geometry | Import only |
| `PROP.DRAW` | 4 | Proposed drawing | Import only |
| `EXG TEXT` | 7 | Existing text | Import only |

**Rule:** Never create new entities on `DEFPOINTS`, `0`, or `LAYER0`.
Always use explicit layer names from the table above.

---

## 3. BES DIMSTYLE Standards

### BES_REPAIR Style (for DXF Repair pipeline)

```python
DIMSTYLE_NAME = "BES_REPAIR"

attribs = {
    "dimtxt": txt_h,              # Text height (150-400mm, from drawing)
    "dimasz": max(80, txt_h*0.6), # Arrow size
    "dimexe": max(120, txt_h*0.5),# Extension overshoot
    "dimexo": min(100, txt_h*0.3),# Extension offset from geometry
    "dimgap": max(60, txt_h*0.35),# Gap between line and text
    "dimlfac": 1.0,               # Model units = mm
    "dimscale": 1.0,              # No overall scale
    "dimdec": 0,                  # No decimal places (mm integers)
    "dimtad": 1,                  # Text above dim line
    "dimclrd": 256,               # BYLAYER for dim line
    "dimclre": 256,               # BYLAYER for extension lines
    "dimclrt": 7,                 # White text
    "dimblk": "",                 # Closed filled arrows (default)
    "dimblk2": "",                # Same for second arrow
}
```

### Arrow Style Options

| Style | `dimblk` value | Description |
|-------|---------------|-------------|
| Closed filled | `""` (empty) | Default — filled triangles |
| Closed outline | `_CLOSED` | Open arrowheads |
| Architectural tick | `_ARCHITECTURAL_TICK` | Slanted ticks |
| Dot | `_DOT` | Dot markers |
| None | `"none"` | No arrows |

---

## 4. Bridge Engineering Drawing Standards (RDSO)

### Span Types & Defaults

| Type | Key | Typical Spans | Girder Depth | Deck Width |
|------|-----|--------------|-------------|-----------|
| RCC Box | `rcc_box` | Any | Slab 350mm, Wall 350mm | 6200mm |
| PSC Slab 3.05m | `psc_slab_3.05` | 3.05m | 450mm | 6200mm |
| PSC Slab 6.1m | `psc_slab_6.1` | 6.1m | 550mm | 6200mm |
| PSC Slab 9.15m | `psc_slab_9.15` | 9.15m | 700mm | 6200mm |
| PSC Slab 12.2m | `psc_slab_12.2` | 12.2m | 850mm | 6200mm |
| PSC Girder 12.2m | `psc_girder_12.2` | 12.2m | 1250mm | 6200mm |
| PSC Girder 18.3m | `psc_girder_18.3` | 18.3m | 1600mm | 6200mm |
| PSC Girder 24.4m | `psc_girder_24.4` | 24.4m | 2000mm | 6200mm |
| Box Girder 24.4m | `box_girder_24.4` | 24.4m | 2500mm | 6200mm |
| Steel Girder 18.3m | `steel_girder_18.3` | 18.3m | 1800mm | 6200mm |
| Steel Girder 24.4m | `steel_girder_24.4` | 24.4m | 2400mm | 6200mm |
| FOB | `fob` | Variable | 450mm | 2400mm |

### Key Levels (from prompt)

- **RL** (Rail Level) — top of rail
- **FL** (Formation Level) — top of embankment/cutting
- **BL** (Bed Level) — bottom of formation
- **HFL** (High Flood Level) — design flood level
- **Scour Level** — maximum scour depth

### Track Parameters

- Standard track gauge: 1676mm (Indian broad gauge)
- C/C track distance: 4000-5300mm (typically 4070mm for BG)
- Loading: 25T-2008 (Co-Co locomotive)

### Common Abbreviations

| Abbrev | Meaning |
|--------|---------|
| RCC | Reinforced Cement Concrete |
| PSC | Pre-stressed Concrete |
| M.S. | Mild Steel |
| FOB | Foot Over Bridge |
| RL | Rail Level |
| FL | Formation Level |
| BL | Bed Level |
| HFL | High Flood Level |
| C/C | Centre to Centre |
| CH | Chainage |
| DN | Down line |
| UP | Up line |

---

## 5. DXF Repair Pipeline Knowledge

### Phase Structure (run_all.py)

```
Phase 0: Load copy → archive hatches → DELETE hatches
Phase 1: Image ↔ DXF calibration (affine transform)
Phase 2: Dimension audit → ground-truth OCR+vision → rebuild
Phase 3: Shape audit → rectangle/circle rebuild
Phase 4: Validation → render → diff → report
```

### Dimension Repair Rules

1. **Never guess** — if OCR/vision disagree, send to NEEDS_REVIEW
2. **Orthogonality gate** — reject non-orthogonal pairs unless scan confirms
3. **Layer discipline** — always use `DIM`/`_DIM`, never inherit victim's layer
4. **Associative text** — use `<>` (geometry-derived), never hardcode values
5. **Spacing** — offset dimension lines perpendicular to geometry, push apart if overlapping
6. **Text visibility** — clamp dimtxt to 150-400mm, ensure clearly visible

### Debris Detection Rules

- MTEXT/TEXT with `parse_dimension_value()` returning `None` + not annotation = debris
- Whitelist: T0-T4, pier numbers, grid marks (A-F), material callouts (RCC, PSC, M.S.)
- Short tokens (< 4 alpha chars) that are valid drawing vocabulary → keep
- Route through `_mark_review()` first, auto-delete only after validation

### Hatch Handling

- Phase 0: archive to `_HATCH_ARCHIVE` (frozen/locked)
- Then DELETE all archived hatches entirely (user requirement: no hatches in output)
- `entities_before` vs `entities_after` shows hatch removal count

---

## 6. AutoLISP Generation Patterns

### Standard Helper Functions (BES-DRAW)

```lisp
(defun BES-MAKE-LAYERS () ...)     ; Create all BES layers
(defun BES-SET-LAYER (lname) ...)  ; Switch current layer
(defun BES-LINE (x1 y1 x2 y2) ...) ; Draw line
(defun BES-PLINE (pts closed) ...) ; Draw polyline
(defun BES-CIRCLE (cx cy r) ...)   ; Draw circle
(defun BES-ARC (cx cy r sa ea) ...); Draw arc
(defun BES-TEXT (txt x y h) ...)   ; Draw MTEXT
(defun BES-HATCH (pat sc ang x1 y1 x2 y2) ...) ; Draw hatch
```

### Coordinate System

- DXF: Y-up (standard math convention)
- AutoLISP IMAGE: Y-down (screen convention)
- Flip function: `(defun fy (y) (- H y))` where H = canvas height

### LISP Command Pattern

```lisp
(command "._LINE" (list x1 y1) (list x2 y2) "")
(command "._CIRCLE" (list cx cy) radius)
(command "._MTEXT" (list x y) "H" height "W" 0 text "")
(command "._LAYER" "M" layername "C" color layername "")
```

---

## 7. OCR & Vision Cross-Check

### Tesseract Configuration

```
--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.,+-
```
- PSM 7: single text line
- PSM 6: uniform block of text
- Whitelist: digits + decimal + sign only

### Ground Truth Logic

```python
def ground_truth_value(crop, ai_provider=None):
    val_ocr, conf, raw = ocr_value(crop)     # Tesseract
    val_vision = vision_value(ai_provider, crop)  # Gemini/Claude

    if both agree (within 0.5% tolerance):  → ACCEPT (high confidence)
    if OCR >= 70 conf alone:                → ACCEPT (OCR only)
    if disagreement or low confidence:      → NEEDS_REVIEW (never guess)
```

### Key Rule

**Geometry is MORE trustworthy than OCR'd junk text.**
Existing dimension defpoints are rebuilt from geometry.
Fragment/unlabeled clusters need confirmed ground truth or go to review.

---

## 8. Calibration (Phase 1)

### Affine Transform

```python
# 2x3 affine matrix: [a b tx; c d ty]
# Maps DXF mm ↔ pixel coordinates
m = np.array([[a, b, tx], [c, d, ty]])

def dxf_to_pixel(pt):
    return (m[0,0]*pt[0] + m[0,1]*pt[1] + m[0,2],
            m[1,0]*pt[0] + m[1,1]*pt[1] + m[1,2])

def pixel_to_dxf(px_pt):
    # Inverse affine
    ...
```

### Control Points

- Minimum 4 points for full affine
- 6-10 points recommended for good fit
- Points should cover the full drawing extent
- Quality measured by max residual (should be < 5mm)

---

## 9. Common Pitfalls & Solutions

### Pitfall 1: Deleted entity crash
**Symptom:** `AttributeError: 'NoneType' object has no attribute 'dxf'`
**Cause:** Entity was deleted by `msp.delete_entity()` earlier in the loop
**Fix:** Check `entity_alive(e)` before accessing `.dxf`

### Pitfall 2: Dimension text wrong layer
**Symptom:** Rebuilt dimensions on `LAYER0` or `DIMENSIONS`
**Cause:** Inheriting victim entity's layer
**Fix:** Use `_resolve_dim_layer(doc)` → always `DIM`/`_DIM`

### Pitfall 3: Diagonal garbage dimensions
**Symptom:** Dimensions at random angles (52°, 77°, -63°...)
**Cause:** Distance-maximizing fallback picking arbitrary point pairs
**Fix:** Orthogonality gate — reject non-orthogonal unless scan confirms

### Pitfall 4: Overlapping dimensions
**Symptom:** Dimension text and lines pile up on each other
**Cause:** Using text cluster center as dimension line base point
**Fix:** `_compute_dim_base()` — perpendicular offset + spacing tracker

### Pitfall 5: Tiny/invisible dimension text
**Symptom:** Dimensions present but unreadable
**Cause:** `dimtxt` too small relative to drawing scale
**Fix:** Clamp `dimtxt` to 150-400mm range, scale proportionally

### Pitfall 6: Hatch bloat
**Symptom:** DXF file huge, slow rendering
**Cause:** Thousands of hatch entities from extraction
**Fix:** Archive to frozen layer, then delete entirely

### Pitfall 7: ezdxf `add_linear_dim` base point
**Symptom:** Dimension line at wrong location
**Cause:** Using text cluster center instead of perpendicular offset
**Fix:** Calculate base point perpendicular to measured geometry

---

## 10. Session History

> **Every time you learn something new about AutoCAD/DXF/BES, append it here.**
> Format: `### [DATE] — Topic\nWhat was learned\nImpact: what changed`

### 2026-08-27 — DXF Repair Pipeline Overhaul
- Fixed 3 bugs in fix_dimensions.py (orthogonality, layer, debris)
- Added dimension spacing/overlap prevention
- Added arrow style options (closed_filled, closed, none, architectural, dot)
- Added hatch deletion (not just archiving)
- Added GUI dropdown for arrow style selection
- Impact: All 10 smoke tests pass, dimensions on correct layer, no overlaps

### 2026-08-27 — Dimension Text Sizing
- Clamped dimtxt to 150-400mm (was raw char_h)
- Increased arrow size, extension overshoot, gap for visibility
- Impact: Dimensions clearly readable at all zoom levels

### 2026-08-27 — Debris Detection Enhancement
- Added pass 3b for isolated junk fragments
- Whitelist for short valid tokens (T0-T4, pier numbers, material callouts)
- Impact: Catches "07", "DL'", "OSZ-", "OZE-" style fragments

---

## 11. Future Additions Checklist

- [ ] Add dimension tolerance display (±) for critical measurements
- [ ] Add leader annotation support for callouts
- [ ] Add block insertion patterns for standard symbols
- [ ] Add linetype mapping for centre lines, hidden lines
- [ ] Add text style definitions (font, width factor)
- [ ] Add plotting/publishing configuration
- [ ] Add xref (external reference) handling
- [ ] Add attribute block support for title blocks
- [ ] Add dynamic block patterns
- [ ] Add section view markers (A-A, B-B)
- [ ] Add elevation markers (triangles)
- [ ] Add grid line patterns (column/row letters + numbers)

---

*Last updated: 2026-08-27*
*This file grows with every BES session. Add new knowledge at the bottom.*
