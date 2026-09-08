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

import json, os, re, time, base64, threading, html
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QStackedWidget, QProgressBar,
    QFileDialog, QTextEdit, QButtonGroup, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui  import QFont, QDragEnterEvent, QDropEvent

from gui.styles import COLORS, THEME_SWATCHES, current_theme

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
    if page_no < 0 or page_no >= len(doc):
        doc.close()
        return {}
    page = doc[page_no]
    if page is None:
        doc.close()
        return {}
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
    """Extract text from a bounding box region on a page."""
    import fitz
    doc  = fitz.open(pdf_path)
    idx  = page_no - 1
    if idx < 0 or idx >= len(doc):
        doc.close()
        return ""
    page = doc[idx]
    if page is None:
        doc.close()
        return ""
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
    doc  = fitz.open(pdf_path)
    idx  = page_no - 1
    if idx < 0 or idx >= len(doc):
        doc.close()
        return ""
    page = doc[idx]
    if page is None:
        doc.close()
        return ""
    zone_rects = detect_zones(pdf_path, idx)
    zr         = zone_rects.get(zone)
    if zr is None:
        text = page.get_text().strip()
    else:
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
            from gui.ai_provider import ANTHROPIC_MODEL, _anthropic_text
            client = anthropic.Anthropic(api_key=claude_key)
            resp   = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=4000,
                system=system_prompt,
                messages=[{"role": "user", "content": content}]
            )
            raw = _anthropic_text(resp).strip()
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
            from gui.ai_provider import ANTHROPIC_MODEL, _anthropic_text
            client = anthropic.Anthropic(api_key=claude_key)
            resp   = client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=3000,
                system=system_prompt,
                messages=[{"role": "user", "content": content}]
            )
            raw = _anthropic_text(resp).strip()
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
    "ELEVATION":  "📐",
    "PLAN":       "🗺",
    "SECTION":    "✂",
    "NOTES":      "📝",
    "BORE LOG":   "🔶",
    "UNKNOWN":    "❓",
}

_METHOD_LABELS = {
    "annotation":                        "📎 Annotation extraction",
    "annotation+semantic_text":          "📎 Annotations + 🔬 Semantic text diff",
    "annotation+semantic_text+ai_verify":"📎 Annotations + 🔬 Semantic diff + 🤖 AI assist",
    "ai_vision":                         "🤖 Full AI Vision (no annotations found)",
    "":                                  "—",
}


def _build_html(report: dict) -> str:
    total    = report["total"]
    attended = report["attended"]
    missed   = report["missed"]
    partial  = report["partial"]
    unknown  = report.get("unknown", [])
    method   = report.get("method", "")
    mlabel   = _METHOD_LABELS.get(method, method)

    # ── Empty state ───────────────────────────────────────────────────────────
    if total == 0:
        return (
            "<div style='background:#0D2119;border:1px solid #3FB950;"
            "border-radius:10px;padding:20px;font-family:Segoe UI,sans-serif;'>"
            "<b style='color:#3FB950;font-size:15px;'>✓ No corrections found</b><br>"
            f"<span style='color:#8B949E;font-size:12px;'>Method: {mlabel}</span>"
            "</div>"
        )

    n_att = len(attended); n_mis = len(missed)
    n_par = len(partial);  n_unk = len(unknown)
    pct   = int(n_att / total * 100) if total else 0

    # ── Status badge helper ───────────────────────────────────────────────────
    _STATUS = {
        "ATTENDED":  ("#0D2119", "#3FB950", "✓ ATTENDED"),
        "MISSED":    ("#2A0E0E", "#F85149", "✗ MISSED"),
        "PARTIAL":   ("#271D07", "#D29922", "△ PARTIAL"),
        "UNCERTAIN": ("#1A1525", "#A371F7", "? UNCERTAIN"),
    }

    def _badge(key):
        bg, clr, lbl = _STATUS[key]
        return (
            f"<span style='background:{bg};color:{clr};border:1px solid {clr};"
            f"border-radius:4px;padding:2px 10px;font-size:11px;"
            f"font-weight:700;letter-spacing:.4px;white-space:nowrap;'>{lbl}</span>"
        )

    def _snippet(txt, clr):
        if not txt: return ""
        s = str(txt).strip()[:160].replace("<","&lt;").replace(">","&gt;")
        return (
            f"<div style='background:#0D1117;border-radius:4px;"
            f"padding:3px 8px;margin-top:4px;font-size:10px;"
            f"font-family:Consolas,monospace;color:{clr};'>{s}</div>"
        )

    # ── Summary strip ─────────────────────────────────────────────────────────
    stat_boxes = "".join(
        f"<div style='background:{bg};border:1px solid {brd};"
        f"border-radius:8px;padding:8px 18px;text-align:center;"
        f"min-width:72px;flex:1;'>"
        f"<div style='font-size:22px;font-weight:800;color:{brd};'>{v}</div>"
        f"<div style='font-size:10px;color:#8B949E;letter-spacing:.5px;'>{l}</div>"
        f"</div>"
        for bg, brd, v, l in [
            ("#0D2119","#3FB950", n_att,   "ATTENDED"),
            ("#2A0E0E","#F85149", n_mis,   "MISSED"),
            ("#271D07","#D29922", n_par,   "PARTIAL"),
            ("#1A1525","#A371F7", n_unk,   "UNCERTAIN"),
            ("#001F3F","#58A6FF", total,   "TOTAL"),
            ("#003D30","#00C8A0", f"{pct}%","COMPLIANCE"),
        ]
    )

    # ── Progress bar ──────────────────────────────────────────────────────────
    bar_segs = ""
    for w, clr in [
        (n_att, "#3FB950"), (n_par, "#D29922"),
        (n_unk, "#A371F7"), (n_mis, "#F85149"),
    ]:
        if w:
            bar_segs += (
                f"<div style='flex:{w};background:{clr};"
                f"height:100%;min-width:2px;'></div>"
            )

    # ── Table rows ────────────────────────────────────────────────────────────
    # Build one row per correction. Sort: missed first, then partial,
    # uncertain, attended — engineer sees problems at the top.
    order = {"missed":0,"partial":1,"unknown":2,"attended":3}
    all_c = report.get("all_corrections", [])
    all_c_sorted = sorted(
        all_c,
        key=lambda c: order.get(c.get("status","unknown").lower(), 2)
    )

    rows = ""
    for i, c in enumerate(all_c_sorted):
        cid    = c.get("id", f"C-{i+1:03d}")
        desc   = (c.get("description","") or "").strip().replace("<","&lt;")
        zone   = c.get("zone", "")
        pg     = c.get("page", "—")
        clr_mk = c.get("color", "")
        txt    = (c.get("text","") or "").strip().replace("<","&lt;")
        base_t = c.get("base_region_txt","")
        corr_t = c.get("corr_region_txt","")
        rem    = (c.get("remarks","") or "").strip()
        st     = c.get("status","unknown").lower()
        zi     = _ZONE_ICONS.get(zone, "📌")

        badge_key = {
            "attended":"ATTENDED","missed":"MISSED",
            "partial":"PARTIAL"
        }.get(st, "UNCERTAIN")
        _, row_bdr, _ = _STATUS[badge_key]

        # Row stripe: alternate very subtly
        row_bg = "#161B22" if i % 2 == 0 else "#0D1117"

        # LEFT cell — observation
        obs_html = (
            f"<div style='font-size:12px;font-weight:700;color:#58A6FF;"
            f"margin-bottom:3px;'>{zi} {zone} &nbsp;"
            f"<span style='font-size:10px;font-weight:400;color:#8B949E;'>"
            f"p.{pg}</span></div>"
            f"<div style='font-size:13px;color:#E6EDF3;line-height:1.5;"
            f"margin-bottom:4px;'>{desc if desc else txt}</div>"
        )
        if txt and desc and txt.lower() != desc.lower():
            obs_html += (
                f"<div style='font-size:10px;color:#8B949E;margin-top:2px;'>"
                f"Annotation: <span style='color:#D29922;'>{txt[:120]}</span></div>"
            )
        if clr_mk:
            obs_html += (
                f"<div style='font-size:10px;color:#8B949E;margin-top:2px;'>"
                f"Ink colour: <span style='color:#A371F7;'>{clr_mk}</span></div>"
            )

        # RIGHT cell — verdict
        vrd_html = (
            f"<div style='margin-bottom:6px;'>{_badge(badge_key)}</div>"
        )
        if base_t:
            vrd_html += (
                "<div style='font-size:10px;color:#8B949E;"
                "margin-top:4px;'>📄 In marked-up file:</div>"
                + _snippet(base_t, "#7dd3fc")
            )
        if corr_t:
            vrd_html += (
                "<div style='font-size:10px;color:#8B949E;"
                "margin-top:6px;'>✅ In corrected file:</div>"
                + _snippet(corr_t, "#86efac")
            )
        if rem:
            vrd_html += (
                f"<div style='font-size:11px;color:#D29922;"
                f"margin-top:6px;font-style:italic;'>→ {rem}</div>"
            )
        if not base_t and not corr_t and not rem:
            vrd_html += (
                "<div style='font-size:11px;color:#8B949E;font-style:italic;'>"
                "No text evidence found in this region</div>"
            )

        rows += (
            f"<tr style='background:{row_bg};"
            f"border-bottom:1px solid #21262D;'>"
            # ID column
            f"<td style='padding:10px 8px;vertical-align:top;"
            f"font-size:11px;font-weight:700;color:{row_bdr};"
            f"white-space:nowrap;border-right:1px solid #21262D;'>"
            f"{cid}</td>"
            # Observation column
            f"<td style='padding:10px 12px;vertical-align:top;"
            f"border-right:1px solid #21262D;'>{obs_html}</td>"
            # Verdict column
            f"<td style='padding:10px 12px;vertical-align:top;"
            f"min-width:220px;'>{vrd_html}</td>"
            f"</tr>"
        )

    # ── Assemble final HTML ───────────────────────────────────────────────────
    html = f"""
<html><body style='margin:0;padding:0;
  font-family:Segoe UI,Arial,sans-serif;
  background:#0D1117;color:#E6EDF3;'>

<!-- Summary strip -->
<div style='display:flex;gap:6px;flex-wrap:wrap;
  padding:12px 14px 8px;border-bottom:1px solid #21262D;'>
{stat_boxes}
</div>

<!-- Progress bar -->
<div style='display:flex;height:5px;background:#21262D;margin:0 0 0 0;'>
{bar_segs}
</div>

<!-- Method label -->
<div style='padding:6px 14px 10px;font-size:10px;color:#8B949E;'>
  Method: {mlabel}
</div>

<!-- Main table -->
<table style='width:100%;border-collapse:collapse;font-size:13px;'>
  <thead>
    <tr style='background:#161B22;border-bottom:2px solid #30363D;'>
      <th style='padding:9px 8px;text-align:left;font-size:10px;
        color:#8B949E;letter-spacing:.8px;font-weight:600;
        width:60px;border-right:1px solid #21262D;'>NO.</th>
      <th style='padding:9px 12px;text-align:left;font-size:10px;
        color:#8B949E;letter-spacing:.8px;font-weight:600;
        border-right:1px solid #21262D;'>
        📋 OBSERVATION &nbsp;(from marked-up base file)</th>
      <th style='padding:9px 12px;text-align:left;font-size:10px;
        color:#8B949E;letter-spacing:.8px;font-weight:600;
        min-width:220px;'>
        🔍 VERIFICATION STATUS &nbsp;(in corrected file)</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>

<!-- Footer -->
<div style='padding:10px 14px;font-size:10px;color:#8B949E;
  border-top:1px solid #21262D;margin-top:4px;'>
  {n_att} attended &nbsp;·&nbsp; {n_mis} missed &nbsp;·&nbsp;
  {n_par} partial &nbsp;·&nbsp; {n_unk} uncertain &nbsp;·&nbsp;
  {total} total &nbsp;·&nbsp; {pct}% compliance
</div>

</body></html>
"""
    return html


# ─────────────────────────────────────────────────────────────────────────────
# Drop zone widget
# ─────────────────────────────────────────────────────────────────────────────

class DropZone(QFrame):
    file_dropped = pyqtSignal(str)

    def __init__(self, label: str, parent=None, compact: bool = False,
                 accept_exts: list[str] | None = None):
        super().__init__(parent)
        self._filepath = ""
        self._compact = compact
        # File types this drop zone accepts, e.g. [".pdf", ".png", ".jpg"].
        # Defaults to PDF-only to preserve existing behaviour.
        self._accept_exts = [e.lower() for e in (accept_exts or [".pdf"])]
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if compact:
            self.setFixedHeight(38)
            lay = QHBoxLayout(self)
            lay.setContentsMargins(12, 0, 12, 0)
            lay.setSpacing(8)
            self._icon = QLabel("📄"); self._icon.setFont(QFont("Segoe UI", 12))
            lay.addWidget(self._icon)
            self._lbl = QLabel(label)
            self._lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lay.addWidget(self._lbl)
            self._hint = QLabel("— click to browse")
            self._hint.setStyleSheet(f"color:{COLORS['text_muted']};font-size:9px;")
            lay.addWidget(self._hint)
            lay.addStretch()
            self._fname = QLabel("")
            self._fname.setStyleSheet(f"color:{ACCENT};font-size:9px;font-weight:600;")
            lay.addWidget(self._fname)
            return

        self.setMinimumHeight(95)
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
            if Path(p).suffix.lower() in self._accept_exts:
                self._set(p)

    def _browse(self):
        patterns = " ".join(f"*{e}" for e in self._accept_exts)
        p, _ = QFileDialog.getOpenFileName(
            self, "Select file", "", f"Supported files ({patterns})")
        if p: self._set(p)

    def _set(self, path):
        self._filepath = path
        self._fname.setText(f"✓  {Path(path).name}")
        self._hint.setText("click to change" if self._compact else "Click to change")
        self.file_dropped.emit(path)

    @property
    def filepath(self): return self._filepath

    def clear(self):
        self._filepath = ""
        self._fname.setText("")
        self._hint.setText("— click to browse" if self._compact else "Drop PDF  or  click to browse")


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
            ("text",   "🔬 Text Only  ✓ Offline",
             "100% offline — annotation extraction + semantic text comparison. No API key needed."),
            ("hybrid", "🔀 Hybrid",
             "Annotations + semantic diff → AI for uncertain cases (requires API key)"),
            ("ai",     "🤖 AI Vision",
             "Full AI Vision analysis — most thorough, requires API key in Settings"),
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

        self._mode_btns["text"].setChecked(True)
        self._mode_btns["text"].setStyleSheet(self._ms(True))
        self._cur_mode = "text"
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
# ─────────────────────────────────────────────────────────────────────────────
# Vertical Clearance calculator — IRS Bridge Rules / Substructure Code
# ─────────────────────────────────────────────────────────────────────────────

# (lower_cumec, upper_cumec, vc_low_mm, vc_high_mm, mode)
#   mode "flat"    → constant VC regardless of discharge within the band
#   mode "prorata" → linear interpolation between vc_low_mm and vc_high_mm
VC_TABLE = [
    (0,     30,   600,  600,  "flat"),
    (31,    300,  600,  1200, "prorata"),
    (301,   3000, 1500, 1500, "flat"),
    (3000,  None, 1800, 1800, "flat"),   # "Above 3000"
]


def compute_vc_mm(discharge_cumecs: float) -> tuple[int, str]:
    """
    Returns (vc_required_mm, explanation_string) for a given discharge.
    Pro-rata band (31-300 cumecs) is linearly interpolated between
    600mm (at 31 cumecs) and 1200mm (at 300 cumecs), per the
    standard IRS Bridge Rules / Substructure Code VC table.
    """
    d = discharge_cumecs

    if d < 0:
        return 0, "Discharge cannot be negative."

    if d <= 30:
        return 600, f"Discharge {d:g} cumecs is in 0–30 band → flat VC = 600 mm."

    if d <= 300:
        # Pro-rata interpolation between (31 → 600mm) and (300 → 1200mm)
        lo_d, hi_d   = 31, 300
        lo_vc, hi_vc = 600, 1200
        frac = (d - lo_d) / (hi_d - lo_d)
        vc   = lo_vc + frac * (hi_vc - lo_vc)
        vc_rounded = int(round(vc / 10.0) * 10)  # round to nearest 10mm
        return vc_rounded, (
            f"Discharge {d:g} cumecs is in 31–300 band (pro-rata).\n"
            f"VC = 600 + [({d:g} − 31) / (300 − 31)] × (1200 − 600)\n"
            f"VC = 600 + {frac:.4f} × 600 = {vc:.1f} mm  →  rounded to {vc_rounded} mm"
        )

    if d <= 3000:
        return 1500, f"Discharge {d:g} cumecs is in 301–3000 band → flat VC = 1500 mm."

    return 1800, f"Discharge {d:g} cumecs is above 3000 cumecs → flat VC = 1800 mm."


