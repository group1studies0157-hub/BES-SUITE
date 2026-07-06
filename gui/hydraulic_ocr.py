"""
hydraulic_ocr.py — OCR/Text Extraction + Autofill Engine
No API keys. Fully embedded. Uses:
  - pdfplumber   : fast text extraction for digital PDFs
  - pdf2image    : PDF → image conversion for scanned PDFs
  - pytesseract  : OCR for images and scanned PDFs
  - Pillow       : image preprocessing for better OCR speed/accuracy

All field patterns are compiled once at module load for maximum speed.
"""

import re
import os
import sys
from pathlib import Path
from typing import Optional

# ── Try importing OCR libraries (graceful degradation) ─────────────────────
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import pytesseract
    from PIL import Image, ImageFilter, ImageEnhance
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    from pdf2image import convert_from_path
    HAS_PDF2IMAGE = True
except ImportError:
    HAS_PDF2IMAGE = False

try:
    import fitz  # PyMuPDF — fastest PDF text extraction
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


# ── Tesseract config for speed: fast mode, digits + letters ────────────────
TESSERACT_CONFIG = r"--oem 1 --psm 6"
TESSERACT_NUM_CONFIG = r"--oem 1 --psm 6 -c tessedit_char_whitelist=0123456789./-"


# ── Compiled regex patterns (compiled ONCE at import for speed) ────────────

def _c(pattern, flags=re.IGNORECASE):
    return re.compile(pattern, flags)

# ─── Shared / General patterns ─────────────────────────────────────────────
RE_BRIDGE_NO   = _c(r"Bridge\s*No[.:]?\s*([A-Z0-9/\-]+)")
RE_SECTION     = _c(r"Section[:\s]+([A-Z]{2,8}[\-/][A-Z]{2,8})")
RE_CHAINAGE    = _c(r"Chainage[:\s]+([\d,]+(?:\.\d+)?\s*m?)")
RE_LATLON      = _c(r"(\d{1,3}[°o]\s*\d{1,2}[''′]?\s*\d{0,2}[""″]?\s*[NS]\s*/\s*\d{1,3}[°o]\s*\d{1,2}[''′]?\s*\d{0,2}[""″]?\s*[EW])")
RE_LATLON2     = _c(r"Lat(?:itude)?[/\s]*Lon(?:gitude)?[:\s]+(.+?)(?:\n|$)")
RE_OHFL        = _c(r"O\.?H\.?F\.?L\.?[:\s]+([\d]+(?:\.[\d]+)?)")
RE_BED_LEVEL   = _c(r"Bed\s*Level[:\s/()]+([\d]+(?:\.[\d]+)?)")
RE_VELOCITY    = _c(r"Velocity[:\s]+([\d]+(?:\.[\d]+)?)")

# ─── New Line specific patterns ────────────────────────────────────────────
RE_CATCH_AREA  = _c(r"Catchment\s*Area[\s\(A\):\-]+([\d]+(?:\.[\d]+)?)\s*km")
RE_STREAM_LEN  = _c(r"(?:Length\s+of\s+Longest\s+Stream|Stream\s+Length|Length\s+.*?Stream)[:\s]+([\d]+(?:\.[\d]+)?)\s*km")
RE_FARTHEST    = _c(r"(?:Farthest\s+Point|Height.*?POI|H_f)[:\s]+([\d]+(?:\.[\d]+)?)\s*m")
RE_R50         = _c(r"(?:50[\s-]*Yr|R50|24[\s-]*Hr\s*Rainfall)[:\s]+([\d]+(?:\.[\d]+)?)\s*mm")
RE_FORM_LEVEL  = _c(r"(?:Formation\s*Level|Adopted\s*FL|FL)[:\s]+([\d]+(?:\.[\d]+)?)\s*m")
RE_WIDTH       = _c(r"(?:Opening\s*Width|Structural.*Width|Width)[:\s]+([\d]+(?:\.[\d]+)?)\s*m")
RE_SLAB_THICK  = _c(r"(?:Slab\s*Thickness|Clearance\s*Thickness)[:\s]+([\d]+(?:\.[\d]+)?)\s*m")
RE_EXIST_OPEN  = _c(r"Existing\s*Opening[:\s]+(.+?)(?:\n|$)")
RE_SUBZONE     = _c(r"Sub[\s-]*Zone[:\s]+([0-9][A-E]?)")
RE_SOIL_RED    = _c(r"Red\s*Soil|Clayey\s*Loam|Cultivated\s*Plains", re.I)
RE_SOIL_SANDY  = _c(r"Sandy\s*Soil|Sandy\s*Loam|Arid\s*Area", re.I)
RE_SOIL_ALLUVIAL = _c(r"Alluvial|Silty\s*Loam|Coastal", re.I)
RE_SOIL_COTTON = _c(r"Black\s*Cotton|Clayey\s*Soil", re.I)
RE_SOIL_HILLY  = _c(r"Hilly\s*Soil|Plateau\s*&?\s*Barren", re.I)

