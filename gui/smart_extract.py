"""
smart_extract.py  —  Bridge Engineering Suite
Rule-based field extractor for Hydraulic Calculations.
No AI / no API key required — works fully offline using regex + keyword matching.

Supports:
  • PDF  (via pdfplumber or pdftotext fallback)
  • Excel .xlsx / .xls  (via openpyxl / xlrd)
  • Image PNG/JPG/BMP/TIFF  (via pytesseract OCR — optional)
"""

import re
import os
import base64
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QDialog, QGridLayout, QLineEdit,
    QProgressBar, QSizePolicy, QFileDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from gui.styles import COLORS


NEWLINE_FIELD_MAP = {
    "section":          ("f_section",   "Section"),
    "bridge_no":        ("f_bridge",    "Bridge No."),
    "chainage":         ("f_chainage",  "Chainage"),
    "existing_opening": ("f_opening",   "Existing Opening"),
    "lat_lon":          ("f_latlon",    "Lat / Lon"),
    "catchment_area":   ("f_area",      "Catchment Area (km²)"),
    "stream_length":    ("f_length",    "Stream Length (km)"),
    "farthest_height":  ("f_hfarthest", "Farthest Point Height (m)"),
    "bed_level":        ("f_bedlevel",  "Bed Level (m)"),
    "ohfl":             ("f_ohfl",      "OHFL (m)"),
    "r50":              ("f_r50",       "R50 (mm)"),
    "formation_level":  ("f_fl",        "Formation Level (m)"),
    "velocity":         ("f_velocity",  "Velocity (m/s)"),
    "width":            ("f_width",     "Opening Width (m)"),
}

DOUBLING_FIELD_MAP = {
    "bridge_no":        ("f_bridge",      "Bridge No."),
    "section":          ("f_section",     "Section"),
    "chainage":         ("f_chainage",    "Chainage"),
    "between_stns":     ("f_between",     "Between Stations"),
    "exg_span_desc":    ("f_exg_desc",    "Existing Span Description"),
    "prop_span_desc":   ("f_prop_desc",   "Proposed Span Description"),
    "n_spans_exg":      ("f_n_spans_exg", "No. of Spans (Exg)"),
    "l_exg":            ("f_l_exg",       "Linear Waterway Exg (m)"),
    "rl_exg":           ("f_rl_exg",      "RL Existing (m)"),
    "fl_exg":           ("f_fl_exg",      "FL Existing (m)"),
    "bos_exg":          ("f_bos_exg",     "BOS Existing (m)"),
    "ohfl":             ("f_ohfl",        "OHFL (m)"),
    "bl":               ("f_bl",          "Bed Level (m)"),
    "n_spans_prop":     ("f_n_spans_prop","No. of Spans (Prop)"),
    "l_prop":           ("f_l_prop",      "Linear Waterway Prop (m)"),
    "rl_prop":          ("f_rl_prop",     "RL Proposed (m)"),
    "fl_prop":          ("f_fl_prop",     "FL Proposed (m)"),
    "bos_prop":         ("f_bos_prop",    "BOS Proposed (m)"),
    "us_ohfl":          ("f_us_ohfl",     "U/S Bridge OHFL (m)"),
}


# ══════════════════════════════════════════════════════════════════════════════
#  RULE-BASED EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

# Helper: extract the first number near a keyword
NUM  = r"[-+]?\d+\.?\d*"
_NUM = rf"({NUM})"

def _first_num(text: str) -> str:
    m = re.search(rf"({NUM})", text)
    return m.group(1) if m else ""

def _clean_num(s: str) -> str:
    """Strip units/trailing text from a numeric string."""
    m = re.search(r"([-+]?\d+\.?\d*)", str(s).replace(",", ""))
    return m.group(1) if m else ""

def _after_colon(line: str) -> str:
    """Return text after the last colon/equals on a line."""
    for sep in ("=", ":"):
        if sep in line:
            return line.split(sep)[-1].strip()
    return line.strip()


# ── Keyword patterns ───────────────────────────────────────────────────────────