# ─────────────────────────────────────────────────────────────────────────────
# Gradient Checker — auto CH/RL/gradient extraction & verification
# ─────────────────────────────────────────────────────────────────────────────
#
# On a GAD "SITE PLAN" sheet, gradient data is drawn as small stacked/rotated
# text groups along the railway boundary lines, e.g.:
#
#     F1 IN 290   R1 IN 120
#     CH : 45420
#     RL:130.257
#
# EXG. (existing) work is drawn in BLACK, PRO. (proposed) work is drawn in RED
# — this is the standing layer convention used across all GAD sheets
# (see EXG WORK / PROP. DRAW colour 1 in the layer standard). The same
# convention is reused here: black chainage/RL/gradient text → EXG,
# red chainage/RL/gradient text → PRO.
#
# The bridge's own location is picked from the centre description line,
# e.g. "C/L OF BRIDGE NO. 47KK @ CH: 45462.393 m".

_CH_RE = re.compile(r'CH\s*[:\.]?\s*([\d][\d,]*\.?\d*)', re.IGNORECASE)
_RL_RE = re.compile(r'RL\s*[:\.]?\s*([\d][\d,]*\.?\d*)', re.IGNORECASE)
# Matches "R1 IN 120", "F1 IN 290", "R 1 IN 100" etc.
_GRAD_RE = re.compile(r'\b([RF])\s*[\d.]*\s*IN\s*([\d,]+\.?\d*)', re.IGNORECASE)
# Matches "C/L OF BRIDGE NO. 47KK @ CH: 45462.393" / "BRIDGE No. 505 AT CH. 284200.00m"
# (also "BR NO", "BRIDGE NO:") — NO./No./no, AT/@, CH:/CH. all tolerated, OCR-friendly.
_BRIDGE_CH_RE = re.compile(
    r'BRIDGE\s+NO\.?\s*([A-Z0-9/\-]+)[^C]{0,60}?CH\s*[:\.]?\s*([\d][\d,]*\.?\d*)',
    re.IGNORECASE | re.DOTALL)


def _classify_gradient_color(rgb) -> str:
    """EXG data is drawn black, PRO data is drawn red — the fixed GAD convention."""
    name = _rgb_name(rgb)
    if name == "red":
        return "PRO"
    if name in ("black", "unknown"):
        return "EXG"
    return "OTHER"


def _span_center(bbox):
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _dist(p1, p2):
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