# ─── Doubling specific patterns ────────────────────────────────────────────
RE_BETWEEN_STN = _c(r"Between\s*(?:Stations?|Stns?)[:\s]+(.+?)(?:\n|$)")
RE_DIVISION    = _c(r"Division[:\s]+(SC|BZA|HYB|GTL|GNT|NED|MAS)")
RE_BRIDGE_CAT  = _c(r"(Minor\s*Bridge|Major\s*Bridge|Bridge|Culvert)")
RE_N_SPANS_EXG = _c(r"(?:No\.?\s*of\s*Spans?|Spans?)[:\s]*(?:Existing)[:\s]+([\d]+)")
RE_N_SPANS_EXG2= _c(r"(?:Existing)[:\s]*(?:Spans?|No\.?\s*of\s*Spans?)[:\s]+([\d]+)")
RE_N_SPANS_PRO = _c(r"(?:No\.?\s*of\s*Spans?|Spans?)[:\s]*(?:Proposed)[:\s]+([\d]+)")
RE_LWY_EXG     = _c(r"(?:Linear\s*Waterway|L(?:WY)?)[:\s]*(?:Existing)?[:\s]+([\d]+(?:\.[\d]+)?)\s*m")
RE_LWY_PROP    = _c(r"(?:Linear\s*Waterway|L(?:WY)?)[:\s]*(?:Proposed)[:\s]+([\d]+(?:\.[\d]+)?)\s*m")
RE_RL_EXG      = _c(r"(?:Rail\s*Level|RL)[:\s]*(?:Existing)?[:\s]+([\d]+(?:\.[\d]+)?)")
RE_RL_PROP     = _c(r"(?:Rail\s*Level|RL)[:\s]*Proposed[:\s]+([\d]+(?:\.[\d]+)?)")
RE_FL_EXG      = _c(r"(?:Formation\s*Level|FL)[:\s]*Existing[:\s]+([\d]+(?:\.[\d]+)?)")
RE_FL_PROP     = _c(r"(?:Formation\s*Level|FL)[:\s]*Proposed[:\s]+([\d]+(?:\.[\d]+)?)")
RE_BOS_EXG     = _c(r"(?:Bottom\s*of\s*Slab|BOS)[:\s]*(?:Existing)?[:\s]+([\d]+(?:\.[\d]+)?)")
RE_BOS_PROP    = _c(r"(?:Bottom\s*of\s*Slab|BOS)[:\s]*Proposed[:\s]+([\d]+(?:\.[\d]+)?)")
RE_US_OHFL     = _c(r"(?:U/S\s*Bridge|Upstream)[:\s]*O\.?H\.?F\.?L\.?[:\s]+([\d]+(?:\.[\d]+)?)")
RE_EXG_SPAN_DESC = _c(r"Existing\s*(?:Span\s*)?Description[:\s]+(.+?)(?:\n|$)")
RE_PROP_SPAN_DESC= _c(r"(?:Proposed\s*(?:Span\s*)?Description)[:\s]+(.+?)(?:\n|$)")

