# Bridge Engineering Suite v2.0

A local-first desktop application for bridge/civil engineering workflows — CD processing, AI-powered AutoCAD generation from scanned drawings, GAD checking, hydraulic calculations, bore-log conversion (Excel/PDF → DXF), and a study knowledge base. Built with Python + PyQt6.

---

## Quick Start

### Windows
```
Double-click run_windows.bat
```

### Linux / macOS
```
bash run_linux_mac.sh
```

Either script creates a virtual environment, installs dependencies from `requirements.txt`, and launches the app.

---

## Panels

The app is a sidebar shell with eleven pages:

| # | Panel | Purpose |
|---|-------|---------|
| 0 | **Home** | Dashboard launcher — tool cards, recent projects, quick links, system status. |
| 1 | **CD Processing** | Enter bridge numbers, pick a mode (Full CD / Drawings / Quantities / Specs / Cross-Ref), run the pipeline with live progress and run history. |
| 2 | **CAD Process** | Upload an image/PDF drawing → AI (or OpenCV fallback) detects geometry, dimensions, text, hatching → outputs an AutoLISP script + editable DXF. |
| 3 | **CAD Process 2** | Second-generation CAD extraction workflow. |
| 4 | **GAD Generator** | **Prompt + dimensions → parametric GAD.** Describe the bridge (spans, RL/FL/BL/HFL, span type), get a draft General Arrangement Drawing as AutoLISP + DXF. |
| 5 | **GAD Checking** | General Arrangement Drawing verification. |
| 6 | **Hydraulic Calculations** | Hydraulic computations with OCR-assisted parameter extraction. |
| 7 | **Bore Log** | Convert bore-log reports (Excel/PDF) into BORE HOLE DETAILS DXF drawings — see *Bore Log → DXF* below. |
| 8 | **Knowledge Base** | Study/reference tools. |
| 9 | **Sheets Sync** | Pull live project tracking data from Google Sheets. |
| 10 | **Settings** | Theme (dark/light) and API keys. |

---

## AI Providers

The suite uses a unified AI layer (`gui/ai_provider.py`) supporting **two providers with automatic fallback**:

- **Google Gemini** (`gemini-2.5-flash`) — tried first when a Gemini key is present.
- **Anthropic Claude** (`claude-sonnet-5`) — used as fallback, or as primary when only a Claude key is set.

If both keys are configured, Gemini runs first and Claude covers any Gemini failure (missing package, quota, auth). If neither is set, CAD Process falls back to local OpenCV structural detection (shapes only, no text/dimension recognition).

---

## API Key Setup

### Option 1 — In-app (recommended)
1. Launch the app.
2. Open **Settings** (bottom-left) → **API Keys**.
3. Paste your Anthropic and/or Google key and click **Save**. Keys are stored locally via `QSettings` (Windows registry) and apply instantly.

You can also paste a key directly in the CAD Process panel's key card.

### Option 2 — Environment variables
```
set ANTHROPIC_API_KEY=sk-ant-api03-...
set GEMINI_API_KEY=AIzaSy...
```

Get keys at: https://console.anthropic.com  and  https://aistudio.google.com

---

## Output DXF Layers (CAD Process)

| Layer | Colour | Contents |
|-------|--------|----------|
| GEOMETRY | White | All structural lines, shapes |
| DIMENSIONS | Green | Dimension lines + values |
| ANNOTATIONS | Yellow | Labels, notes, titles |
| HATCHING | Grey | Hatch region outlines |
| ELEVATIONS | Green | RL/FL/BL level markers |
| SYMBOLS | Magenta | Arrows, section marks |
| BORDER | Blue | Drawing border |
| TITLEBLOCK | Cyan | Source, date, scale info |

Load the LISP in AutoCAD with `(load "file.lsp")` then run `(BES-DRAW)`, or open the `.DXF` directly in any CAD tool (AutoCAD, BricsCAD, LibreCAD, FreeCAD).

---

## GAD Generator (Panel 3)

The **inverse** of CAD Process: instead of reading a drawing, you *describe* it
and the suite drafts a General Arrangement Drawing for you. The engine is
**fully dynamic** — one generator, many bridges — driven by per-bridge levels
and the span-type catalogue in `core/gad_standards.py` (seeded from the
standard documentation / reference GAD set).

1. Open **GAD Generator** in the sidebar.
2. Type a prompt with dimensions, e.g.:
   `3KK: (1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX, RL 178.741, FL 177.979, BL 175.877, HFL 176.877, max scour 174.5, 2 tracks C/C 9450, 25T-2008`
3. **Generate with AI** (Claude/Gemini fills the structured parameter schema,
   with deterministic fallback) or **Generate (offline)**. Optionally pick a
   span type from the catalogue to apply RDSO defaults.
4. Inspect the **live in-app preview** (rendered locally with Pillow — no
   AutoCAD needed; zoom Fit/25–150%). Untick **"Save DXF + LISP files"** to
   preview only, without writing anything.