def extract_gradient_data(pdf_path: str) -> dict:
    """
    Smart-recognises chainage (CH), reduced level (RL) and gradient labels
    ("R1 IN 120", "F1 IN 290" …) anywhere on the sheet, classifying each by
    ink colour into EXG (black) / PRO (red). Also locates every bridge's
    own chainage from its centre-line description text.

    Returns:
      {
        "bridges": [{"no": "47KK", "ch": 45462.393, "page": 1}, ...],
        "points":  {"EXG": [{"ch","rl","pos","page"}, ...], "PRO": [...]},
        "labels":  {"EXG": [{"dir","ratio","pos","page","raw"}, ...], "PRO": [...]},
      }
    """
    import fitz
    doc = fitz.open(pdf_path)

    points, labels, bridges = {"EXG": [], "PRO": []}, {"EXG": [], "PRO": []}, []

    for pg_no, page in enumerate(doc, start=1):
        raw = page.get_text("dict")
        spans = []
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for sp in line.get("spans", []):
                    txt = sp.get("text", "").strip()
                    if not txt:
                        continue
                    ci = sp.get("color", 0)
                    rgb = (((ci >> 16) & 255) / 255.0,
                           ((ci >> 8) & 255) / 255.0,
                           (ci & 255) / 255.0)
                    spans.append({"text": txt, "bbox": sp["bbox"], "rgb": rgb})

        # Bridge centre-line chainage (from full page text, colour-agnostic)
        full_text = page.get_text()
        for m in _BRIDGE_CH_RE.finditer(full_text):
            try:
                ch_val = float(m.group(2).replace(",", ""))
            except ValueError:
                continue
            bridges.append({"no": m.group(1).strip().rstrip(".:,"),
                             "ch": ch_val, "page": pg_no})

        ch_spans, rl_spans, grad_spans = [], [], []
        for sp in spans:
            txt, cat = sp["text"], _classify_gradient_color(sp["rgb"])
            if cat == "OTHER":
                continue
            if "BRIDGE" in txt.upper():
                continue  # avoid re-capturing the bridge description as a CH point
            m_ch, m_rl, m_gr = _CH_RE.search(txt), _RL_RE.search(txt), _GRAD_RE.search(txt)
            if m_ch:
                try:
                    ch_spans.append({"val": float(m_ch.group(1).replace(",", "")),
                                      "pos": _span_center(sp["bbox"]), "cat": cat})
                except ValueError:
                    pass
            if m_rl:
                try:
                    rl_spans.append({"val": float(m_rl.group(1).replace(",", "")),
                                      "pos": _span_center(sp["bbox"]), "cat": cat})
                except ValueError:
                    pass
            if m_gr:
                try:
                    grad_spans.append({"dir": m_gr.group(1).upper(),
                                        "ratio": float(m_gr.group(2).replace(",", "")),
                                        "pos": _span_center(sp["bbox"]),
                                        "cat": cat, "raw": txt, "page": pg_no})
                except ValueError:
                    pass

        # Pair each CH with the nearest same-colour RL (they sit stacked together)
        used_rl = set()
        for chs in ch_spans:
            best_i, best_d = None, 1e9
            for i, rls in enumerate(rl_spans):
                if i in used_rl or rls["cat"] != chs["cat"]:
                    continue
                d = _dist(chs["pos"], rls["pos"])
                if d < best_d:
                    best_d, best_i = d, i
            if best_i is not None and best_d <= 120:
                used_rl.add(best_i)
                points[chs["cat"]].append({"ch": chs["val"], "rl": rl_spans[best_i]["val"],
                                            "pos": chs["pos"], "page": pg_no})

        for gr in grad_spans:
            labels[gr["cat"]].append(gr)

    doc.close()

    for cat in points:
        seen, uniq = set(), []
        for p in points[cat]:
            key = (round(p["ch"], 3), round(p["rl"], 3), p["page"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(p)
        points[cat] = sorted(uniq, key=lambda p: p["ch"])

    return {"bridges": bridges, "points": points, "labels": labels}


def compute_gradients(points: list[dict]) -> list[dict]:
    """
    Auto-calculates the gradient of every consecutive CH/RL pair (ascending
    chainage order): direction R (rising) / F (falling) / LEVEL, and the
    "1 in X" ratio, purely from the surveyed CH & RL values.
    """
    segs = []
    for p1, p2 in zip(points, points[1:]):
        d_ch = p2["ch"] - p1["ch"]
        d_rl = p2["rl"] - p1["rl"]
        if d_ch <= 0:
            continue
        if abs(d_rl) < 1e-6:
            direction, ratio = "LEVEL", None
        else:
            direction, ratio = ("R" if d_rl > 0 else "F"), abs(d_ch / d_rl)
        ch_mid = (p1["ch"] + p2["ch"]) / 2.0
        rl_mid = p1["rl"] + (ch_mid - p1["ch"]) * (d_rl / d_ch)
        segs.append({
            "ch1": p1["ch"], "rl1": p1["rl"], "pos1": p1["pos"],
            "ch2": p2["ch"], "rl2": p2["rl"], "pos2": p2["pos"], "page": p1["page"],
            "delta_ch": d_ch, "delta_rl": d_rl,
            "ch_mid": ch_mid, "rl_mid": rl_mid,
            "direction": direction, "ratio": ratio,
            "slope_pct": (d_rl / d_ch * 100) if d_ch else 0.0,
        })
    return segs


def match_labels_to_segments(segments: list[dict], labels: list[dict],
                              max_dist: float = 260.0) -> list[dict]:
    """
    Cross-checks each computed segment against the nearest drawn gradient
    label (by page position, using whichever segment endpoint is closer),
    flagging MATCH / MISMATCH / UNLABELLED for each segment.
    """
    out = []
    for seg in segments:
        best, best_d = None, 1e9
        for lb in labels:
            if lb.get("page") != seg["page"]:
                continue
            d = min(_dist(lb["pos"], seg["pos1"]), _dist(lb["pos"], seg["pos2"]))
            if d < best_d:
                best_d, best = d, lb
        status, remark, matched = "UNLABELLED", \
            "No gradient label found on the drawing near this segment.", None
        if best is not None and best_d <= max_dist:
            matched = best["raw"]
            if seg["direction"] == "LEVEL" or seg["ratio"] is None:
                status  = "INFO"
                remark  = f'Nearest drawn label is "{best["raw"]}" — segment computes as level.'
            else:
                dir_ok   = best["dir"] == seg["direction"]
                ratio_ok = best["ratio"] and abs(best["ratio"] - seg["ratio"]) / best["ratio"] <= 0.05
                if dir_ok and ratio_ok:
                    status = "MATCH"
                    remark = f'Drawn label "{best["raw"]}" agrees with the computed gradient.'
                else:
                    status = "MISMATCH"
                    remark = (f'Drawn label "{best["raw"]}" does not match the value computed '
                              f'from CH/RL ({seg["direction"]}1 in {seg["ratio"]:.1f}).')
        out.append({**seg, "label_status": status, "label_remark": remark,
                    "matched_label": matched})
    return out


def bridges_in_segments(bridges: list[dict], segments: list[dict]) -> dict:
    """Maps each bridge chainage to the segment (of the given colour group) it falls within."""
    out = {}
    for br in bridges:
        for seg in segments:
            if seg["ch1"] <= br["ch"] <= seg["ch2"]:
                out[br["no"]] = seg
                break
    return out


def run_gradient_check(pdf_path: str) -> dict:
    """Top-level entry point: extract → compute → cross-check for EXG and PRO."""
    data = extract_gradient_data(pdf_path)
    result = {"bridges": data["bridges"], "colors": {}}
    for cat in ("EXG", "PRO"):
        pts  = data["points"][cat]
        segs = compute_gradients(pts)
        segs = match_labels_to_segments(segs, data["labels"][cat])
        at_bridge = bridges_in_segments(data["bridges"], segs)
        result["colors"][cat] = {
            "points": pts, "segments": segs,
            "labels_found": len(data["labels"][cat]),
            "bridge_segments": at_bridge,
        }
    return result


def _build_gradient_html(result: dict) -> str:
    bridges = result.get("bridges", [])
    colors  = result.get("colors", {})

    if not any(colors.get(c, {}).get("segments") for c in ("EXG", "PRO")):
        return (
            "<div style='background:#271D07;border:1px solid #D29922;"
            "border-radius:10px;padding:20px;font-family:Segoe UI,sans-serif;'>"
            "<b style='color:#D29922;font-size:14px;'>⚠ No chainage/RL pairs recognised</b><br>"
            "<span style='color:#8B949E;font-size:12px;'>Could not find CH:/RL: text pairs "
            "on this sheet — the sheet may not carry a Site Plan with gradient data.</span></div>"
        )

    STATUS = {
        "MATCH":      ("#0D2119", "#3FB950", "✓ MATCH"),
        "MISMATCH":   ("#2A0E0E", "#F85149", "✗ MISMATCH"),
        "UNLABELLED": ("#1A1525", "#A371F7", "? UNLABELLED"),
        "INFO":       ("#0D1B2A", "#58A6FF", "· LEVEL"),
    }

    def badge(status):
        bg, clr, lbl = STATUS.get(status, STATUS["UNLABELLED"])
        return (f"<span style='background:{bg};color:{clr};border:1px solid {clr};"
                f"border-radius:4px;padding:2px 9px;font-size:10px;font-weight:700;"
                f"white-space:nowrap;'>{lbl}</span>")

    bridge_html = ""
    if bridges:
        rows = "".join(
            f"<div style='padding:4px 0;font-size:12px;color:#E6EDF3;'>"
            f"🌉 <b>Bridge {b['no']}</b> — CH: {b['ch']:.3f} m &nbsp;"
            f"<span style='color:#8B949E;font-size:10px;'>(page {b['page']})</span></div>"
            for b in bridges
        )
        bridge_html = (
            "<div style='background:#161B22;border:1px solid #30363D;border-radius:8px;"
            f"padding:10px 14px;margin-bottom:14px;'>{rows}</div>"
        )

    def color_block(cat, label, accent):
        c = colors.get(cat, {})
        segs = c.get("segments", [])
        if not segs:
            return (f"<div style='margin-bottom:16px;color:#8B949E;font-size:12px;'>"
                     f"No {label} chainage/RL pairs recognised.</div>")
        at_bridge = c.get("bridge_segments", {})
        bridge_ch_by_seg = {}
        for no, seg in at_bridge.items():
            bridge_ch_by_seg.setdefault(id(seg), []).append(no)

        rows = ""
        bridge_by_no = {b["no"]: b for b in bridges}
        for seg in segs:
            flag = bridge_ch_by_seg.get(id(seg))
            ratio_txt = (f"{seg['direction']} 1 in {seg['ratio']:.1f}"
                         if seg["ratio"] else "LEVEL")
            bridge_tag = (f"<div style='margin-top:4px;font-size:10px;color:#D29922;'>"
                          f"🌉 Bridge {', '.join(flag)} falls in this reach</div>"
                          if flag else "")
            if flag:
                d_ch, d_rl = seg["ch2"] - seg["ch1"], seg["rl2"] - seg["rl1"]
                bits = []
                for no in flag:
                    br = bridge_by_no.get(no)
                    ch_b = br["ch"] if br else seg["ch_mid"]
                    rl_b = seg["rl1"] + (ch_b - seg["ch1"]) * (d_rl / d_ch) if d_ch else seg["rl1"]
                    bits.append(f"Br.{no}: CH {ch_b:.3f} → RL {rl_b:.3f} m")
                centre_txt = "<br>".join(bits)
            else:
                centre_txt = f"(mid) CH {seg['ch_mid']:.3f} → RL {seg['rl_mid']:.3f} m"
            rows += (
                "<tr style='border-bottom:1px solid #21262D;'>"
                f"<td style='padding:8px 10px;font-size:12px;color:#E6EDF3;white-space:nowrap;'>"
                f"CH {seg['ch1']:.3f} → {seg['ch2']:.3f}</td>"
                f"<td style='padding:8px 10px;font-size:12px;color:#E6EDF3;white-space:nowrap;'>"
                f"RL {seg['rl1']:.3f} → {seg['rl2']:.3f}</td>"
                f"<td style='padding:8px 10px;font-size:12px;font-weight:700;color:{accent};"
                f"white-space:nowrap;'>{ratio_txt}{bridge_tag}</td>"
                f"<td style='padding:8px 10px;font-size:11px;color:#E6EDF3;white-space:nowrap;'>"
                f"{centre_txt}</td>"
                f"<td style='padding:8px 10px;'>{badge(seg['label_status'])}"
                f"<div style='font-size:10px;color:#8B949E;margin-top:3px;max-width:260px;'>"
                f"{seg['label_remark']}</div></td>"
                "</tr>"
            )

        n_match = sum(1 for s in segs if s["label_status"] == "MATCH")
        n_mis   = sum(1 for s in segs if s["label_status"] == "MISMATCH")
        n_unl   = sum(1 for s in segs if s["label_status"] == "UNLABELLED")

        return f"""
<div style='margin-bottom:18px;'>
  <div style='display:flex;align-items:center;gap:8px;margin-bottom:6px;'>
    <span style='width:10px;height:10px;border-radius:50%;background:{accent};display:inline-block;'></span>
    <span style='font-size:13px;font-weight:700;color:{accent};'>{label}</span>
    <span style='font-size:10px;color:#8B949E;'>
      {len(segs)} segment(s) &nbsp;·&nbsp; {n_match} match &nbsp;·&nbsp;
      {n_mis} mismatch &nbsp;·&nbsp; {n_unl} unlabelled</span>
  </div>
  <table style='width:100%;border-collapse:collapse;background:#161B22;border-radius:8px;overflow:hidden;'>
    <thead><tr style='background:#0D1117;'>
      <th style='padding:7px 10px;text-align:left;font-size:9px;color:#8B949E;'>CHAINAGE</th>
      <th style='padding:7px 10px;text-align:left;font-size:9px;color:#8B949E;'>LEVEL (RL)</th>
      <th style='padding:7px 10px;text-align:left;font-size:9px;color:#8B949E;'>COMPUTED GRADIENT</th>
      <th style='padding:7px 10px;text-align:left;font-size:9px;color:#8B949E;'>RL @ BRIDGE (CENTRE)</th>
      <th style='padding:7px 10px;text-align:left;font-size:9px;color:#8B949E;'>VS. DRAWN LABEL</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""

    html = f"""
<html><body style='margin:0;padding:0;font-family:Segoe UI,Arial,sans-serif;
  background:#0D1117;color:#E6EDF3;padding:14px;'>
{bridge_html}
{color_block("EXG", "EXG. GRADIENTS  (black)", "#C9D1D9")}
{color_block("PRO", "PRO. GRADIENTS  (red)", "#F85149")}
<div style='padding:6px 0 0;font-size:10px;color:#8B949E;border-top:1px solid #21262D;'>
  Gradients are auto-calculated from recognised CH:/RL: pairs (Δ RL ÷ Δ CH) and cross-checked
  against drawn "R/F 1 IN X" labels within ~5% tolerance.
</div>
</body></html>"""
    return html


# ─────────────────────────────────────────────────────────────────────────────
# Corner-Block Gradient RL Check  (title-block CH/RL/gradient projection)
# ─────────────────────────────────────────────────────────────────────────────
#
# GAD / Site Plan sheets carry a small "corner block" (commonly top-right,
# but position varies) with FIVE components:
#
#   1. ONE centre value  — "¢ OF BRIDGE NO. 505 AT CH: 284200.00 m"
#      This is the bridge/culvert's own chainage — the TARGET chainage we
#      project every side value onto.
#   2-5. FOUR CH:/RL: boxes, one to the left and one to the right of the
#      centre value, plus a near-bridge gradient (ratio + Rising/Falling)
#      that is the SAME on both sides (see note below):
#        - BLACK  boxes/labels → EXG. (existing) bridge, left & right side
#        - RED    boxes/labels → PRO. (proposed) bridge, left & right side
#
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
_SIDE_KEYS = ["EXG_LEFT", "EXG_RIGHT", "PRO_LEFT", "PRO_RIGHT"]
_CAT_KEYS = ["EXG", "PRO"]

# NOTE ON THE GRADIENT MODEL (corrected):
# The near-bridge approach gradient (ratio + Rising/Falling) is laid as ONE
# continuous, uniform grade running straight through the bridge — the SAME
# ratio and the SAME Rise/Fall sense is printed on both the left and right
# side of the corner block. It is not two independent gradients that happen
# to match; it's one grade, quoted twice. So we only need ONE (direction,
# ratio) per colour (EXG / PRO), not one per side.
#
# Direction is read relative to the FIXED, physical direction of increasing
# chainage (the standard railway convention — gradient boards are always
# read travelling up-kilometrage) — never "towards/away from the bridge",
# which flips meaning depending which side you're standing on and is what
# caused the apparent sign error on the right-hand side when each side was
# (wrongly) treated as an independent value.
#
# CHECK LOGIC (same direction+ratio used for both LEFT and RIGHT):
#   Distance      = CH_target - CH_start        (signed — negative when the
#                                                  survey point's chainage is
#                                                  AHEAD of the bridge, i.e.
#                                                  on the right-hand side)
#   Delta RL      = Distance / N                 (N = "1 in N" ratio)
#   RL_target     = RL_start + Delta RL   (Rising / R)
#   RL_target     = RL_start - Delta RL   (Falling / F)
# Because Distance is signed (not absolute), this single formula is already
# correct on BOTH sides without needing a separate sign rule per side —
# verified against Bridge No. 505 (EXG: CH 282460.00/RL 351.889 and
# CH 285380.00/RL 364.158, both R 1 in 238, CH_target 284200.00) which lands
# on RL 359.200 from EITHER side, exactly.
# The left-side and right-side projections should therefore land on (very
# nearly) the same RL at the bridge centre-line — any spread beyond
# tolerance flags a drawing inconsistency (bad CH/RL/gradient figures).


def _dominant_ink_rgb(crop) -> tuple:
    """Median colour of the darker ('ink') pixels in a cropped word/line
    region, ignoring the near-white paper/screen background. This is more
    robust than sampling a single pixel — screenshots and scans both have
    anti-aliased edges around the actual stroke colour."""
    import numpy as np
    if crop.size == 0:
        return (0.0, 0.0, 0.0)
    flat = crop.reshape(-1, 3).astype(float)
    brightness = flat.sum(axis=1)
    lo, hi = brightness.min(), brightness.max()
    if hi <= lo:
        return tuple((flat[0] / 255.0).tolist())
    thresh = lo + (hi - lo) * 0.5
    ink = flat[brightness <= thresh]
    if ink.size == 0:
        ink = flat
    med = np.median(ink, axis=0) / 255.0
    return (float(med[0]), float(med[1]), float(med[2]))


def _spans_from_pil(img, psm: int = 3) -> tuple:
    """OCRs a PIL image and returns (spans, width, height, full_text) in the
    same shape used for native PDF text-spans: {"text","bbox","rgb"}.
    OCR words are grouped into lines (Tesseract's block/par/line grouping),
    matching how a native PDF span covers a run of same-style text — the
    regexes (_CH_RE / _RL_RE / _GRAD_RE / _BRIDGE_CH_RE) run per line.

    psm: Tesseract page-segmentation mode. 11 ("sparse text — find as much
    text as possible in no particular order") works far better than the
    default on CAD/GAD sheets, where small text labels sit scattered among
    dense line-art rather than in paragraph blocks.

    Requires: pillow, pytesseract, numpy, and the Tesseract OCR binary
    installed and on PATH (e.g. `winget install UB-Mannheim.TesseractOCR`
    on Windows, or `apt install tesseract-ocr` on Linux).
    """
    import numpy as np
    try:
        import pytesseract
    except ImportError as e:
        raise RuntimeError(
            "OCR support needs the 'pytesseract' and 'numpy' packages "
            "(pip install pytesseract numpy) plus the Tesseract OCR engine "
            "installed separately (not a pip package) — see "
            "https://github.com/UB-Mannheim/tesseract/wiki for Windows."
        ) from e

    rgb_img = img.convert("RGB")
    w, h = rgb_img.size
    arr = np.asarray(rgb_img)

    config = f"--oem 3 --psm {psm}"
    data = pytesseract.image_to_data(rgb_img, config=config,
                                      output_type=pytesseract.Output.DICT)
    n = len(data["text"])
    lines: dict[tuple, list[int]] = {}
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(i)

    spans, full_lines = [], []
    for idxs in lines.values():
        idxs.sort(key=lambda i: data["left"][i])
        words = [data["text"][i].strip() for i in idxs]
        line_text = " ".join(words)
        full_lines.append(line_text)
        x0 = min(data["left"][i] for i in idxs)
        y0 = min(data["top"][i] for i in idxs)
        x1 = max(data["left"][i] + data["width"][i] for i in idxs)
        y1 = max(data["top"][i] + data["height"][i] for i in idxs)
        crop = arr[max(y0, 0):max(y1, 1), max(x0, 0):max(x1, 1)]
        rgb = _dominant_ink_rgb(crop)
        spans.append({"text": line_text, "bbox": (x0, y0, x1, y1), "rgb": rgb})

    return spans, float(w), float(h), "\n".join(full_lines)


def _inverse_rotate_bbox(bbox: tuple, rot: int, crop_w: int, crop_h: int) -> tuple:
    """Maps a bbox from a rotated crop's coordinate space back to the
    PRE-rotation crop's coordinate space. crop_w/crop_h are the dimensions
    of the crop BEFORE rotation. rot is 0, 90 (CCW / Image.ROTATE_90), or
    270 (CW / Image.ROTATE_270) — matching PIL's transpose() constants."""
    bx0, by0, bx1, by1 = bbox
    corners = [(bx0, by0), (bx1, by0), (bx0, by1), (bx1, by1)]
    pts = []
    for rx, ry in corners:
        if rot == 90:      # crop was rotated 90° CCW to make (crop_h, crop_w)
            x = crop_w - 1 - ry
            y = rx
        elif rot == 270:   # crop was rotated 90° CW to make (crop_h, crop_w)
            x = ry
            y = crop_h - 1 - rx
        else:
            x, y = rx, ry
        pts.append((x, y))
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _ocr_crop_multi(img, box: tuple, upscale: int = 3, psm: int = 11,
                     try_rotations: tuple = (0, 90, 270)) -> list:
    """Heavily up-scaled, rotation-robust OCR of one region of a page.
    Tries the crop right-way-up AND rotated ±90° (Indian Railway GAD
    corner-blocks sometimes squeeze the CH:/RL:/gradient labels in reading
    top-to-bottom to save width), merging whatever each orientation reads.
    Every returned span's bbox is translated back into the ORIGINAL (un-
    cropped, un-scaled) page's coordinate space so it can be compared
    directly against spans from the full-page pass."""
    from PIL import Image
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, img.width), min(y1, img.height)
    if x1 <= x0 or y1 <= y0:
        return []

    crop = img.crop((x0, y0, x1, y1))
    if upscale != 1:
        crop = crop.resize((crop.width * upscale, crop.height * upscale), Image.LANCZOS)
    cw, ch = crop.size  # dims of the (upscaled) pre-rotation crop

    out = []
    for rot in try_rotations:
        if rot == 90:
            rimg = crop.transpose(Image.ROTATE_90)
        elif rot == 270:
            rimg = crop.transpose(Image.ROTATE_270)
        else:
            rimg = crop
        spans, _, _, _ = _spans_from_pil(rimg, psm=psm)
        for sp in spans:
            fx0, fy0, fx1, fy1 = _inverse_rotate_bbox(sp["bbox"], rot, cw, ch)
            out.append({
                "text": sp["text"],
                "bbox": (x0 + fx0 / upscale, y0 + fy0 / upscale,
                         x0 + fx1 / upscale, y0 + fy1 / upscale),
                "rgb": sp["rgb"],
            })
    return out


def _ocr_full_and_detail(img) -> tuple:
    """Two-pass OCR of a full GAD sheet:
      Pass 1 — sparse-text OCR of the WHOLE sheet (psm 11), mainly to
        locate the "¢ OF BRIDGE NO... AT CH..." header and get the overall
        page size / bridge no. / target chainage.
      Pass 2 — a small, ~3x up-scaled, rotation-robust re-OCR of just the
        band around that header (full width, generous height either side).
        The corner-block CH:/RL:/gradient labels are tiny relative to a
        whole A0/A1 sheet and easily missed at whole-sheet OCR resolution;
        re-reading just that band at effectively much higher DPI — and
        trying it rotated in case the labels read top-to-bottom — is far
        more reliable than raising the whole-sheet OCR resolution (which
        would make the OCR pass very slow on a large drawing).
    Returns (spans, width, height, full_text) — full_text is from pass 1
    only (used for the bridge-header regex); pass-2 spans are appended to
    the returned spans list for the corner-block field extraction.
    """
    spans, w, h, full_text = _spans_from_pil(img, psm=11)

    header_bbox = None
    for sp in spans:
        if "BRIDGE" in sp["text"].upper():
            header_bbox = sp["bbox"]
            break

    if header_bbox is not None:
        x0, y0, x1, y1 = header_bbox
        line_h = max(y1 - y0, 14)
        crop_box = (0, max(0, y0 - line_h * 2), w, min(h, y0 + line_h * 18))
        detail = _ocr_crop_multi(img, crop_box, upscale=3, psm=11,
                                   try_rotations=(0, 90, 270))
        spans = spans + detail

    return spans, w, h, full_text


def _nearest_gradients(grad_spans: list[dict], ref_pos: tuple, cat: str,
                        page_cx: float, max_dist: float = 260.0) -> list[dict]:
    """Gradient label spans of the given colour near a reference point,
    nearest-to-sheet-centre first (i.e. the 'inner'/near-bridge label is
    returned first — that's the one shared, near-bridge grade)."""
    cands = [g for g in grad_spans
              if g["cat"] == cat and _dist(g["pos"], ref_pos) <= max_dist]
    cands.sort(key=lambda g: abs(g["pos"][0] - page_cx))
    return cands


def _compute_box_rl(ch_start: float, rl_start: float, direction: str,
                     ratio: float, ch_target: float) -> float:
    """RL at ch_target, projected from a known (ch_start, rl_start) point
    along a uniform "1 in ratio" grade. `direction` ("R"=Rising / "F"=
    Falling) is read relative to the FIXED direction of increasing
    chainage, so the SAME (direction, ratio) pair is valid from either side
    of the bridge — the sign of (ch_target - ch_start) does the rest."""
    distance = ch_target - ch_start
    delta = distance / ratio
    return round(rl_start + delta, 3) if direction == "R" else round(rl_start - delta, 3)


def _page_spans(path: str):
    """Yields (page_no, spans, page_width, full_text, extraction) for every
    page of a PDF or a single image, choosing native text where available
    and two-pass OCR where it isn't:
      - PNG/JPG/... input        → OCR directly (full-sheet + detail pass).
      - PDF page WITH a text layer → native fitz text extraction (fast, exact).
      - PDF page with NO text layer (a scanned/rasterised sheet, or a PDF
        made by "print to PDF" from a screenshot) → rendered to an image
        at 300 DPI and OCR'd (full-sheet + detail pass), same as a raw
        image would be.
    """
    ext = Path(path).suffix.lower()
    if ext in _IMAGE_EXTS:
        from PIL import Image
        img = Image.open(path)
        spans, w, h, full_text = _ocr_full_and_detail(img)
        yield 1, spans, w, full_text, "ocr"
        return

    import fitz
    doc = fitz.open(path)
    for pg_no, page in enumerate(doc, start=1):
        full_text = page.get_text()
        raw = page.get_text("dict")
        spans = []
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for sp in line.get("spans", []):
                    txt = sp.get("text", "").strip()
                    if not txt:
                        continue
                    ci = sp.get("color", 0)
                    rgb = (((ci >> 16) & 255) / 255.0,
                           ((ci >> 8) & 255) / 255.0,
                           (ci & 255) / 255.0)
                    spans.append({"text": txt, "bbox": sp["bbox"], "rgb": rgb})

        if spans and full_text.strip():
            yield pg_no, spans, page.rect.width, full_text, "native"
        else:
            # No text layer on this page — fall back to OCR on a 300 DPI render.
            from PIL import Image
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            o_spans, w, h, o_text = _ocr_full_and_detail(img)
            yield pg_no, o_spans, w, o_text, "ocr"
    doc.close()


def extract_corner_block(path: str) -> dict:
    """
    Auto-detects the corner-block data from a GAD sheet (PDF — native text
    or scanned — or a PNG/JPG screenshot). ALWAYS returns one diagnostic
    entry per page, even when some or all components could not be found,
    so the caller can offer manual completion for whatever is missing
    instead of just failing.

    Per category (EXG / PRO) the near-bridge approach gradient is a SINGLE
    (direction, ratio) value shared by both the left and right side (see
    module note above) — so we detect ONE gradient label per colour, not
    one per side, picking whichever candidate sits closest to the sheet's
    horizontal centre (i.e. the near-bridge grade, not a further reach).

    Returns:
      {"pages": [
          {"page": 1, "bridge_no": "471"|None, "ch_target": 262606.02|None,
           "extraction": "native"|"ocr",
           "ch_rl": {"EXG_LEFT": {"ch_start":..,"rl_start":..}|None, ...},
           "gradients": {"EXG": {"dir":"R","ratio":238.0}|None, "PRO": ...},
           "missing": ["ch_target", "PRO_RIGHT", "EXG_GRADIENT", ...],
           "raw_lines": [...]}, ...
      ]}
    """
    results = []
    for pg_no, spans, page_w, full_text, extraction in _page_spans(path):
        page_cx = page_w / 2.0
        m = _BRIDGE_CH_RE.search(full_text)
        bridge_no = m.group(1).strip().rstrip(".:,") if m else None
        ch_target = None
        if m:
            try:
                ch_target = float(m.group(2).replace(",", ""))
            except ValueError:
                ch_target = None

        ch_spans, rl_spans, grad_spans = [], [], []
        for sp in spans:
            txt = sp["text"]
            if "BRIDGE" in txt.upper():
                continue  # skip the centre header itself
            cat = _classify_gradient_color(sp["rgb"])
            if cat == "OTHER":
                continue
            pos = _span_center(sp["bbox"])
            m_ch, m_rl, m_gr = _CH_RE.search(txt), _RL_RE.search(txt), _GRAD_RE.search(txt)
            if m_ch:
                try:
                    ch_spans.append({"val": float(m_ch.group(1).replace(",", "")),
                                      "pos": pos, "cat": cat})
                except ValueError:
                    pass
            if m_rl:
                try:
                    rl_spans.append({"val": float(m_rl.group(1).replace(",", "")),
                                      "pos": pos, "cat": cat})
                except ValueError:
                    pass
            if m_gr:
                try:
                    grad_spans.append({"dir": m_gr.group(1).upper(),
                                        "ratio": float(m_gr.group(2).replace(",", "")),
                                        "pos": pos, "cat": cat, "raw": txt})
                except ValueError:
                    pass

        used_rl = set()
        ch_rl = {k: None for k in _SIDE_KEYS}
        for chs in ch_spans:
            best_i, best_d = None, 1e9
            for i, rls in enumerate(rl_spans):
                if i in used_rl or rls["cat"] != chs["cat"]:
                    continue
                d = _dist(chs["pos"], rls["pos"])
                if d < best_d:
                    best_d, best_i = d, i
            if best_i is None or best_d > 170:
                continue
            used_rl.add(best_i)
            rls = rl_spans[best_i]
            side = "LEFT" if chs["pos"][0] < page_cx else "RIGHT"
            key = f'{chs["cat"]}_{side}'
            if ch_rl.get(key) is not None:
                continue  # keep first match for this slot
            ch_rl[key] = {"ch_start": chs["val"], "rl_start": rls["val"], "source": "auto"}

        # ONE shared gradient per colour — pick the candidate nearest the
        # sheet centre (the near-bridge grade), searched relative to the
        # page centre itself rather than any one side's box.
        gradients = {}
        for cat in _CAT_KEYS:
            near = _nearest_gradients(grad_spans, (page_cx, 0), cat, page_cx,
                                       max_dist=page_w)  # search whole width
            gradients[cat] = ({"dir": near[0]["dir"], "ratio": near[0]["ratio"],
                                "source": "auto"} if near else None)

        missing = []
        if ch_target is None:
            missing.append("ch_target")
        for key in _SIDE_KEYS:
            if ch_rl.get(key) is None:
                missing.append(key)
        for cat in _CAT_KEYS:
            if gradients.get(cat) is None:
                missing.append(f"{cat}_GRADIENT")

        results.append({
            "page": pg_no, "bridge_no": bridge_no, "ch_target": ch_target,
            "extraction": extraction, "ch_rl": ch_rl, "gradients": gradients,
            "missing": missing,
            # Kept only for diagnostics — every line of text + colour the
            # OCR/parser actually found, so a still-missing field can be
            # debugged against what Tesseract really read.
            "raw_lines": [
                {"text": sp["text"], "cat": _classify_gradient_color(sp["rgb"])}
                for sp in spans if sp["text"].strip()
            ][:400],
        })

    return {"pages": results}


def apply_manual_overrides(data: dict, manual: dict | None) -> dict:
    """Fills gaps in extract_corner_block()'s output with user-supplied
    values:
      manual = {
        "bridge_no": "471", "ch_target": 262606.02,
        "ch_rl": {"EXG_LEFT": {"ch_start":.., "rl_start":..}, "EXG_RIGHT": {...},
                   "PRO_LEFT": {...}, "PRO_RIGHT": {...}},
        "gradients": {"EXG": {"dir": "R", "ratio": 238}, "PRO": {"dir": "R", "ratio": 240}},
      }
    Auto-detected fields are always kept; manual values only fill gaps."""
    if not manual:
        return data
    for pr in data["pages"]:
        if not pr["missing"]:
            continue
        if manual.get("bridge_no") and not pr["bridge_no"]:
            pr["bridge_no"] = manual["bridge_no"]
        if manual.get("ch_target") is not None and pr["ch_target"] is None:
            pr["ch_target"] = manual["ch_target"]

        for key, mb in (manual.get("ch_rl") or {}).items():
            if key not in _SIDE_KEYS or not mb:
                continue
            if pr["ch_rl"].get(key) is None and mb.get("ch_start") is not None \
                    and mb.get("rl_start") is not None:
                pr["ch_rl"][key] = {"ch_start": mb["ch_start"], "rl_start": mb["rl_start"],
                                     "source": "manual"}

        for cat, mg in (manual.get("gradients") or {}).items():
            if cat not in _CAT_KEYS or not mg:
                continue
            if pr["gradients"].get(cat) is None and mg.get("dir") and mg.get("ratio") is not None:
                pr["gradients"][cat] = {"dir": mg["dir"], "ratio": mg["ratio"], "source": "manual"}

        missing = []
        if pr["ch_target"] is None:
            missing.append("ch_target")
        for key in _SIDE_KEYS:
            if pr["ch_rl"].get(key) is None:
                missing.append(key)
        for cat in _CAT_KEYS:
            if pr["gradients"].get(cat) is None:
                missing.append(f"{cat}_GRADIENT")
        pr["missing"] = missing
    return data


def check_corner_block_rls(path: str, manual: dict | None = None,
                            tol: float = 0.015) -> dict:
    """Runs extract_corner_block(), merges any manual overrides, then
    cross-checks LEFT vs RIGHT projected RL at the bridge centre-line,
    separately for EXG (black) and PRO (red) — using the ONE shared
    (direction, ratio) gradient for each colour."""
    data = extract_corner_block(path)
    data = apply_manual_overrides(data, manual)

    out_pages = []
    for pr in data["pages"]:
        if pr["missing"]:
            out_pages.append({**pr, "checks": {}, "ready": False})
            continue
        ch_target = pr["ch_target"]
        checks = {}
        for cat in _CAT_KEYS:
            grad = pr["gradients"][cat]
            sides = [pr["ch_rl"][f"{cat}_LEFT"], pr["ch_rl"][f"{cat}_RIGHT"]]
            computed = []
            for side_name, b in (("LEFT", sides[0]), ("RIGHT", sides[1])):
                if not b:
                    continue
                rl_t = _compute_box_rl(b["ch_start"], b["rl_start"], grad["dir"],
                                        grad["ratio"], ch_target)
                computed.append({"side": side_name, "ch_start": b["ch_start"],
                                  "rl_start": b["rl_start"], "dir": grad["dir"],
                                  "ratio": grad["ratio"], "ch_target": ch_target,
                                  "rl_target_computed": rl_t,
                                  "source": b.get("source", "auto")})
            if len(computed) < 2:
                checks[cat] = {"boxes": computed, "status": "INCOMPLETE",
                                "remark": "Only one side available."}
                continue
            vals = [b["rl_target_computed"] for b in computed]
            spread = round(max(vals) - min(vals), 3)
            status = "MATCH" if spread <= tol else "MISMATCH"
            checks[cat] = {
                "boxes": computed, "status": status, "spread": spread,
                "avg_rl": round(sum(vals) / len(vals), 3),
                "remark": (f"LEFT & RIGHT projections agree within {tol:.3f} m."
                           if status == "MATCH" else
                           f"LEFT vs RIGHT projected RL differ by {spread:.3f} m "
                           f"(> {tol:.3f} m tolerance) — check drawn gradient/CH/RL figures.")
            }
        out_pages.append({**pr, "checks": checks, "ready": True})

    return {"pages": out_pages, "tolerance": tol}


def _build_corner_block_html(result: dict) -> str:
    pages = result.get("pages", [])
    tol = result.get("tolerance", 0.015)

    if not pages:
        return (
            "<div style='background:#271D07;border:1px solid #D29922;"
            "border-radius:10px;padding:20px;font-family:Segoe UI,sans-serif;'>"
            "<b style='color:#D29922;font-size:14px;'>⚠ No corner-block found</b><br>"
            "<span style='color:#8B949E;font-size:12px;'>Could not read this sheet at all "
            "— check the file isn't corrupted.</span></div>"
        )

    STATUS = {
        "MATCH":      ("#0D2119", "#3FB950", "✓ MATCH"),
        "MISMATCH":   ("#2A0E0E", "#F85149", "✗ MISMATCH"),
        "INCOMPLETE": ("#1A1525", "#A371F7", "? INCOMPLETE"),
    }

    def badge(status):
        bg, clr, lbl = STATUS.get(status, STATUS["INCOMPLETE"])
        return (f"<span style='background:{bg};color:{clr};border:1px solid {clr};"
                f"border-radius:4px;padding:2px 9px;font-size:10px;font-weight:700;"
                f"white-space:nowrap;'>{lbl}</span>")

    blocks = ""
    for pr in pages:
        extraction_tag = (
            "<span style='font-size:9px;color:#D29922;font-weight:700;'>OCR</span>"
            if pr.get("extraction") == "ocr" else
            "<span style='font-size:9px;color:#8B949E;'>native text</span>")

        if not pr["ready"]:
            need = ", ".join(pr["missing"])
            raw_lines = pr.get("raw_lines") or []
            CAT_CLR = {"EXG": "#C9D1D9", "PRO": "#F85149", "OTHER": "#586069"}
            raw_html = "".join(
                f"<div style='color:{CAT_CLR.get(rl['cat'],'#586069')};'>"
                f"[{rl['cat']}] {html.escape(rl['text'])}</div>"
                for rl in raw_lines) or "<i>(nothing recognised)</i>"
            blocks += f"""
<div style='margin-bottom:18px;background:#271D07;border:1px solid #D29922;
  border-radius:8px;padding:14px;'>
  <b style='color:#D29922;font-size:13px;'>⚠ Page {pr['page']} — incomplete
  ({extraction_tag})</b>
  <div style='font-size:11px;color:#E6EDF3;margin-top:6px;'>
    Auto-detected: bridge {pr['bridge_no'] or '—'},
    target CH {f"{pr['ch_target']:.3f}" if pr['ch_target'] is not None else '—'}.<br>
    Still missing: <b>{need}</b> — fill these in below and re-run.
  </div>
  <div style='font-size:10px;color:#8B949E;margin-top:10px;margin-bottom:3px;'>
    Raw text the OCR/parser found on this sheet (for debugging — share this
    if fields keep going missing):
  </div>
  <div style='font-family:Consolas,monospace;font-size:10px;background:#0D1117;
    border:1px solid #30363D;border-radius:6px;padding:8px;max-height:160px;
    overflow-y:auto;line-height:1.5;'>{raw_html}</div>
</div>"""
            continue

        rows = ""
        for cat, label, accent in (("EXG", "EXG. (black)", "#C9D1D9"),
                                     ("PRO", "PRO. (red)", "#F85149")):
            c = pr["checks"].get(cat)
            if not c:
                continue
            box_rows = "".join(
                f"<div style='font-size:11px;color:{accent};padding:2px 0;'>"
                f"&nbsp;&nbsp;{b['side']}: CH {b['ch_start']:.3f} → RL {b['rl_start']:.3f} m, "
                f"{b['dir']} 1 in {b['ratio']:.0f} &nbsp;→&nbsp; RL@CH{b['ch_target']:.0f} = "
                f"<b>{b['rl_target_computed']:.3f} m</b>"
                f"{' <i style=\"color:#D29922;\">(manual)</i>' if b.get('source') != 'auto' else ''}"
                f"</div>" for b in c["boxes"])
            rows += (
                "<tr style='border-bottom:1px solid #21262D;'>"
                f"<td style='padding:8px 10px;font-size:12px;font-weight:700;color:{accent};"
                f"white-space:nowrap;'>{label}</td>"
                f"<td style='padding:8px 10px;'>{box_rows}</td>"
                f"<td style='padding:8px 10px;'>{badge(c['status'])}"
                f"<div style='font-size:10px;color:#8B949E;margin-top:3px;max-width:240px;'>"
                f"{c.get('remark','')}</div></td>"
                "</tr>"
            )
        blocks += f"""
<div style='margin-bottom:18px;'>
  <div style='font-size:13px;font-weight:700;color:#E6EDF3;margin-bottom:6px;'>
    🌉 Bridge {pr['bridge_no'] or '?'} — centre-line CH
    {f"{pr['ch_target']:.3f}" if pr['ch_target'] is not None else '?'} m
    <span style='font-size:10px;color:#8B949E;font-weight:400;'>
    (page {pr['page']}, {extraction_tag})</span></div>
  <table style='width:100%;border-collapse:collapse;background:#161B22;border-radius:8px;overflow:hidden;'>
    <thead><tr style='background:#0D1117;'>
      <th style='padding:7px 10px;text-align:left;font-size:9px;color:#8B949E;'>SET</th>
      <th style='padding:7px 10px;text-align:left;font-size:9px;color:#8B949E;'>LEFT / RIGHT PROJECTION</th>
      <th style='padding:7px 10px;text-align:left;font-size:9px;color:#8B949E;'>CROSS-CHECK</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""

    return f"""
<html><body style='margin:0;padding:0;font-family:Segoe UI,Arial,sans-serif;
  background:#0D1117;color:#E6EDF3;padding:14px;'>
{blocks}
<div style='padding:6px 0 0;font-size:10px;color:#8B949E;border-top:1px solid #21262D;'>
  RL@bridge-CH is projected from each side's CH:/RL: point (RL_start ± (CH_target-CH_start)/N)
  using the ONE shared near-bridge gradient for that colour (same value used for both sides,
  read relative to increasing chainage); LEFT vs RIGHT are cross-checked to ±{tol:.3f} m.
  PDF pages with no text layer, and PNG/JPG files, are read via OCR.
</div>
</body></html>"""


def run_corner_block_check(path: str, manual: dict | None = None) -> dict:
    """Top-level entry point used by the Scrutiny panel. Accepts a PDF or an
    image (PNG/JPG/...). Pass `manual` to fill in fields the auto-detector
    couldn't trace (see apply_manual_overrides for the expected shape)."""
    return check_corner_block_rls(path, manual=manual)



# ─────────────────────────────────────────────────────────────────────────────
# Scrutiny — Vertical Clearance Calculator
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Loop Interface — eDAS auto-login & keep-alive
# ─────────────────────────────────────────────────────────────────────────────
# NOTE: field/button selectors below are best-effort placeholders. eDAS is a
# login-gated site so the actual DOM couldn't be inspected while building
# this — open the login page once, check the real field names/ids with
# browser dev-tools, and adjust the By.* selectors in _login() if they don't
# match. Everything else (loop, keep-alive, captcha solving) is selector-
# independent and needs no changes.

EDAS_URL       = "https://edas.rcil.gov.in/auth/login2"
EDAS_USER_DEF  = "DYCE-C-DESIGN-SCR"
EDAS_PASS_DEF  = "Dcedscr@123"
LI_REFRESH_SEC = 2


def _edas_creds() -> tuple[str, str]:
    """Credentials from QSettings if the user has overridden them there,
    else the defaults above — same precedence pattern as _load_keys()."""
    s = QSettings("BES", "BridgeEngineeringSuite")
    u = str(s.value("edas_username", "") or "").strip() or EDAS_USER_DEF
    p = str(s.value("edas_password", "") or "").strip() or EDAS_PASS_DEF
    return u, p


# ── shared eDAS session helpers (used by LoopInterfaceWorker AND
#    StatusUpdationWorker so both drive the login/captcha flow identically) ──

def _edas_browser_alive(driver) -> bool:
    try:
        _ = driver.title
        return True
    except Exception:
        return False


def _edas_is_logged_in(driver) -> bool:
    try:
        url = driver.current_url.lower()
        return "login" not in url and "auth" not in url
    except Exception:
        return False


def _edas_minimize(driver):
    """Keep the automation out of the user's way — Selenium drives the
    page over the WebDriver protocol so this works even minimized."""
    try:
        driver.minimize_window()
    except Exception:
        pass


def _edas_solve_captcha_text(text: str):
    m = re.search(r"(\d+)\s*([+\-x×*])\s*(\d+)", text)
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    if op == "+":            return a + b
    if op == "-":            return a - b
    return a * b


def _edas_solve_captcha_ai(driver, log_fn=lambda *a: None):
    """Fallback if the equation can't be regex-parsed from page text —
    screenshots the whole viewport and asks the AI to read/solve it."""
    claude_key, gemini_key = _load_keys()
    if not (claude_key or gemini_key):
        return None
    b64 = base64.b64encode(driver.get_screenshot_as_png()).decode()
    prompt = ("This is a login page with an arithmetic captcha challenge "
              "(labelled 'Solve'). Find the equation and solve it. "
              "Reply with ONLY the final number, nothing else.")
    try:
        if gemini_key:
            from gui.ai_provider import AIProvider, PROVIDER_GEMINI
            ai  = AIProvider(gemini_key, PROVIDER_GEMINI)
            raw = ai.vision(system="You solve simple arithmetic captchas.",
                             image_b64=b64, mime="image/png",
                             user=prompt, max_tokens=20)
        else:
            import anthropic
            from gui.ai_provider import ANTHROPIC_MODEL, _anthropic_text
            client = anthropic.Anthropic(api_key=claude_key)
            resp = client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=20,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                      "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": prompt}]}])
            raw = _anthropic_text(resp).strip()
        m = re.search(r"-?\d+", raw)
        return int(m.group()) if m else None
    except Exception as e:
        log_fn(f"AI captcha solve failed: {e}", "warn")
        return None


