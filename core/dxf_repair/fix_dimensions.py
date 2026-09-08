"""
fix_dimensions.py — Phase 2: corrupt-dimension audit → ground-truth rebuild.

Detection (spec 2.1)
    * DIMENSION entities whose displayed text contradicts their defpoint
      measurement (>max(2 %, 5 mm)) or whose text is non-numeric garbage.
    * Clusters of split/fragmented MTEXT/TEXT that look like one broken
      dimension string (greedy proximity clustering, eps ≈ 3 × char height).
    * Dimension lines + extension lines with NO label at all.

Ground truth (spec 2.2)
    * Crop generously around the DXF-space anchor (via calibration inverse),
      upscale ×3, Tesseract --psm 7 with an engineering whitelist; cross-check
      with the app's AI vision provider (Gemini-first, Claude fallback) when a
      key is configured.  Both agree → rebuild; disagree / low confidence →
      NEEDS_REVIEW (never guess on a structural drawing).

Rebuild (spec 2.3–2.4)
    * Corrupt fragments are fully deleted — zero orphaned text.
    * True associative DIMENSION entities via ezdxf's factory against REAL
      snapped geometry vertices, ONE shared DIMSTYLE ("BES_REPAIR", dimlfac 1,
      mm).  Displayed value stays derived-from-geometry ('<>' — never typed),
      so nudging/stretching in AutoCAD re-measures automatically.
    * Levels / grades (RL, FL, BL, HFL, "1:3:6" …) are annotations → clean
      MTEXT fallback instead of a fake dimension.
"""

from __future__ import annotations

import math
import os
import re
import unicodedata
from collections import namedtuple

import cv2
import numpy as np

from core.dxf_repair import ARCHIVE_LAYER, DIMSTYLE_NAME, REVIEW_LAYER
from core.dxf_repair.common import (
    ChangeLog, apply_affine, bucket_of, box_center, boxes_overlap,
    collect_geometry_vertices, ensure_layer, entity_bbox_2d, iter_bucket,
    keep_alive, polyline_points, snap_vertex, text_content,
)

# ── tunables ─────────────────────────────────────────────────────────────────
VALUE_MISMATCH_REL = 0.02          # >2 % mismatch counts as drift
VALUE_MISMATCH_ABS_MM = 5.0        # floor of tolerance
SNAP_RADIUS_FACTOR = 4.0           # × char-height search radius for vertices (was 6, too generous)
MAX_ITEMS = 200                    # hard cap per run to bound runtime
REVIEW_DIRNAME = "_review"

Cluster = namedtuple("Cluster", "kind center radius items measure")

_NUM_CLEAN_RE = re.compile(r"[^0-9.,+\-]")
_NUM_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^[+-]?\d+(?:\.\d+)?$")
_LEVEL_RE = re.compile(r"\b(R\s*[_.]?L|F\s*[_.]?L|B\s*[_.]?L|H\s*F\s*L|RAIL\s+LEVEL"
                       r"|FORMATION|BED\s+LEVEL|HFL)\b", re.IGNORECASE)
_GRADE_RE = re.compile(r"\b\d+\s*:\s*\d+(?:\s*:\s*\d+)+\b")     # 1:2:4 concrete mixes
_SLOPE_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\s*$")   # 1:1 batter


def is_annotation_only(text: str) -> bool:
    """Levels / mix grades / slope callouts are annotations, not measured dims."""
    t = text.strip()
    if not t:
        return False
    return bool(_LEVEL_RE.search(t) or _GRADE_RE.search(t.replace(" ", ""))
                or _SLOPE_RE.match(t))


def parse_dimension_value(text: str):
    """Best-effort float from a (possibly dirty) dimension string."""
    if not text:
        return None
    t = unicodedata.normalize("NFKC", str(text)).strip()
    m = _SLOPE_RE.match(t)
    if m or _LEVEL_RE.search(t):
        return None                       # annotation-style content
    cleaned = _NUM_CLEAN_RE.sub("", t.split(" ")[0])
    cleaned = cleaned.lstrip("+")
    if not cleaned or cleaned in {".", "-", ",", "-.", ",."}:
        return None
    if not _NUM_RE.match(cleaned.replace(",", "")):
        # single stray characters / letters-only ⇒ unusable
        if len(cleaned.replace(".", "").replace(",", "").replace("-", "")) < 2:
            return None
    try:
        val = cleaned.replace(",", "")
        return float(val) if any(c.isdigit() for c in val) else None
    except ValueError:
        return None


def _fragment_is_junk(text: str) -> bool:
    """True when a standalone text piece can't stand alone as a dim value."""
    if parse_dimension_value(text) is not None:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Text clustering & detection of corrupt items
# ─────────────────────────────────────────────────────────────────────────────

