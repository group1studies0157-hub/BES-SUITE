"""
gui/gad_panel.py  —  Bridge Engineering Suite
═══════════════════════════════════════════════
GAD Checking — Verification (semantic hybrid) + Scrutiny (stub)

VERIFICATION ENGINE  (v2 — semantic, engineer-focused)
────────────────────────────────────────────────────────
A GAD drawing is divided into four semantic zones using title keywords:

  ELEVATION  — top-left  "HALF SECTION - HALF ELEVATION"
  PLAN       — left, mid-to-bottom  "HALF TOP PLAN - HALF BOTTOM PLAN"
  SECTION    — centre  "SECTION"
  NOTES      — right side  (text / specs / notes, no keyword needed)

Stage 1 — PDF Annotation extraction  (PyMuPDF, free, instant)
  Reads every annotation object: sticky notes, free-text boxes, highlights,
  strikethroughs, underlines, ink.  Each annotation's bounding box is mapped
  to a drawing zone via keyword proximity search in the text layer.
  Annotations with text give a "what to change" description directly.

Stage 2 — Text-layer semantic comparison  (free, no AI)
  For each annotation:
    • Extract the text block nearest to the annotation rect in the BASE file.
    • Extract the same spatial region from the CORRECTED file's text layer.
    • Compare: if the annotation text (the "correct value") now appears in
      the corrected file region AND the old value is gone → ATTENDED.
    • Strikethrough/highlight annotations → look for text removal.
    • Uses fuzzy matching (normalised edit-distance) so "1500" vs "1,500"
      and minor OCR noise still match.

Stage 3 — AI semantic fallback  (Claude/Gemini, only when needed)
  Triggered when:
    (a) Stage 1 finds zero structured annotations, OR
    (b) Mode is explicitly "AI only"
  The prompt is zone-aware: it tells the AI which zone each correction
  belongs to and asks it to verify the actual engineering values
  (dimensions, elevations, notes text) were updated — NOT pixel positions.
  AI keys come from QSettings (set in the main Settings panel).

ZONE DETECTION
──────────────
  fitz extracts the full text layer with word bounding-boxes.
  We search for the landmark strings case-insensitively:
    "HALF SECTION" or "HALF ELEVATION"  → ELEVATION zone
    "HALF TOP PLAN" or "HALF BOTTOM PLAN" → PLAN zone
    "SECTION"  (standalone heading)      → SECTION zone
  The remainder of the right half of the page → NOTES zone.
  Annotation bounding boxes are then classified by proximity to these
  zone anchor rectangles.
"""

from __future__ import annotations

import json, os, re
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QStackedWidget, QProgressBar,
    QFileDialog, QTextEdit, QButtonGroup, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui  import QFont, QDragEnterEvent, QDropEvent

from gui.styles import COLORS

ACCENT = COLORS["accent"]

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_keys() -> tuple[str, str]:
    """Load API keys from QSettings / env vars.  Returns (claude_key, gemini_key)."""
    s  = QSettings("BES", "BridgeEngineeringSuite")
    ck = s.value("anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    gk = s.value("gemini_api_key",    "") or os.environ.get("GEMINI_API_KEY",    "")
    return str(ck).strip(), str(gk).strip()


def _rgb_name(rgb) -> str:
    if not rgb:
        return "unknown"
    r, g, b = rgb
    if r < 0.3 and g < 0.3 and b > 0.5:  return "blue"
    if r > 0.5 and g < 0.3 and b < 0.3:  return "red"
    if r < 0.3 and g > 0.5 and b < 0.3:  return "green"
    if r > 0.5 and g < 0.3 and b > 0.5:  return "magenta"
    if r > 0.6 and g > 0.5 and b < 0.2:  return "yellow"
    if r > 0.5 and g > 0.3 and b < 0.2:  return "orange"
    if r < 0.2 and g < 0.2 and b < 0.2:  return "black"
    return f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"


_ANNOT_NAMES = {
    0:"Sticky note", 2:"Free text", 3:"Line", 4:"Rectangle",
    5:"Circle", 8:"Highlight", 9:"Underline", 11:"Strikethrough",
    15:"Ink/freehand",
}


def _edit_distance(a: str, b: str) -> int:
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return max(len(a), len(b))
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        ndp = [i + 1]
        for j, cb in enumerate(b):
            ndp.append(min(dp[j] + (0 if ca == cb else 1),
                           dp[j+1] + 1, ndp[-1] + 1))
        dp = ndp
    return dp[-1]


def _fuzzy_match(needle: str, haystack: str, threshold: float = 0.75) -> bool:
    """True if needle is present in haystack with ≥threshold similarity."""
    needle = needle.lower().strip()
    if not needle:
        return False
    if needle in haystack.lower():
        return True
    # sliding window
    n = len(needle)
    hay = haystack.lower()
    for i in range(len(hay) - n + 1):
        window = hay[i:i+n]
        sim = 1 - _edit_distance(needle, window) / max(len(needle), 1)
        if sim >= threshold:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Zone detection
# ─────────────────────────────────────────────────────────────────────────────

ZONE_KEYWORDS = {
    "ELEVATION": ["HALF SECTION - HALF ELEVATION", "HALF ELEVATION",
                  "SECTION - ELEVATION", "ELEVATION"],
    "PLAN":      ["HALF TOP PLAN - HALF BOTTOM PLAN", "HALF TOP PLAN",
                  "HALF BOTTOM PLAN", "TOP PLAN", "BOTTOM PLAN", "PLAN"],
    "SECTION":   ["CROSS SECTION", "HALF SECTION", "SECTION"],
}

def detect_zones(pdf_path: str, page_no: int = 0) -> dict:
    """
    Returns {zone_name: fitz.Rect} for zones found on the page.
    Also returns "NOTES" as the right-side remainder.
    page_no is 0-indexed.
    """
    import fitz
    doc  = fitz.open(pdf_path)
    page = doc[page_no]
    pw, ph = page.rect.width, page.rect.height

    # Extract all words with their bounding boxes
    words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,word_idx)

    # Build full text blocks grouped by Y proximity (line ~8pt tolerance)
    lines: dict[int, list] = {}
    for w in words:
        y_key = int(w[1] / 10) * 10
        lines.setdefault(y_key, []).append(w)

    # Search for keyword anchors
    zone_anchors = {}
    full_text_lower = page.get_text().lower()

    for zone, keywords in ZONE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in full_text_lower:
                # Find the bounding rect of this keyword in the word list
                kw_words = kw.lower().split()
                for i, w in enumerate(words):
                    if w[4].lower() == kw_words[0]:
                        # Try to match the full keyword phrase
                        match_words = [w]
                        ok = True
                        j = i + 1
                        for kw_part in kw_words[1:]:
                            if j < len(words) and words[j][4].lower() == kw_part:
                                match_words.append(words[j])
                                j += 1
                            else:
                                ok = False
                                break
                        if ok and match_words:
                            x0 = min(mw[0] for mw in match_words)
                            y0 = min(mw[1] for mw in match_words)
                            x1 = max(mw[2] for mw in match_words)
                            y1 = max(mw[3] for mw in match_words)
                            import fitz as _fitz
                            zone_anchors[zone] = _fitz.Rect(x0, y0, x1, y1)
                            break
                if zone in zone_anchors:
                    break

    # Build zone rects from anchor positions
    # ELEVATION: anchor found in upper portion → rect = left half, top portion
    # PLAN: anchor found in lower-left portion → rect = left half, bottom portion
    # SECTION: anchor found mid-page → rect = centre strip
    # NOTES: right side remainder

    import fitz as _fitz
    zone_rects = {}

    if "ELEVATION" in zone_anchors:
        a = zone_anchors["ELEVATION"]
        # Zone extends from anchor y downward to middle of page, left half
        zone_rects["ELEVATION"] = _fitz.Rect(0, a.y0 - 5, pw * 0.55, ph * 0.52)

    if "PLAN" in zone_anchors:
        a = zone_anchors["PLAN"]
        # Zone extends from anchor downward, left half
        zone_rects["PLAN"] = _fitz.Rect(0, a.y0 - 5, pw * 0.55, ph)

    if "SECTION" in zone_anchors:
        a = zone_anchors["SECTION"]
        # Zone is a centre strip
        zone_rects["SECTION"] = _fitz.Rect(pw * 0.25, a.y0 - 5, pw * 0.75, ph)

    # NOTES always = right side
    zone_rects["NOTES"] = _fitz.Rect(pw * 0.60, 0, pw, ph)

    # Fallback: if no keywords found, divide page into quadrants
    if len(zone_rects) == 1:  # only NOTES
        zone_rects["ELEVATION"] = _fitz.Rect(0,      0,      pw*0.5, ph*0.5)
        zone_rects["PLAN"]      = _fitz.Rect(0,      ph*0.5, pw*0.5, ph)
        zone_rects["SECTION"]   = _fitz.Rect(pw*0.5, 0,      pw*0.75, ph)

    doc.close()
    return zone_rects