_PATTERNS_NEWLINE = [
    # (field_key, list_of_regex_patterns)   patterns tried in order, first match wins

    ("section",         [
        r"Section[:\s]+([A-Z]{2,5}[-/][A-Z]{2,5}(?:[-/][A-Z]{2,5})?)",
        r"SECTION\s+([A-Z]{2,5}[-/][A-Z]{2,5})",
    ]),
    ("bridge_no",       [
        r"Bridge\s*No\.?\s*[:\s]+(\d+[A-Z]?(?:MB)?)",
        r"BR(?:IDGE)?\s*NO\.?\s*[:\s]+(\d+[A-Z]*)",
        r"BRIDGE NO\.\s+(\S+)",
    ]),
    ("chainage",        [
        r"Chainage[:\s]+([0-9]+\.?[0-9]*\s*m)",
        r"CHAINAGE\s+\(Rly Km\)\s+([0-9]+\.?[0-9]*\s*m)",
        r"Chainage:\s*([0-9]+\.?[0-9]*m?)",
    ]),
    ("existing_opening",[
        r"Existing Opening\s+(.+?)(?:\n|$)",
        r"EXISTING OPENING\s+(.+?)(?:\n|$)",
    ]),
    ("lat_lon",         [
        r"Latitude\s*/\s*Longitude\s+([\d°'\"\s NES]+/[\d°'\"\s EW]+)",
        r"(\d+\s*\d+'\d+\"\s*[NS]\s*/\s*\d+\s*\d+'\d+\"\s*[EW])",
    ]),
    ("catchment_area",  [
        r"Catchment Area\s*\(A\)\s*({NUM})\s*km".format(NUM=NUM),
        r"Catchment Area\s*[:\(]\s*A\s*[\):]?\s*({NUM})".format(NUM=NUM),
        r"A\s*=\s*({NUM})\s*km".format(NUM=NUM),
    ]),
    ("stream_length",   [
        r"Length of Longest Stream[^:]*\(L\)\s*({NUM})\s*km".format(NUM=NUM),
        r"L\s*=\s*({NUM})\s*km".format(NUM=NUM),
    ]),
    ("farthest_height", [
        r"Height of Farthest Point[^\n]*\s({NUM})\s*m\s*$".format(NUM=NUM),
        r"Farthest\s+Point[^:\n]*({NUM})".format(NUM=NUM),
    ]),
    ("bed_level",       [
        r"Bed Level[^\n]*\s({NUM})\s*m\s*$".format(NUM=NUM),
        r"BL\s*[/=]\s*Avg\.?BL\s*({NUM})".format(NUM=NUM),
        r"Site Average Bed Level[^:]*\(BL\)\s*({NUM})".format(NUM=NUM),
    ]),
    ("ohfl",            [
        r"O\.?H\.?F\.?L\.?[^\n]*\s({NUM})\s*m\s*$".format(NUM=NUM),
        r"OHFL\s*[:/=]?\s*({NUM})".format(NUM=NUM),
        r"Observed Highest Flood Level[^:]*\(O\.H\.F\.L\.\)\s*({NUM})".format(NUM=NUM),
    ]),
    ("r50",             [
        r"50\s*Year\s*-\s*24\s*Hour\s*Rainfall\s*\(R50\)[^\n]*\s({NUM})\s*mm\s*$".format(NUM=NUM),
        r"R50\s*[:/=]?\s*({NUM})\s*mm".format(NUM=NUM),
        r"24.hour\s+point\s+rainfall\s+({NUM})\s*mm".format(NUM=NUM),
    ]),
    ("formation_level", [
        r"Adopted Formation Level[^\n]*\s({NUM})\s*m\s*$".format(NUM=NUM),
        r"Formation Level[^\n]*\s({NUM})\s*m\s*$".format(NUM=NUM),
        r"FL\s*[:/=]\s*({NUM})".format(NUM=NUM),
    ]),
]