# ─── Span types ────────────────────────────────────────────────────────────
SPAN_TYPE_MAP = [
    (re.compile(r"RCC\s*Box", re.I),         "RCC Box"),
    (re.compile(r"Arch", re.I),              "Arch Bridge"),
    (re.compile(r"RCC\s*Slab", re.I),        "RCC Slab"),
    (re.compile(r"PSC\s*Girder", re.I),      "PSC Girder"),
    (re.compile(r"Steel\s*Girder", re.I),    "Steel Girder"),
    (re.compile(r"Plate\s*Girder", re.I),    "Plate Girder"),
    (re.compile(r"Pipe\s*Culvert", re.I),    "Pipe Culvert"),
    (re.compile(r"Open\s*Web", re.I),        "Open Web Girder"),
]

STRUCTURE_MAP = [
    (re.compile(r"RCC\s*BOX", re.I),         "RCC BOX"),
    (re.compile(r"ARCH", re.I),              "ARCH"),
    (re.compile(r"SLAB\s*CULVERT", re.I),    "SLAB CULVERT"),
    (re.compile(r"PIPE\s*CULVERT", re.I),    "PIPE CULVERT"),
    (re.compile(r"BRIDGE", re.I),            "BRIDGE"),
]

SUBZONE_LIST = ["3E", "1", "2", "3A", "3B", "3C", "3D", "4", "5", "6", "7"]


# ── Text extraction functions ───────────────────────────────────────────────

def extract_text_from_pdf(path: str) -> str:
    """Extract text from PDF. Tries PyMuPDF first (fastest), then pdfplumber,
    then OCR as last resort."""
    text = ""

    # Method 1: PyMuPDF (fastest for digital PDFs)
    if HAS_PYMUPDF:
        try:
            doc = fitz.open(path)
            for page in doc:
                text += page.get_text()
            doc.close()
            if text.strip():
                return text
        except Exception:
            pass

    # Method 2: pdfplumber
    if HAS_PDFPLUMBER and not text.strip():
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text += t + "\n"
            if text.strip():
                return text
        except Exception:
            pass

    # Method 3: OCR fallback for scanned PDFs
    if HAS_PDF2IMAGE and HAS_TESSERACT and not text.strip():
        try:
            images = convert_from_path(path, dpi=200, first_page=1, last_page=3)
            for img in images:
                img = _preprocess_image(img)
                text += pytesseract.image_to_string(img, config=TESSERACT_CONFIG)
        except Exception:
            pass

    return text


def extract_text_from_image(path: str) -> str:
    """Extract text from image. Tries 3 strategies, returns the longest result."""
    if not HAS_TESSERACT:
        return ""
    results = []
    try:
        img = Image.open(path)

        # Strategy 1: raw upscaled color image (works best for clear prints)
        try:
            img2 = img.convert("RGB")
            w, h = img2.size
            if w < 1800:
                img2 = img2.resize((w * 2, h * 2), Image.LANCZOS)
            t = pytesseract.image_to_string(img2, config=TESSERACT_CONFIG)
            if t.strip():
                results.append(t)
        except Exception:
            pass

        # Strategy 2: min(G,B) channel — fixes red/colored text
        try:
            processed = _preprocess_image(img)
            t = pytesseract.image_to_string(processed, config=TESSERACT_CONFIG)
            if t.strip():
                results.append(t)
        except Exception:
            pass

        # Strategy 3: grayscale 3x upscale, sparse text mode
        try:
            gray = img.convert("L")
            w, h = gray.size
            gray = gray.resize((w * 3, h * 3), Image.LANCZOS)
            gray = ImageEnhance.Contrast(gray).enhance(2.5)
            t = pytesseract.image_to_string(gray, config=r"--oem 1 --psm 11")
            if t.strip():
                results.append(t)
        except Exception:
            pass

    except Exception:
        pass
    # Return whichever strategy extracted the most text
    return max(results, key=len) if results else ""


