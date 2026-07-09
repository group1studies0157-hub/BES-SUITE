# Bridge Engineering Suite v2.0

A local-first desktop application for bridge/civil engineering workflows — CD processing, AI-powered AutoCAD generation from scanned drawings, GAD checking, hydraulic calculations, and a study knowledge base. Built with Python + PyQt6.

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

The app is a sidebar shell with seven pages:

| # | Panel | Purpose |
|---|-------|---------|
| 0 | **CD Processing** | Enter bridge numbers, pick a mode (Full CD / Drawings / Quantities / Specs / Cross-Ref), run the pipeline with live progress and run history. |
| 1 | **CAD Process** | Upload an image/PDF drawing → AI (or OpenCV fallback) detects geometry, dimensions, text, hatching → outputs an AutoLISP script + editable DXF. |
| 2 | **CAD Process 2** | Second-generation CAD extraction workflow. |
| 3 | **GAD Checking** | General Arrangement Drawing verification. |
| 4 | **Hydraulic Calculations** | Hydraulic computations with OCR-assisted parameter extraction. |
| 5 | **Knowledge Base** | Study/reference tools. |
| 6 | **Settings** | Theme (dark/light) and API keys. |

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
│  ├─ knowledge_panel.py   Panel 5
│  └─ files/               param_extractor, vc_lookup, ...
└─ Database/               Reference PDFs
```

---

## Requirements
- Python 3.10+
- Windows 10/11 (Linux/macOS supported via `run_linux_mac.sh`)
- ~600 MB disk (dependencies)

Core libraries: PyQt6, OpenCV, ezdxf, Pillow, PyMuPDF, anthropic, google-generativeai, pytesseract.