def cluster_fragments(annotations, char_h):
    """Greedy proximity clustering of MTEXT/TEXT fragments (no sklearn needed)."""
    frags = []
    for e in annotations:
        if e.dxftype() not in ("MTEXT", "TEXT"):
            continue
        bbox = entity_bbox_2d(e)
        if bbox is None:
            continue
        h = float(getattr(e.dxf, "char_height", None)
                  or getattr(e.dxf, "height", char_h) or char_h)
        frags.append({"e": e, "bbox": bbox, "h": h,
                      "text": text_content(e).strip()})
    if not frags:
        return []
    eps = max(3.0 * char_h, 900.0)
    frags.sort(key=lambda f: (f["bbox"][0], f["bbox"][1]))
    clusters, cur = [], []
    for f in frags:
        if cur:
            last = cur[-1]["bbox"]
            if (f["bbox"][0] - last[2]) > eps or \
               abs(box_center(f["bbox"])[1] - box_center(last)[1]) > eps:
                clusters.append(cur)
                cur = []
        cur.append(f)
    if cur:
        clusters.append(cur)
    out = []
    for group in clusters:
        xs0 = min(f["bbox"][0] for f in group); ys0 = min(f["bbox"][1] for f in group)
        xs1 = max(f["bbox"][2] for f in group); ys1 = max(f["bbox"][3] for f in group)
        cx, cy = (xs0 + xs1) / 2.0, (ys0 + ys1) / 2.0
        radius = math.hypot(xs1 - xs0, ys1 - ys0) / 2.0
        combined = "".join(f["text"] for f in sorted(
            group, key=lambda f: (f["bbox"][0], -f["bbox"][1])))
        multi_piece = len(group) > 1
        junky = bool(combined) is False or \
            all(_fragment_is_junk(f["text"]) for f in group if f["text"])
        measurable_gap = max(f["bbox"][2] for f in group) - \
            min(f["bbox"][0] for f in group)
        out.append(Cluster("fragments", (cx, cy), radius,
                           [f["e"] for f in group],
                           {"combined": combined, "multi_piece": multi_piece,
                            "junky": junky, "gap_mm": measurable_gap}))
    return out


def _dim_measurement(ent):
    """Geometry-derived measurement of a DIMENSION entity (mm), plus hint."""
    dt = int(getattr(ent.dxf, "dimtype", 0)) % 16

    def p(v):
        return ((float(v.x), float(v.y)) if v is not None else None)

    dp = ent.dxf.get("defpoint", None)
    dp2 = ent.dxf.get("defpoint2", None)
    dp3 = ent.dxf.get("defpoint3", None)
    try:
        if dt == 0 and dp2 is not None and dp3 is not None:   # linear/rotated
            a, b = p(dp2), p(dp3)          # span = ext origins p1↔p2
            angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            rad = math.radians(angle)
            proj = abs((b[0] - a[0]) * math.cos(rad) + (b[1] - a[1]) * math.sin(rad))
            return proj, ("linear", angle)
        if dt == 1 and dp2 is not None and dp3 is not None:   # aligned
            a, b = p(dp2), p(dp3)
            return math.hypot(b[0] - a[0], b[1] - a[1]), ("aligned", None)
        if dt == 3:                                        # diameter
            return abs(float(getattr(ent.dxf, "actual_measurement", 0.0)) or
                       2.0 * math.hypot(p(dp)[0] - p(dp2)[0],
                                        p(dp)[1] - p(dp2)[1])), ("diameter", None)
        if dt == 4:                                        # radius
            return 2.0 * math.hypot(p(dp)[0] - p(dp2)[0],
                                    p(dp)[1] - p(dp2)[1]), ("radius", None)
    except Exception:                     # noqa: BLE001
        pass
    return None, (None, None)