def _edas_login(driver, log_fn=lambda *a: None) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    user, pwd = _edas_creds()
    wait = WebDriverWait(driver, 15)
    try:
        driver.get(EDAS_URL)
        # Fields have no name/id — matched by placeholder text instead
        # (English half of the bilingual placeholder, so it's stable
        # even if the Hindi text changes).
        uf = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//input[contains(@placeholder,'Username')]")))
        pf = driver.find_element(
            By.XPATH, "//input[contains(@placeholder,'Password')]"
        )
        def _wipe_field(el):
            """If the field is pre-filled (browser autofill / saved values),
            wipe it reliably — some pages ignore element.clear(), so fall
            back to select-all + delete."""
            from selenium.webdriver.common.keys import Keys
            if el.get_attribute("value"):
                el.clear()
                el.send_keys(Keys.CONTROL, "a")
                el.send_keys(Keys.DELETE)
                time.sleep(0.3)
                # Double-check: if still has value, force-clear via JS
                if el.get_attribute("value"):
                    driver.execute_script("arguments[0].value='';", el)
                    time.sleep(0.2)

        # MUST CHECK: if fields have autofilled data, clear it first
        uf_val = uf.get_attribute("value") or ""
        pf_val = pf.get_attribute("value") or ""
        if uf_val.strip():
            log_fn(f"🧹 Autofilled username detected ('{uf_val.strip()[:8]}...') — clearing.", "warn")
        if pf_val.strip():
            log_fn("🧹 Autofilled password detected — clearing.", "warn")

        _wipe_field(uf); uf.send_keys(user)
        _wipe_field(pf); pf.send_keys(pwd)
    except Exception as e:
        log_fn(f"⚠ Could not find username/password fields: {e}", "err")
        return False

    # Arithmetic captcha — e.g. "Solve / हल करें : 3 * 1 = ?"
    try:
        try:
            capt_text = driver.find_element(
                By.XPATH, "//*[contains(text(),'Solve')]").text
        except Exception:
            capt_text = driver.find_element(By.TAG_NAME, "body").text
        answer = _edas_solve_captcha_text(capt_text) or _edas_solve_captcha_ai(driver, log_fn)
        if answer is not None:
            cf = driver.find_element(
                By.XPATH, "//input[contains(@placeholder,'solved') or "
                          "contains(@placeholder,'उत्तर')]")
            cf.clear(); cf.send_keys(str(answer))
            log_fn(f"🧮 Captcha solved → {answer}", "ok")
        else:
            log_fn("⚠ Could not read the captcha equation.", "warn")
    except Exception as e:
        log_fn(f"⚠ Captcha step failed: {e}", "warn")

    try:
        btn = driver.find_element(By.XPATH, "//button[contains(., 'LOGIN')]")
        btn.click()
    except Exception as e:
        log_fn(f"⚠ Could not click login button: {e}", "err")
        return False

    time.sleep(2)
    ok = _edas_is_logged_in(driver)
    log_fn("✅ Logged in to eDAS." if ok else
           "⚠ Login submitted but dashboard not detected.", "ok" if ok else "warn")
    return ok