def classify_zone(rect_list: list, zone_rects: dict) -> str:
    """Given an annotation rect [x0,y0,x1,y1], return the best matching zone name."""
    import fitz as _fitz
    if not rect_list or len(rect_list) < 4:
        return "UNKNOWN"
    ar = _fitz.Rect(rect_list[0], rect_list[1], rect_list[2], rect_list[3])
    best_zone, best_area = "UNKNOWN", 0
    for zone, zr in zone_rects.items():
        inter = ar & zr  # intersection
        if inter.is_empty:
            continue
        area = inter.width * inter.height
        if area > best_area:
            best_area = area
            best_zone = zone
    return best_zone


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Annotation extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_annotations(pdf_path: str) -> list[dict]:
    import fitz
    doc    = fitz.open(pdf_path)
    result = []
    idx    = 1
    for pg_no, page in enumerate(doc, start=1):
        zone_rects = detect_zones(pdf_path, pg_no - 1)
        for annot in page.annots():
            colors = annot.colors
            stroke = colors.get("stroke") or colors.get("fill")
            cname  = _rgb_name(stroke) if stroke else "unknown"
            if cname in ("black", "unknown"):
                txt = (annot.info.get("content","") or annot.info.get("title","")).strip()
                if not txt:
                    continue  # skip plain black marks with no text
            atype = _ANNOT_NAMES.get(annot.type[0], f"annot-{annot.type[0]}")
            r     = annot.rect
            rect  = [round(r.x0), round(r.y0), round(r.x1), round(r.y1)]
            txt   = (annot.info.get("content","") or
                     annot.info.get("title","") or
                     annot.info.get("subject","")).strip()
            zone  = classify_zone(rect, zone_rects)

            # Derive a human description
            if txt:
                if annot.type[0] == 11:  # strikethrough
                    desc = f'Strikethrough on "{txt}" — this value must be replaced'
                elif annot.type[0] == 8:  # highlight
                    desc = f'Highlighted text: "{txt}" — verify this value is updated'
                else:
                    desc = f'Annotation says: "{txt}"'
            else:
                desc = (f"{atype} mark in {cname} at "
                        f"x={rect[0]}–{rect[2]}, y={rect[1]}–{rect[3]}")

            result.append({
                "id":          f"C-{idx:03d}",
                "page":        pg_no,
                "zone":        zone,
                "annot_type":  atype,
                "color":       cname,
                "rect":        rect,
                "text":        txt,
                "description": desc,
                "source":      "annotation",
            })
            idx += 1
    doc.close()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Text-layer semantic comparison (no AI)
# ─────────────────────────────────────────────────────────────────────────────

def _get_text_in_rect(pdf_path: str, page_no: int, rect: list,
                       expand: int = 40) -> str:
    """Extract text from a bounding box region (expanded by `expand` pt) on a page."""
    import fitz
    doc  = fitz.open(pdf_path)
    page = doc[page_no - 1]
    r    = fitz.Rect(
        max(0, rect[0] - expand),
        max(0, rect[1] - expand),
        rect[2] + expand,
        rect[3] + expand,
    )
    text = page.get_text("text", clip=r).strip()
    doc.close()
    return text


def _get_zone_text(pdf_path: str, page_no: int, zone: str) -> str:
    """Get all text from a drawing zone on a page."""
    import fitz
    doc        = fitz.open(pdf_path)
    page       = doc[page_no - 1]
    zone_rects = detect_zones(pdf_path, page_no - 1)
    zr         = zone_rects.get(zone)
    if zr is None:
        doc.close()
        return page.get_text().strip()
    text = page.get_text("text", clip=zr).strip()
    doc.close()
    return text


def _normalise(s: str) -> str:
    """Normalise a value string for comparison: strip spaces, commas, units."""
    s = re.sub(r"[\s,]", "", s.lower())
    s = re.sub(r"(mm|m|cm|kg|kn|mpa|°|deg)$", "", s)
    return s