def detect_corrupt_items(msp, geometry_entities, char_h):
    """
    Returns list of Cluster records to rebuild.
      kind='dimension'  → existing DIMENSION entities flagged bad
      kind='fragments'  → split-text clusters
      kind='unlabeled'  → dim-line pattern missing its text entirely
    """
    flagged = []

    # 1) existing DIMENSION entities whose text contradicts their defpoints
    for e in msp.query("DIMENSION"):
        if getattr(e.dxf, "layer", "") in (ARCHIVE_LAYER, REVIEW_LAYER):
            continue
        measure, hint = _dim_measurement(e)
        txt = (text_content(e) or "").strip()
        val = parse_dimension_value(txt)
        empty_ok_txt = txt in ("<>", "")          # factory default = fine
        tol = max(VALUE_MISMATCH_REL * (measure or 0.0), VALUE_MISMATCH_ABS_MM)
        mismatched = measure is not None and val is not None and abs(measure - val) > tol
        garbage = bool(txt) and not empty_ok_txt and \
            parse_dimension_value(txt) is None and not is_annotation_only(txt)
        if mismatched or garbage:
            bb = entity_bbox_2d(e)
            center = box_center(bb) if bb else (
                float(e.dxf.defpoint.x), float(e.dxf.defpoint.y))
            anchors = []
            for k in ("defpoint2", "defpoint3"):   # true ext-origin points
                v = e.dxf.get(k, None)
                if v is not None:
                    anchors.append((float(v.x), float(v.y)))
            flagged.append(Cluster(
                "dimension", tuple(center), float(char_h), [e],
                {"text": txt, "measurement": measure, "hint": hint[0],
                 "anchors": anchors}))

    # 2) fragmented / junk text clusters sitting next to real geometry
    frag_clusters = cluster_fragments(iter_bucket(msp.query("*"), "ANNOTATION"),
                                      char_h)
    for c in frag_clusters:
        meta = c.measure if isinstance(c.measure, dict) else {}
        if meta.get("junky") or (meta.get("multi_piece") and
                                 meta.get("gap_mm", 9e9) < 8 * char_h):
            if _geometry_near(geometry_entities, c.center,
                              SNAP_RADIUS_FACTOR * char_h) >= 2:
                flagged.append(c)

    # 2b) level / grade callouts anywhere — cleaned up as annotation fallback,
    #     whether or not they sit near geometry (never faked as dimensions)
    for e in iter_bucket(msp.query("*"), "ANNOTATION"):
        if e.dxftype() not in ("MTEXT", "TEXT"):
            continue
        txt = text_content(e).strip()
        if txt and is_annotation_only(txt):
            bb = entity_bbox_2d(e)
            center = box_center(bb) if bb else (
                float(getattr(e.dxf, "insert").x),
                float(getattr(e.dxf, "insert").y))
            h = float(getattr(e.dxf, "char_height", None)
                      or getattr(e.dxf, "height", char_h) or char_h)
            flagged.append(Cluster("fragments", tuple(center), float(h),
                                   [e], {"junky": True,
                                         "gap_mm": 0, "multi_piece": False}))

    # 3) unlabeled dimension-line patterns with no text anywhere nearby
    for c in _detect_unlabeled_dims(geometry_entities, msp, char_h)[:MAX_ITEMS]:
        flagged.append(c)

    # 3b) BUG 3 FIX: isolated debris fragments that were never caught.
    #     Any MTEXT/TEXT that is not a valid dim value, not an annotation,
    #     and not a whitelisted short token is flagged as debris.
    #     Routed through _mark_review (not auto-deleted) on first rollout.
    _DEBRIS_WHITELIST = {
        "T0", "T1", "T2", "T3", "T4",          # pier numbers
        "A", "B", "C", "D", "E", "F",           # grid marks
        "P1", "P2", "P3", "P4", "P5",
        "S1", "S2", "S3",
        "NOS", "N.T.", "N.S.", "CL",          # common abbreviations
        "RCC", "PSC", "M.S.", "GR", "SWR",  # material call-outs
        "SP", "AP", "IP",                       # chainage markers
    }
    seen_debris_ids = set()  # track entities already flagged above
    for cl in flagged:
        for item in cl.items:
            seen_debris_ids.add(id(item))
    for e in iter_bucket(msp.query("*"), "ANNOTATION"):
        if id(e) in seen_debris_ids:
            continue
        if e.dxftype() not in ("MTEXT", "TEXT"):
            continue
        txt = text_content(e).strip()
        if not txt:
            continue
        # Skip if it's a valid dimension value or an annotation
        if parse_dimension_value(txt) is not None:
            continue
        if is_annotation_only(txt):
            continue
        # Whitelist: short tokens that are legitimate drawing vocabulary
        clean = txt.strip().upper()
        if clean in _DEBRIS_WHITELIST:
            continue
        # Heuristic: if >= 4 alphabetic chars and looks like a word, skip
        # (likely a label like "ABUTMENT", "PIER", "SPAN")
        alpha_only = re.sub(r"[^A-Za-z]", "", clean)
        if len(alpha_only) >= 4 and alpha_only.isalpha():
            continue
        # This is debris — flag it for review (not auto-delete on first pass)
        bb = entity_bbox_2d(e)
        center = box_center(bb) if bb else (
            float(getattr(e.dxf, "insert").x),
            float(getattr(e.dxf, "insert").y))
        h = float(getattr(e.dxf, "char_height", None)
                  or getattr(e.dxf, "height", char_h) or char_h)
        flagged.append(Cluster("fragments", tuple(center), float(h),
                               [e], {"junky": True,
                                     "gap_mm": 0, "multi_piece": False}))
        seen_debris_ids.add(id(e))

    seen, uniq = set(), []
    for c in flagged:
        key = (c.kind, round(c.center[0] / 5.0), round(c.center[1] / 5.0),
               tuple(sorted(id(x) for x in c.items))[:8])
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq[:MAX_ITEMS]


def _geometry_near(geometry_entities, point, radius):
    """True when ≥2 GEOMETRY vertices sit within `radius` of point."""
    n = 0
    for e in geometry_entities:
        for v in polyline_points(e)[:40]:
            if math.hypot(v[0] - point[0], v[1] - point[1]) <= radius:
                n += 1
                if n >= 2:
                    return n
    return n


def snap_toward(pt, center, step):
    """Nudge endpoint toward the label area by `step` mm along the pair axis."""
    dx, dy = center[0] - pt[0], center[1] - pt[1]
    d = math.hypot(dx, dy) or 1.0
    return (pt[0] + dx / d * step, pt[1] + dy / d * step)


def _detect_unlabeled_dims(geometry_entities, msp, char_h):
    """Connector line flanked by two short near-parallel lines ⇒ lost label."""
    lines = []
    for e in geometry_entities:
        if e.dxftype() == "LINE":
            s, t = e.dxf.start, e.dxf.end
            v = (t.x - s.x, t.y - s.y)
            L = math.hypot(*v)
            if L > 0:
                lines.append((e, (s.x, s.y), (t.x, t.y), v, L))
    shorts = [(e, a, b, v, L) for e, a, b, v, L in lines if L < 4 * char_h]
    connectors = [(e, a, b, v, L) for e, a, b, v, L in lines if L > 2 * char_h]
    out = []
    for ce, ca, cb, cv, cl in connectors[:4000]:
        ux, uy = cv[0] / cl, cv[1] / cl
        ends = []
        for se, sa, sb, sv, sl in shorts:
            dot = abs(sv[0] * ux + sv[1] * uy) / sl
            if dot >= 0.12:                     # want ⊥ connector
                continue
            mid = ((sa[0] + sb[0]) / 2.0, (sa[1] + sb[1]) / 2.0)
            d_along = (mid[0] - ca[0]) * ux + (mid[1] - ca[1]) * uy
            d_perp = -(mid[0] - ca[0]) * uy + (mid[1] - ca[1]) * ux
            if abs(d_along) <= cl + sl and abs(d_perp) <= 1.5 * char_h:
                ends.append((d_along, mid, se))
        if len(ends) < 2:
            continue
        ends.sort(key=lambda x: x[0])
        a_end, b_end = ends[0], ends[-1]
        if (b_end[0] - a_end[0]) < max(2 * char_h, 0.25 * cl):
            continue
        center = ((a_end[1][0] + b_end[1][0]) / 2.0,
                  (a_end[1][1] + b_end[1][1]) / 2.0)
        if _any_annotation_near(msp, center, 2.5 * char_h):
            continue
        inner_a = snap_toward(a_end[1], center, char_h * 0.5)
        inner_b = snap_toward(b_end[1], center, char_h * 0.5)
        out.append(Cluster("unlabeled", center, char_h,
                           [a_end[2], b_end[2]],
                           {"combined": "", "junky": True,
                            "multi_piece": False, "gap_mm": 0,
                            "anchors": [inner_a, inner_b],
                            "axis": 0 if abs(ux) > abs(uy) else 1}))
    return out


