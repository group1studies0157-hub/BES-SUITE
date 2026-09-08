"""
core/smart_extractor.py  —  Bridge Engineering Suite
═══════════════════════════════════════════════════════
Shared extraction engine used by every panel's Smart Extract button
(Hydraulic, GAD, CAD, CAD2, and any future panel).

This module owns ONLY the mechanics that were previously reimplemented
independently in multiple places:

    read_source(path)        text extraction from PDF/image — best-of merge
                              of gui/smart_extract.py's pdfplumber path and
                              gui/hydraulic_ocr.py's PyMuPDF-first + 3-strategy
                              OCR path (the more robust of the two).

    extract_fields(...)      generic regex field-matcher — same logic as
                              smart_extract.py's extract_fields_from_text(),
                              parameterized on a pattern map instead of a
                              hardcoded mode string, so every panel can reuse
                              the engine with its own field definitions.

    load_api_keys()          single source of truth for reading the Claude /
                              Gemini keys from QSettings + env var fallback.
                              Replaces gad_panel.py's local _load_keys() and
                              any other ad-hoc copy of the same four lines.

    extract_ai_text() /
    extract_ai_vision()       one call path into AIProvider.dual() (Gemini
                              first, Claude fallback) for every panel's AI
                              assist / fallback step — text or scanned image.

Panels keep everything that is genuinely panel-specific: field maps, regex
pattern sets, AI prompts, Excel cell-layout templates, dataclass schemas.
Only the plumbing lives here.
"""

from __future__ import annotations

import os
import re
import base64
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSettings


# ══════════════════════════════════════════════════════════════════════════
#  API KEYS — single source of truth
# ══════════════════════════════════════════════════════════════════════════