def _extract_numeric_values(text: str) -> set[str]:
    """Pull all numbers (incl. decimals) from a text block."""
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def semantic_compare(corrections: list[dict],
                      base_path: str,
                      corr_path: str,
                      log_fn=None) -> list[dict]:
    """
    For each correction:
    1. Get text of the annotation region + zone from BASE file
    2. Get text of the same zone from CORRECTED file
    3. Compare whether:
       a. Annotation text (new value) now appears in corrected zone
       b. Numeric values that were in base region are now absent (replaced)
       c. Strikethrough annotations: old text is gone from corrected file
    Returns corrections with status, remarks, zone_text_base, zone_text_corr added.
    """
    import fitz

    updated = []
    for c in corrections:
        pg   = c["page"]
        rect = c["rect"]
        zone = c["zone"]
        txt  = c.get("text", "").strip()
        atype = c.get("annot_type", "")

        # ── Text in the annotation's bounding region ──────────────────────
        base_region_text = _get_text_in_rect(base_path, pg, rect, expand=50)
        corr_region_text = _get_text_in_rect(corr_path, pg, rect, expand=50)

        # ── Text in the full zone ──────────────────────────────────────────
        base_zone_text = _get_zone_text(base_path, pg, zone)
        corr_zone_text = _get_zone_text(corr_path, pg, zone)

        status  = "unknown"
        remarks = ""

        # ── Case A: annotation has explicit text content ───────────────────
        if txt:
            norm_txt = _normalise(txt)

            # Strikethrough: old value should be ABSENT in corrected file
            if "strikethrough" in atype.lower():
                if not _fuzzy_match(txt, corr_region_text):
                    status  = "attended"
                    remarks = (f'Strikethrough value "{txt}" is no longer present '
                               f'in the corrected drawing at this location.')
                else:
                    status  = "missed"
                    remarks = (f'Strikethrough value "{txt}" still appears in the '
                               f'corrected drawing — the old value was not removed.')

            # Highlight / free-text: new value should APPEAR in corrected region
            elif annot_type_is_correction(atype):
                if _fuzzy_match(txt, corr_region_text):
                    status  = "attended"
                    remarks = (f'Correction value "{txt}" found in corrected '
                               f'drawing at the expected location.')
                elif _fuzzy_match(txt, corr_zone_text):
                    status  = "attended"
                    remarks = (f'Correction value "{txt}" found in the {zone} zone '
                               f'(slightly different position, may be acceptable).')
                else:
                    status  = "missed"
                    remarks = (f'Correction value "{txt}" was NOT found in the '
                               f'corrected drawing.  Expected in {zone} zone.')

            else:
                # Generic annotation with text — check if text now present
                if _fuzzy_match(txt, corr_region_text):
                    status  = "attended"
                    remarks = f'Text "{txt}" is present in corrected file at this location.'
                else:
                    status  = "missed"
                    remarks = f'Text "{txt}" not found at this location in corrected file.'

        # ── Case B: no text — compare numeric values in region ────────────
        else:
            base_nums = _extract_numeric_values(base_region_text)
            corr_nums = _extract_numeric_values(corr_region_text)
            added     = corr_nums - base_nums
            removed   = base_nums - corr_nums

            if added or removed:
                status  = "attended"
                remarks = (f"Numeric values changed in this region. "
                           f"Removed: {', '.join(sorted(removed)) or 'none'}. "
                           f"Added: {', '.join(sorted(added)) or 'none'}.")
            elif corr_region_text.strip() != base_region_text.strip():
                status  = "attended"
                remarks = "Text content at this location changed between files."
            else:
                status  = "unknown"
                remarks = (f"No text content in annotation and region text unchanged. "
                           f"Cannot verify without AI — consider switching to Hybrid or AI mode.")

        updated.append({
            **c,
            "status":          status,
            "remarks":         remarks,
            "base_region_txt": base_region_text[:200],
            "corr_region_txt": corr_region_text[:200],
            "comparison_method": "semantic_text",
        })

        if log_fn:
            icon = {"attended": "✅", "missed": "❌", "unknown": "❓"}.get(status, "·")
            log_fn(f"  {icon} {c['id']} [{zone}]  {c['annot_type']}  → {status}", 
                   {"attended": "ok", "missed": "err", "unknown": "warn"}.get(status, "info"))

    return updated


def annot_type_is_correction(atype: str) -> bool:
    """Return True if this annotation type typically carries a replacement value."""
    return any(k in atype.lower() for k in
               ("free text", "sticky", "note", "text", "ink", "freehand", "caret"))


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — AI semantic fallback
# ─────────────────────────────────────────────────────────────────────────────

def _pages_to_b64(path: str, max_pages: int = 8) -> list[str]:
    import fitz, base64 as _b64
    doc, out = fitz.open(path), []
    for i, pg in enumerate(doc):
        if i >= max_pages: break
        pix = pg.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        out.append(_b64.b64encode(pix.tobytes("jpeg")).decode())
    doc.close()
    return out


def _ai_full_verification(base_path: str, corr_path: str,
                           zone_rects: dict,
                           claude_key: str, gemini_key: str,
                           log_fn=None) -> list[dict]:
    """
    Full AI-based verification when no annotations are found.
    Sends both PDFs page-images with zone context and asks the AI to
    identify corrections AND verify them — focused on engineering values,
    not pixel positions.
    """
    if log_fn:
        log_fn("🤖 Sending both PDFs to AI for semantic analysis…", "info")

    base_pages = _pages_to_b64(base_path, 8)
    corr_pages = _pages_to_b64(corr_path, 8)

    zone_desc = "\n".join(
        f"  • {z}: {ZONE_KEYWORDS.get(z, [z])[0] if z in ZONE_KEYWORDS else 'right-side notes/specs'}"
        for z in ["ELEVATION", "PLAN", "SECTION", "NOTES"]
    )

    system_prompt = (
        "You are an expert bridge engineer reviewing GAD (General Arrangement Drawing) corrections. "
        "Your task is to compare a marked-up BASE drawing against a CORRECTED revision.\n\n"
        "The drawing is divided into four semantic zones:\n"
        f"{zone_desc}\n\n"
        "Focus on ENGINEERING VALUES: dimensions (mm, m), elevations (RL), section sizes, "
        "notes text, rebar details, clearances. Do NOT mention pixel positions.\n\n"
        "For each correction you identify:\n"
        "  1. Describe the old value and the new (corrected) value.\n"
        "  2. State which zone it belongs to.\n"
        "  3. Verify whether the corrected file has adopted the new value.\n\n"
        "Return ONLY valid JSON:\n"
        '[\n  {\n    "id": "C-001",\n    "zone": "ELEVATION",\n'
        '    "description": "Pier height changed from 4500mm to 4800mm",\n'
        '    "old_value": "4500",\n    "new_value": "4800",\n'
        '    "status": "attended",\n    "remarks": "4800mm now shown in elevation",\n'
        '    "source": "ai",\n    "comparison_method": "ai_vision"\n  }\n]'
    )

    # Build content: interleave base and corrected page images
    content = []
    content.append({"type": "text",
                     "text": "BASE FILE (with engineer markups):"})
    for b64 in base_pages[:4]:
        content.append({"type": "image",
                        "source": {"type": "base64",
                                   "media_type": "image/jpeg",
                                   "data": b64}})
    content.append({"type": "text",
                     "text": "CORRECTED FILE (revised drawing):"})
    for b64 in corr_pages[:4]:
        content.append({"type": "image",
                        "source": {"type": "base64",
                                   "media_type": "image/jpeg",
                                   "data": b64}})
    content.append({"type": "text",
                     "text": (
                         "Compare these drawings zone by zone. Find every correction "
                         "in the base file and verify whether it was carried out in "
                         "the corrected file. Return JSON only."
                     )})

    raw = ""

    # Try Gemini first
    if gemini_key:
        try:
            if log_fn: log_fn("  → Trying Gemini…", "info")
            from gui.ai_provider import AIProvider, PROVIDER_GEMINI
            ai = AIProvider(gemini_key, PROVIDER_GEMINI)
            raw = ai.vision(system=system_prompt,
                            image_b64=base_pages[0],
                            mime="image/jpeg",
                            user=content[-1]["text"],
                            max_tokens=4000)
        except Exception as e:
            if log_fn: log_fn(f"  Gemini failed: {e}", "warn")
            raw = ""

    # Try Claude
    if not raw and claude_key:
        try:
            if log_fn: log_fn("  → Trying Claude…", "info")
            import anthropic
            client = anthropic.Anthropic(api_key=claude_key)
            resp   = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=4000,
                system=system_prompt,
                messages=[{"role": "user", "content": content}]
            )
            raw = resp.content[0].text.strip()
        except Exception as e:
            if log_fn: log_fn(f"  Claude failed: {e}", "err")
            return []

    if not raw:
        return []

    raw = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()
    try:
        result = json.loads(raw)
        if log_fn:
            log_fn(f"🤖 AI identified {len(result)} corrections", "ok")
        return result
    except Exception:
        if log_fn: log_fn("⚠ AI response could not be parsed as JSON.", "warn")
        return []