def _any_annotation_near(msp, point, radius):
    probe = (point[0] - radius, point[1] - radius,
             point[0] + radius, point[1] + radius)
    for e in iter_bucket(msp.query("*"), "ANNOTATION"):
        if e.dxftype() in ("MTEXT", "TEXT"):
            bb = entity_bbox_2d(e)
            if bb and boxes_overlap(probe, bb):
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Ground truth from the source scan (OCR + AI vision cross-check)
# ─────────────────────────────────────────────────────────────────────────────

TESSERACT_CONFIG_PSM7 = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.,+-"
TESSERACT_CONFIG_PSM6 = "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789.,+-"


def _mm_per_px(calib):
    m = np.asarray(calib.matrix if calib.kind == "global"
                   else calib.cells[0]["matrix"], float)
    return (abs(m[0, 0]) + abs(m[0, 1]) + abs(m[1, 0]) + abs(m[1, 1])) / 2.0


def load_source_image_cached(image_path, cache={}):
    key = os.path.abspath(image_path)
    if key not in cache:
        from core.dxf_repair.calibrate import load_image
        cache[key] = load_image(image_path)
    return cache[key]


def extract_crop(image_path, calib, dxf_center, char_h_mm):
    """Generously padded crop around a DXF-space anchor (≥3× text height/side)."""
    img = load_source_image_cached(image_path)
    scale = _mm_per_px(calib)
    px_pt = calib.dxf_to_pixel(dxf_center)
    pad_px = max(60.0, 3.0 * char_h_mm / max(scale, 1e-9))
    H, W = img.shape[:2]
    x0 = int(max(0, px_pt[0] - pad_px)); y0 = int(max(0, px_pt[1] - pad_px))
    x1 = int(min(W, px_pt[0] + pad_px)); y1 = int(min(H, px_pt[1] + pad_px))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    crop = img[y0:y1, x0:x1].copy()
    return crop


def _prep_ocr(crop_bgr):
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    _t, binimg = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binimg = cv2.medianBlur(binimg, 3)
    return cv2.copyMakeBorder(binimg, 20, 20, 20, 20,
                              cv2.BORDER_CONSTANT, value=255)


def ocr_value(crop_bgr):
    """Tesseract with engineering whitelist; returns (float|None, conf, raw)."""
    try:
        import pytesseract
    except ImportError:
        return None, 0.0, "pytesseract not installed"
    img = _prep_ocr(crop_bgr)
    best = (None, 0.0, "")
    for cfg in (TESSERACT_CONFIG_PSM7, TESSERACT_CONFIG_PSM6):
        try:
            data = pytesseract.image_to_data(img, config=cfg, output_type=pytesseract.Output.DICT)
        except Exception as exc:       # noqa: BLE001
            return None, 0.0, f"tesseract error: {exc}"
        words = [w for w in data["text"] if w.strip()]
        confs = [float(c) for w, c in zip(data["text"], data["conf"])
                 if str(w).strip() and c not in ("-1", "-1.0")]
        raw = " ".join(words)
        joined = "".join(words)
        val = parse_dimension_value(joined)
        conf = float(np.mean(confs)) if confs else 0.0
        if val is not None and conf > best[1]:
            best = (val, conf, raw)
            if conf >= 70:
                break
    return best


VISION_SYSTEM = ("You read dimensions on scanned railway bridge drawings. "
                 "Reply with ONLY the number you see (digits, dot optional, "
                 "in millimetres), nothing else.")


def vision_value(ai_provider, crop_bgr):
    """Optional LLM cross-check via the app's Gemini-first provider layer."""
    if ai_provider is None:
        return None
    try:
        ok, buf = cv2.imencode(".png", crop_bgr)
        if not ok:
            return None
        import base64
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        reply = ai_provider.vision(VISION_SYSTEM, b64, "image/png",
                                   "Dimension value only:", max_tokens=16)
        txt = (reply or "").strip().split()[0] if (reply or "").strip() else ""
        txt = re.sub(r"[^0-9.,]", "", txt).strip(".")
        return float(txt.replace(",", "")) if txt else None
    except Exception:                  # noqa: BLE001 — vision is best-effort only
        return None


def ground_truth_value(crop_bgr, ai_provider=None):
    """
    Returns (value|None, method, needs_review_bool).
      both engines agree   → high confidence
      OCR ≥70 conf alone   → accepted
      disagreement / low   → NEEDS_REVIEW (never guess on structural drawings)
    """
    val, conf, raw = ocr_value(crop_bgr)
    vval = vision_value(ai_provider, crop_bgr)
    if val is not None and vval is not None:
        tol = max(0.005 * abs(val), 5.0)
        if abs(val - vval) <= tol:
            return val, f"ocr+vision ({raw}, t={conf:.0f})", False
        return None, f"MISMATCH ocr={val} vision={vval}", True
    if val is not None and conf >= 70:
        return val, f"ocr(conf={conf:.0f}; {raw})", False
    if val is not None:
        return None, f"low-conf ocr({val}, {conf:.0f}); vision={vval}", True
    return None, f"unreadable ({raw or 'blank'}); vision={vval}", True


