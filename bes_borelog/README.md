# BES Bore-Log \u2192 DXF

Converts bore-log reports (SPT/RQD stratigraphy sheets, "one borehole per
sheet/page" style, as used in South Central Railway / geotech consultant
reports) from **Excel (.xls/.xlsx)** or **PDF** into an AutoCAD **DXF**
"BORE HOLE DETAILS (NOT TO SCALE)" drawing — hatched soil/rock columns,
SPT-N / RQD annotations, depth ticks, termination markers and a legend,
laid out side by side exactly like the reference GAD bore-log sheets.

## Output styles

Two look-and-feel options, pick whichever fits what the sheet is for:

- **`schematic`** (default) — clean hatched columns, tick marks, one
  underlined label below each hole ("BORE HOLE AT A-01"). Matches the
  standard "BORE HOLE DETAILS (NOT TO SCALE)" GAD sheet look — this is
  what you want for the drawing itself.
- **`detailed`** — every layer depth, SPT/RQD note, density and sample
  type printed next to the column, plus a legend. Use this as a
  working/QC drawing when you need to see the full data, not just the
  profile shape.

GUI: pick from the "Output style" dropdown before clicking **Generate
DXF**. CLI: `--style schematic` (default) or `--style detailed`.

## Install

### Windows — easiest way

Just double-click **`Run_BoreLog_Tool.bat`**. The first time you run it,
it will:
1. Find your Python install (or tell you where to get one if it's missing)
2. Create a local `.venv` folder next to the tool
3. Install all required packages into it
4. Open the app

Every time after that, double-clicking it just opens the app straight away
(no reinstalling). It also checks whether Tesseract OCR is on your PATH
and gives you a heads-up (not a hard stop) if it isn't — Excel and normal
PDF conversion don't need it, only OCR of scanned PDFs does.

For quick batch conversion without opening the app, drag one or more
`.xls` / `.xlsx` / `.pdf` files onto **`Convert_DragDrop.bat`** — it
converts each one and drops the DXF next to the original file. Run
`Run_BoreLog_Tool.bat` at least once first so the `.venv` exists.

### Manual / any OS

```bash
pip install -r requirements.txt
```

PDF OCR (for scanned reports) also needs the Tesseract binary on your
system PATH:

```bash
# Windows: install from https://github.com/UB-Mannheim/tesseract/wiki
# Ubuntu/Debian:
sudo apt install tesseract-ocr
```

## Use it — desktop app (recommended)

```bash
python -m borelog_dxf.gui
```

1. **Open Excel / PDF Bore-Log Report...** and pick a file.
2. Every borehole found is listed on the left. Click one to review its
   soil layers and SPT/RQD test rows on the right — **edit any cell
   directly** (double-click). This matters most for OCR'd scans, which
   can misread digits — always check the *Parser warnings* box and the
   numbers before generating.
3. **Generate DXF...** and choose where to save.

## Use it — command line (batch / scripted)

```bash
# one file, auto-named output
python -m borelog_dxf.cli 533.xls

# explicit output path
python -m borelog_dxf.cli 533.xls -o 533_BoreHole_Details.dxf

# a whole folder of reports, one DXF each
python -m borelog_dxf.cli reports/*.xls --out-dir converted/

# merge every borehole from several files into one sheet
python -m borelog_dxf.cli A1.pdf P1.pdf P2.pdf --combine -o Bridge_533_All_BH.dxf

# scanned PDF, higher OCR resolution
python -m borelog_dxf.cli scanned_report.pdf --ocr-dpi 400
```

## Use it — from your own Python code

```python
from borelog_dxf.parser_xls import parse_workbook
from borelog_dxf.dxf_builder import BoreLogDxfBuilder

boreholes, warnings = parse_workbook("533.xls")
for w in warnings:
    print("WARN:", w)

BoreLogDxfBuilder(project_line="Br.No.533 - Obulavaripalle to Guntakal").save(
    boreholes, "533_BoreHole_Details.dxf"
)
```

Same idea for PDFs: `from borelog_dxf.parser_pdf import parse_pdf`.

## How it works / how to extend it

```
borelog_dxf/
  model.py           BoreholeRecord / SoilLayer / TestRecord - the shared
                      data model every parser produces and the DXF
                      builder consumes. Add a new input format by writing
                      a new parser that returns this model; nothing else
                      needs to change.
  soil_classify.py    Maps free-text soil/rock descriptions ("Clayey
                      Gravels", "Hard Rock", ...) to a hatch style. Add
                      new keyword rules here as new terminology shows up
                      in reports you feed it.
  table_common.py     Shared "grid of cells -> BoreholeRecord" parsing
                      logic. Column positions are auto-detected from
                      header-row keywords (HEADER_KEYWORDS), with a
                      fallback to the column layout of the reference
                      533.xls file if detection fails.
  parser_xls.py       Reads .xls (xlrd) / .xlsx (openpyxl) sheets into a
                      grid and hands off to table_common. One sheet = one
                      borehole.
  parser_pdf.py       Three-strategy PDF parser, tried per page in order:
                        1. pdfplumber table extraction -> table_common
                        2. digital-text regex fallback (narrative-style
                           logs, "0.00 - 1.50 m: Clayey Gravel")
                        3. OCR (PyMuPDF render + pytesseract), first
                           trying word-position table reconstruction,
                           then falling back to the same regex parser
                           on the raw OCR text.
                      One page = one borehole.
  dxf_builder.py      Pure drawing code - only depends on model.py, so it
                      is reused unchanged by every input format and by
                      the GUI/CLI.
  gui.py              PyQt6 desktop app (edit-then-export workflow).
  cli.py              Headless / batch command line interface.
```

### Known limitations

- **OCR is best-effort.** Numeric grid cells packed tightly against
  table borders are the hardest thing for Tesseract to read reliably;
  descriptive text (soil names, "Rock Core Recovery...", termination
  notes) OCRs much more reliably than the numbers. Always review OCR'd
  values in the GUI before trusting them — the parser flags every
  OCR-derived borehole with a warning for this reason.
- One borehole is assumed per Excel sheet / PDF page. If a report packs
  several boreholes onto one page, or splits one across pages, you'll
  need to split the source file first (or extend `parser_pdf.py` to
  detect multiple `Location Name:` blocks per page).
- The soil/rock keyword rules in `soil_classify.py` cover the
  terminology seen in the reference report (gravel/sand/silt/clay,
  disintegrated/soft/hard rock). Add rules for other terminology
  (murrum, laterite, etc.) as you encounter it — the hatch pattern
  library already includes many more AutoCAD patterns than are
  currently mapped (see `ezdxf.tools.pattern.IMPERIAL_PATTERN` for the
  full list).
