"""
Parses bore-log PDFs. Three strategies are tried in order, per page:

  1. Table extraction (pdfplumber) - works for PDFs exported straight
     from Excel/Word where the grid is still a real table.
  2. Free-text regex extraction - works for narrative-style bore logs
     ("0.00 - 1.50 m : Clayey Gravel", "SPT N = 22 @ 3.00 m", ...).
  3. OCR (PyMuPDF rasterisation + pytesseract) - used automatically
     when a page has no extractable text at all (i.e. it's a scanned
     image), then strategy 2's regexes are run on the OCR text.

Each page is treated as one borehole. If a report puts several
boreholes on one page, or splits one borehole across several pages,
adjust `boreholes_per_page` / merge manually afterwards - this covers
the common one-page-per-borehole layout.
"""
from __future__ import annotations
import re

from .model import BoreholeRecord, SoilLayer, TestRecord
from .table_common import parse_grid, find_header_columns, HEADER_KEYWORDS


# ---------------------------------------------------------------- helpers
def _looks_like_borelog_table(rows: list[list]) -> bool:
    """Heuristic: does this extracted table actually contain the
    keyword columns we know how to parse?"""
    if not rows:
        return False
    flat_text = ' '.join(str(c).lower() for row in rows[:10] for c in row if isinstance(c, str))
    return any(k in flat_text for k in ('r.l of layer', 'depth of spt', 'engineering description'))


# ------------------------------------------------------------ text fallback
DEPTH_RANGE_RE = re.compile(
    r'(\d{1,2}(?:\.\d{1,2})?)\s*(?:m)?\s*(?:-|to|–)\s*(\d{1,2}(?:\.\d{1,2})?)\s*m?\s*[:\-]?\s*(.+)')
SPT_RE = re.compile(
    r"(?:depth\s*[:=]?\s*)?(\d{1,2}(?:\.\d{1,2})?)\s*m.{0,40}?N\s*[-=]\s*(\d{1,3})", re.IGNORECASE)
RQD_RE = re.compile(
    r"(\d{1,2}(?:\.\d{1,2})?)\s*m.{0,60}?RQD\s*[:=]?\s*([\d.]+%|Nil)", re.IGNORECASE)
LOCATION_RE = re.compile(r"(?:Location\s*Name|Bore\s*Hole\s*No\.?|BH\s*No\.?)\s*[:\-]?\s*([A-Za-z0-9\-\/]+)",
                          re.IGNORECASE)
TERMINATED_RE = re.compile(r"[Tt]erminated\s+at\s+a?\s*depth\s+of\s+([\d.]+)\s*m", re.IGNORECASE)


def parse_freetext(name: str, text: str, warnings: list[str]) -> BoreholeRecord | None:
    if not text or not text.strip():
        return None

    loc_match = LOCATION_RE.search(text)
    location = loc_match.group(1).strip() if loc_match else name

    layers: list[SoilLayer] = []
    tests: list[TestRecord] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = DEPTH_RANGE_RE.match(line)
        if m:
            f, t, desc = float(m.group(1)), float(m.group(2)), m.group(3).strip()
            # sanity: skip false-positives where "desc" is itself just numbers
            if t > f and len(desc) > 2 and not desc.replace('.', '').isdigit():
                layers.append(SoilLayer(f, t, desc))
                continue
        spt = SPT_RE.search(line)
        if spt:
            tests.append(TestRecord(float(spt.group(1)), f"N={spt.group(2)}"))
            continue
        rqd = RQD_RE.search(line)
        if rqd:
            tests.append(TestRecord(float(rqd.group(1)), f"RQD: {rqd.group(2)}"))

    term_match = TERMINATED_RE.search(text)
    termination_note = term_match.group(0) if term_match else ''

    if not layers and not tests:
        warnings.append(f"[{name}] Free-text parser found no recognisable "
                         f"depth ranges or SPT/RQD values")
        return None

    return BoreholeRecord(location=location, layers=layers, tests=tests,
                           termination_note=termination_note, source_sheet=name)


# ------------------------------------------------------------------- OCR
def _ocr_page_text(pdf_path: str, page_index: int, dpi: int = 300) -> str:
    import fitz  # PyMuPDF
    import pytesseract
    from PIL import Image
    import io

    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img)