# ─────────────────────────────────────────────────────────────────────────────
# Rebuild — ONE shared DIMSTYLE, associative dimension factories, fallbacks
# ─────────────────────────────────────────────────────────────────────────────

def dominant_char_height(msp, default=250.0):
    """Median surviving annotation height = the drawing's real text size."""
    hs = []
    for e in iter_bucket(msp.query("*"), "ANNOTATION"):
        if e.dxftype() in ("MTEXT", "TEXT"):
            h = getattr(e.dxf, "char_height", None) or getattr(e.dxf, "height", None)
            if h and float(h) > 0:
                hs.append(float(h))
        elif e.dxftype() == "DIMENSION":
            t = getattr(e.dxf, "dimtxt", None)
            if t:
                hs.append(float(t))
    return float(np.median(hs)) if len(hs) >= 3 else default


# Arrowhead style options — block names AutoCAD / ezdxf understand
# Matched to the user's AutoCAD dimension style settings.
_ARROW_STYLES = {
    "oblique": "_OBLIQUE",            # ← DEFAULT: oblique slashes (user's setting)
    "closed_filled": "",              # closed filled arrow
    "closed": "_CLOSED",              # closed outline, not filled
    "none": "none",                   # no arrows at any end
    "architectural": "_ARCHITECTURAL_TICK",  # slanted tick marks
    "dot": "_DOT",
}


def _ensure_oblique_block(doc):
    """Create the _OBLIQUE arrow block if it doesn't exist.

    ezdxf doesn't auto-create this block, so we draw it as a simple
    diagonal line (the oblique tick mark used in engineering drawings).
    """
    blk_name = "_OBLIQUE"
    if blk_name in doc.blocks:
        return
    blk = doc.blocks.new(blk_name)
    # Oblique tick: a 45-degree line through the origin
    # Length = 1.0 (will be scaled by dimasz)
    half = 0.5
    blk.add_line((-half, -half), (half, half),
                 dxfattribs={"layer": "0"})


def ensure_dimstyle(doc, char_h, arrow_style="oblique"):
    """Create/reuse a single BES_REPAIR style matching the user's AutoCAD settings.

    Key settings from user's AutoCAD dimension style:
      - Arrow style: Oblique (both ends)
      - Arrow size: 150mm (fixed, not scaled)
      - Dim line extension: 0 (no overshoot beyond extension lines)
      - Extension line offset: 50mm (gap from geometry)
      - Text height: 250mm (fixed, clearly visible)
      - Text offset: 0.09 (tiny gap between dim line and text)
      - Text position: Centered (horizontally and vertically)
      - Text rotation: 0 (always horizontal)
    """
    ds = doc.dimstyles
    try:
        return ds.get(DIMSTYLE_NAME)
    except Exception:                  # noqa: BLE001
        pass
    # Match user's AutoCAD settings exactly
    txt_h = max(250.0, float(char_h))  # minimum 250mm for visibility
    arrow_block = _ARROW_STYLES.get(arrow_style, "_OBLIQUE")
    # Arrow size: 150mm fixed (user's setting)
    if arrow_style == "none":
        arrow_sz = 0.0
    else:
        arrow_sz = 150.0  # Fixed 150mm — matches user's AutoCAD setting
    attribs = {
        "dimtxt": txt_h,                         # 250mm text height
        "dimasz": arrow_sz,                       # 150mm arrow size
        "dimexe": 0.0,                            # NO extension overshoot
        "dimexo": 50.0,                           # 50mm offset from geometry
        "dimgap": max(10.0, txt_h * 0.04),        # tiny gap (0.09 offset)
        "dimlfac": 1.0,                # model units are mm ⇒ value == true mm
        "dimscale": 1.0,
        "dimdec": 0,
        "dimtad": 0,                   # text CENTERED on dim line (user's setting)
        "dimtih": 1,                   # text inside horizontal — always horizontal
        "dimtoh": 1,                   # text outside horizontal — always horizontal
        "dimclrd": 256, "dimclre": 256, "dimclrt": 7,   # BYLAYER lines/white text
        "dimblk": arrow_block,          # first arrow block
        "dimblk2": arrow_block,         # second arrow block (same style both ends)
    }
    # Create the oblique arrow block if it doesn't exist (ezdxf doesn't auto-create it)
    _ensure_oblique_block(doc)
    try:
        sty = ds.add(DIMSTYLE_NAME, dxfattribs=attribs)
    except TypeError:
        sty = ds.add(DIMSTYLE_NAME)
        for k, v in attribs.items():
            try:
                sty.set_dxf_attrib(k, v)
            except Exception:          # noqa: BLE001
                pass
    except Exception:                  # noqa: BLE001 — exists race etc.
        sty = ds.get(DIMSTYLE_NAME)
    return sty