_PATTERNS_DOUBLING = [
    # ── Bridge identity ────────────────────────────────────────────────────
    ("bridge_no",      [
        r"Bridge\s*No\.?\s*[:\s]+(\S+)",
        r"BRIDGE\s+NO\.?\s+(\S+)",
        r"Br\.?\s*No\.?[:\s]+(\S+)",
        r"Waterway Calculations for Br\.No\.(\S+)",
    ]),
    ("section",        [
        r"Section[:\s]+([A-Z]{2,5}[-/][A-Z]{2,5}(?:[-/][A-Z]{2,5})?)",
        r"SECTION[:\s]+([A-Z]{2,5}[-/][A-Z]{2,5})",
        r"on\s+([A-Z]{2,5}[-/][A-Z]{2,5})\s+[Ss]ection",
    ]),
    ("chainage",       [
        r"[Cc]hainage[:\s]+([0-9]+\.?[0-9]*\s*m)",
        r"Km\.?\s*[:\s]*([0-9]+\.?[0-9]*)",
        r"at Chainage[:\s]+([0-9]+\.?[0-9]*m?)",
    ]),
    ("between_stns",   [
        r"Between\s+Stations?[:\s]+(.+?)(?:\n|$)",
        r"between\s+(.+?)\s+and\s+(.+?)(?:\n|$)",
    ]),
    ("exg_span_desc",  [
        r"Exg\.?\s*Span[:\s]+(.+?)(?:\n|$)",
        r"EXG\.?\s*MAIN\s+LINE[^\n]*\n[^\n]*\n[^\n]*\n.+?\d",
        r"Existing\s+(?:Bridge|Span)[:\s]*(.+?)(?:\n|$)",
        r"(\d+\s*[xX×]\s*[\d.]+\s*m\s*(?:ARCH|SLAB|BOX|PIPE|CULVERT))",
    ]),
    ("prop_span_desc", [
        r"Prop\.?\s*Size[:\s]+(.+?)(?:\n|$)",
        r"PRO\.?\s*LINE[^\n]*\n.*?(\d+[xX×\d\s.mM]+(?:RCC\s*BOX|SLAB|ARCH|BOX))",
        r"Proposed\s+(?:Span|Bridge)[:\s]+(.+?)(?:\n|$)",
        r"(\d+\s*[xX×]\s*[\d.]+\s*[xX×]\s*[\d.]+\s*m\s*RCC\s*BOX)",
    ]),

    # ── Existing levels ────────────────────────────────────────────────────
    # Format 1 (table):  "4. RAIL LEVEL(m)  -  371.302  371.324"
    # Format 2 (CAD):    "EXG. RAIL LEVEL: 371.302"
    # Format 3 (Excel):  handled separately in extract_from_excel()

    ("rl_exg",         [
        # CAD drawing annotation
        r"EXG\.?\s*RAIL\s+LEVEL\s*[:\-]\s*({NUM})".format(NUM=NUM),
        # Table: "RAIL LEVEL(m) - 371.302  371.324" → first number
        r"RAIL\s+LEVEL[^\n]*-\s*({NUM})\s+{NUM}".format(NUM=NUM),
        # Table without proposed column
        r"RAIL\s+LEVEL[^\n]*-\s*({NUM})".format(NUM=NUM),
        # Generic RL table row
        r"\bRL\s+({NUM})\s+{NUM}".format(NUM=NUM),
        r"Rail\s+Level[^\n]*\(RL\)[^\n]*({NUM})".format(NUM=NUM),
    ]),
    ("fl_exg",         [
        r"EXG\.?\s*FORMATION\s+LEVEL\s*[:\-]\s*({NUM})".format(NUM=NUM),
        r"FORMATION\s+LEVEL[^\n]*-\s*({NUM})\s+{NUM}".format(NUM=NUM),
        r"FORMATION\s+LEVEL[^\n]*-\s*({NUM})".format(NUM=NUM),
        r"\bFL\s+({NUM})\s+{NUM}".format(NUM=NUM),
        r"Formation\s+Level[^\n]*({NUM})\s+{NUM}".format(NUM=NUM),
    ]),
    ("bos_exg",        [
        r"EXG\.?\s*(?:BOTTOM\s+OF\s+SLAB|BOS)[^\n]*[:\-]\s*({NUM})".format(NUM=NUM),
        r"\bBOS\s+({NUM})\s+{NUM}".format(NUM=NUM),
        r"Bottom\s+of\s+Slab[^\n]*({NUM})\s+{NUM}".format(NUM=NUM),
        r"\bBOS[:\s]+({NUM})".format(NUM=NUM),
    ]),
    ("ohfl",           [
        r"OHFL/CHFL[^\n]*-\s*({NUM})".format(NUM=NUM),
        r"OHFL\s*/\s*CHFL[^\n]*({NUM})\s+{NUM}".format(NUM=NUM),
        r"OHFL[^/\n]*({NUM})\s*(?:\n|m|$)".format(NUM=NUM),
        r"O\.?H\.?F\.?L\.?[^\n]*[:\-]\s*({NUM})".format(NUM=NUM),
    ]),
    ("bl",             [
        r"BED\s+LEVEL[^\n]*[:\-]\s*({NUM})".format(NUM=NUM),
        r"\bBL[:\s]+({NUM})".format(NUM=NUM),          # CAD: "BL: 356.366"
        r"BL\s*/\s*Avg\.?BL[^\n]*({NUM})\s+{NUM}".format(NUM=NUM),
        r"Bed\s+Level[^\n]*({NUM})\s*m\s*$".format(NUM=NUM),
        r"\bBL\s+({NUM})\s+{NUM}".format(NUM=NUM),
    ]),
    ("l_exg",          [
        r"Total\s+L\.?W\.?/?[Ww]ay[^:\n]*({NUM})\s+{NUM}".format(NUM=NUM),
        r"Lineal\s+[Ww]aterway[^=:\n]*=\s*({NUM})\s*m".format(NUM=NUM),
        r"L/W\.?way\s*=\s*({NUM})".format(NUM=NUM),
        r"(?:Exg|Existing)\s+[Ll]ineal[^=:\n]*=\s*({NUM})".format(NUM=NUM),
    ]),

    # ── Proposed levels ────────────────────────────────────────────────────
    # Format 1 (table):  second number on same row  "RAIL LEVEL(m)  -  371.302  371.324"
    # Format 2 (CAD):    "PRO. RAIL LEVEL : 371.324"  /  "PRO.RAIL LEVEL : 371.324"

    ("rl_prop",        [
        r"PRO\.?\s*RAIL\s+LEVEL\s*[:\s]+({NUM})".format(NUM=NUM),
        r"RAIL\s+LEVEL[^\n]*-\s*{NUM}\s+({NUM})".format(NUM=NUM),
        r"\bRL\s+{NUM}\s+({NUM})".format(NUM=NUM),
        r"Rail\s+Level[^:\n]*{NUM}[^:\n]*({NUM})".format(NUM=NUM),
    ]),
    ("fl_prop",        [
        r"PRO\.?\s*FORMATION\s+LEVEL\s*[:\s]+({NUM})".format(NUM=NUM),
        r"FORMATION\s+LEVEL[^\n]*-\s*{NUM}\s+({NUM})".format(NUM=NUM),
        r"\bFL\s+{NUM}\s+({NUM})".format(NUM=NUM),
        r"Formation\s+Level[^:\n]*{NUM}[^:\n]*({NUM})".format(NUM=NUM),
    ]),
    ("bos_prop",       [
        r"PRO\.?\s*(?:BOTTOM\s+OF\s+SLAB|BOS)[^\n]*[:\s]+({NUM})".format(NUM=NUM),
        r"\bBOS\s+{NUM}\s+({NUM})".format(NUM=NUM),
        r"Bottom\s+of\s+Slab[^:\n]*{NUM}[^:\n]*({NUM})".format(NUM=NUM),
    ]),
    ("l_prop",         [
        r"Total\s+L\.?W\.?/?[Ww]ay[^:\n]*{NUM}\s+({NUM})".format(NUM=NUM),
        r"Proposed\s+Lineal\s+[Ww]aterway[^=:\n]*=\s*({NUM})".format(NUM=NUM),
        r"Proposed\s+Linear\s+[Ww]aterway[^=:\n]*=\s*({NUM})".format(NUM=NUM),
    ]),
    ("n_spans_exg",    [
        r"Total\s+No\.?\s*of\s+Spans?\s+(\d+)\s+\d+",
        r"No\.?\s*of\s+Spans?[:\s]+(\d+)",
    ]),
    ("n_spans_prop",   [
        r"Total\s+No\.?\s*of\s+Spans?\s+\d+\s+(\d+)",
        r"Prop(?:osed)?\s+[Ll]inear\s+[Ss]pans?[:\s]*(\d+)",
    ]),
    ("us_ohfl",        [
        r"[Uu]/[Ss][^:\n]*CHFL\s*=\s*({NUM})".format(NUM=NUM),
        r"[Uu]/[Ss][^:\n]*OHFL\s*=?\s*({NUM})".format(NUM=NUM),
        r"[Bb]ridge\s+on\s+U/S[^:\n]*=\s*({NUM})".format(NUM=NUM),
        r"Adopted.*[Uu]/[Ss][^:\n]*({NUM})".format(NUM=NUM),
    ]),
]