def _ai_compare_annotations(corrections: list[dict],
                              base_path: str, corr_path: str,
                              claude_key: str, gemini_key: str,
                              log_fn=None) -> list[dict]:
    """
    Used when annotations WERE found but semantic text comparison returned
    'unknown' — ask AI to verify those specific corrections.
    """
    unknown = [c for c in corrections if c.get("status") == "unknown"]
    if not unknown:
        return corrections

    if log_fn:
        log_fn(f"🤖 Asking AI to resolve {len(unknown)} uncertain corrections…", "info")

    base_pages = _pages_to_b64(base_path, 6)
    corr_pages = _pages_to_b64(corr_path, 6)

    corr_json = json.dumps([
        {"id": c["id"], "zone": c["zone"],
         "description": c["description"],
         "text": c.get("text", ""),
         "annot_type": c.get("annot_type", "")}
        for c in unknown
    ], indent=2)

    system_prompt = (
        "You are a bridge engineer verifying GAD drawing corrections.\n"
        "The drawing zones are:\n"
        "  ELEVATION (top-left), PLAN (left mid-to-bottom), "
        "SECTION (centre), NOTES (right side).\n"
        "Focus on engineering values — dimensions, elevations, text notes.\n"
        "Do NOT refer to pixel positions."
    )

    content = [{"type": "text", "text": "BASE FILE pages:"}]
    for b64 in base_pages[:3]:
        content.append({"type": "image",
                        "source": {"type": "base64",
                                   "media_type": "image/jpeg",
                                   "data": b64}})
    content.append({"type": "text", "text": "CORRECTED FILE pages:"})
    for b64 in corr_pages[:3]:
        content.append({"type": "image",
                        "source": {"type": "base64",
                                   "media_type": "image/jpeg",
                                   "data": b64}})
    content.append({"type": "text", "text": (
        f"For each correction below, verify if it was attended in the corrected file.\n"
        f"CORRECTIONS:\n{corr_json}\n\n"
        f'Return JSON only: [{{"id":"C-001","status":"attended","remarks":"..."}}]'
    )})

    raw = ""
    if gemini_key:
        try:
            from gui.ai_provider import AIProvider, PROVIDER_GEMINI
            ai  = AIProvider(gemini_key, PROVIDER_GEMINI)
            raw = ai.vision(system=system_prompt,
                            image_b64=base_pages[0], mime="image/jpeg",
                            user=content[-1]["text"], max_tokens=3000)
        except Exception:
            raw = ""

    if not raw and claude_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=claude_key)
            resp   = client.messages.create(
                model="claude-opus-4-5", max_tokens=3000,
                system=system_prompt,
                messages=[{"role": "user", "content": content}]
            )
            raw = resp.content[0].text.strip()
        except Exception as e:
            if log_fn: log_fn(f"AI compare failed: {e}", "err")
            return corrections

    if not raw:
        return corrections

    raw = re.sub(r"```[a-z]*", "", raw).strip().strip("`")
    try:
        updates = {r["id"]: r for r in json.loads(raw)}
    except Exception:
        return corrections

    merged = []
    for c in corrections:
        if c["id"] in updates and c.get("status") == "unknown":
            u = updates[c["id"]]
            merged.append({**c,
                           "status":  u.get("status", c["status"]),
                           "remarks": u.get("remarks", c.get("remarks", "")),
                           "comparison_method": "semantic_text+ai_verify"})
        else:
            merged.append(c)
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Worker thread
# ─────────────────────────────────────────────────────────────────────────────