def _orient_pair(p1, p2):
    """Return ('h'|'v'|'a', angle_deg) for a measured pair."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ang = math.degrees(math.atan2(dy, dx)) % 180.0
    if ang < 7.5 or ang > 172.5:
        return "h", 0.0
    if 82.5 < ang < 97.5:
        return "v", 90.0
    return "a", ang


def _delete_entities(msp, doc, entities):
    """Delete entities plus their anonymous geometry blocks (dimensions)."""
    for e in entities:
        blk = None
        if e.dxftype() == "DIMENSION":
            blk = getattr(e.dxf, "geometry", None)
        try:
            msp.delete_entity(e)
        except Exception:              # noqa: BLE001
            continue
        if blk is not None:
            try:
                name = blk.dxf.name
                if name.startswith("*D") and name in doc.blocks:
                    doc.blocks.delete_block(name, safe=False)
            except Exception:          # noqa: BLE001 — block cleanup best effort
                pass


def _mark_review(msp, log, center, why, crop_path=None):
    """Bright magenta flag on _NEEDS_REVIEW so humans cannot miss it."""
    r = 500.0
    msp.add_circle(center=(center[0], center[1], 0.0), radius=r,
                   dxfattribs={"layer": REVIEW_LAYER})
    msp.add_lwpolyline([(center[0] - r, center[1] - r),
                        (center[0] + r, center[1] + r)],
                       dxfattribs={"layer": REVIEW_LAYER})
    msp.add_lwpolyline([(center[0] - r, center[1] + r),
                        (center[0] + r, center[1] - r)],
                       dxfattribs={"layer": REVIEW_LAYER})
    log.add("needs_review", at=[round(center[0], 1), round(center[1], 1)],
            reason=why, crop=crop_path or "", status="NEEDS_REVIEW")

# ─────────────────────────────────────────────────────────────────────────────
# Endpoint resolution + public repair entry point
# ─────────────────────────────────────────────────────────────────────────────

def _pair_from_pool(pool, center, char_h):
    """Left/right (or top/bottom) vertex pair around a fragment cluster.

    FIXED (Bug 1): removed the distance-maximizing fallback that produced
    diagonal garbage.  If no clean left/right or top/bottom split exists,
    returns None (caller routes to NEEDS_REVIEW).
    Tightened search radius to 4x char height (was 6x with a 1200 mm floor).
    """
    radius = SNAP_RADIUS_FACTOR * char_h
    near = [v for v in pool
            if math.hypot(v[0] - center[0], v[1] - center[1]) <= radius]
    if len(near) < 2:
        return None
    left = [v for v in near if v[0] < center[0]]
    right = [v for v in near if v[0] >= center[0]]
    if left and right:
        return max(left, key=lambda v: v[0]), min(right, key=lambda v: v[0])
    top = [v for v in near if v[1] >= center[1]]
    bot = [v for v in near if v[1] < center[1]]
    if top and bot:
        return max(top, key=lambda v: v[1]), min(bot, key=lambda v: v[1])
    # BUG 1 FIX: distance-maximizing fallback removed -- do NOT manufacture
    # a pair by force.  Return None so the caller routes to NEEDS_REVIEW.
    return None


def _snap_pair(p1, p2, pool, char_h):
    r = char_h * 1.5
    return (snap_vertex(p1, pool, r) or tuple(p1),
            snap_vertex(p2, pool, r) or tuple(p2))


def _compute_dim_base(p1, p2, orient, ang, char_h, placed_dims, spacing,
                      dim_index=0):
    """Compute the dimension-line base point perpendicular to the measured
    pair, offset far enough from existing dimensions to avoid overlap.

    ALTERNATING SIDES (user requirement):
      - Even-indexed dims: above (horizontal) / right (vertical)
      - Odd-indexed dims: below (horizontal) / left (vertical)

    This prevents all dimensions from piling up on one side.

    ``placed_dims`` is a list of (minx, miny, maxx, maxy) bounding
    boxes of already-placed dimension entities; ``spacing`` is the minimum
    gap between any two dimension lines (in mm).
    ``dim_index`` is the sequential index of this dimension (0, 1, 2, ...).
    """
    mid_x = (p1[0] + p2[0]) / 2.0
    mid_y = (p1[1] + p2[1]) / 2.0

    # Base offset: enough room for text + arrows
    base_offset = char_h * 1.5
    # Alternate side based on dimension index
    side = 1 if (dim_index % 2 == 0) else -1

    if orient == "v":
        # Vertical dimension → base is to the right (+1) or left (-1)
        base_x = mid_x + side * base_offset
        base_y = mid_y
        # Push further if overlapping existing dims
        for (bx0, by0, bx1, by1) in placed_dims:
            if side > 0:  # pushing right
                if (by0 - spacing) < base_y < (by1 + spacing) and base_x < (bx1 + spacing):
                    base_x = bx1 + spacing
            else:  # pushing left
                if (by0 - spacing) < base_y < (by1 + spacing) and base_x > (bx0 - spacing):
                    base_x = bx0 - spacing
        return (base_x, base_y)
    else:
        # Horizontal dimension (or aligned) → base is above (+1) or below (-1)
        base_x = mid_x
        base_y = mid_y + side * base_offset
        # Push further if overlapping existing dims
        for (bx0, by0, bx1, by1) in placed_dims:
            if side > 0:  # pushing up
                if (bx0 - spacing) < base_x < (bx1 + spacing) and base_y < (by1 + spacing):
                    base_y = by1 + spacing
            else:  # pushing down
                if (bx0 - spacing) < base_x < (bx1 + spacing) and base_y > (by0 - spacing):
                    base_y = by0 - spacing
        return (base_x, base_y)


def _dim_bbox(p1, p2, base, char_h):
    """Rough bounding box of a dimension entity for overlap detection."""
    xs = [p1[0], p2[0], base[0]]
    ys = [p1[1], p2[1], base[1]]
    pad = char_h * 2.0
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _create_dimension(msp, doc, char_h, layer, p1, p2, dim_line_pt,
                      align_hint="linear", arrow_style="oblique"):
    """Associative DIMENSION built against REAL vertices. Returns (entity, mm)."""
    ensure_dimstyle(doc, char_h, arrow_style=arrow_style)
    attribs = {"layer": layer} if layer else {}
    orient, ang = _orient_pair(p1, p2)
    try:
        if orient != "a" and align_hint != "aligned":
            override = msp.add_linear_dim(
                base=(float(dim_line_pt[0]), float(dim_line_pt[1])),
                p1=p1, p2=p2, angle=float(ang), dimstyle=DIMSTYLE_NAME,
                dxfattribs=attribs)
        else:
            px = np.asarray(p1, float)
            pb = np.asarray(p2, float)
            pd = np.asarray(dim_line_pt, float)[:2]
            u = (pb - px)
            u /= (np.linalg.norm(u) or 1.0)
            signed = float(u[0] * (pd[1] - px[1]) - u[1] * (pd[0] - px[0]))
            override = msp.add_aligned_dim(p1=p1, p2=p2, distance=signed,
                                           dimstyle=DIMSTYLE_NAME,
                                           dxfattribs=attribs)
        # ezdxf ≥1.x: render() returns a BaseDimensionRenderer; the actual
        # DXF DIMENSION entity hangs off it (or off the DimStyleOverride).
        renderer = override.render()
        ent = (getattr(renderer, "dimension", None)
               or getattr(override, "dimension", None))
        if ent is None:
            raise RuntimeError("factory did not expose the DIMENSION entity")
        # true geometric span = p1↔p2 (NOT defpoint↔defpoint2: for linear/
        # aligned dimensions defpoint holds the *dimension-line* location)
        measure = math.hypot(float(p2[0]) - float(p1[0]),
                             float(p2[1]) - float(p1[1]))
        return ent, measure
    except Exception as exc:           # noqa: BLE001
        raise RuntimeError(f"dimension factory failed: {exc}")


def _clean_annotation_text(raw):
    t = unicodedata.normalize("NFKC", str(raw)).strip()
    return re.sub(r"\s+", " ", t)


def _resolve_dim_layer(doc):
    """BUG 2 FIX: find or create the project's real dimension layer.

    Never inherit the victim entity's layer.  Prefer _DIM (matches the
    underscore-prefix convention used by ARCHIVE_LAYER / REVIEW_LAYER),
    fall back to DIM, create DIM if neither exists.
    """
    for name in ("_DIM", "DIM"):
        if name in doc.layers:
            return name
    ensure_layer(doc, "DIM", color=3)  # green — standard dimension layer
    return "DIM"


def repair_dimensions(doc, msp, image_path, calib, log, out_dir,
                      ai_provider=None, progress_cb=None,
                      arrow_style="oblique") -> dict:
    """
    Full Phase-2 pass on an in-memory working copy (run_all owns the copy).

    arrow_style: passed to ensure_dimstyle — one of 'closed_filled',
                 'closed', 'none', 'architectural', 'dot'.
    """
    geometry_entities = list(iter_bucket(msp.query("*"), "GEOMETRY"))
    char_h = dominant_char_height(msp)
    pool = collect_geometry_vertices(geometry_entities)
    ensure_layer(doc, REVIEW_LAYER, color=6)          # bright magenta
    review_dir = os.path.join(out_dir, REVIEW_DIRNAME)
    os.makedirs(review_dir, exist_ok=True)

    items = detect_corrupt_items(msp, geometry_entities, char_h)
    if progress_cb:
        progress_cb(f"phase 2: flagged {len(items)} corrupt dimension item(s)")

    stats = {"rebuilt": 0, "annotation_fallback": 0,
             "needs_review": 0, "deleted": 0}
    endpoints_registry = []
    placed_dim_boxes = []  # bounding boxes of placed dims for spacing
    dim_spacing = char_h * 2.5  # minimum gap between dimension lines
    dim_index = 0  # counter for alternating dimension sides

    for idx, cl in enumerate(items):
        # drop entities another cluster already deleted/shared earlier in the
        # loop (destroyed ezdxf entities lose .dxf and would crash below)
        cl = cl._replace(items=keep_alive(cl.items))
        if not cl.items:
            continue
        anchors = []
        if isinstance(cl.measure, dict) and cl.measure.get("anchors"):
            anchors = list(cl.measure["anchors"])
        if cl.kind == "fragments" or len(anchors) < 2:
            pair = _pair_from_pool(pool, cl.center, char_h)
            if pair:
                anchors = list(pair)

        mid = anchors[len(anchors) // 2] if anchors else cl.center
        crop_path = ""
        try:
            crop = extract_crop(image_path, calib, mid, char_h)
        except Exception as exc:       # noqa: BLE001
            crop = None
            log.warn(f"crop failed at {cl.center}", error=str(exc))
        if crop is not None:
            crop_path = os.path.join(review_dir, f"item_{idx:03d}.png")
            cv2.imwrite(crop_path, crop)

        frag_texts = [text_content(e) for e in cl.items
                      if e.dxftype() in ("MTEXT", "TEXT")]
        combined_raw = "".join(t.strip() for t in frag_texts)

        # ── annotation-only callouts (levels / grades): clean MTEXT fallback
        if combined_raw and is_annotation_only(combined_raw) \
                and cl.kind == "fragments":
            layer = cl.items[0].dxf.layer or "ANNOTATIONS"
            _delete_entities(msp, doc, cl.items)
            mt = msp.add_mtext(_clean_annotation_text(combined_raw),
                               dxfattribs={"layer": layer,
                                           "char_height": char_h})
            mt.set_location((cl.center[0], cl.center[1], 0.0),
                            attachment_point=7)
            log.add("dimension", action="text_annotation",
                    old=[t for t in frag_texts], new=combined_raw,
                    method="annotation-fallback", associative=False,
                    crop=crop_path, status="ok")
            stats["annotation_fallback"] += 1
            stats["deleted"] += len(cl.items)
            continue

        # ── ground-truth cross-check
        # Geometry is MORE trustworthy than OCR'd junk text (spec §4):
        # existing-DIMENSION defpoint drift is rebuilt straight from its
        # definition points; fragment/unlabeled clusters require confirmed
        # ground truth or go to NEEDS_REVIEW.
        need_review_reason = ""
        value, method = None, "geometry-derived"
        numeric_content = parse_dimension_value(combined_raw) is not None
        if cl.kind != "dimension" and crop is not None and numeric_content:
            value, method, nr = ground_truth_value(crop, ai_provider)
            if nr:
                need_review_reason = f"ground truth unconfirmed — {method}"
        elif cl.kind == "dimension" and crop is not None:
            # keep the reading as evidence in the log, never as a blocker
            try:
                value, method, nr = ground_truth_value(crop, ai_provider)
                if nr:
                    log.warn(f"ground-truth disagreement at dim defpoints "
                             f"{cl.center}", detail=method)
                    value, method = None, "geometry-derived"
            except Exception as exc:   # noqa: BLE001
                log.warn(f"crop read failed at {cl.center}", error=str(exc))
        has_anchor_geometry = len(anchors) == 2
        if not has_anchor_geometry:
            need_review_reason = need_review_reason or \
                "no measurable endpoint pair found near the corrupted item"

        if need_review_reason:
            _mark_review(msp, log, cl.center, need_review_reason, crop_path)
            stats["needs_review"] += 1
            continue                   # nothing silently inserted as a guess

        p1, p2 = _snap_pair(anchors[0], anchors[1], pool, char_h)
        old_values = ([cl.measure.get("text", "")] if cl.kind == "dimension"
                      else [t for t in frag_texts if t])

        # ── BUG 1 FIX: orthogonality gate ──────────────────────────────────
        # Reject non-orthogonal pairs unless positively confirmed by scan
        # OCR/vision cross-check (ground_truth_value returned a value, not
        # NEEDS_REVIEW).  This prevents diagonal garbage dimensions.
        orient, ang = _orient_pair(p1, p2)
        if orient == "a":
            # Only accept aligned dimensions when we have positive scan
            # evidence (value was confirmed by ground_truth_value above)
            has_scan_evidence = value is not None and not need_review_reason
            if not has_scan_evidence:
                _mark_review(msp, log, cl.center,
                             f"non-orthogonal pair rejected (angle={ang:.1f}, "
                             f"no scan confirmation)", crop_path)
                stats["needs_review"] += 1
                continue

        victims = list(cl.items)
        # ── BUG 2 FIX: dimension layer — never inherit victim's layer ─────
        # Always place rebuilt dimensions on the project's real dimension layer.
        dim_layer = _resolve_dim_layer(doc)

        # ── Dimension spacing: compute proper base point perpendicular to
        # the measured line, offset far enough from already-placed dims.
        # Alternate sides based on dim_index (even=above/right, odd=below/left).
        dim_base = _compute_dim_base(p1, p2, orient, ang, char_h,
                                    placed_dim_boxes, dim_spacing,
                                    dim_index=dim_index)

        _delete_entities(msp, doc, victims)
        try:
            ent, geom_mm = _create_dimension(
                msp, doc, char_h, dim_layer, p1, p2, dim_base,
                arrow_style=arrow_style)
        except RuntimeError as exc:
            log.warn(f"rebuild skipped at {cl.center}", error=str(exc),
                     old=old_values)
            stats["needs_review"] += 1
            continue

        # Track this dimension's bbox so subsequent dims push away
        placed_dim_boxes.append(_dim_bbox(p1, p2, dim_base, char_h))
        dim_index += 1  # next dimension will be on the opposite side
        endpoints_registry.append((p1, p2))
        stats["rebuilt"] += 1
        stats["deleted"] += len(victims)
        log.add("dimension",
                action="rebuilt-associative",
                old=old_values, new="<geometry-derived>",
                measurement_mm=round(geom_mm, 2),
                ocr_ground_truth=value, method=method,
                associative=True, layer=dim_layer,
                p1=[round(p1[0], 1), round(p1[1], 1)],
                p2=[round(p2[0], 1), round(p2[1], 1)],
                deleted_handles=[getattr(getattr(e, 'dxf', e), 'handle', '')
                                 for e in victims],
                new_handle=getattr(getattr(ent, 'dxf', ent), 'handle', ''),
                crop=crop_path, status="ok")
        if progress_cb and (idx % 10 == 0 or idx == len(items) - 1):
            progress_cb(f"phase 2: {idx + 1}/{len(items)} processed")

    # ── BUG 2 post-build assertion: all DIMENSION entities on correct layer ──
    bad_layers = []
    for de in msp.query("DIMENSION"):
        lyr = getattr(de.dxf, "layer", "")
        if lyr not in ("DIM", "_DIM"):
            bad_layers.append((de.handle, lyr))
    if bad_layers:
        summary_errors = [
            f"DIMENSION {h} on unexpected layer '{l}'" for h, l in bad_layers[:10]
        ]
        log.warn(f"{len(bad_layers)} DIMENSION entity(ies) outside DIM/_DIM",
                 details=summary_errors)

    return {"stats": stats, "dim_endpoints": endpoints_registry,
            "char_height": char_h}
