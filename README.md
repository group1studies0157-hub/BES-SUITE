# Bridge Engineering Suite v2.0

A local-first desktop application for CD Processing and AI-powered AutoCAD drawing generation.

---

## Quick Start (Windows)
```
Double-click run_windows.bat
```
It creates a virtual environment, installs all dependencies, and launches automatically.

---

## Features

### Button 1 — CD Processing
- Enter one or more Bridge Numbers (e.g. BRG-2024-001)
- Choose processing mode: Full CD / Drawings / Quantities / Specs
- Full pipeline with live progress and run history

### Button 2 — CAD Process (AI-Powered)
- Upload JPEG, JPG, PNG, TIFF, BMP or PDF
- Claude Vision AI analyses the entire drawing and identifies:
  - All structural lines, rectangles, circles, arcs, polygons
  - Every dimension value, unit, witness line and arrow
  - All text labels, notes, callouts via OCR
  - Hatching regions (earth fill, concrete, steel) — outlined, not noisy lines
  - Symbols: arrows, section marks, rebar indicators
  - Elevation/level markers (RL, FL, BL)
- Outputs a fully editable .DXF file with named layers:
  - GEOMETRY, DIMENSIONS, ANNOTATIONS, HATCHING, ELEVATIONS, SYMBOLS, BORDER, TITLEBLOCK

---

## API Key Setup

### Option 1 — In-app (recommended)
1. Launch the app
2. Go to CAD Process panel
3. Paste your Anthropic API key in the field and click Save Key

### Option 2 — Environment variable
```
set ANTHROPIC_API_KEY=sk-ant-api03-...
```

Get a key at: https://console.anthropic.com

### Without a key
The app still works using OpenCV structural detection (lines and rectangles only, no text/dimension recognition).

---

## Cost
| Component | Cost |
|-----------|------|
| PyQt6, OpenCV, ezdxf, PyMuPDF | Free |
| Claude Vision API per drawing | ~$0.001–$0.005 |
| 500 drawings/month | ~₹50–200/month |

---

## Output DXF Layers
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

---

## Requirements
- Python 3.10+
- Windows 10/11 (Linux/macOS via run_linux_mac.sh)
- ~600 MB disk (dependencies)