class VerificationWorker(QThread):
    progress = pyqtSignal(int, str)
    log      = pyqtSignal(str, str)      # message, level
    finished = pyqtSignal(bool, str, str)

    MODE_HYBRID = "hybrid"
    MODE_TEXT   = "text"
    MODE_AI     = "ai"

    def __init__(self, base_path, corr_path, mode=MODE_HYBRID):
        super().__init__()
        self.base_path = base_path
        self.corr_path = corr_path
        self.mode      = mode

    def _log(self, msg, level="info"):
        self.log.emit(msg, level)

    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            import traceback
            self.finished.emit(
                False,
                f"<p style='color:#F85149'><b>Error:</b> {e}</p>"
                f"<pre style='font-size:10px;color:#8B949E'>{traceback.format_exc()}</pre>",
                ""
            )

    def _run_inner(self):
        claude_key, gemini_key = _load_keys()
        corrections: list[dict] = []
        method = ""

        # ── Detect zones once (first page) ────────────────────────────────
        self.progress.emit(5, "Detecting drawing zones…")
        try:
            zone_rects = detect_zones(self.base_path, 0)
            found_zones = [z for z in zone_rects if z != "NOTES"]
            if found_zones:
                self._log(f"📐 Zones detected: {', '.join(found_zones)}", "ok")
            else:
                self._log("📐 No zone keywords found — using default quadrant layout.", "warn")
        except Exception as e:
            self._log(f"Zone detection error: {e}", "warn")
            zone_rects = {}

        # ── Stage 1: Annotation extraction ────────────────────────────────
        if self.mode in (self.MODE_HYBRID, self.MODE_TEXT):
            self.progress.emit(15, "Stage 1 — Reading PDF annotations…")
            self._log("🔎 Extracting annotations from base file…", "info")
            corrections = extract_annotations(self.base_path)

            if corrections:
                by_zone = {}
                for c in corrections:
                    by_zone.setdefault(c["zone"], []).append(c["id"])
                for zone, ids in by_zone.items():
                    self._log(f"  📎 {zone}: {len(ids)} annotation(s) — "
                              f"{', '.join(ids[:5])}", "ok")
                method = "annotation"
            else:
                self._log("ℹ No structured annotations found in base file.", "warn")

        # ── Stage 2: Semantic text comparison ────────────────────────────
        if corrections and self.mode in (self.MODE_HYBRID, self.MODE_TEXT):
            self.progress.emit(35, "Stage 2 — Semantic text comparison…")
            self._log("🔬 Comparing engineering values in text layer…", "info")
            corrections = semantic_compare(
                corrections, self.base_path, self.corr_path,
                log_fn=self._log
            )
            method = "annotation+semantic_text"

            n_unknown = sum(1 for c in corrections if c.get("status") == "unknown")
            if n_unknown:
                self._log(f"  ⚠ {n_unknown} correction(s) unresolved by text comparison.", "warn")

            # ── AI assist for unknowns (hybrid mode only) ────────────────
            if n_unknown and self.mode == self.MODE_HYBRID:
                if claude_key or gemini_key:
                    self.progress.emit(60, "Stage 3 — AI resolving uncertain cases…")
                    corrections = _ai_compare_annotations(
                        corrections, self.base_path, self.corr_path,
                        claude_key, gemini_key, log_fn=self._log
                    )
                    method = "annotation+semantic_text+ai_verify"
                else:
                    self._log("  💡 Add API keys in Settings to resolve uncertain cases with AI.", "warn")

        # ── Stage 3: Full AI fallback (no annotations found) ─────────────
        if not corrections:
            if self.mode == self.MODE_AI or (
                    self.mode == self.MODE_HYBRID and (claude_key or gemini_key)):
                self.progress.emit(50, "Stage 3 — Full AI semantic analysis…")
                corrections = _ai_full_verification(
                    self.base_path, self.corr_path,
                    zone_rects, claude_key, gemini_key,
                    log_fn=self._log
                )
                method = "ai_vision"
            elif self.mode == self.MODE_HYBRID and not (claude_key or gemini_key):
                self._log("  💡 No annotations found and no API keys configured.", "warn")
                self._log("  Add keys in Settings ➜ API Keys, or use AI mode.", "warn")

        # ── Build report ─────────────────────────────────────────────────
        self.progress.emit(90, "Building report…")
        report = self._build_report(corrections, method)
        html   = _build_html(report)
        self.progress.emit(100, "Complete.")

        n_att = len(report["attended"])
        n_mis = len(report["missed"])
        self._log(
            f"✅ Done — {report['total']} corrections  |  "
            f"{n_att} attended  {n_mis} missed  "
            f"[{method or 'no corrections found'}]",
            "ok"
        )
        self.finished.emit(True, html, json.dumps(report, indent=2))

    @staticmethod
    def _build_report(corrections, method):
        attended, missed, partial, unknown = [], [], [], []
        for c in corrections:
            st = c.get("status", "unknown").lower()
            if   st == "attended": attended.append(c)
            elif st == "partial":  partial.append(c)
            elif st == "missed":   missed.append(c)
            else:                  unknown.append(c)
        return {
            "total":    len(corrections),
            "attended": attended,
            "missed":   missed,
            "partial":  partial,
            "unknown":  unknown,
            "method":   method,
            "all_corrections": corrections,
        }


# ─────────────────────────────────────────────────────────────────────────────
# HTML report
# ─────────────────────────────────────────────────────────────────────────────

_ZONE_ICONS = {
    "ELEVATION": "📐",
    "PLAN":      "🗺",
    "SECTION":   "✂",
    "NOTES":     "📝",
    "UNKNOWN":   "❓",
}

_METHOD_LABELS = {
    "annotation":                        "📎 Annotation extraction",
    "annotation+semantic_text":          "📎 Annotations + 🔬 Semantic text diff",
    "annotation+semantic_text+ai_verify":"📎 Annotations + 🔬 Semantic diff + 🤖 AI assist",
    "ai_vision":                         "🤖 Full AI Vision (no annotations found)",
    "":                                  "—",
}


def _build_html(report: dict) -> str:
    total   = report["total"]
    attended= report["attended"]
    missed  = report["missed"]
    partial = report["partial"]
    unknown = report.get("unknown", [])
    method  = report.get("method", "")

    mlabel = _METHOD_LABELS.get(method, method)

    if total == 0:
        return (
            f"<div style='background:#0D2119;border:1px solid #3FB950;"
            f"border-radius:8px;padding:16px;'>"
            f"<b style='color:#3FB950;font-size:14px;'>✓ No corrections found</b><br>"
            f"<span style='color:#8B949E;font-size:12px;'>"
            f"No coloured annotations were found in the base file, and no changes "
            f"were detected.  Method: {mlabel}</span></div>"
        )

    n_att = len(attended); n_mis = len(missed)
    n_par = len(partial);  n_unk = len(unknown)
    pct   = int(n_att / total * 100) if total else 0

    # Stat boxes
    html = (
        f"<div style='margin-bottom:10px;'>"
        f"<span style='font-size:17px;font-weight:700;color:#E6EDF3;'>"
        f"Verification Report</span><br>"
        f"<span style='font-size:10px;color:#8B949E;'>Method: {mlabel}</span>"
        f"</div>"
        f"<div style='display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;'>"
        + "".join(
            f"<div style='background:{bg};border:1px solid {border};"
            f"border-radius:8px;padding:7px 14px;min-width:80px;text-align:center;'>"
            f"<div style='font-size:20px;font-weight:700;color:{border};'>{val}</div>"
            f"<div style='font-size:10px;color:#8B949E;'>{lbl}</div></div>"
            for bg, border, val, lbl in [
                ("#0D2119","#3FB950", n_att, "Attended"),
                ("#2A0E0E","#F85149", n_mis, "Missed"),
                ("#271D07","#D29922", n_par, "Partial"),
                ("#1A1525","#A371F7", n_unk, "Uncertain"),
                ("#003D30","#00C8A0", total, "Total"),
                ("#0D1F36","#58A6FF", f"{pct}%", "Compliance"),
            ]
        )
        + "</div>"
    )

    def _item(c: dict, bdr: str, icon: str, badge: str) -> str:
        cid    = c.get("id","")
        desc   = c.get("description","")
        rem    = c.get("remarks","")
        zone   = c.get("zone","")
        pg     = c.get("page","—")
        clr    = c.get("color","")
        txt    = c.get("text","")
        base_t = c.get("base_region_txt","")
        corr_t = c.get("corr_region_txt","")
        cm     = c.get("comparison_method","")
        zi     = _ZONE_ICONS.get(zone, "")

        val_rows = ""
        if txt:
            val_rows += (
                f"<div style='background:#0D1117;border-radius:4px;"
                f"padding:4px 8px;margin:4px 0;font-size:11px;'>"
                f"<span style='color:#8B949E;'>Correction value: </span>"
                f"<span style='color:#E6EDF3;font-family:monospace;'>{txt}</span>"
                f"</div>"
            )
        if base_t:
            val_rows += (
                f"<div style='font-size:10px;color:#8B949E;margin-top:2px;'>"
                f"<b>Base region:</b> "
                f"<code style='color:#7dd3fc;'>{base_t[:120]}</code></div>"
            )
        if corr_t:
            val_rows += (
                f"<div style='font-size:10px;color:#8B949E;'>"
                f"<b>Corrected region:</b> "
                f"<code style='color:#86efac;'>{corr_t[:120]}</code></div>"
            )

        return (
            f"<div style='background:#161B22;border:1px solid #21262D;"
            f"border-left:3px solid {bdr};border-radius:8px;"
            f"padding:10px 12px;margin-bottom:6px;'>"
            f"<div style='display:flex;justify-content:space-between;"
            f"align-items:center;margin-bottom:3px;'>"
            f"<span style='font-weight:700;color:{bdr};font-size:12px;'>"
            f"{icon} {cid}  "
            f"<span style='font-weight:400;color:#58A6FF;'>{zi} {zone}</span>"
            f"</span>"
            f"<span style='font-size:10px;background:{bdr}22;color:{bdr};"
            f"border-radius:4px;padding:1px 7px;font-weight:600;'>{badge}</span>"
            f"</div>"
            f"<div style='color:#E6EDF3;font-size:12px;margin-bottom:4px;'>{desc}</div>"
            f"{val_rows}"
            f"<div style='color:#8B949E;font-size:10px;margin-top:4px;'>"
            f"📄 p.{pg}  ·  🖊 {clr}  ·  {cm}</div>"
            + (f"<div style='color:#8B949E;font-size:11px;"
               f"font-style:italic;margin-top:4px;'>→ {rem}</div>" if rem else "")
            + "</div>"
        )

    if missed:
        html += ("<div style='font-weight:700;color:#F85149;"
                 "margin:12px 0 6px;font-size:13px;'>❌ Missed Corrections</div>")
        for c in missed:
            html += _item(c, "#F85149", "✗", "MISSED")

    if partial:
        html += ("<div style='font-weight:700;color:#D29922;"
                 "margin:12px 0 6px;font-size:13px;'>⚠ Partially Attended</div>")
        for c in partial:
            html += _item(c, "#D29922", "△", "PARTIAL")

    if unknown:
        html += ("<div style='font-weight:700;color:#A371F7;"
                 "margin:12px 0 6px;font-size:13px;'>❓ Uncertain (add API key to resolve)</div>")
        for c in unknown:
            html += _item(c, "#A371F7", "?", "UNCERTAIN")

    if attended:
        html += ("<div style='font-weight:700;color:#3FB950;"
                 "margin:12px 0 6px;font-size:13px;'>✅ Attended Corrections</div>")
        for c in attended:
            html += _item(c, "#3FB950", "✓", "ATTENDED")

    return html