def _ocr_page_image(pdf_path: str, page_index: int, dpi: int = 300):
    import fitz
    from PIL import Image
    import io
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(dpi=dpi)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def _ocr_reconstruct_table(pdf_path: str, page_index: int, dpi: int = 300) -> list[list[str]] | None:
    """Bordered tables confuse Tesseract's default page-segmentation
    (it tends to mangle cell borders into garbage tokens), so plain
    image_to_string often loses tabular content entirely. This
    reconstructs a grid from word bounding boxes instead: cluster
    words into text lines by y-position, use the header line's word
    x-positions as column anchors, then bucket every other line's
    words into the nearest column. Works for simple ruled tables;
    skewed/rotated scans or multi-line cell text will degrade it -
    verify results in the GUI preview before trusting them."""
    import pytesseract
    from pytesseract import Output

    img = _ocr_page_image(pdf_path, page_index, dpi=dpi)
    data = pytesseract.image_to_data(img, output_type=Output.DICT)

    words = []
    n = len(data['text'])
    for i in range(n):
        txt = data['text'][i].strip()
        if not txt or int(data.get('conf', ['0'] * n)[i] if isinstance(data['conf'][i], str) else data['conf'][i]) < 0:
            pass
        if not txt:
            continue
        words.append(dict(text=txt, left=data['left'][i], top=data['top'][i],
                           width=data['width'][i], height=data['height'][i]))
    if not words:
        return None

    avg_h = sum(w['height'] for w in words) / len(words)
    row_tol = max(8, avg_h * 0.6)

    # cluster into rows by vertical centre
    words.sort(key=lambda w: w['top'])
    rows: list[list[dict]] = []
    for w in words:
        yc = w['top'] + w['height'] / 2
        placed = False
        for row in rows:
            row_yc = sum(r['top'] + r['height'] / 2 for r in row) / len(row)
            if abs(yc - row_yc) <= row_tol:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])
    rows.sort(key=lambda row: sum(r['top'] for r in row) / len(row))
    for row in rows:
        row.sort(key=lambda w: w['left'])

    # find the header row: the one containing the most of our known keywords
    header_idx, best_score = None, 0
    for idx, row in enumerate(rows):
        line = ' '.join(w['text'] for w in row).lower()
        score = sum(1 for kws in HEADER_KEYWORDS.values() for k in kws if k.split()[0] in line)
        if score > best_score:
            best_score, header_idx = score, idx
    if header_idx is None or best_score == 0:
        return None  # doesn't look like our known table layout

    # merge adjacent words in the header row into column labels, get anchor x
    header_words = rows[header_idx]
    col_anchors = []
    cur_text, cur_x, last_right = '', None, None
    GAP = 25
    for w in header_words:
        if last_right is not None and w['left'] - last_right > GAP:
            col_anchors.append((cur_x, cur_text.strip()))
            cur_text, cur_x = '', None
        if cur_x is None:
            cur_x = w['left']
        cur_text += ' ' + w['text']
        last_right = w['left'] + w['width']
    if cur_text.strip():
        col_anchors.append((cur_x, cur_text.strip()))

    grid = [[label for _, label in col_anchors]]
    for row in rows[header_idx + 1:]:
        cells = [''] * len(col_anchors)
        for w in row:
            wc = w['left'] + w['width'] / 2
            nearest = min(range(len(col_anchors)), key=lambda i: abs(col_anchors[i][0] - wc))
            cells[nearest] = (cells[nearest] + ' ' + w['text']).strip()
        if any(cells):
            grid.append(cells)
    return grid


# --------------------------------------------------------------- entrypoint
def parse_pdf(path: str, ocr_dpi: int = 300) -> tuple[list[BoreholeRecord], list[str]]:
    """Parse a bore-log PDF, one borehole per page.
    Returns (boreholes, warnings)."""
    import pdfplumber

    warnings: list[str] = []
    boreholes: list[BoreholeRecord] = []

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_name = f"page{i + 1}"
            bh = None

            # 1. try real tables first
            tables = page.extract_tables()
            for table in tables:
                if _looks_like_borelog_table(table):
                    bh = parse_grid(page_name, table, warnings)
                    if bh is not None:
                        break

            # table parsers only see the grid; if the location/project
            # metadata sits outside the table as plain paragraphs (common
            # in PDF exports), pull it from the full page text instead
            page_text_for_meta = page.extract_text() or ''
            if bh is not None and bh.location == page_name:
                loc_match = LOCATION_RE.search(page_text_for_meta)
                if loc_match:
                    bh.location = loc_match.group(1).strip()

            # 2. try page text (digital PDF, no clean table)
            if bh is None:
                text = page.extract_text() or ''
                if text.strip():
                    bh = parse_freetext(page_name, text, warnings)

            # 3. OCR fallback (scanned / image-only page)
            if bh is None:
                try:
                    ocr_grid = _ocr_reconstruct_table(path, i, dpi=ocr_dpi)
                except Exception as e:
                    warnings.append(f"[{page_name}] OCR table reconstruction failed: {e}")
                    ocr_grid = None
                if ocr_grid:
                    bh = parse_grid(page_name, ocr_grid, warnings)
                    if bh is not None:
                        warnings.append(f"[{page_name}] Parsed via OCR table reconstruction - "
                                         f"please double-check depths/values against the scan")
                        loc_match = LOCATION_RE.search(page_text_for_meta)
                        if loc_match and bh.location == page_name:
                            bh.location = loc_match.group(1).strip()

            if bh is None:
                try:
                    ocr_text = _ocr_page_text(path, i, dpi=ocr_dpi)
                except Exception as e:
                    warnings.append(f"[{page_name}] OCR failed: {e}")
                    ocr_text = ''
                if ocr_text.strip():
                    bh = parse_freetext(page_name, ocr_text, warnings)
                    if bh is not None:
                        warnings.append(f"[{page_name}] Parsed via OCR free-text - please "
                                         f"double-check depths/values against the scan")

            if bh is not None:
                boreholes.append(bh)
            else:
                warnings.append(f"[{page_name}] Could not extract any borehole data "
                                 f"(no table, no text, OCR empty)")

    return boreholes, warnings