class LoopInterfaceWorker(QThread):
    """Opens eDAS in Edge, logs in (solving the arithmetic captcha), then
    keeps the session alive by refreshing every LI_REFRESH_SEC seconds and
    re-logging in automatically if the session drops — until stop() is
    called or the browser window is closed manually."""

    log     = pyqtSignal(str, str)   # message, level
    stopped = pyqtSignal(str)        # reason: "user_stop" | "browser_closed" | "error"

    def __init__(self):
        super().__init__()
        self._stop_evt = threading.Event()
        self.driver = None

    def stop(self):
        self._stop_evt.set()

    def _log(self, msg, level="info"):
        self.log.emit(msg, level)

    # ── lifecycle ──────────────────────────────────────────────────────
    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            import traceback
            self._log(f"Fatal error: {e}", "err")
            print(traceback.format_exc())
            self.stopped.emit("error")
        finally:
            try:
                if self.driver:
                    self.driver.quit()
            except Exception:
                pass

    def _open_browser(self):
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options as EdgeOptions
        opts = EdgeOptions()
        opts.add_experimental_option("detach", True)   # survives if driver handle dies
        self.driver = webdriver.Edge(options=opts)
        self.driver.set_window_size(1280, 900)
        _edas_minimize(self.driver)   # minimized from the start — never on-screen
        self._log("🌐 Edge launched (minimized) — working in the background.", "ok")

    # ── main loop ──────────────────────────────────────────────────────
    def _run_inner(self):
        self._open_browser()
        logged_in = _edas_login(self.driver, self._log)
        if not logged_in:
            self._log("Retrying login on next cycle…", "warn")

        while not self._stop_evt.is_set():
            if not _edas_browser_alive(self.driver):
                self._log("🛑 Browser window closed — stopping.", "warn")
                self.stopped.emit("browser_closed")
                return
            if not _edas_is_logged_in(self.driver):
                self._log("🔁 Session dropped — logging in again…", "warn")
                _edas_login(self.driver, self._log)
            else:
                try:
                    self.driver.refresh()
                except Exception:
                    pass
            self._stop_evt.wait(LI_REFRESH_SEC)

        self._log("⏹ Loop Interface stopped.", "info")
        self.stopped.emit("user_stop")


# ─────────────────────────────────────────────────────────────────────────────
# Status Updation — All Drawings ↔ Google Sheet sync
# ─────────────────────────────────────────────────────────────────────────────
# NOTE (same caveat as Loop Interface): the All-Drawings table and the
# Members modal DOM could only be inspected from screenshots, not live —
# the XPath selectors below are matched against what's visible in those
# screenshots (placeholder text, column order, badge text pattern) and may
# need small tweaks once run against the live page. The Google Sheets
# selectors (Name Box #t-name-box, formula bar) are Google's own stable,
# long-standing element ids and are unlikely to need changes.

def _short_drawing_id(full_id: str) -> str:
    """Extract the short numerical drawing ID from a full eDAS Drawing ID.
    E.g. 'GM(W)-SCR-BRIDGES -TRACK-CON SC-DUU-407-2025' → '407-2025'.
    If no pattern matches, returns the original string unchanged."""
    # Match trailing digits-digits pattern like 407-2025, 12-2024, 1234-2025
    m = re.search(r'(\d{1,6}-(?:19|20)\d{2})\s*$', full_id.strip())
    if m:
        return m.group(1)
    # Fallback: match the last two hyphen-separated numeric segments
    m = re.search(r'(\d[\d-]*\d)\s*$', full_id.strip())
    if m and any(c.isdigit() for c in m.group(1)):
        return m.group(1)
    return full_id


GOOGLE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1rj_hOPCON6KbMq0BE9M6rn0OIRG1EFhgnb-YvoXFmy8/edit?gid=1766497510#gid=1766497510"
)
SU_CHAR_DELAY      = 2.0    # per-character typing delay in the eDAS search box
                             # — minimum 2 seconds between each keystroke
SU_TRIO_PAUSE      = 10.0   # extra pause after every 3rd character typed (10s)
SU_SPACE_SETTLE    = 1.0    # pause before the trailing space after a bridge no.
SU_RESULT_WAIT     = 20.0   # max seconds to poll for the results table to settle
SU_MIN_RESULT_WAIT = 10.0   # always allow at least this long for results to appear
# Second Check uses even longer delays to give slow pages more time
SU2_CHAR_DELAY     = 3.0    # per-character delay for second check
SU2_TRIO_PAUSE     = 15.0   # extra pause after every 3rd character (second check)
SU2_RESULT_WAIT    = 25.0   # max seconds to poll (second check)
SU2_MIN_RESULT_WAIT= 15.0   # minimum settle time (second check)
SU_MAX_RETRIES     = 3
SU_ROW_START       = 5      # first data row in the sheet (row 4 is the header)
SU_COL_BRNO        = "B"
SU_COL_DRAWING_ID  = "C"
SU_COL_GAD_SUBMIT  = "F"
SU_COL_STAGE       = "G"
SU_COL_DESIGN_SEC  = "H"
SU_COL_CBE_OFFICE  = "I"
SU_COL_REMARKS     = "J"


def _su_edge_profile_dir() -> str:
    """A dedicated, isolated Edge profile just for this automation — separate
    from the user's real everyday profile, so it never opens their normal
    startup tabs/homepage/extensions and never conflicts with their regular
    Edge being open. It's persistent on disk, so Google sign-in here only
    ever needs to happen once."""
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    path = os.path.join(base, "BES", "automation_profile")
    os.makedirs(path, exist_ok=True)
    return path