def extract_fields_from_text(text: str, mode: str) -> dict:
    """
    Apply regex patterns to plain text and return extracted field dict.
    mode: "1" = NewLine, "2" = Doubling
    """
    patterns = _PATTERNS_NEWLINE if mode == "1" else _PATTERNS_DOUBLING
    result = {}

    for field, pats in patterns:
        for pat in pats:
            try:
                m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
                if m:
                    val = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else ""
                    # Clean up trailing junk
                    val = re.sub(r"\s+km2?$", "", val, flags=re.I).strip()
                    val = re.sub(r"\s+m$", "", val, flags=re.I).strip()
                    val = re.sub(r"\s+mm$", "", val, flags=re.I).strip()
                    if val:
                        result[field] = val
                        break
            except re.error:
                continue

    return result


# ── Excel-specific extractor ───────────────────────────────────────────────────

def extract_from_excel(path: str, mode: str) -> dict:
    """
    For Excel, use the known cell layout from the standard SCR template.
    Falls back to text-based regex if layout doesn't match.
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        cells = {}
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None and str(cell.value).strip():
                    cells[cell.coordinate] = str(cell.value).strip()
    except Exception:
        try:
            import xlrd
            wb = xlrd.open_workbook(path)
            ws = wb.sheet_by_index(0)
            cells = {}
            for r in range(ws.nrows):
                for c in range(ws.ncols):
                    v = str(ws.cell_value(r, c)).strip()
                    if v:
                        # Approximate coordinate
                        coord = f"{chr(65+c)}{r+1}"
                        cells[coord] = v
        except Exception as e:
            return {"_error": str(e)}

    result = {}

    if mode == "2":
        # Known SCR Doubling template layout
        _cell = lambda *coords: next(
            (_clean_num(cells[c]) for c in coords if c in cells and _clean_num(cells.get(c,""))),
            cells.get(coords[0], "").strip() if coords[0] in cells else ""
        )
        _text = lambda *coords: next(
            (cells[c].strip() for c in coords if c in cells and cells[c].strip()),
            ""
        )

        result["bridge_no"]      = _text("D3")
        result["section"]        = _text("J4")
        result["chainage"]       = _text("J6")
        result["between_stns"]   = _text("J5")
        result["exg_span_desc"]  = _text("D4")
        result["prop_span_desc"] = _text("D6")

        # Table: col E = existing, col F = proposed
        result["n_spans_exg"]  = _clean_num(cells.get("E11",""))
        result["n_spans_prop"] = _clean_num(cells.get("F11",""))
        result["l_exg"]        = _clean_num(cells.get("E13",""))
        result["l_prop"]       = _clean_num(cells.get("F13",""))
        result["rl_exg"]       = _clean_num(cells.get("E14",""))
        result["rl_prop"]      = _clean_num(cells.get("F14",""))
        result["fl_exg"]       = _clean_num(cells.get("E15",""))
        result["fl_prop"]      = _clean_num(cells.get("F15",""))
        result["bos_exg"]      = _clean_num(cells.get("E16",""))
        result["bos_prop"]     = _clean_num(cells.get("F16",""))
        result["ohfl"]         = _clean_num(cells.get("E17",""))
        result["bl"]           = _clean_num(cells.get("E18",""))

        # U/S OHFL — cell U17 in the standard template
        us = _clean_num(cells.get("U17",""))
        if not us:
            # Try F47 (alternate location)
            us = _clean_num(cells.get("F47",""))
        result["us_ohfl"] = us

    else:
        # NewLine: build flat text from all cells and run regex
        flat = "\n".join(f"{k}: {v}" for k, v in sorted(cells.items()))
        result = extract_fields_from_text(flat, mode="1")

    # Remove empty strings
    return {k: v for k, v in result.items() if v}


# ── Text extraction from PDF ────────────────────────────────────────────────

def extract_text_from_pdf(path: str) -> str:
    """Extract text from PDF using pdfplumber (best) or pdftotext fallback."""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n".join(pages)
    except ImportError:
        pass
    try:
        import subprocess
        r = subprocess.run(
            ["pdftotext", "-layout", path, "-"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except Exception:
        pass
    try:
        import subprocess
        r = subprocess.run(
            ["python3", "-m", "pypdf2", path],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            return r.stdout
    except Exception:
        pass
    return ""


# ── Text extraction from image (OCR) ────────────────────────────────────────

def extract_text_from_image(path: str) -> str:
    """OCR using pytesseract. Returns empty string if not installed."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(path)
        return pytesseract.image_to_string(img, config="--psm 6")
    except ImportError:
        return ""
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
#  WORKER THREAD
# ══════════════════════════════════════════════════════════════════════════════