# ─────────────────────────────────────────────────────────────────────────────
# Drop zone widget
# ─────────────────────────────────────────────────────────────────────────────

class DropZone(QFrame):
    file_dropped = pyqtSignal(str)

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._filepath = ""
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(95)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(3)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon = QLabel("📄")
        self._icon.setFont(QFont("Segoe UI", 18))
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._icon)

        self._lbl = QLabel(label)
        self._lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl)

        self._hint = QLabel("Drop PDF  or  click to browse")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet(f"color:{COLORS['text_muted']};font-size:10px;")
        lay.addWidget(self._hint)

        self._fname = QLabel("")
        self._fname.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fname.setStyleSheet(f"color:{ACCENT};font-size:10px;font-weight:600;")
        lay.addWidget(self._fname)

    def mousePressEvent(self, e):  self._browse()
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.setStyleSheet(f"border:2px dashed {ACCENT};border-radius:12px;"
                               f"background:{COLORS['accent_glow']};")
    def dragLeaveEvent(self, e):  self.setStyleSheet("")
    def dropEvent(self, e: QDropEvent):
        self.setStyleSheet("")
        urls = e.mimeData().urls()
        if urls:
            p = urls[0].toLocalFile()
            if p.lower().endswith(".pdf"): self._set(p)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF (*.pdf)")
        if p: self._set(p)

    def _set(self, path):
        self._filepath = path
        self._fname.setText(f"✓  {Path(path).name}")
        self._hint.setText("Click to change")
        self.file_dropped.emit(path)

    @property
    def filepath(self): return self._filepath

    def clear(self):
        self._filepath = ""
        self._fname.setText("")
        self._hint.setText("Drop PDF  or  click to browse")


# ─────────────────────────────────────────────────────────────────────────────
# Verification Panel UI
# ─────────────────────────────────────────────────────────────────────────────

class VerificationPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._worker    = None
        self._base_path = ""
        self._corr_path = ""
        self._report_json = ""
        self._build()

    def _build(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        cont = QWidget()
        lay  = QVBoxLayout(cont)
        lay.setContentsMargins(28, 22, 28, 28)
        lay.setSpacing(0)
        scroll.setWidget(cont)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # Header
        hdr = QLabel("Verification")
        hdr.setObjectName("panelTitle")
        lay.addWidget(hdr)
        sub = QLabel(
            "Compare a marked-up base drawing against the corrected revision. "
            "The engine reads annotations, identifies the drawing zone "
            "(Elevation / Plan / Section / Notes), then checks whether the "
            "corrected values were actually adopted."
        )
        sub.setObjectName("panelSubtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(14)

        # ── Zone legend card ────────────────────────────────────────────────
        legend = QFrame()
        legend.setObjectName("card")
        ll = QHBoxLayout(legend)
        ll.setContentsMargins(16, 10, 16, 10)
        ll.setSpacing(0)
        for icon, zone, kw in [
            ("📐", "ELEVATION", "HALF SECTION - HALF ELEVATION"),
            ("🗺", "PLAN",      "HALF TOP PLAN - HALF BOTTOM PLAN"),
            ("✂",  "SECTION",   "SECTION"),
            ("📝", "NOTES",     "Right-side text / specs"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(1)
            i = QLabel(f"{icon} {zone}")
            i.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            i.setStyleSheet(f"color:{COLORS['text_primary']};")
            k = QLabel(kw)
            k.setStyleSheet(f"color:{COLORS['text_muted']};font-size:9px;")
            col.addWidget(i); col.addWidget(k)
            ll.addLayout(col)
            if zone != "NOTES":
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setStyleSheet(f"color:{COLORS['border']};")
                sep.setFixedWidth(1)
                ll.addSpacing(12); ll.addWidget(sep); ll.addSpacing(12)
        lay.addWidget(legend)
        lay.addSpacing(12)

        # ── Mode selector ───────────────────────────────────────────────────
        mode_card = QFrame()
        mode_card.setObjectName("accentCard")
        ml = QVBoxLayout(mode_card)
        ml.setContentsMargins(18, 12, 18, 12)
        ml.setSpacing(6)
        mode_lbl = QLabel("ANALYSIS MODE")
        mode_lbl.setObjectName("fieldLabel")
        ml.addWidget(mode_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._mode_btns: dict[str, QPushButton] = {}
        self._mode_grp  = QButtonGroup(self)
        self._mode_grp.setExclusive(True)

        modes = [
            ("hybrid", "🔀 Hybrid",
             "Annotations → Semantic text diff → AI for unknowns (recommended)"),
            ("text",   "🔬 Text only",
             "Annotation extraction + semantic text comparison — no AI, free"),
            ("ai",     "🤖 AI only",
             "Full AI Vision — most thorough, requires API key in Settings"),
        ]
        for key, label, tip in modes:
            b = QPushButton(label)
            b.setCheckable(True); b.setToolTip(tip)
            b.setFixedHeight(30); b.setFont(QFont("Segoe UI", 9))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(self._ms(False))
            b.clicked.connect(lambda _, k=key: self._sel_mode(k))
            self._mode_btns[key] = b
            self._mode_grp.addButton(b)
            btn_row.addWidget(b)
        btn_row.addStretch()
        ml.addLayout(btn_row)

        self._mode_desc = QLabel("Annotations → Semantic text diff → AI for unknowns")
        self._mode_desc.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:10px;font-style:italic;")
        ml.addWidget(self._mode_desc)

        self._key_hint = QLabel("💡 API keys are configured in  ⚙ Settings → API Keys")
        self._key_hint.setStyleSheet(
            f"color:{COLORS['accent']};font-size:10px;")
        self._key_hint.setVisible(False)
        ml.addWidget(self._key_hint)

        self._mode_btns["hybrid"].setChecked(True)
        self._mode_btns["hybrid"].setStyleSheet(self._ms(True))
        self._cur_mode = "hybrid"
        lay.addWidget(mode_card)
        lay.addSpacing(12)

        # ── Upload card ─────────────────────────────────────────────────────
        up = QFrame(); up.setObjectName("card")
        ul = QVBoxLayout(up)
        ul.setContentsMargins(18, 14, 18, 14); ul.setSpacing(10)
        ul.addWidget(QLabel("Upload Files") if False else
                     self._bold_label("Upload Files", 12))

        dr = QHBoxLayout(); dr.setSpacing(10)

        bc = QVBoxLayout()
        bl = QLabel("BASE FILE  (marked up)"); bl.setObjectName("fieldLabel")
        bc.addWidget(bl)
        self._base_zone = DropZone("Base / Markup PDF")
        self._base_zone.file_dropped.connect(lambda p: setattr(self,"_base_path",p))
        bc.addWidget(self._base_zone)
        hint_b = QLabel("Engineer corrections in blue, red, green etc.")
        hint_b.setStyleSheet(f"color:{COLORS['text_muted']};font-size:10px;")
        bc.addWidget(hint_b)
        dr.addLayout(bc)

        arr = QLabel("→"); arr.setFont(QFont("Segoe UI",16))
        arr.setStyleSheet(f"color:{COLORS['text_muted']};")
        arr.setAlignment(Qt.AlignmentFlag.AlignCenter); arr.setFixedWidth(24)
        dr.addWidget(arr)

        cc = QVBoxLayout()
        cl2 = QLabel("CORRECTED FILE  (revised)"); cl2.setObjectName("fieldLabel")
        cc.addWidget(cl2)
        self._corr_zone = DropZone("Corrected PDF")
        self._corr_zone.file_dropped.connect(lambda p: setattr(self,"_corr_path",p))
        cc.addWidget(self._corr_zone)
        hint_c = QLabel("Revised drawing after incorporating corrections")
        hint_c.setStyleSheet(f"color:{COLORS['text_muted']};font-size:10px;")
        cc.addWidget(hint_c)
        dr.addLayout(cc)

        ul.addLayout(dr)

        rr = QHBoxLayout(); rr.addStretch()
        self._run_btn = QPushButton("▶  Run Verification")
        self._run_btn.setObjectName("primaryBtn")
        self._run_btn.setFixedHeight(38); self._run_btn.setFixedWidth(170)
        self._run_btn.clicked.connect(self._run)
        rr.addWidget(self._run_btn)
        ul.addLayout(rr)
        lay.addWidget(up)
        lay.addSpacing(12)

        # ── Log card ────────────────────────────────────────────────────────
        self._log_card = QFrame()
        self._log_card.setObjectName("card")
        self._log_card.setVisible(False)
        ll2 = QVBoxLayout(self._log_card)
        ll2.setContentsMargins(14, 10, 14, 10); ll2.setSpacing(5)

        lh = QHBoxLayout()
        lt = QLabel("Analysis Log"); lt.setFont(QFont("Segoe UI",10,QFont.Weight.Bold))
        lh.addWidget(lt); lh.addStretch()
        self._prog_pct = QLabel("0%")
        self._prog_pct.setStyleSheet(f"color:{ACCENT};font-weight:600;font-size:11px;")
        lh.addWidget(self._prog_pct)
        ll2.addLayout(lh)

        self._prog_bar = QProgressBar()
        self._prog_bar.setFixedHeight(5); self._prog_bar.setRange(0,100)
        ll2.addWidget(self._prog_bar)

        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True); self._log_box.setFixedHeight(105)
        self._log_box.setFont(QFont("Consolas", 9))
        self._log_box.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;"
            f"padding:5px;color:{COLORS['text_secondary']};}}")
        ll2.addWidget(self._log_box)
        lay.addWidget(self._log_card)
        lay.addSpacing(12)

        # ── Results card ────────────────────────────────────────────────────
        self._result_card = QFrame()
        self._result_card.setObjectName("card")
        self._result_card.setVisible(False)
        rl = QVBoxLayout(self._result_card)
        rl.setContentsMargins(18, 14, 18, 14); rl.setSpacing(8)

        rh = QHBoxLayout()
        rh.addWidget(self._bold_label("Results", 12))
        rh.addStretch()
        eb = QPushButton("Export JSON"); eb.setObjectName("secondaryBtn")
        eb.setFixedWidth(95); eb.clicked.connect(self._export)
        rh.addWidget(eb)
        cb = QPushButton("Clear"); cb.setObjectName("dangerBtn")
        cb.clicked.connect(self._clear); rh.addWidget(cb)
        rl.addLayout(rh)

        self._result_view = QTextEdit()
        self._result_view.setReadOnly(True); self._result_view.setMinimumHeight(360)
        self._result_view.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:8px;"
            f"padding:10px;font-size:12px;color:{COLORS['text_primary']};}}")
        rl.addWidget(self._result_view)
        lay.addWidget(self._result_card)
        lay.addStretch()

    @staticmethod
    def _bold_label(text, size=11):
        l = QLabel(text); l.setFont(QFont("Segoe UI", size, QFont.Weight.Bold))
        return l

    @staticmethod
    def _ms(active: bool) -> str:
        if active:
            return (f"QPushButton{{background:{ACCENT};color:#0D1117;"
                    f"border:none;border-radius:6px;font-weight:700;"
                    f"font-size:9px;padding:4px 10px;}}"
                    f"QPushButton:hover{{background:#00A080;}}")
        return (f"QPushButton{{background:{COLORS['input_bg']};"
                f"color:{COLORS['text_secondary']};"
                f"border:1px solid {COLORS['border_dark']};"
                f"border-radius:6px;font-size:9px;padding:4px 10px;}}"
                f"QPushButton:hover{{background:{COLORS['hover_bg']};"
                f"color:{COLORS['text_primary']};}}")

    def _sel_mode(self, key):
        self._cur_mode = key
        descs = {
            "hybrid": "Annotations → Semantic text diff → AI for unknowns",
            "text":   "Annotation extraction + semantic text comparison (no AI)",
            "ai":     "Full AI Vision — requires API key in Settings",
        }
        self._mode_desc.setText(descs.get(key,""))
        for k, b in self._mode_btns.items():
            b.setStyleSheet(self._ms(k == key))
        self._key_hint.setVisible(key in ("hybrid","ai"))

    def _run(self):
        if not self._base_path:
            self._base_zone.setStyleSheet(
                f"border:2px dashed {COLORS['error']};border-radius:12px;")
            return
        if not self._corr_path:
            self._corr_zone.setStyleSheet(
                f"border:2px dashed {COLORS['error']};border-radius:12px;")
            return

        # Validate AI mode has keys
        if self._cur_mode == "ai":
            ck, gk = _load_keys()
            if not ck and not gk:
                self._key_hint.setStyleSheet(f"color:{COLORS['error']};font-size:10px;font-weight:600;")
                self._key_hint.setText("⚠ No API keys found — go to ⚙ Settings → API Keys")
                self._key_hint.setVisible(True)
                return

        self._run_btn.setEnabled(False)
        self._log_card.setVisible(True)
        self._result_card.setVisible(False)
        self._log_box.clear()
        self._prog_bar.setValue(0)
        self._report_json = ""

        self._worker = VerificationWorker(
            self._base_path, self._corr_path, mode=self._cur_mode)
        self._worker.progress.connect(self._on_prog)
        self._worker.log.connect(self._on_log)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_prog(self, pct, msg):
        self._prog_bar.setValue(pct)
        self._prog_pct.setText(f"{pct}%")

    def _on_log(self, msg, level):
        C = {"info":"#7dd3fc","ok":"#4ade80","warn":"#fbbf24","err":"#f87171"}
        col = C.get(level, COLORS["text_secondary"])
        self._log_box.append(f'<span style="color:{col}">{msg}</span>')
        self._log_box.moveCursor(self._log_box.textCursor().MoveOperation.End)

    def _on_done(self, ok, html, raw_json):
        self._run_btn.setEnabled(True)
        self._report_json = raw_json
        self._result_card.setVisible(True)
        self._result_view.setHtml(html)

    def _export(self):
        if not self._report_json: return
        p, _ = QFileDialog.getSaveFileName(
            self, "Export", "verification_report.json", "JSON (*.json)")
        if p:
            with open(p,"w") as f: f.write(self._report_json)

    def _clear(self):
        self._result_card.setVisible(False)
        self._log_card.setVisible(False)
        self._log_box.clear(); self._report_json = ""
        self._base_zone.clear(); self._base_path = ""
        self._corr_zone.clear(); self._corr_path = ""
        self._prog_bar.setValue(0)


# ─────────────────────────────────────────────────────────────────────────────
# Scrutiny stub
# ─────────────────────────────────────────────────────────────────────────────

class ScrutinyPanel(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32,28,32,32)
        hdr = QLabel("Scrutiny"); hdr.setObjectName("panelTitle")
        lay.addWidget(hdr)
        sub = QLabel("Automated GAD drawing scrutiny against engineering standards.")
        sub.setObjectName("panelSubtitle"); sub.setWordWrap(True)
        lay.addWidget(sub); lay.addSpacing(28)
        card = QFrame(); card.setObjectName("accentCard")
        cl   = QVBoxLayout(card)
        cl.setContentsMargins(28,24,28,24); cl.setSpacing(10)
        for txt, sz, bold, muted in [
            ("🔬",30,False,False),
            ("Scrutiny module — coming soon",14,True,False),
            ("Custom engineering check rules will be applied\nto uploaded GAD drawings.",12,False,True),
        ]:
            l = QLabel(txt); l.setWordWrap(True)
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setFont(QFont("Segoe UI", sz,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            if muted: l.setStyleSheet(f"color:{COLORS['text_secondary']};")
            cl.addWidget(l)
        lay.addWidget(card); lay.addStretch()


# ─────────────────────────────────────────────────────────────────────────────
# GAD Panel container
# ─────────────────────────────────────────────────────────────────────────────

class GADPanel(QWidget):
    def __init__(self):
        super().__init__()
        ml = QVBoxLayout(self)
        ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)

        top = QWidget(); top.setObjectName("gadTopBar")
        top.setStyleSheet(
            f"QWidget#gadTopBar{{background:{COLORS['navy']};"
            f"border-bottom:1px solid {COLORS['navy_border']};}}")
        tl = QVBoxLayout(top)
        tl.setContentsMargins(32,16,32,0); tl.setSpacing(0)

        tr = QHBoxLayout()
        pt = QLabel("GAD Checking")
        pt.setFont(QFont("Segoe UI",16,QFont.Weight.Bold))
        pt.setStyleSheet(f"color:{COLORS['text_sidebar']};")
        tr.addWidget(pt); tr.addStretch()
        badge = QLabel("Semantic Engine")
        badge.setObjectName("tagInfo"); tr.addWidget(badge)
        tl.addLayout(tr); tl.addSpacing(2)

        ps = QLabel("Annotation extraction → Zone classification → Semantic value comparison → AI assist")
        ps.setStyleSheet(f"color:{COLORS['text_muted']};font-size:10px;")
        tl.addWidget(ps); tl.addSpacing(12)

        br = QHBoxLayout(); br.setSpacing(0)
        self._btn_v = self._tbtn("🔍  Verification", 0)
        self._btn_s = self._tbtn("🔬  Scrutiny", 1)
        self._btn_v.setChecked(True)
        self._btn_v.setStyleSheet(self._ts(True))
        br.addWidget(self._btn_v); br.addWidget(self._btn_s); br.addStretch()
        tl.addLayout(br)
        ml.addWidget(top)

        self._stack = QStackedWidget()
        self._vp = VerificationPanel()
        self._sp = ScrutinyPanel()
        self._stack.addWidget(self._vp)
        self._stack.addWidget(self._sp)
        ml.addWidget(self._stack)

    def _tbtn(self, text, idx):
        b = QPushButton(text); b.setCheckable(True)
        b.setFont(QFont("Segoe UI",10,QFont.Weight.Bold))
        b.setFixedHeight(38); b.setMinimumWidth(145)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(self._ts(False))
        b.clicked.connect(lambda _, i=idx: self._sw(i))
        return b

    @staticmethod
    def _ts(active):
        if active:
            return (f"QPushButton{{background:transparent;color:{ACCENT};"
                    f"border:none;border-bottom:3px solid {ACCENT};"
                    f"border-radius:0;padding:7px 16px;}}")
        return (f"QPushButton{{background:transparent;color:{COLORS['text_muted']};"
                f"border:none;border-bottom:3px solid transparent;"
                f"border-radius:0;padding:7px 16px;}}"
                f"QPushButton:hover{{color:{COLORS['text_sidebar']};"
                f"background:{COLORS['navy_light']};}}")

    def _sw(self, idx):
        self._stack.setCurrentIndex(idx)
        self._btn_v.setChecked(idx==0); self._btn_s.setChecked(idx==1)
        self._btn_v.setStyleSheet(self._ts(idx==0))
        self._btn_s.setStyleSheet(self._ts(idx==1))