class StatusUpdationWorker(QThread):
    """Walks every Br.No already listed in the Google Sheet, looks it up in
    eDAS All Drawings, and fills in Drawing ID / Work Flow Stage / Design
    Section / CBE-Office / Remarks accordingly. Runs until it reaches the
    last populated row, stop() is called, or the browser is closed."""

    log      = pyqtSignal(str, str)
    progress = pyqtSignal(int, int)   # current row, last row
    stopped  = pyqtSignal(str)

    def __init__(self, second_check=False):
        super().__init__()
        self._stop_evt = threading.Event()
        self.driver = None
        self._edas_handle = None
        self._sheet_handle = None
        self._second_check = second_check
        # Use longer delays for second check
        if second_check:
            self._char_delay = SU2_CHAR_DELAY
            self._trio_pause = SU2_TRIO_PAUSE

    def stop(self):
        self._stop_evt.set()

    def _log(self, msg, level="info"):
        self.log.emit(msg, level)

    # ── lifecycle ──────────────────────────────────────────────────────
    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            import traceback
            self._log(f"Fatal error: {e}", "err")
            print(traceback.format_exc())
            self.stopped.emit("error")
        finally:
            try:
                if self.driver:
                    self.driver.quit()
            except Exception:
                pass

    def _open_browser(self) -> bool:
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options as EdgeOptions

        opts = EdgeOptions()
        opts.add_experimental_option("detach", True)
        opts.add_argument(f"--user-data-dir={_su_edge_profile_dir()}")
        opts.add_argument("--profile-directory=Default")
        # Strip the fingerprints Google's login page uses to flag/block an
        # automated browser — this (not reusing a real profile) is the
        # actual fix for the "browser may not be secure" block.
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--disable-blink-features=AutomationControlled")
        # Suppress Edge's "restore pages?" crash-recovery bubble — after an
        # unclean shutdown it otherwise steals focus from new tabs and can
        # make them die before Selenium can drive them.
        opts.add_argument("--hide-crash-restore-bubble")
        try:
            self.driver = webdriver.Edge(options=opts)
        except Exception as e:
            self._log(f"⚠ Could not launch the automation browser: {e}", "err")
            return False
        self.driver.set_window_size(1400, 900)
        self._edas_handle = self.driver.current_window_handle
        _edas_minimize(self.driver)   # minimized from the start — never on-screen
        self._log("🌐 Edge launched (isolated profile, minimized).", "ok")
        return True

    def _open_sheet_tab(self):
        self.driver.switch_to.new_window('tab')
        self._sheet_handle = self.driver.current_window_handle
        self.driver.get(GOOGLE_SHEET_URL)
        time.sleep(3)
        if "accounts.google.com" in self.driver.current_url:
            try:
                self.driver.maximize_window()   # visible only for this one-time step
            except Exception:
                pass
            self._log("👤 One-time Google sign-in needed — please sign in inside "
                       "the automated Edge window. This is saved permanently after "
                       "today; it will minimize itself once you're signed in.", "warn")
            waited = 0
            while "accounts.google.com" in self.driver.current_url and waited < 300:
                if self._stop_evt.is_set():
                    return False
                time.sleep(2); waited += 2
            if "accounts.google.com" in self.driver.current_url:
                self._log("⚠ Timed out waiting for Google sign-in.", "err")
                return False
            self._log("✅ Signed in — this won't be needed again.", "ok")
            time.sleep(2)
            _edas_minimize(self.driver)
        self._log("📊 Sheet opened.", "ok")
        return True

    # ── eDAS: All Drawings search ────────────────────────────────────────
    def _goto_all_drawings(self):
        from selenium.webdriver.common.by import By
        try:
            if "all" in self.driver.current_url.lower() or \
               self.driver.find_elements(By.XPATH, "//input[contains(@placeholder,'Keyword')]"):
                return True
        except Exception:
            pass
        try:
            nav = self.driver.find_element(By.XPATH, "//*[contains(text(),'All Drawings')]")
            nav.click()
            time.sleep(2)
            return True
        except Exception as e:
            self._log(f"⚠ Could not open All Drawings: {e}", "err")
            return False

    def _type_slowly(self, element, text, trailing_space=False):
        """Very deliberate typing pace: configurable delay between characters,
        plus an extra pause after every third character — eDAS's live
        search-as-you-type drops keystrokes when it can't keep up.
        After trailing space, waits for results or 10s whichever is earliest."""
        element.clear()
        char_delay = getattr(self, '_char_delay', SU_CHAR_DELAY)
        trio_pause = getattr(self, '_trio_pause', SU_TRIO_PAUSE)
        for i, ch in enumerate(text):
            element.send_keys(ch)
            time.sleep(char_delay)
            if (i + 1) % 3 == 0 and i + 1 < len(text):
                self._log(f"  ⏳ Pausing {trio_pause:.0f}s after {(i+1)} characters…", "info")
                time.sleep(trio_pause)
        if trailing_space:
            time.sleep(SU_SPACE_SETTLE)
            element.send_keys(" ")
            # After trailing space, wait for page to load or 10 seconds, whichever is earliest
            self._log("  ⏳ Waiting for search results after space…", "info")
            from selenium.webdriver.common.by import By
            settled = False
            for waited in range(10):
                time.sleep(1.0)
                try:
                    rows = self.driver.find_elements(By.XPATH, "//table//tbody/tr")
                    if len(rows) > 0:
                        settled = True
                        self._log(f"  ✅ Results loaded after {waited+1}s.", "ok")
                        break
                except Exception:
                    pass
            if not settled:
                self._log("  ⏳ 10s timeout reached, proceeding.", "warn")
        time.sleep(1.0)  # let the results table start updating

    def _wait_results_settled(self):
        """eDAS's search-as-you-type needs a moment to catch up — poll the
        row count until it stops changing (or timeout). Uses longer waits
        for second_check mode."""
        from selenium.webdriver.common.by import By
        result_wait = SU2_RESULT_WAIT if self._second_check else SU_RESULT_WAIT
        min_wait = SU2_MIN_RESULT_WAIT if self._second_check else SU_MIN_RESULT_WAIT
        last_count, stable_ticks = -1, 0
        waited = 0.0
        while waited < result_wait:
            try:
                count = len(self.driver.find_elements(By.XPATH, "//table//tbody/tr"))
            except Exception:
                count = 0
            if count == last_count:
                stable_ticks += 1
                if stable_ticks >= 2:
                    return
            else:
                stable_ticks = 0
            last_count = count
            time.sleep(0.5); waited += 0.5
        # Even if the row count looked stable early, give the grid the full
        # minimum window to surface late-arriving results.
        if waited < min_wait:
            time.sleep(min_wait - waited)

    def _extract_result_rows(self):
        """Parses the visible All Drawings table. Column order assumed from
        the screenshots: Drawing ID, Description, Name Of Work, Workflow
        Name, Project Name, Drawing Details, Workflow Stage, Latest
        Activity, Actions (eye icon)."""
        from selenium.webdriver.common.by import By
        rows = []
        try:
            trs = self.driver.find_elements(By.XPATH, "//table//tbody/tr")
        except Exception:
            return rows
        for tr in trs:
            try:
                tds = tr.find_elements(By.TAG_NAME, "td")
                if len(tds) < 8:
                    continue
                drawing_id = tds[1].text.strip()
                description = tds[2].text.strip()
                name_of_work = tds[3].text.strip()
                workflow_name = tds[4].text.strip()
                project_name = tds[5].text.strip()
                stage = tds[7].text.strip()
                latest_activity = tds[8].text.strip() if len(tds) > 8 else ""
                eye_el = None
                try:
                    eye_el = tr.find_element(By.XPATH, ".//button|.//*[name()='svg']")
                except Exception:
                    pass
                rows.append({
                    "drawing_id": drawing_id, "description": description,
                    "name_of_work": name_of_work, "workflow_name": workflow_name,
                    "project_name": project_name, "stage": stage,
                    "latest_activity": latest_activity, "row_el": tr, "eye_el": eye_el,
                })
            except Exception:
                continue
        return rows

    def _search_edas(self, query, trailing_space=False):
        from selenium.webdriver.common.by import By
        self.driver.switch_to.window(self._edas_handle)
        if not self._goto_all_drawings():
            return []
        try:
            box = self.driver.find_element(
                By.XPATH, "//input[contains(@placeholder,'Keyword')]")
        except Exception as e:
            self._log(f"⚠ Could not find the keyword search box: {e}", "err")
            return []
        self._type_slowly(box, query, trailing_space=trailing_space)
        self._wait_results_settled()
        return self._extract_result_rows()

    def _matches_keywords(self, row) -> bool:
        text = " ".join([row["drawing_id"], row["description"], row["name_of_work"],
                          row["workflow_name"], row["project_name"]]).lower()
        return "duu" in text and "dhne" in text and "sc" in text

    def _pick_row(self, rows, filter_keywords: bool):
        candidates = [r for r in rows if self._matches_keywords(r)] if filter_keywords else rows
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # tie-break: most recent Latest Activity text, best-effort string compare
        return sorted(candidates, key=lambda r: r["latest_activity"], reverse=True)[0]

    # ── eDAS: Members modal ──────────────────────────────────────────────
    def _read_members(self, row):
        """Clicks the row's eye icon, opens Members, parses badges like
        'CBE-SCR (Sunil Kumar Verma) (Approved)', then closes the modal.
        Returns a list of (role, name, status) tuples."""
        from selenium.webdriver.common.by import By
        members = []
        try:
            eye = row.get("eye_el") or row["row_el"].find_element(By.XPATH, ".//button")
            eye.click()
            time.sleep(1.5)
            tab = self.driver.find_element(By.XPATH, "//*[contains(text(),'Members')]")
            tab.click()
            time.sleep(1.0)
            badge_els = self.driver.find_elements(
                By.XPATH, "//*[contains(text(),'(') and contains(text(),')')]")
            pat = re.compile(r"([\w\-]+)\s*\(([^)]+)\)\s*\(([^)]+)\)")
            for el in badge_els:
                m = pat.search(el.text.strip())
                if m:
                    members.append((m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
            try:
                close_btn = self.driver.find_element(By.XPATH, "//button[contains(.,'Close')]")
                close_btn.click()
            except Exception:
                pass
        except Exception as e:
            self._log(f"⚠ Could not read Members panel: {e}", "warn")
        return members

    # ── Google Sheets ─────────────────────────────────────────────────────
    def _sheet_goto(self, cell_ref):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        self.driver.switch_to.window(self._sheet_handle)
        name_box = self.driver.find_element(By.ID, "t-name-box")
        name_box.click()
        name_box.send_keys(f"{Keys.CONTROL}a")
        name_box.send_keys(cell_ref)
        name_box.send_keys(Keys.ENTER)
        time.sleep(0.4)

    def _sheet_read(self, cell_ref) -> str:
        from selenium.webdriver.common.by import By
        self._sheet_goto(cell_ref)
        try:
            bar = self.driver.find_element(By.ID, "t-formula-bar-input")
            return (bar.text or bar.get_attribute("value") or "").strip()
        except Exception:
            return ""

    def _sheet_write(self, cell_ref, value):
        from selenium.webdriver.common.keys import Keys
        if not value:
            return
        self._sheet_goto(cell_ref)
        active = self.driver.switch_to.active_element
        text = ("'" + value) if value.startswith("=") else value
        active.send_keys(text)
        active.send_keys(Keys.ENTER)
        time.sleep(0.3)

    def _sheet_set_checkbox(self, cell_ref, checked: bool):
        from selenium.webdriver.common.keys import Keys
        self._sheet_goto(cell_ref)
        active = self.driver.switch_to.active_element
        active.send_keys("TRUE" if checked else "FALSE")
        active.send_keys(Keys.ENTER)
        time.sleep(0.3)

    def _find_last_row(self) -> int:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        self._sheet_goto(f"{SU_COL_BRNO}{SU_ROW_START}")
        name_box = self.driver.find_element(By.ID, "t-name-box")
        name_box.click()
        name_box.send_keys(f"{Keys.CONTROL}a")
        name_box.send_keys(f"{SU_COL_BRNO}{SU_ROW_START}")
        name_box.send_keys(Keys.ENTER)
        time.sleep(0.3)
        active = self.driver.switch_to.active_element
        active.send_keys(Keys.CONTROL, Keys.DOWN)
        time.sleep(0.4)
        ref = self.driver.find_element(By.ID, "t-name-box").get_attribute("value") or ""
        m = re.search(r"(\d+)$", ref)
        return int(m.group(1)) if m else SU_ROW_START

    # ── main loop ──────────────────────────────────────────────────────
    def _process_row(self, row_n: int, brno: str):
        """Search eDAS for one bridge number and write results back to its
        sheet row. Logic unchanged — extracted verbatim from the run loop so
        a mid-row failure can be recovered without losing the whole pass."""
        self._ensure_edas_session()
        existing_id = self._sheet_read(f"{SU_COL_DRAWING_ID}{row_n}")

        rows, attempts = [], 0
        picked = None
        while attempts < SU_MAX_RETRIES and not picked:
            if existing_id:
                rows = self._search_edas(existing_id, trailing_space=False)
                picked = self._pick_row(rows, filter_keywords=False)
            else:
                rows = self._search_edas(brno, trailing_space=True)
                picked = self._pick_row(rows, filter_keywords=True)
            attempts += 1
            if not picked:
                self._ensure_edas_session()

        if not picked:
            self._log(f"Br.No {brno}: no drawing found — clearing GAD-submitted tick.", "warn")
            self._sheet_set_checkbox(f"{SU_COL_GAD_SUBMIT}{row_n}", False)
            return

        short_id = _short_drawing_id(picked["drawing_id"])
        self._sheet_write(f"{SU_COL_DRAWING_ID}{row_n}", short_id)
        stage = picked["stage"]
        self._sheet_write(f"{SU_COL_STAGE}{row_n}", stage)
        stage_l = stage.lower()

        members = []
        if "chq" in stage_l or "hq" in stage_l:
            self.driver.switch_to.window(self._edas_handle)
            members = self._read_members(picked)
            names_joined = " ; ".join(f"{r} ({n})" for r, n, _ in members)

            if "chq" in stage_l:
                self._sheet_write(f"{SU_COL_DESIGN_SEC}{row_n}", names_joined)

            if "hq" in stage_l:
                self._sheet_write(f"{SU_COL_CBE_OFFICE}{row_n}",
                                   f"{stage} | {names_joined}")

            if "hq-approval1" in stage_l.replace(" ", "").replace("_", "-"):
                if members and all(s.lower() == "approved" for _, _, s in members):
                    self._sheet_write(f"{SU_COL_REMARKS}{row_n}", "CBE-Approved")

        self._log(f"Br.No {brno}: {picked['drawing_id']} → {stage}", "ok")

    def _recover_windows(self) -> bool:
        """A tab/window died mid-run — re-anchor our handles to whatever Edge
        still has open and restore whichever page is missing. Returns False
        only when the browser itself is gone."""
        from selenium.common.exceptions import WebDriverException
        try:
            handles = list(self.driver.window_handles)
        except WebDriverException:
            return False   # browser process gone entirely

        def valid(h):
            try:
                self.driver.switch_to.window(h)
                self.driver.title
                return True
            except Exception:
                return False

        handles = [h for h in handles if valid(h)]
        if not handles:
            return False

        if self._edas_handle not in handles:
            self._edas_handle = None
        if self._sheet_handle not in handles or self._sheet_handle == self._edas_handle:
            self._sheet_handle = None

        if not self._edas_handle:
            self._edas_handle = handles[0]
        if not self._sheet_handle:
            if not self._open_sheet_tab():
                return False

        self.driver.switch_to.window(self._edas_handle)
        _edas_login(self.driver, self._log)
        return True

    def _ensure_edas_session(self):
        self.driver.switch_to.window(self._edas_handle)
        if not _edas_is_logged_in(self.driver):
            self._log("🔁 eDAS session dropped — logging in again…", "warn")
            _edas_login(self.driver, self._log)

    def _run_inner(self):
        if not self._open_browser():
            self.stopped.emit("error")
            return
        # Login with retries — a misread captcha or a crashed tab shouldn't
        # abort the whole run before it even starts.
        for attempt in range(1, 4):
            try:
                if _edas_login(self.driver, self._log):
                    break
            except Exception as e:
                self._log(f"⚠ Login attempt {attempt} failed ({type(e).__name__}).", "warn")
            if attempt < 3:
                time.sleep(3)
                try:                      # if the tab died mid-login, open a fresh one
                    _ = self.driver.current_url
                except Exception:
                    self.driver.switch_to.new_window("tab")
                    self._edas_handle = self.driver.current_window_handle
        if not self._open_sheet_tab():
            self.stopped.emit("error")
            return

        last_row = self._find_last_row()
        self._log(f"📋 Found bridge rows {SU_ROW_START}–{last_row}.", "info")

        mode_label = "Second Check" if self._second_check else "Status Updation"
        self._log(f"📋 {mode_label}: Scanning rows {SU_ROW_START}–{last_row}.", "info")

        skipped_count = 0
        processed_count = 0
        for row_n in range(SU_ROW_START, last_row + 1):
            if self._stop_evt.is_set():
                break
            if not _edas_browser_alive(self.driver):
                self._log("🛑 Browser closed — stopping.", "warn")
                self.stopped.emit("browser_closed")
                return

            self.progress.emit(row_n, last_row)
            brno = self._sheet_read(f"{SU_COL_BRNO}{row_n}")
            if not brno:
                continue

            # Second Check: only process rows WITHOUT a GAD submitted tick
            if self._second_check:
                gad_tick = self._sheet_read(f"{SU_COL_GAD_SUBMIT}{row_n}")
                if gad_tick.strip().upper() in ("TRUE", "YES", "✓", "T"):
                    skipped_count += 1
                    continue

            try:
                self._process_row(row_n, brno)
                processed_count += 1
            except Exception as e:
                # One dead tab shouldn't kill a 60-bridge run — recover and
                # move on; only abort if the browser itself is gone.
                self._log(
                    f"⚠ Br.No {brno}: {type(e).__name__} mid-row — attempting recovery…",
                    "warn",
                )
                if not self._recover_windows():
                    raise

        if self._second_check:
            self._log(
                f"✅ Second Check complete — processed {processed_count} missing drawing(s), "
                f"skipped {skipped_count} already-submitted.", "ok"
            )
        else:
            self._log("⏹ Status Updation stopped." if self._stop_evt.is_set()
                       else "✅ Status Updation complete.", "info")
        self.stopped.emit("user_stop" if self._stop_evt.is_set() else "done")


class ScrutinyPanel(QWidget):
    def __init__(self):
        super().__init__()
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        cont = QWidget()
        lay  = QVBoxLayout(cont)
        lay.setContentsMargins(32,28,32,32)
        lay.setSpacing(0)
        scroll.setWidget(cont)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        hdr = QLabel("Scrutiny"); hdr.setObjectName("panelTitle")
        lay.addWidget(hdr)
        sub = QLabel("Automated GAD drawing scrutiny against engineering standards.")
        sub.setObjectName("panelSubtitle"); sub.setWordWrap(True)
        lay.addWidget(sub); lay.addSpacing(24)

        # ── VC Calculator card ──────────────────────────────────────────────
        card = QFrame(); card.setObjectName("card")
        card.setStyleSheet(
            f"QFrame#card{{background:{COLORS['card_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:10px;}}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24,20,24,20); cl.setSpacing(14)

        title_row = QHBoxLayout()
        icon_lbl = QLabel("📏")
        icon_lbl.setFont(QFont("Segoe UI", 18))
        title_row.addWidget(icon_lbl)
        title_col = QVBoxLayout(); title_col.setSpacing(0)
        t1 = QLabel("Vertical Clearance Calculator")
        t1.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        t1.setStyleSheet(f"color:{COLORS['text_primary']};")
        t2 = QLabel("Enter discharge (cumecs) — VC required is computed automatically")
        t2.setFont(QFont("Segoe UI", 9))
        t2.setStyleSheet(f"color:{COLORS['text_muted']};")
        title_col.addWidget(t1); title_col.addWidget(t2)
        title_row.addLayout(title_col); title_row.addStretch()
        cl.addLayout(title_row)

        # Input row
        in_row = QHBoxLayout(); in_row.setSpacing(10)
        in_lbl = QLabel("Discharge:")
        in_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        in_lbl.setStyleSheet(f"color:{COLORS['text_secondary']};")
        in_row.addWidget(in_lbl)

        self._discharge_input = QLineEdit()
        self._discharge_input.setPlaceholderText("e.g. 145.5")
        self._discharge_input.setFixedWidth(160)
        self._discharge_input.setFixedHeight(34)
        self._discharge_input.setFont(QFont("Segoe UI", 11))
        self._discharge_input.setStyleSheet(
            f"QLineEdit{{background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;"
            f"padding:0 10px;color:{COLORS['text_primary']};}}"
            f"QLineEdit:focus{{border:1px solid {ACCENT};}}")
        self._discharge_input.returnPressed.connect(self._on_calc)
        in_row.addWidget(self._discharge_input)

        unit_lbl = QLabel("cumecs")
        unit_lbl.setFont(QFont("Segoe UI", 10))
        unit_lbl.setStyleSheet(f"color:{COLORS['text_muted']};")
        in_row.addWidget(unit_lbl)

        calc_btn = QPushButton("Calculate VC")
        calc_btn.setFixedHeight(34)
        calc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        calc_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        calc_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#06241C;"
            f"border:none;border-radius:6px;padding:0 18px;}}"
            f"QPushButton:hover{{background:{COLORS.get('accent_hover', ACCENT)};}}")
        calc_btn.clicked.connect(self._on_calc)
        in_row.addWidget(calc_btn)
        in_row.addStretch()
        cl.addLayout(in_row)

        # Result display
        self._result_frame = QFrame()
        self._result_frame.setVisible(False)
        self._result_frame.setStyleSheet(
            f"QFrame{{background:{COLORS.get('accent_glow', COLORS['input_bg'])};"
            f"border:1px solid {ACCENT};border-radius:8px;}}")
        rf_lay = QVBoxLayout(self._result_frame)
        rf_lay.setContentsMargins(18,14,18,14); rf_lay.setSpacing(6)

        result_top = QHBoxLayout()
        self._vc_value_lbl = QLabel("—")
        self._vc_value_lbl.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        self._vc_value_lbl.setStyleSheet(f"color:{ACCENT};")
        result_top.addWidget(self._vc_value_lbl)
        unit2 = QLabel("mm")
        unit2.setFont(QFont("Segoe UI", 13))
        unit2.setStyleSheet(f"color:{COLORS['text_muted']};")
        unit2.setAlignment(Qt.AlignmentFlag.AlignBottom)
        result_top.addWidget(unit2)
        result_top.addStretch()
        rf_lay.addLayout(result_top)

        vc_required_lbl = QLabel("VERTICAL CLEARANCE REQUIRED")
        vc_required_lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        vc_required_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};letter-spacing:1px;")
        rf_lay.addWidget(vc_required_lbl)

        self._explain_lbl = QLabel("")
        self._explain_lbl.setFont(QFont("Consolas", 9))
        self._explain_lbl.setWordWrap(True)
        self._explain_lbl.setStyleSheet(f"color:{COLORS['text_secondary']};")
        rf_lay.addWidget(self._explain_lbl)

        cl.addWidget(self._result_frame)

        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet("color:#F85149;font-size:11px;")
        self._error_lbl.setVisible(False)
        cl.addWidget(self._error_lbl)

        lay.addWidget(card)
        lay.addSpacing(16)

        # ── Reference table card ────────────────────────────────────────────
        ref_card = QFrame()
        ref_card.setStyleSheet(
            f"QFrame{{background:{COLORS['card_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:10px;}}")
        ref_lay = QVBoxLayout(ref_card)
        ref_lay.setContentsMargins(24,18,24,18); ref_lay.setSpacing(10)

        ref_title = QLabel("📋 Reference Table — Discharge vs Vertical Clearance")
        ref_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        ref_title.setStyleSheet(f"color:{COLORS['text_primary']};")
        ref_lay.addWidget(ref_title)

        table_html = f"""
        <table style='width:100%;border-collapse:collapse;font-family:Segoe UI;font-size:12px;'>
          <tr style='background:{COLORS['input_bg']};'>
            <th style='padding:8px 12px;text-align:left;color:{COLORS['text_muted']};
              border-bottom:2px solid {COLORS['border']};font-size:10px;'>
              DISCHARGE (cumecs)</th>
            <th style='padding:8px 12px;text-align:left;color:{COLORS['text_muted']};
              border-bottom:2px solid {COLORS['border']};font-size:10px;'>
              VERTICAL CLEARANCE (mm)</th>
          </tr>
          <tr><td style='padding:7px 12px;color:{COLORS['text_secondary']};
            border-bottom:1px solid {COLORS['border']};'>0 – 30</td>
              <td style='padding:7px 12px;color:{COLORS['text_primary']};
            border-bottom:1px solid {COLORS['border']};font-weight:600;'>600</td></tr>
          <tr><td style='padding:7px 12px;color:{COLORS['text_secondary']};
            border-bottom:1px solid {COLORS['border']};'>31 – 300</td>
              <td style='padding:7px 12px;color:{COLORS['text_primary']};
            border-bottom:1px solid {COLORS['border']};font-weight:600;'>
            600 – 1200 (Pro-rata)</td></tr>
          <tr><td style='padding:7px 12px;color:{COLORS['text_secondary']};
            border-bottom:1px solid {COLORS['border']};'>301 – 3000</td>
              <td style='padding:7px 12px;color:{COLORS['text_primary']};
            border-bottom:1px solid {COLORS['border']};font-weight:600;'>1500</td></tr>
          <tr><td style='padding:7px 12px;color:{COLORS['text_secondary']};'>
            Above 3000</td>
              <td style='padding:7px 12px;color:{COLORS['text_primary']};
            font-weight:600;'>1800</td></tr>
        </table>
        """
        ref_view = QTextEdit()
        ref_view.setHtml(table_html)
        ref_view.setReadOnly(True)
        ref_view.setFixedHeight(190)
        ref_view.setStyleSheet(
            f"QTextEdit{{background:transparent;border:none;}}")
        ref_lay.addWidget(ref_view)

        lay.addWidget(ref_card)
        lay.addSpacing(16)

        # ── Gradient Checker card ───────────────────────────────────────────
        grad_card = QFrame(); grad_card.setObjectName("card")
        grad_card.setStyleSheet(
            f"QFrame#card{{background:{COLORS['card_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:10px;}}")
        gl = QVBoxLayout(grad_card)
        gl.setContentsMargins(24, 20, 24, 20); gl.setSpacing(14)

        g_title_row = QHBoxLayout()
        g_icon = QLabel("📈"); g_icon.setFont(QFont("Segoe UI", 18))
        g_title_row.addWidget(g_icon)
        g_title_col = QVBoxLayout(); g_title_col.setSpacing(0)
        g_t1 = QLabel("Gradient Checker  (EXG vs PRO)")
        g_t1.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        g_t1.setStyleSheet(f"color:{COLORS['text_primary']};")
        g_t2 = QLabel("Drop a GAD/Site-Plan PDF — chainage, RL and gradient labels are "
                       "auto-recognised and gradients computed for EXG (black) & PRO (red)")
        g_t2.setFont(QFont("Segoe UI", 9)); g_t2.setWordWrap(True)
        g_t2.setStyleSheet(f"color:{COLORS['text_muted']};")
        g_title_col.addWidget(g_t1); g_title_col.addWidget(g_t2)
        g_title_row.addLayout(g_title_col); g_title_row.addStretch()
        gl.addLayout(g_title_row)

        self._grad_zone = DropZone("GAD / Site Plan PDF", compact=True)
        self._grad_zone.file_dropped.connect(lambda p: setattr(self, "_grad_path", p))
        gl.addWidget(self._grad_zone)

        g_run_btn = QPushButton("▶  Check Gradients")
        g_run_btn.setFixedHeight(36)
        g_run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        g_run_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        g_run_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#06241C;"
            f"border:none;border-radius:6px;}}"
            f"QPushButton:hover{{background:{COLORS.get('accent_hover', ACCENT)};}}")
        g_run_btn.clicked.connect(self._on_gradient_check)
        gl.addWidget(g_run_btn)

        self._grad_error_lbl = QLabel("")
        self._grad_error_lbl.setStyleSheet("color:#F85149;font-size:11px;")
        self._grad_error_lbl.setVisible(False)
        gl.addWidget(self._grad_error_lbl)

        self._grad_result_view = QTextEdit()
        self._grad_result_view.setReadOnly(True)
        self._grad_result_view.setVisible(False)
        self._grad_result_view.setMinimumHeight(280)
        self._grad_result_view.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:8px;}}")
        gl.addWidget(self._grad_result_view)

        lay.addWidget(grad_card)
        self._grad_path = ""
        lay.addSpacing(16)

        # ── Corner-Block RL Check card ──────────────────────────────────────
        cb_card = QFrame(); cb_card.setObjectName("card")
        cb_card.setStyleSheet(
            f"QFrame#card{{background:{COLORS['card_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:10px;}}")
        cbl = QVBoxLayout(cb_card)
        cbl.setContentsMargins(24, 20, 24, 20); cbl.setSpacing(14)

        cb_title_row = QHBoxLayout()
        cb_icon = QLabel("📐"); cb_icon.setFont(QFont("Segoe UI", 18))
        cb_title_row.addWidget(cb_icon)
        cb_title_col = QVBoxLayout(); cb_title_col.setSpacing(0)
        cb_t1 = QLabel("Corner-Block RL Check  (¢ OF BRIDGE title-block)")
        cb_t1.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        cb_t1.setStyleSheet(f"color:{COLORS['text_primary']};")
        cb_t2 = QLabel("Finds the CH:/RL: points either side of the bridge centre chainage "
                        "and, using ONE shared near-bridge gradient per colour, projects "
                        "each side's RL onto the bridge — flags LEFT vs RIGHT mismatches "
                        "for EXG (black) & PRO (red)")
        cb_t2.setFont(QFont("Segoe UI", 9)); cb_t2.setWordWrap(True)
        cb_t2.setStyleSheet(f"color:{COLORS['text_muted']};")
        cb_title_col.addWidget(cb_t1); cb_title_col.addWidget(cb_t2)
        cb_title_row.addLayout(cb_title_col); cb_title_row.addStretch()
        cbl.addLayout(cb_title_row)

        self._cb_zone = DropZone(
            "GAD / Site Plan — PDF or Image", compact=True,
            accept_exts=[".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"])
        self._cb_zone.file_dropped.connect(lambda p: setattr(self, "_cb_path", p))
        cbl.addWidget(self._cb_zone)

        cb_run_btn = QPushButton("▶  Check Corner-Block RLs")
        cb_run_btn.setFixedHeight(36)
        cb_run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cb_run_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        cb_run_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#06241C;"
            f"border:none;border-radius:6px;}}"
            f"QPushButton:hover{{background:{COLORS.get('accent_hover', ACCENT)};}}")
        cb_run_btn.clicked.connect(self._on_corner_block_check)
        cbl.addWidget(cb_run_btn)

        self._cb_error_lbl = QLabel("")
        self._cb_error_lbl.setStyleSheet("color:#F85149;font-size:11px;")
        self._cb_error_lbl.setVisible(False)
        cbl.addWidget(self._cb_error_lbl)

        self._cb_result_view = QTextEdit()
        self._cb_result_view.setReadOnly(True)
        self._cb_result_view.setVisible(False)
        self._cb_result_view.setMinimumHeight(240)
        self._cb_result_view.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:8px;}}")
        cbl.addWidget(self._cb_result_view)

        # ── Manual-entry fallback (shown only when auto-detection is
        #    incomplete) — pre-filled with whatever WAS auto-detected,
        #    blank for whatever wasn't, so the user only has to type the
        #    missing figures off the drawing. The near-bridge gradient is
        #    ONE shared value per colour (same ratio + Rise/Fall on both
        #    sides — see backend note), not one per side.
        self._cb_manual_frame = QFrame()
        self._cb_manual_frame.setVisible(False)
        self._cb_manual_frame.setStyleSheet(
            f"QFrame{{background:{COLORS['input_bg']};border:1px solid {COLORS['border']};"
            f"border-radius:8px;}}")
        mfl = QVBoxLayout(self._cb_manual_frame)
        mfl.setContentsMargins(16, 14, 16, 14); mfl.setSpacing(8)

        mf_title = QLabel("✏  Couldn't auto-trace everything — fill in the rest")
        mf_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        mf_title.setStyleSheet(f"color:{COLORS['text_primary']};")
        mfl.addWidget(mf_title)

        self._cb_edits: dict[str, QLineEdit] = {}

        def add_row(parent_lay, label_text, key, width=110, placeholder=""):
            row = QHBoxLayout()
            lbl = QLabel(label_text); lbl.setFixedWidth(170)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setStyleSheet(f"color:{COLORS['text_muted']};")
            row.addWidget(lbl)
            ed = QLineEdit(); ed.setFixedWidth(width)
            ed.setPlaceholderText(placeholder)
            ed.setFont(QFont("Segoe UI", 9))
            row.addWidget(ed)
            row.addStretch()
            parent_lay.addLayout(row)
            self._cb_edits[key] = ed

        add_row(mfl, "Bridge No.", "bridge_no", 140, "e.g. 471")
        add_row(mfl, "Target CH (bridge centre)", "ch_target", 140, "e.g. 262606.020")

        for cat, cat_label in (("EXG", "EXG. (black)"), ("PRO", "PRO. (red)")):
            sub = QLabel(cat_label)
            sub.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            sub.setStyleSheet(f"color:{COLORS['text_primary']};margin-top:6px;")
            mfl.addWidget(sub)

            for side, side_label in (("LEFT", "  LEFT  —  CH / RL"),
                                       ("RIGHT", "  RIGHT —  CH / RL")):
                row = QHBoxLayout(); row.setSpacing(6)
                lbl = QLabel(side_label); lbl.setFixedWidth(120)
                lbl.setFont(QFont("Segoe UI", 9))
                lbl.setStyleSheet(f"color:{COLORS['text_muted']};")
                row.addWidget(lbl)
                for field, ph, w in (("ch_start", "CH e.g. 282460.00", 130),
                                      ("rl_start", "RL e.g. 351.889", 110)):
                    ed = QLineEdit(); ed.setPlaceholderText(ph); ed.setFixedWidth(w)
                    ed.setFont(QFont("Segoe UI", 9))
                    row.addWidget(ed)
                    self._cb_edits[f"{cat}_{side}.{field}"] = ed
                row.addStretch()
                mfl.addLayout(row)

            grow = QHBoxLayout(); grow.setSpacing(6)
            glbl = QLabel("  Gradient (shared, both sides)"); glbl.setFixedWidth(200)
            glbl.setFont(QFont("Segoe UI", 9))
            glbl.setStyleSheet(f"color:{COLORS['text_muted']};")
            grow.addWidget(glbl)
            ed_dir = QLineEdit(); ed_dir.setPlaceholderText("R/F"); ed_dir.setFixedWidth(40)
            ed_dir.setFont(QFont("Segoe UI", 9))
            grow.addWidget(ed_dir)
            ed_ratio = QLineEdit(); ed_ratio.setPlaceholderText("1 in N e.g. 238")
            ed_ratio.setFixedWidth(110)
            ed_ratio.setFont(QFont("Segoe UI", 9))
            grow.addWidget(ed_ratio)
            grow.addStretch()
            mfl.addLayout(grow)
            self._cb_edits[f"{cat}.dir"] = ed_dir
            self._cb_edits[f"{cat}.ratio"] = ed_ratio

        cb_manual_btn = QPushButton("✓  Compute with these values")
        cb_manual_btn.setFixedHeight(32)
        cb_manual_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cb_manual_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cb_manual_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{ACCENT};"
            f"border:1px solid {ACCENT};border-radius:6px;margin-top:6px;}}"
            f"QPushButton:hover{{background:{COLORS['accent_glow']};}}")
        cb_manual_btn.clicked.connect(self._on_corner_block_manual_compute)
        mfl.addWidget(cb_manual_btn)

        cbl.addWidget(self._cb_manual_frame)

        lay.addWidget(cb_card)
        self._cb_path = ""
        lay.addSpacing(16)

        # ── Loop Interface card ─────────────────────────────────────────────
        li_card = QFrame(); li_card.setObjectName("card")
        li_card.setStyleSheet(
            f"QFrame#card{{background:{COLORS['card_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:10px;}}")
        lil = QVBoxLayout(li_card)
        lil.setContentsMargins(24, 20, 24, 20); lil.setSpacing(14)

        li_title_row = QHBoxLayout()
        li_icon = QLabel("🔁"); li_icon.setFont(QFont("Segoe UI", 18))
        li_title_row.addWidget(li_icon)
        li_title_col = QVBoxLayout(); li_title_col.setSpacing(0)
        li_t1 = QLabel("Loop Interface  (eDAS auto-login)")
        li_t1.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        li_t1.setStyleSheet(f"color:{COLORS['text_primary']};")
        li_t2 = QLabel("Opens eDAS in Edge, logs in, solves the arithmetic captcha, "
                        "and keeps the session alive with a refresh every "
                        f"{LI_REFRESH_SEC}s — re-logging in automatically on logout")
        li_t2.setFont(QFont("Segoe UI", 9)); li_t2.setWordWrap(True)
        li_t2.setStyleSheet(f"color:{COLORS['text_muted']};")
        li_title_col.addWidget(li_t1); li_title_col.addWidget(li_t2)
        li_title_row.addLayout(li_title_col); li_title_row.addStretch()
        lil.addLayout(li_title_row)

        li_btn_row = QHBoxLayout(); li_btn_row.setSpacing(10)
        self._li_start_btn = QPushButton("▶  Start LI")
        self._li_start_btn.setFixedHeight(36)
        self._li_start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._li_start_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._li_start_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#06241C;"
            f"border:none;border-radius:6px;padding:0 18px;}}"
            f"QPushButton:hover{{background:{COLORS.get('accent_hover', ACCENT)};}}")
        self._li_start_btn.clicked.connect(self._on_li_start)
        li_btn_row.addWidget(self._li_start_btn)

        self._li_stop_btn = QPushButton("⏹  Stop LI")
        self._li_stop_btn.setFixedHeight(36)
        self._li_stop_btn.setEnabled(False)
        self._li_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._li_stop_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._li_stop_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['text_secondary']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;padding:0 18px;}}"
            f"QPushButton:hover:enabled{{border:1px solid {COLORS['error']};color:{COLORS['error']};}}"
            f"QPushButton:disabled{{color:{COLORS['text_muted']};}}")
        self._li_stop_btn.clicked.connect(self._on_li_stop)
        li_btn_row.addWidget(self._li_stop_btn)
        li_btn_row.addStretch()
        lil.addLayout(li_btn_row)

        self._li_log_view = QTextEdit()
        self._li_log_view.setReadOnly(True)
        self._li_log_view.setFixedHeight(140)
        self._li_log_view.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:8px;"
            f"font-family:Consolas;font-size:10px;}}")
        lil.addWidget(self._li_log_view)

        lay.addWidget(li_card)
        self._li_worker = None
        lay.addSpacing(16)

        # ── Status Updation card ────────────────────────────────────────────
        su_card = QFrame(); su_card.setObjectName("card")
        su_card.setStyleSheet(
            f"QFrame#card{{background:{COLORS['card_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:10px;}}")
        sul = QVBoxLayout(su_card)
        sul.setContentsMargins(24, 20, 24, 20); sul.setSpacing(14)

        su_title_row = QHBoxLayout()
        su_icon = QLabel("🗂️"); su_icon.setFont(QFont("Segoe UI", 18))
        su_title_row.addWidget(su_icon)
        su_title_col = QVBoxLayout(); su_title_col.setSpacing(0)
        su_t1 = QLabel("Status Updation  (eDAS → Google Sheet)")
        su_t1.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        su_t1.setStyleSheet(f"color:{COLORS['text_primary']};")
        su_t2 = QLabel("Walks every Br.No in the sheet, looks it up in All Drawings, "
                        "and fills in Drawing ID / Work Flow Stage / Design Section / "
                        "CBE-Office / Remarks")
        su_t2.setFont(QFont("Segoe UI", 9)); su_t2.setWordWrap(True)
        su_t2.setStyleSheet(f"color:{COLORS['text_muted']};")
        su_title_col.addWidget(su_t1); su_title_col.addWidget(su_t2)
        su_title_row.addLayout(su_title_col); su_title_row.addStretch()
        sul.addLayout(su_title_row)

        su_btn_row = QHBoxLayout(); su_btn_row.setSpacing(10)
        self._su_start_btn = QPushButton("▶  Start Status Updation")
        self._su_start_btn.setFixedHeight(36)
        self._su_start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._su_start_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._su_start_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#06241C;"
            f"border:none;border-radius:6px;padding:0 18px;}}"
            f"QPushButton:hover{{background:{COLORS.get('accent_hover', ACCENT)};}}")
        self._su_start_btn.clicked.connect(self._on_su_start)
        su_btn_row.addWidget(self._su_start_btn)

        self._su_second_check_btn = QPushButton("🔍  Second Check")
        self._su_second_check_btn.setFixedHeight(36)
        self._su_second_check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._su_second_check_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._su_second_check_btn.setToolTip(
            "Re-check only missing drawings (no tick in GAD Submitted column) "
            "with extra search time for slow-loading pages")
        self._su_second_check_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['text_primary']};"
            f"border:2px solid {ACCENT};border-radius:6px;padding:0 18px;}}"
            f"QPushButton:hover{{background:{COLORS['accent_glow']};}}")
        self._su_second_check_btn.clicked.connect(self._on_su_second_check)
        su_btn_row.addWidget(self._su_second_check_btn)

        self._su_stop_btn = QPushButton("⏹  Stop")
        self._su_stop_btn.setFixedHeight(36)
        self._su_stop_btn.setEnabled(False)
        self._su_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._su_stop_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._su_stop_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['text_secondary']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;padding:0 18px;}}"
            f"QPushButton:hover:enabled{{border:1px solid {COLORS['error']};color:{COLORS['error']};}}"
            f"QPushButton:disabled{{color:{COLORS['text_muted']};}}")
        self._su_stop_btn.clicked.connect(self._on_su_stop)
        su_btn_row.addWidget(self._su_stop_btn)

        self._su_progress_lbl = QLabel("")
        self._su_progress_lbl.setFont(QFont("Segoe UI", 9))
        self._su_progress_lbl.setStyleSheet(f"color:{COLORS['text_muted']};")
        su_btn_row.addWidget(self._su_progress_lbl)
        su_btn_row.addStretch()
        sul.addLayout(su_btn_row)

        self._su_log_view = QTextEdit()
        self._su_log_view.setReadOnly(True)
        self._su_log_view.setFixedHeight(140)
        self._su_log_view.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:8px;"
            f"font-family:Consolas;font-size:10px;}}")
        sul.addWidget(self._su_log_view)

        lay.addWidget(su_card)
        self._su_worker = None
        lay.addStretch()

    def _cb_prefill_manual(self, result: dict):
        """Pre-fills the manual-entry fields with whatever the auto-detector
        DID find, leaving the rest blank for the user to type in."""
        pages = result.get("pages", [])
        if not pages:
            return
        pr = pages[0]  # single-sheet tool — first page is the relevant one
        self._cb_edits["bridge_no"].setText(pr.get("bridge_no") or "")
        self._cb_edits["ch_target"].setText(
            f'{pr["ch_target"]:.3f}' if pr.get("ch_target") is not None else "")
        for key in _SIDE_KEYS:
            b = pr.get("ch_rl", {}).get(key) or {}
            self._cb_edits[f"{key}.ch_start"].setText(
                f'{b["ch_start"]:.3f}' if b.get("ch_start") is not None else "")
            self._cb_edits[f"{key}.rl_start"].setText(
                f'{b["rl_start"]:.3f}' if b.get("rl_start") is not None else "")
        for cat in _CAT_KEYS:
            g = pr.get("gradients", {}).get(cat) or {}
            self._cb_edits[f"{cat}.dir"].setText(g.get("dir") or "")
            self._cb_edits[f"{cat}.ratio"].setText(
                f'{g["ratio"]:.0f}' if g.get("ratio") is not None else "")

    def _cb_gather_manual(self) -> dict | None:
        """Reads the manual-entry fields into the `manual=` dict shape
        expected by run_corner_block_check(). Returns None (and sets the
        error label) if a filled-in number can't be parsed. The gradient
        (direction + ratio) is read ONCE per colour and shared by both
        LEFT and RIGHT — see the shared-gradient note in the backend."""
        def fnum(key):
            txt = self._cb_edits[key].text().strip().replace(",", "")
            if not txt:
                return None
            return float(txt)

        try:
            manual = {
                "bridge_no": self._cb_edits["bridge_no"].text().strip() or None,
                "ch_target": fnum("ch_target"),
                "ch_rl": {}, "gradients": {},
            }
            for key in _SIDE_KEYS:
                ch_start = fnum(f"{key}.ch_start")
                rl_start = fnum(f"{key}.rl_start")
                if ch_start is not None and rl_start is not None:
                    manual["ch_rl"][key] = {"ch_start": ch_start, "rl_start": rl_start}
            for cat in _CAT_KEYS:
                direction = self._cb_edits[f"{cat}.dir"].text().strip().upper() or None
                if direction and direction not in ("R", "F"):
                    self._cb_error_lbl.setText(
                        f"'{cat}' gradient direction must be R or F, got '{direction}'.")
                    self._cb_error_lbl.setVisible(True)
                    return None
                ratio = fnum(f"{cat}.ratio")
                if direction and ratio is not None:
                    manual["gradients"][cat] = {"dir": direction, "ratio": ratio}
            return manual
        except ValueError as e:
            self._cb_error_lbl.setText(f"Enter numbers for CH/RL/ratio fields ({e}).")
            self._cb_error_lbl.setVisible(True)
            return None

    def _on_corner_block_check(self):
        self._cb_error_lbl.setVisible(False)
        if not self._cb_path:
            self._cb_zone.setStyleSheet(
                f"border:2px dashed {COLORS['error']};border-radius:12px;")
            self._cb_error_lbl.setText("Drop or select a GAD PDF or image first.")
            self._cb_error_lbl.setVisible(True)
            return
        self._cb_zone.setStyleSheet("")
        try:
            result = run_corner_block_check(self._cb_path)
        except Exception as e:
            import traceback
            self._cb_error_lbl.setText(f"Could not read corner-block: {e}")
            self._cb_error_lbl.setVisible(True)
            self._cb_result_view.setVisible(False)
            self._cb_manual_frame.setVisible(False)
            print(traceback.format_exc())
            return

        result_html = _build_corner_block_html(result)
        self._cb_result_view.setHtml(result_html)
        self._cb_result_view.setVisible(True)

        needs_manual = any(not pr["ready"] for pr in result.get("pages", []))
        if needs_manual:
            self._cb_prefill_manual(result)
        self._cb_manual_frame.setVisible(needs_manual)

    def _on_corner_block_manual_compute(self):
        self._cb_error_lbl.setVisible(False)
        if not self._cb_path:
            return
        manual = self._cb_gather_manual()
        if manual is None:
            return
        try:
            result = run_corner_block_check(self._cb_path, manual=manual)
        except Exception as e:
            import traceback
            self._cb_error_lbl.setText(f"Could not compute: {e}")
            self._cb_error_lbl.setVisible(True)
            print(traceback.format_exc())
            return
        result_html = _build_corner_block_html(result)
        self._cb_result_view.setHtml(result_html)
        self._cb_result_view.setVisible(True)

    def _on_gradient_check(self):
        self._grad_error_lbl.setVisible(False)
        if not self._grad_path:
            self._grad_zone.setStyleSheet(
                f"border:2px dashed {COLORS['error']};border-radius:12px;")
            self._grad_error_lbl.setText("Drop or select a GAD PDF first.")
            self._grad_error_lbl.setVisible(True)
            return
        self._grad_zone.setStyleSheet("")
        try:
            result = run_gradient_check(self._grad_path)
        except Exception as e:
            import traceback
            self._grad_error_lbl.setText(f"Could not read gradients: {e}")
            self._grad_error_lbl.setVisible(True)
            self._grad_result_view.setVisible(False)
            print(traceback.format_exc())
            return
        html = _build_gradient_html(result)
        self._grad_result_view.setHtml(html)
        self._grad_result_view.setVisible(True)

    # ── Loop Interface handlers ─────────────────────────────────────────
    def _li_append(self, msg: str, level: str = "info"):
        color = {"ok": "#3FB950", "warn": "#D29922", "err": "#F85149"}.get(level, "#8B949E")
        self._li_log_view.append(f"<span style='color:{color}'>{msg}</span>")

    def _on_li_start(self):
        if self._li_worker is not None:
            return
        self._li_log_view.clear()
        self._li_append("Starting Loop Interface…")
        self._li_worker = LoopInterfaceWorker()
        self._li_worker.log.connect(self._li_append)
        self._li_worker.stopped.connect(self._on_li_stopped)
        self._li_worker.start()
        self._li_start_btn.setEnabled(False)
        self._li_stop_btn.setEnabled(True)

    def _on_li_stop(self):
        if self._li_worker is not None:
            self._li_worker.stop()
        self._li_stop_btn.setEnabled(False)

    def _on_li_stopped(self, reason: str):
        self._li_worker = None
        self._li_start_btn.setEnabled(True)
        self._li_stop_btn.setEnabled(False)

    # ── Status Updation handlers ────────────────────────────────────────
    def _su_append(self, msg: str, level: str = "info"):
        color = {"ok": "#3FB950", "warn": "#D29922", "err": "#F85149"}.get(level, "#8B949E")
        self._su_log_view.append(f"<span style='color:{color}'>{msg}</span>")

    def _on_su_start(self):
        if self._su_worker is not None:
            return
        self._su_log_view.clear()
        self._su_progress_lbl.setText("")
        self._su_append("Starting Status Updation…")
        self._su_worker = StatusUpdationWorker(second_check=False)
        self._su_worker.log.connect(self._su_append)
        self._su_worker.progress.connect(self._on_su_progress)
        self._su_worker.stopped.connect(self._on_su_stopped)
        self._su_worker.start()
        self._su_start_btn.setEnabled(False)
        self._su_second_check_btn.setEnabled(False)
        self._su_stop_btn.setEnabled(True)

    def _on_su_second_check(self):
        """Re-check only missing drawings (no GAD submitted tick) with extra
        search time for slow-loading pages."""
        if self._su_worker is not None:
            return
        self._su_log_view.clear()
        self._su_progress_lbl.setText("")
        self._su_append("Starting Second Check — only missing drawings…")
        self._su_worker = StatusUpdationWorker(second_check=True)
        self._su_worker.log.connect(self._su_append)
        self._su_worker.progress.connect(self._on_su_progress)
        self._su_worker.stopped.connect(self._on_su_stopped)
        self._su_worker.start()
        self._su_start_btn.setEnabled(False)
        self._su_second_check_btn.setEnabled(False)
        self._su_stop_btn.setEnabled(True)

    def _on_su_stop(self):
        if self._su_worker is not None:
            self._su_worker.stop()
        self._su_stop_btn.setEnabled(False)

    def _on_su_progress(self, current: int, last: int):
        self._su_progress_lbl.setText(f"Row {current} / {last}")

    def _on_su_stopped(self, reason: str):
        self._su_worker = None
        self._su_start_btn.setEnabled(True)
        self._su_second_check_btn.setEnabled(True)
        self._su_stop_btn.setEnabled(False)

    def _on_calc(self):
        self._error_lbl.setVisible(False)
        raw = self._discharge_input.text().strip()
        if not raw:
            self._error_lbl.setText("Enter a discharge value.")
            self._error_lbl.setVisible(True)
            self._result_frame.setVisible(False)
            return
        try:
            discharge = float(raw)
        except ValueError:
            self._error_lbl.setText("Enter a valid numeric discharge value.")
            self._error_lbl.setVisible(True)
            self._result_frame.setVisible(False)
            return

        if discharge < 0:
            self._error_lbl.setText("Discharge cannot be negative.")
            self._error_lbl.setVisible(True)
            self._result_frame.setVisible(False)
            return

        vc_mm, explanation = compute_vc_mm(discharge)
        self._vc_value_lbl.setText(f"{vc_mm:,}")
        self._explain_lbl.setText(explanation)
        self._result_frame.setVisible(True)