5. Outputs (when saving): `<bridge>-GAD.dxf` (open directly in AutoCAD → Save
   As DWG), `<bridge>-GAD.lsp` (load in AutoCAD, run `BES-GAD`) and
   `<bridge>-GAD-preview.png`.

**Dynamic inputs** — anything the prompt mentions changes the drawing:

| Input | Effect |
|-------|--------|
| `RL` / `FL` / `BL` | rail / formation / bed levels → construction depths, wall & return-wall heights |
| `HFL` | water line drawn at its real level + `F.B. =` freeboard note |
| `max scour` | foundation extended below scour + foundation-level & scour markers |
| span expression (`(1x4.25+1x4.5+1x4.25)x1.50 m`) | any number of cells / spans, any vent height |
| `N tracks C/C xxxx` | single / double / multi-track layout & track centre lines |
| span family (`RCC box`, `PSC slab`, `PSC girder`, `box girder`, `steel girder`, `FOB`) | matching view template + RDSO defaults + standard notes |
| engineering fit checks | automatic WARNING notes when the box stack exceeds depth below formation or freeboard is negative |

Span families and their defaults live in `core/gad_standards.py` — edit to
match your approved section drawings. The input schema mirrors
`core/param_extractor.py` dataclasses, so a GAD you extract can be
round-tripped straight back into a generated drawing.

### Batch generation — many bridges from one spreadsheet
```
python batch_gad.py bridges.csv --out ./generated --json
python batch_gad.py bridges.xlsx          # openpyxl required
python batch_gad.py --sample             # write a template first
```
Each row is a `prompt` (same free-text format as above) plus optional override
columns (`bridge_no`, `span_type`, `rail_level_m`, `formation_level_m`,
`bed_level_m`, `hfl_m`, `scour_level_m`, `num_tracks`, `track_centres_mm`, …).
Per-bridge folders: `./generated/<bridge_no>/<bridge_no>-GAD.dxf|.lsp`.

Single bridge, headless:
```
python generate_gad.py "2x9.15 m PSC slab at CH 52.300, RL 112.25, FL 111.15, BL 108.2, HFL 109.4" --offline --out ./out
```

---

## Bore Log → DXF (`bes_borelog/`)

The bore-log converter now lives **inside this repository** under
`bes_borelog/borelog_dxf/`. It was subtree-merged from its former
standalone repo (`bes_borelog` is no longer a separate Git repository or
submodule), so the tool and the suite are versioned together.

It converts bore-log reports (SPT/RQD stratigraphy sheets, "one borehole
per sheet/page") from **Excel (.xls/.xlsx)** or **PDF** into an AutoCAD
**DXF** "BORE HOLE DETAILS (NOT TO SCALE)" drawing — hatched soil/rock
columns, SPT-N / RQD annotations, depth ticks, termination markers and a
legend.

Ways to use it:

- **In the app:** open the **Bore Log** panel — `gui/borelog_panel.py`
  wraps `borelog_dxf` (parsers → shared model → DXF builder).
- **Standalone GUI:** from `bes_borelog/`, run `python -m borelog_dxf.gui`
  (or double-click `bes_borelog/Run_BoreLog_Tool.bat`, which manages its
  own `.venv`).
- **CLI / batch:** from `bes_borelog/`, run
  `python -m borelog_dxf.cli report.xls -o output.dxf` (drag-drop:
  `Convert_DragDrop.bat`).

Its dependencies (xlrd, openpyxl, pdfplumber, PyMuPDF, ezdxf,
pytesseract) are already in the root `requirements.txt` — no extra
install step. Full docs: `bes_borelog/README.md`.

---

## Project Structure

```
BES/
├─ main.py                 Entry point — theme + MainWindow
├─ requirements.txt
├─ run_windows.bat / run_linux_mac.sh
├─ core/
│  └─ cad_engine.py        CV → dedup → AutoLISP → DXF engine
├─ gui/
│  ├─ main_window.py       Sidebar + 7-page stack + Settings
│  ├─ styles.py            COLORS, STYLESHEET, theming
│  ├─ ai_provider.py       Unified Claude + Gemini wrapper (dual-key fallback)
│  ├─ cd_panel.py          Panel 0
│  ├─ cad_panel.py         Panel 1
│  ├─ cad_panel2.py        Panel 2
│  ├─ gad_panel.py         Panel 3
│  ├─ hydraulic_panel.py   Panel 4  (+ hydraulic_ocr.py)
│  ├─ borelog_panel.py     Panel 7 — wraps bes_borelog/borelog_dxf
│  ├─ knowledge_panel.py   Panel 5
│  └─ files/               param_extractor, vc_lookup, ...
├─ bes_borelog/            Bore-log → DXF tool, merged into this repo
│  └─ borelog_dxf/         parsers (xls/pdf) → model → DXF builder + GUI/CLI
└─ Database/               Reference PDFs
```

---

## Requirements
- Python 3.10+
- Windows 10/11 (Linux/macOS supported via `run_linux_mac.sh`)
- ~600 MB disk (dependencies)

Core libraries: PyQt6, OpenCV, ezdxf, Pillow, PyMuPDF, anthropic, google-generativeai, pytesseract.