def _preprocess_image(img) -> "Image":
    """
    Smart preprocessing for engineering drawings with colored text.
    Key insight: red text becomes washed out with standard grayscale.
    Fix: use min(G,B) channel so ALL colors (red/black/blue) appear dark.
      Red text   : G=0, B=0   -> min=0   -> dark  OK
      Black text : G=0, B=0   -> min=0   -> dark  OK
      White bg   : G=255,B=255 -> min=255 -> light OK
    """
    from PIL import ImageChops
    img_rgb = img.convert("RGB")
    w, h = img_rgb.size
    if w < 1800:
        scale = max(2, 1800 // max(w, 1))
        img_rgb = img_rgb.resize((w * scale, h * scale), Image.LANCZOS)
    _, g, b = img_rgb.split()
    combined = ImageChops.darker(g, b)   # pixel-wise min(G,B)
    combined = ImageEnhance.Contrast(combined).enhance(3.0)
    combined = combined.filter(ImageFilter.SHARPEN)
    return combined


def extract_text(file_path: str) -> str:
    """Main entry point: detect file type and extract text."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"):
        return extract_text_from_image(file_path)
    return ""


# ── Field extraction functions ──────────────────────────────────────────────

def _match(pattern, text) -> Optional[str]:
    """Return first group match stripped, or None."""
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _detect_span_type(text: str, span_options: list) -> Optional[str]:
    for pat, val in SPAN_TYPE_MAP:
        if pat.search(text) and val in span_options:
            return val
    return None


def _detect_structure_type(text: str) -> Optional[str]:
    for pat, val in STRUCTURE_MAP:
        if pat.search(text):
            return val
    return None


def _detect_soil(text: str) -> Optional[int]:
    """Return index 0-4 into SOIL_OPTIONS based on detected keywords."""
    return _get_soil_index(text)


def _detect_subzone(text: str) -> Optional[str]:
    m = RE_SUBZONE.search(text)
    if m:
        val = m.group(1).upper()
        if val in SUBZONE_LIST:
            return val
    return None


# ── Main autofill mappers ───────────────────────────────────────────────────

def autofill_newline(text: str) -> dict:
    """
    Extract all NewLine form field values from OCR/extracted text.
    Returns a dict with field_name -> value (None if not found).
    """
    fields = {}

    fields["section"]          = _match(RE_SECTION, text)
    fields["bridge_no"]        = _match(RE_BRIDGE_NO, text)
    fields["chainage"]         = _match(RE_CHAINAGE, text)
    fields["existing_opening"] = _match(RE_EXIST_OPEN, text)

    # Lat/Lon
    lat_lon = _match(RE_LATLON, text) or _match(RE_LATLON2, text)
    fields["lat_lon"] = lat_lon

    fields["catchment_area"]   = _match(RE_CATCH_AREA, text)
    fields["stream_length"]    = _match(RE_STREAM_LEN, text)
    fields["farthest_height"]  = _match(RE_FARTHEST, text)
    fields["bed_level"]        = _match(RE_BED_LEVEL, text)
    fields["ohfl"]             = _match(RE_OHFL, text)
    fields["r50"]              = _match(RE_R50, text)
    fields["formation_level"]  = _match(RE_FORM_LEVEL, text)
    fields["velocity"]         = _match(RE_VELOCITY, text)
    fields["width"]            = _match(RE_WIDTH, text)
    fields["slab_thickness"]   = _match(RE_SLAB_THICK, text)

    # Combo fields
    fields["sub_zone"]         = _detect_subzone(text)
    fields["structure_type"]   = _detect_structure_type(text)
    fields["soil_type"]        = None  # resolved by caller from SOIL_OPTIONS index
    fields["_soil_raw"]        = _get_soil_index(text)  # index into SOIL_OPTIONS

    return fields


def autofill_doubling(text: str) -> dict:
    """
    Extract all Doubling form field values from OCR/extracted text.
    Returns a dict with field_name -> value (None if not found).
    """
    fields = {}

    fields["bridge_no"]      = _match(RE_BRIDGE_NO, text)
    fields["section"]        = _match(RE_SECTION, text)
    fields["chainage"]       = _match(RE_CHAINAGE, text)
    fields["between_stns"]   = _match(RE_BETWEEN_STN, text)
    fields["division"]       = _match(RE_DIVISION, text)
    fields["bridge_cat"]     = _match(RE_BRIDGE_CAT, text)
    fields["exg_span_desc"]  = _match(RE_EXG_SPAN_DESC, text)
    fields["prop_span_desc"] = _match(RE_PROP_SPAN_DESC, text)

    # Spans
    n_exg = _match(RE_N_SPANS_EXG, text) or _match(RE_N_SPANS_EXG2, text)
    fields["n_spans_exg"]   = n_exg
    fields["n_spans_prop"]  = _match(RE_N_SPANS_PRO, text)

    # Existing bridge measurements
    fields["l_exg"]         = _match(RE_LWY_EXG, text)
    fields["rl_exg"]        = _match(RE_RL_EXG, text)
    fields["fl_exg"]        = _match(RE_FL_EXG, text)
    fields["bos_exg"]       = _match(RE_BOS_EXG, text)
    fields["ohfl"]          = _match(RE_OHFL, text)
    fields["bl"]            = _match(RE_BED_LEVEL, text)

    # Proposed bridge measurements
    fields["l_prop"]        = _match(RE_LWY_PROP, text)
    fields["rl_prop"]       = _match(RE_RL_PROP, text)
    fields["fl_prop"]       = _match(RE_FL_PROP, text)
    fields["bos_prop"]      = _match(RE_BOS_PROP, text)
    fields["us_ohfl"]       = _match(RE_US_OHFL, text)

    # Combo: span types
    fields["_span_type_exg_raw"] = _detect_span_type(text, ["RCC Box", "Arch Bridge", "RCC Slab",
                                    "PSC Girder", "Steel Girder", "Plate Girder",
                                    "Pipe Culvert", "Open Web Girder"])
    fields["_span_type_prop_raw"] = fields["_span_type_exg_raw"]  # often same doc

    return fields


def _get_soil_index(text: str) -> Optional[int]:
    """Returns 0-4 index into SOIL_OPTIONS, or None if not found."""
    if RE_SOIL_HILLY.search(text):    return 4
    if RE_SOIL_COTTON.search(text):   return 3
    if RE_SOIL_ALLUVIAL.search(text): return 2
    if RE_SOIL_SANDY.search(text):    return 1
    if RE_SOIL_RED.search(text):      return 0
    return None


# ── Dependency check ───────────────────────────────────────────────────────

def check_dependencies() -> dict:
    """Returns status of each required library."""
    return {
        "PyMuPDF (fitz)": HAS_PYMUPDF,
        "pdfplumber": HAS_PDFPLUMBER,
        "pytesseract": HAS_TESSERACT,
        "pdf2image": HAS_PDF2IMAGE,
    }


def get_missing_deps() -> list:
    deps = check_dependencies()
    missing = []
    if not deps["PyMuPDF (fitz)"]:
        missing.append("PyMuPDF  →  pip install pymupdf")
    if not deps["pdfplumber"]:
        missing.append("pdfplumber  →  pip install pdfplumber")
    if not deps["pytesseract"]:
        missing.append("pytesseract  →  pip install pytesseract  (also install Tesseract OCR)")
    if not deps["pdf2image"]:
        missing.append("pdf2image  →  pip install pdf2image  (also install Poppler)")
    return missing