# ─────────────────────────────────────────────────────────────────────────────
# GAD Panel container
# ─────────────────────────────────────────────────────────────────────────────

class GADPanel(QWidget):
    def __init__(self):
        super().__init__()
        ml = QVBoxLayout(self)
        ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)

        top = QWidget(); top.setObjectName("gadTopBar")
        _a, _b = THEME_SWATCHES[current_theme()]
        top.setStyleSheet(
            f"QWidget#gadTopBar{{"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {_a},stop:1 {_b});"
            f"border-bottom:1px solid {COLORS['navy_border']};}}")
        tl = QVBoxLayout(top)
        tl.setContentsMargins(32,16,32,0); tl.setSpacing(0)

        tr = QHBoxLayout()
        pt = QLabel("GAD Checking")
        pt.setFont(QFont("Segoe UI",16,QFont.Weight.Bold))
        pt.setStyleSheet("color:#FFFFFF;")
        tr.addWidget(pt); tr.addStretch()
        badge = QLabel("Semantic Engine")
        badge.setObjectName("tagInfo"); tr.addWidget(badge)
        tl.addLayout(tr); tl.addSpacing(2)

        ps = QLabel("Annotation extraction → Zone classification → Semantic value comparison → AI assist")
        ps.setStyleSheet("color:rgba(255,255,255,0.85);font-size:10px;")
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
            return ("QPushButton{background:rgba(255,255,255,0.18);color:#FFFFFF;"
                    "border:none;border-bottom:3px solid #FFFFFF;"
                    "border-radius:6px 6px 0 0;padding:7px 16px;}")
        return ("QPushButton{background:transparent;color:rgba(255,255,255,0.75);"
                "border:none;border-bottom:3px solid transparent;"
                "border-radius:6px 6px 0 0;padding:7px 16px;}"
                "QPushButton:hover{color:#FFFFFF;background:rgba(255,255,255,0.10);}")

    def _sw(self, idx):
        self._stack.setCurrentIndex(idx)
        self._btn_v.setChecked(idx==0); self._btn_s.setChecked(idx==1)
        self._btn_v.setStyleSheet(self._ts(idx==0))
        self._btn_s.setStyleSheet(self._ts(idx==1))
