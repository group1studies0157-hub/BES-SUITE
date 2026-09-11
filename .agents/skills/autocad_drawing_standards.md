# AutoCAD Drawing Standards & Skills — BES Drawing Tools

> **Serves:** CAD Process (core/cad_engine.py), CAD Process 2 (gui/cad_panel2.py),
> GAD Generator (core/gad_generator.py). **NOT bore log** (gui/borelog_panel.py,
> borelog_dxf/*) — that tool has its own drawing conventions and must not be
> changed by this knowledge.
>
> **How to use:** this file is the *specification*. The live values are exported
> by `core/cad_knowledge.py` (single source of truth). Read both when changing
> any drawing-generation code in the three tools above.

---

## 1. Universal quality bar (every drawing BES emits)

These rules come from the National CAD Standard (NCS) layer model,
Autodesk CAD-standards guidance, and Indian Railways GAD practice. They apply
to all three tools.

1. **1:1 model space, millimetres.** One drawing unit = 1 mm. Never scale
   geometry; scale only annotations (text, ticks, gaps).
2. **Annotate to plot size.** Text plots at 2.5 mm minimum (2.0 mm only for
   dense stacks). At 1:100 that is 250 model-mm; the height is computed from
   the drawing extent, never hard-coded.
3. **Layer discipline.** Every entity sits on a named layer from the layer
   table below. Never draw on layer `0` or `DEFPOINTS`.
4. **Dimension chains are complete.** Every chain covers its full extent —
   the sum of segments must equal the overall dimension (see §4).
5. **RDSO reference notes travel with the drawing.** If the bridge type matches
   a standard drawing, quote it in the notes block.
6. **Title block is mandatory.** Bridge no., description, project/section/
   division, chainage, loading, scale, drawing number, date.

---

## 2. Layer model

Canonical layers (colour = AutoCAD Color Index):

| Layer | ACI | Purpose |
|---|---|---|
| GEOMETRY | 7 | structural outlines, decks, walls, girders |
| DIMENSIONS | 3 | dimension chains and their text |
| CENTRELINES | 1 | bridge axis, track centre, CL marks |
| ANNOTATIONS | 2 | labels, notes, title text |
| LEVELS | 3 | RL / HFL / BL / FRL markers and text |
| SYMBOLS | 6 | arrows, section marks, north, ticks |
| BORDER | 5 | drawing border and title block frame |
| TITLEBLOCK | 4 | title block text |

Rules (NCS-style):
- layers are created before first use; emitting on a missing layer is a bug
- `0`, `DEFPOINTS`, `LAYER0` are forbidden for generated geometry
- do not freeze/lock layers the drawing depends on
- lineweight hierarchy via layer, not per-entity overrides: border/borderline
  0.50, structure 0.35, dims/annotations 0.25, hatch/secondary 0.18

---

## 3. Text & annotation sizing

Height ladder (plot-mm → model-mm at 1:100): **title 5.0 → 500**,
**dim 2.5 → 250**, **note 3.0 → 300**, **level 2.5 → 250** (micro 2.0/200 for
dense stacks only).

- Style `STANDARD`, simplex/romans-class SHX — portable, no font substitution.
- Justification: notes left-aligned, level values centred on the marker.
- Long notes wrap at ~90 characters; continuation lines indent to align.

Sizing algorithm (used by CAD Process / CAD Process 2 / GAD Generator):
```
ext = max drawing extent (mm)
h_dim  = clamp(ext * 0.0025, 2.5 * scale, 50)   # ≤ 0.025 of extent
h_note = clamp(ext * 0.0030, 3.0 * scale, 60)   # ≤ 0.020 of extent
h_title= clamp(ext * 0.0050, 5.0 * scale, 35)   # ≤ 0.015 of extent
```

---

## 4. Dimensioning rules

From the ezdxf dimensioning model + railway drafting practice:

- Chains: place dimension line offset ~`ext * 0.01` from geometry, stack
  multiple chains at ~`4 × text height` pitch.
- **Chain completeness check:** `sum(segments) == overall ± 1 mm`. BES repairs
  broken chains by redistributing the residual across segments (see
  `repair_dimension_chain` in core/cad_knowledge.py).
- Text: above the dimension line (dimtad=1), centred (dimjust=0), never
  overlapping ticks. If crowded, alternate text sides; suppress nothing.
- Ticks: oblique ARCHTICK style, size ~`0.8 × text height`.
- Units: mm everywhere; RL/HFL/BL values in metres with 3 decimals.
- Zero suppression: leading zeros off, trailing zeros on (masonry-style
  "4350" reads best on GADs).
- ezdxf note: `add_linear_dim(...).render()` — always call `render()`, or the
  dimension displays only in applications that re-render blocks.

---

## 5. Hatching — soil, concrete & materials

Canonical pattern vocabulary (AutoCAD standard patterns only — portable,
no custom .pat files):

| Material | Pattern | Angle | Scale guide |
|---|---|---|---|
| Earth / soil fill (section) | `EARTH` | 45 | spacing ≈ 3–5 mm plot (extent/300 at 1:100) |
| Earth (BES line technique) | manual 45° ticks | 45 | tick pairs at 300 model-mm pitch |
| Structural steel sections | `ANSI31` | 45 | tight — spacing ≈ 1.5–2 mm plot |
| Plain / mass concrete | `AR-CONC` | 0 | sparse — aggregate reads at extent/100 |
| RCC / PSC (GAD views) | *no hatch* | — | plain outline + concrete-grade note; hatch only in detail drawings |
| Brick masonry | `ANSI37` | 45 | medium — cross-hatch reads at extent/200 |
| Random rubble masonry | `GRAVEL` | 0 | medium, denser than concrete |
| Sand / gravel bed | `AR-SAND` | 0 | sparse |
| Water (reservoir/tank) | `AR-RSHKE` | 0 | sparse |
| Generic cross-hatch (misc) | `NET` | 0 | fallback only |

Rules:
1. **Soil in section:** prefer the BES line technique (as used by GAD
   Generator: 45° ticks from the bed line, 300 model-mm pitch, HATCHING
   layer) for GADs — it plots cleaner than `EARTH` at 1:100. Use the `EARTH`
   pattern when a closed boundary region is already traced (CAD Process).
2. **Concrete:** RCC/PSC superstructure stays unhatched in GAD views (RDSO
   convention); mass concrete in foundations/abutments uses `AR-CONC` sparse;
   structural-steel sections use tight `ANSI31` at 45°.
3. **Adjacent parts alternate** — where two hatched parts meet in one
   section, alternate angle 45°/135° or vary spacing (ANSI section-lining
   rule) so the joint stays readable.
4. **Layer:** every hatch goes on `HATCHING` (ACI 8). Never hatch over text,
   dimensions or level markers — emit hatches *before* annotations, or mask
   annotation backgrounds.
5. **Scale with the drawing:** hatch spacing is derived from the drawing
   extent like text sizes (§3) — never a fixed magic number, or it disappears
   at 1:500 and blacks out at 1:10.
6. **Purging/archiving:** when deleting hatches during repair, archive to
   `_HATCH_ARCHIVE` (frozen + locked) — see bes_cad_knowledge.py.

## 6. AutoLISP emission rules

BES emits LISP for the AutoCAD-native route (CAD Process + CAD Process 2).
Rules that keep generated LISP reliable (Lee Mac conventions, adapted):

1. **entmake over command calls.** `(entmake (list (cons 0 "LINE") ...))` is
   transaction-safe, CMDECHO-independent, and does not touch OSNAP.
2. **Define helpers before `c:BES-DRAW`.** Layer/text/line helpers must be
   loaded before the command function runs.
3. **Localise and preserve system variables.** Wrap bodies with
   `(setq oe (getvar "CMDECHO")) (setvar "CMDECHO" 0)` … restore in a wrapper
   `*error*` handler AND at normal exit.
4. **Escape literal text**: backslash and double-quote in note strings.
5. **One defun per concern** (`bes-layer`, `bes-line`, `bes-text`, `bes-circle`).
   No global namespace pollution beyond the `bes-` / `c:BES-` prefixes.
6. **Numbers formatted to 3 decimals** — 1:1 mm precision without float noise.

---

## 7. RDSO / Indian Railways drawing practice

- Standard references to quote: RDSO B-10221 (3.05 m), B-10221R (6.1 m),
  B-10361 (12.2 m PSC slab), girder drawings per RDSO catalogue
  (see core/gad_standards.py SPAN_TYPES for the canonical list + defaults).
- Notes block order: superstructure → substructure → materials → drainage
  (weep holes) → approaches → general. ALL CAPS.
- Title block order: BRIDGE NO. / DESCRIPTION / PROJECT-SECTION-DIVISION /
  CHAINAGE / LOADING / SCALE / DRG NO. / DATE.
- Levels annotation: RAIL LEVEL, FORMATION, HFL, BED,_CC top/bottom — metres,
  3 decimals, stacked vertically on the elevation with markers on CENTRELINES.

---

## 8. Vision/AI extraction prompts (the three hook points)

The knowledge pack is injected into these prompts at runtime:

| Tool | Constant | Injection |
|---|---|---|
| CAD Process | `VISION_PROMPT` in core/cad_engine.py | `build_vision_rules_block()` appended after the layer table |
| CAD Process 2 | `EXTRACT_HEAD` / `OBSERVE_SYSTEM_PROMPT` / `VERIFY_SYSTEM_PROMPT` in gui/cad_panel2.py | `extract_rules_block()` appended to each |
| GAD Generator | `GadInput.from_ai()` system string in core/gad_generator.py | `gad_rules_block()` appended to the rules sentence |

Prompt rules for extraction AIs (keep when editing prompts):
- Output ONE JSON object, no prose/fences. `null` for unreadable values.
- mm for dimensions, m for levels, 3-decimal metres for RLs.
- Read every number in a chain; never sum or skip chain members.
- Assign every entity to a §2 layer; annotation geometry goes to ANNOTATIONS.
- Quote the RDSO reference when the bridge type matches the §6 catalogue.

---

## 9. Ponginess guard — what NOT to do

- Do not scale geometry to fit; compute annotation size from extent.
- Do not emit dimensions without `render()` (ezdxf) or the rendered block.
- Do not put notes as raw TEXT on GEOMETRY layer.
- Do not hard-code text heights that break at other scales.
- Do not hatch RCC/PSC superstructure in GAD views, or hatch over text/dims.
- Do not use custom .pat patterns — standard AutoCAD names only (§5 table).
- Do not touch gui/borelog_panel.py or borelog_dxf/* from this knowledge path.