def load_api_keys() -> tuple[str, str]:
    """
    Returns (claude_key, gemini_key), read from QSettings (Settings panel)
    with a fallback to ANTHROPIC_API_KEY / GEMINI_API_KEY env vars.

    Every panel's AI-assist step should call this instead of reading
    QSettings directly, so key-loading behaviour never drifts between panels.
    """
    s = QSettings("BES", "BridgeEngineeringSuite")
    ck = s.value("anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    gk = s.value("gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
    return str(ck).strip(), str(gk).strip()


# ══════════════════════════════════════════════════════════════════════════
#  TEXT / OCR EXTRACTION  (best-of merge — see module docstring)
# ══════════════════════════════════════════════════════════════════════════

try:
    import fitz  # PyMuPDF — fastest PDF text extraction
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    from pdf2image import convert_from_path
    HAS_PDF2IMAGE = True
except ImportError:
    HAS_PDF2IMAGE = False

try:
    import pytesseract
    from PIL import Image, ImageChops, ImageFilter, ImageEnhance
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

TESSERACT_CONFIG = r"--oem 1 --psm 6"


def _preprocess_image(img):
    """
    Colored-text-safe preprocessing (from hydraulic_ocr.py).
    Engineering drawings often use red/blue annotation text that washes out
    under plain grayscale conversion. Using the pixel-wise min(G,B) channel
    makes red, blue, and black text all render dark while white background
    stays light — then upscale + sharpen for small CAD-drawing fonts.
    """
    img_rgb = img.convert("RGB")
    w, h = img_rgb.size
    if w < 1800:
        scale = max(2, 1800 // max(w, 1))
        img_rgb = img_rgb.resize((w * scale, h * scale), Image.LANCZOS)
    _, g, b = img_rgb.split()
    combined = ImageChops.darker(g, b)
    combined = ImageEnhance.Contrast(combined).enhance(3.0)
    combined = combined.filter(ImageFilter.SHARPEN)
    return combined


def extract_text_from_pdf(path: str) -> str:
    """PyMuPDF (fastest) -> pdfplumber -> OCR fallback for scanned PDFs."""
    text = ""

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

    if HAS_PDF2IMAGE and HAS_TESSERACT and not text.strip():
        try:
            images = convert_from_path(path, dpi=200, first_page=1, last_page=3)
            for img in images:
                text += pytesseract.image_to_string(
                    _preprocess_image(img), config=TESSERACT_CONFIG
                )
        except Exception:
            pass

    return text


def extract_text_from_image(path: str) -> str:
    """
    Multi-strategy OCR (from hydraulic_ocr.py): tries a plain upscaled color
    pass, the colored-text-safe preprocessing above, and a high-contrast
    grayscale sparse-text pass — returns whichever produced the most text,
    since a longer read is a reasonable proxy for the more successful
    strategy on a given scan quality.
    """
    if not HAS_TESSERACT:
        return ""
    results = []
    try:
        img = Image.open(path)

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

        try:
            t = pytesseract.image_to_string(_preprocess_image(img), config=TESSERACT_CONFIG)
            if t.strip():
                results.append(t)
        except Exception:
            pass

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

    return max(results, key=len) if results else ""


def read_source(path: str) -> str:
    """
    Main text-extraction entry point: detect file type by extension and
    return the best-effort extracted text.

    Excel is intentionally NOT handled here — cell-layout extraction is
    template-specific per panel (see smart_extract.extract_from_excel) and
    stays owned by whichever panel defines that template.
    """
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(path)
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"):
        return extract_text_from_image(path)
    return ""


def check_dependencies() -> dict:
    """Returns install status of each optional extraction dependency."""
    return {
        "PyMuPDF (fitz)": HAS_PYMUPDF,
        "pdfplumber": HAS_PDFPLUMBER,
        "pytesseract": HAS_TESSERACT,
        "pdf2image": HAS_PDF2IMAGE,
    }


def get_missing_deps() -> list[str]:
    """Human-readable install instructions for anything not available."""
    deps = check_dependencies()
    missing = []
    if not deps["PyMuPDF (fitz)"]:
        missing.append("PyMuPDF  ->  pip install pymupdf")
    if not deps["pdfplumber"]:
        missing.append("pdfplumber  ->  pip install pdfplumber")
    if not deps["pytesseract"]:
        missing.append("pytesseract  ->  pip install pytesseract  (also install Tesseract OCR)")
    if not deps["pdf2image"]:
        missing.append("pdf2image  ->  pip install pdf2image  (also install Poppler)")
    return missing


# ══════════════════════════════════════════════════════════════════════════
#  GENERIC REGEX FIELD-MATCHING ENGINE
# ══════════════════════════════════════════════════════════════════════════

PatternMap = list[tuple[str, list[str]]]


def extract_fields(text: str, pattern_map: PatternMap) -> dict:
    """
    Generic version of smart_extract.py's extract_fields_from_text().

    pattern_map: list of (field_name, [regex_patterns_in_priority_order]).
    Patterns for a field are tried in order; the first match wins.
    Each panel defines its own pattern_map (e.g. hydraulic's NewLine /
    Doubling patterns, a future CAD panel's dimension patterns) and passes
    it in — the matching logic itself is identical everywhere, so it lives
    here once instead of being copy-pasted per panel.
    """
    result = {}
    for field, patterns in pattern_map:
        for pat in patterns:
            try:
                m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            except re.error:
                continue
            if m and m.lastindex:
                val = m.group(1).strip()
                val = re.sub(r"\s+km2?$", "", val, flags=re.I).strip()
                val = re.sub(r"\s+m$", "", val, flags=re.I).strip()
                val = re.sub(r"\s+mm$", "", val, flags=re.I).strip()
                if val:
                    result[field] = val
                    break
    return result


# ══════════════════════════════════════════════════════════════════════════
#  AI-ASSISTED EXTRACTION — one call path for every panel's AI fallback
# ══════════════════════════════════════════════════════════════════════════

_MIME_MAP = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "bmp": "image/bmp",
    "tif": "image/tiff", "tiff": "image/tiff",
}


def extract_ai_text(system_prompt: str, user_prompt: str,
                     claude_key: str = "", gemini_key: str = "",
                     max_tokens: int = 2000) -> str:
    """
    Text-only AI extraction call. Gemini-first with automatic Claude
    fallback via AIProvider.dual() — the same dual-key logic used
    throughout the app, called from one place instead of being
    reconstructed per panel.
    """
    from gui.ai_provider import AIProvider
    provider = AIProvider.dual(gemini_key=gemini_key, claude_key=claude_key)
    return provider.chat(system_prompt, user_prompt, max_tokens=max_tokens)


def extract_ai_vision(system_prompt: str, image_path: str, user_prompt: str,
                       claude_key: str = "", gemini_key: str = "",
                       max_tokens: int = 2000) -> str:
    """
    Vision AI extraction call for scanned drawings — Gemini-first, Claude
    fallback. Reads the image from disk and base64-encodes it once here,
    so callers just pass a file path.
    """
    from gui.ai_provider import AIProvider

    ext = Path(image_path).suffix.lower().lstrip(".")
    mime = _MIME_MAP.get(ext, "image/png")

    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("ascii")

    provider = AIProvider.dual(gemini_key=gemini_key, claude_key=claude_key)
    return provider.vision(system_prompt, image_b64, mime, user_prompt, max_tokens=max_tokens)


def extract_ai_pdf(system_prompt: str, pdf_path: str, user_prompt: str,
                    claude_key: str = "", gemini_key: str = "",
                    max_tokens: int = 2000) -> str:
    """Vision-style AI extraction for a PDF passed directly (not pre-rasterized)."""
    from gui.ai_provider import AIProvider

    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode("ascii")

    provider = AIProvider.dual(gemini_key=gemini_key, claude_key=claude_key)
    return provider.vision_pdf(system_prompt, pdf_b64, user_prompt, max_tokens=max_tokens)


def extract_ai_fields(text: str, field_labels: dict, claude_key: str = "", gemini_key: str = "",
                       extra_context: str = "", max_tokens: int = 1500) -> dict:
    """
    Generic AI-assisted field extraction — the fallback for messy/scattered
    text that regex reliably fails on: CAD-exported PDFs linearize text in
    drawing-object order, not reading order, and phrasing varies drawing to
    drawing, so labels and values that sit next to each other visually can
    end up far apart (or reordered) in the extracted text stream. An AI
    model reasoning over the whole passage handles that variance; a fixed
    regex library tuned to one document's phrasing does not.

    field_labels : {field_key: human_label}, e.g. {"rl_prop": "Proposed Rail Level"}
                   — same shape as a panel's FIELD_MAP values' second element.
    extra_context: optional one-line hint about the document type/quirks.

    Returns {field_key: value_as_string} for fields the model was confident
    about; omits (rather than guesses) anything it couldn't support from text.
    """
    import json as _json

    schema_lines = "\n".join(f'  "{k}": null,' for k in field_labels)
    label_lines = "\n".join(f"  {k} = {v}" for k, v in field_labels.items())

    system_prompt = (
        "You are extracting structured engineering values from noisy text "
        "extracted from an Indian Railways bridge drawing or calculation "
        "report. The raw text may be out of reading order and inconsistently "
        "labeled. Extract ONLY values you are confident about from the given "
        "text; use null for anything not clearly present — never guess or "
        "infer a value that isn't supported by the text. "
        "Return ONLY a single valid JSON object, no other text, no markdown fences."
    )
    user_prompt = (
        f"{extra_context}\n\n"
        f"Field key meanings:\n{label_lines}\n\n"
        f"Raw extracted text:\n{text[:6000]}\n\n"
        f"Return JSON with exactly these keys:\n{{\n{schema_lines}\n}}"
    )

    raw = extract_ai_text(system_prompt, user_prompt,
                           claude_key=claude_key, gemini_key=gemini_key,
                           max_tokens=max_tokens)
    try:
        clean = re.sub(r'```json|```', '', raw).strip()
        data = _json.loads(clean)
        return {k: v for k, v in data.items() if v not in (None, "", "null")}
    except Exception:
        return {}