class ExtractWorker(QThread):
    finished = pyqtSignal(dict, str)   # fields, source_text_preview
    error    = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, file_path: str, mode: str):
        super().__init__()
        self.file_path = file_path
        self.mode      = mode

    def run(self):
        path = self.file_path
        ext  = os.path.splitext(path)[1].lower()
        try:
            if ext in ('.xlsx', '.xls'):
                self.progress.emit("Reading Excel file...")
                fields = extract_from_excel(path, self.mode)
                preview = f"Excel: {os.path.basename(path)}"

            elif ext == '.pdf':
                self.progress.emit("Extracting text from PDF...")
                text = extract_text_from_pdf(path)
                if not text.strip():
                    self.error.emit(
                        "Could not extract text from this PDF.\n"
                        "If it is a scanned image PDF, install pytesseract for OCR support."
                    )
                    return
                self.progress.emit("Matching fields...")
                fields = extract_fields_from_text(text, self.mode)
                preview = text[:200].replace("\n", " ")

            elif ext in ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp'):
                self.progress.emit("Running OCR on image...")
                text = extract_text_from_image(path)
                if not text.strip():
                    self.error.emit(
                        "Could not read text from this image.\n"
                        "Install pytesseract + Tesseract OCR for image support:\n"
                        "  pip install pytesseract\n"
                        "  https://github.com/tesseract-ocr/tesseract"
                    )
                    return
                self.progress.emit("Matching fields...")
                fields = extract_fields_from_text(text, self.mode)
                preview = text[:200].replace("\n", " ")

            else:
                self.error.emit(f"Unsupported file type: {ext}")
                return

            if "_error" in fields:
                self.error.emit(fields["_error"])
                return

            self.finished.emit(fields, preview)

        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n\n{traceback.format_exc()[-400:]}")


# ══════════════════════════════════════════════════════════════════════════════
#  REVIEW DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class ReviewDialog(QDialog):
    def __init__(self, extracted: dict, field_map: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Extracted Values")
        self.setModal(True)
        self.setMinimumWidth(640)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self._fields = {}
        self._build(extracted, field_map)

    def _build(self, extracted, field_map):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        hdr = QLabel("Review Extracted Values — Edit if Needed, Then Apply")
        hdr.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{COLORS['accent']};")
        lay.addWidget(hdr)

        found = sum(1 for k in field_map if extracted.get(k))
        total = len(field_map)
        sub = QLabel(
            f"✔  {found} of {total} fields extracted automatically.  "
            f"{'Blank fields were not found in the document — fill manually.' if found < total else 'All fields found.'}"
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:11px;")
        lay.addWidget(sub)

        # Field grid in scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(440)

        container = QWidget()
        grid = QGridLayout(container)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 3)

        for col, text in [(1, "Field"), (2, "Extracted Value  (editable)")]:
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color:{COLORS['text_muted']};")
            grid.addWidget(lbl, 0, col)

        for row, (key, (attr, label)) in enumerate(field_map.items(), start=1):
            val = extracted.get(key, "")

            # Row index
            num = QLabel(str(row))
            num.setStyleSheet(f"color:{COLORS['accent']}; font-weight:600; font-size:11px;")
            grid.addWidget(num, row, 0)

            # Label
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
            grid.addWidget(lbl, row, 1)

            # Editable value
            edit = QLineEdit(str(val) if val else "")
            edit.setFixedHeight(30)
            if val:
                edit.setStyleSheet(
                    f"border:1.5px solid {COLORS['accent']}; border-radius:4px; "
                    f"padding:2px 6px; font-weight:600;"
                )
            else:
                edit.setPlaceholderText("Not found — enter manually")
                edit.setStyleSheet(
                    f"border:1px dashed {COLORS['border']}; border-radius:4px; "
                    f"color:{COLORS['text_muted']}; padding:2px 6px;"
                )
            grid.addWidget(edit, row, 2)
            self._fields[key] = edit

        scroll.setWidget(container)
        lay.addWidget(scroll)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryBtn")
        cancel.setFixedHeight(36)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        apply = QPushButton("✔  Apply to Form")
        apply.setObjectName("primaryBtn")
        apply.setFixedHeight(36)
        apply.clicked.connect(self.accept)
        btn_row.addWidget(apply)
        lay.addLayout(btn_row)

    def get_values(self) -> dict:
        return {key: edit.text().strip() for key, edit in self._fields.items()}


# ══════════════════════════════════════════════════════════════════════════════
#  DROP ZONE WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class SmartExtractWidget(QWidget):
    """
    Drag-drop zone for rule-based field extraction.
    No AI — uses regex + Excel cell mapping.
    """

    SUPPORTED = {'.png','.jpg','.jpeg','.bmp','.tiff','.tif','.webp',
                 '.pdf','.xlsx','.xls'}

    def __init__(self, mode: str, parent_form, parent=None):
        super().__init__(parent)
        self._mode   = mode
        self._form   = parent_form
        self._worker = None
        self._field_map = DOUBLING_FIELD_MAP if mode == "2" else NEWLINE_FIELD_MAP
        self.setAcceptDrops(True)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        # Drop zone
        self._drop_frame = QFrame()
        self._drop_frame.setObjectName("dropZone")
        self._drop_frame.setMinimumHeight(95)
        self._drop_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._set_drop_style(active=False)

        dz = QVBoxLayout(self._drop_frame)
        dz.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dz.setSpacing(4)

        icon = QLabel("📂")
        icon.setFont(QFont("Segoe UI", 20))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("border:none; background:transparent;")
        dz.addWidget(icon)

        self._drop_lbl = QLabel(
            "Drag & drop a PDF / Excel / Image to auto-extract bridge data\n"
            "No internet required — works offline"
        )
        self._drop_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_lbl.setWordWrap(True)
        self._drop_lbl.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:12px; "
            f"border:none; background:transparent;")
        dz.addWidget(self._drop_lbl)

        types = QLabel("PDF  ·  Excel (.xlsx/.xls)  ·  Image (PNG/JPG/BMP/TIFF)")
        types.setAlignment(Qt.AlignmentFlag.AlignCenter)
        types.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:10px; "
            f"border:none; background:transparent;")
        dz.addWidget(types)

        lay.addWidget(self._drop_frame)

        # Bottom row
        bot = QHBoxLayout()
        bot.setSpacing(8)

        self._browse_btn = QPushButton("📁  Browse")
        self._browse_btn.setObjectName("secondaryBtn")
        self._browse_btn.setFixedHeight(30)
        self._browse_btn.setFixedWidth(100)
        self._browse_btn.clicked.connect(self._browse)
        bot.addWidget(self._browse_btn)

        self._prog = QProgressBar()
        self._prog.setRange(0, 0)
        self._prog.setFixedHeight(6)
        self._prog.setVisible(False)
        bot.addWidget(self._prog, 1)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:11px; font-style:italic;")
        bot.addWidget(self._status)
        lay.addLayout(bot)

    def _set_drop_style(self, active=False):
        border_color = COLORS['accent'] if active else COLORS['border']
        bg = COLORS.get('hover_bg', COLORS['navy_light']) if active \
             else COLORS.get('navy_light', '#1a2540')
        self._drop_frame.setStyleSheet(
            f"QFrame#dropZone {{"
            f"  border: 2px dashed {border_color};"
            f"  border-radius: 10px;"
            f"  background: {bg};"
            f"}}"
        )

    # ── Drag / drop ────────────────────────────────────────────────────────

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            path = e.mimeData().urls()[0].toLocalFile()
            if os.path.splitext(path)[1].lower() in self.SUPPORTED:
                e.acceptProposedAction()
                self._set_drop_style(True)
                self._drop_lbl.setText("Release to extract fields")
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self._set_drop_style(False)
        self._drop_lbl.setText(
            "Drag & drop a PDF / Excel / Image to auto-extract bridge data\n"
            "No internet required — works offline"
        )

    def dropEvent(self, e):
        self._set_drop_style(False)
        self._drop_lbl.setText(
            "Drag & drop a PDF / Excel / Image to auto-extract bridge data\n"
            "No internet required — works offline"
        )
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.splitext(path)[1].lower() in self.SUPPORTED:
                self._start(path)
            else:
                self._set_status(
                    f"Unsupported: {os.path.splitext(path)[1]}", error=True)

    # ── Browse ─────────────────────────────────────────────────────────────

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select File",
            "",
            "All Supported (*.pdf *.xlsx *.xls *.png *.jpg *.jpeg *.bmp *.tiff *.tif);;"
            "PDF (*.pdf);;"
            "Excel (*.xlsx *.xls);;"
            "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.tif)"
        )
        if path:
            self._start(path)

    # ── Extraction flow ────────────────────────────────────────────────────

    def _start(self, path: str):
        self._set_status(f"Reading {os.path.basename(path)}...")
        self._prog.setVisible(True)
        self._browse_btn.setEnabled(False)

        self._worker = ExtractWorker(path, self._mode)
        self._worker.progress.connect(self._set_status)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self, fields: dict, preview: str):
        self._prog.setVisible(False)
        self._browse_btn.setEnabled(True)

        if not fields:
            self._set_status(
                "No fields found. Check the document has searchable text.", error=True)
            return

        found = sum(1 for k in self._field_map if fields.get(k))
        self._set_status(f"Found {found}/{len(self._field_map)} fields — review below")

        dlg = ReviewDialog(fields, self._field_map, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            values = dlg.get_values()
            self._autofill(values)
            filled = sum(1 for v in values.values() if v)
            self._set_status(
                f"✔  {filled} fields applied — verify and click Calculate",
                ok=True
            )

    def _on_error(self, msg: str):
        self._prog.setVisible(False)
        self._browse_btn.setEnabled(True)
        self._set_status(f"Error: {msg[:80]}", error=True)

    def _autofill(self, values: dict):
        from PyQt6.QtWidgets import QLineEdit, QComboBox
        for key, (attr, _) in self._field_map.items():
            val = values.get(key, "")
            if not val:
                continue
            widget = getattr(self._form, attr, None)
            if widget is None:
                continue
            if isinstance(widget, QLineEdit):
                widget.setText(val)
                orig = widget.styleSheet()
                widget.setStyleSheet(
                    f"border:2px solid {COLORS['accent']}; border-radius:4px;")
                QTimer.singleShot(2500, lambda w=widget, s=orig: w.setStyleSheet(s))
            elif isinstance(widget, QComboBox):
                idx = widget.findText(val, Qt.MatchFlag.MatchContains)
                if idx >= 0:
                    widget.setCurrentIndex(idx)

    def _set_status(self, msg: str, error=False, ok=False):
        if error:   color = COLORS.get('error', '#FF6B6B')
        elif ok:    color = COLORS['accent']
        else:       color = COLORS['text_muted']
        self._status.setStyleSheet(f"color:{color}; font-size:11px;")
        self._status.setText(msg[:100])
