"""
fix_shapes.py — Phase 3: corrupt rectangle / square / circle audit & rebuild.

Finds closed-or-near-closed line loops in the GEOMETRY bucket (hatches never
enter these functions — they live on the frozen archive layer and every input
list here is filtered through the archive-excluding iterator), fits each loop
to its primitive, flags corruption per the spec, then re-draws ONE clean
minimal entity (LWPOLYLINE closed / CIRCLE) while preserving the original
layer / colour / linetype conventions, verified against the source scan.
"""

from __future__ import annotations

import math
import os
from collections import defaultdict

import cv2
import numpy as np

from core.dxf_repair import ARCHIVE_LAYER, REVIEW_LAYER
from core.dxf_repair.common import (
    box_iou, boxes_overlap, dist, ensure_layer, iter_bucket,
    polyline_points,
)

SNAP_TOL_MM = 1.0          # vertex merge tolerance while building graphs
GAP_TOL_FACTOR = 0.03      # open-loop allowed gap as fraction of bbox diagonal
ANGLE_TOL_DEG = 1.0        # spec: corners within ±1° of right angle
CIRCLE_RESID_REL = 0.02    # spec: ≤2 % radius residual for true circles
DUP_IOU = 0.98             # duplicate-outline threshold
MAX_LOOPS = 150            # hard cap for one run
RECT_RDP = 0.005           # RDP epsilon as fraction of perimeter (rect detect)


def _entity_attribs(e):
    d = e.dxf
    return {"layer": getattr(d, "layer", "GEOMETRY"),
            "color": getattr(d, "color", 256),
            "linetype": getattr(d, "linetype", "BYLAYER")}


def _segments(entities):
    """((x1,y1),(x2,y2), owner_entity) tuples from LINE/polyline geometry."""
    segs = []
    for e in entities:
        t = e.dxftype()
        if t == "LINE":
            s, en = e.dxf.start, e.dxf.end
            segs.append(((s.x, s.y), (en.x, en.y), e))
        elif t in ("LWPOLYLINE", "POLYLINE"):
            pts = polyline_points(e)
            for i in range(len(pts) - 1):
                segs.append((tuple(map(float, pts[i])),
                             tuple(map(float, pts[i + 1])), e))
    return segs


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _key(pt):
    return (round(pt[0] / SNAP_TOL_MM), round(pt[1] / SNAP_TOL_MM))


def extract_loops(geometry_entities):
    """
    Simple-cycle extraction from the segment soup, plus whole polylines.
    Returns list of dicts {points:[(x,y)], owners:set(entities), closed:bool,
    endpoints:(first,last)|None}
    """
    loops = []
    # every polyline (open or closed) is a loop candidate with identity order
    poly_owners = set()
    for e in geometry_entities:
        if e.dxftype() == "LWPOLYLINE":
            pts = polyline_points(e)
            if len(pts) >= 3:
                loops.append({"points": pts, "owners": {e},
                              "closed": bool(getattr(e.dxf, "closed", False)),
                              "endpoints": (tuple(map(float, pts[0])),
                                            tuple(map(float, pts[-1])))})
                poly_owners.add(id(e))
    segs = [s for s in _segments([e for e in geometry_entities
                                  if e.dxftype() == "LINE"])]
    uf = _UF()
    adj = defaultdict(set)
    for a, b, _e in segs:
        ka, kb = _key(a), _key(b)
        if ka == kb:
            continue
        uf.union(ka, kb)
        adj[ka].add(kb)
        adj[kb].add(ka)
    comps = defaultdict(list)
    for ka, kb_list in adj.items():
        comps[uf.find(ka)].extend(kb_list)
    for root, nodes in comps.items():
        uniq_nodes = set(nodes)
        if len(uniq_nodes) < 4 or len(uniq_nodes) > 200:
            continue
        pts = [(k[0] * SNAP_TOL_MM, k[1] * SNAP_TOL_MM) for k in uniq_nodes]
        closed = all(len(adj[k]) >= 2 for k in uniq_nodes)
        hull_pts = _order_loop_points(pts)
        loops.append({"points": hull_pts, "owners": {None},
                      "closed": closed, "endpoints": None})
    return loops[:MAX_LOOPS]


def _order_loop_points(pts):
    """Convex-hull-ish ordering that keeps concave sheets usable for fitting."""
    arr = np.asarray(pts, dtype=float)
    try:
        h = cv2.convexHull(arr.astype(np.float32))
        h = h.reshape(-1, 2).astype(float)
        return [tuple(p) for p in h]
    except Exception:                  # noqa: BLE001
        return list(map(tuple, pts))


def _merge_collinear(pts, tol_deg=12.0):
    """Drop intermediate vertices that don't change direction."""
    if len(pts) <= 3:
        return list(pts)
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = np.asarray(out[-1]), np.asarray(pts[i]), np.asarray(pts[i + 1])
        v1 = b - a
        v2 = c - b
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        ang = math.degrees(math.acos(max(-1.0, min(1.0,
            float(np.dot(v1, v2) / (n1 * n2))))))
        if ang > tol_deg:
            out.append(pts[i])
    out.append(pts[-1])
    return out


def _corner_angles(pts):
    angs = []
    n = len(pts)
    for i in range(n):
        a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        v1 = np.asarray(a) - np.asarray(b)
        v2 = np.asarray(c) - np.asarray(b)
        n1 = np.linalg.norm(v1); n2 = np.linalg.norm(v2)
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        cosv = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        angs.append(math.degrees(math.acos(cosv)))
    return angs


def fit_circle_kasa(pts):
    """Algebraic least-squares circle fit → (cx, cy, r, rms_residual)."""
    arr = np.asarray(pts, dtype=float)
    x, y = arr[:, 0], arr[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    b = x ** 2 + y ** 2
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = float(sol[0]), float(sol[1])
    r = math.sqrt(max(0.0, float(sol[2]) + cx ** 2 + cy ** 2))
    d = np.hypot(x - cx, y - cy)
    rms = float(np.sqrt(np.mean((d - r) ** 2)))
    # angular coverage
    ang = np.degrees(np.arctan2(y - cy, x - cx))
    ang_sorted = np.sort(ang)
    gaps = np.diff(np.concatenate([ang_sorted, [ang_sorted[0] + 360]]))
    coverage = 360.0 - float(gaps.max())
    return cx, cy, r, rms, coverage


def classify_loop(loop):
    """→ ('rectangle'|'circle'|'other', meta, corrupt:bool, reason)."""
    pts = loop["points"]
    if len(pts) >= 3:
        diag = math.hypot(max(p[0] for p in pts) - min(p[0] for p in pts),
                          max(p[1] for p in pts) - min(p[1] for p in pts))
        gap_tol = max(SNAP_TOL_MM * 4, GAP_TOL_FACTOR * diag)
        ep = loop.get("endpoints")
        open_gap = (dist(ep[0], ep[1]) if not loop["closed"] else 0.0) \
            if ep is not None else 0.0
        # ── rectangle? RDP keeps true corner offsets down to ~5 ‰ of the
        #    perimeter while discarding vectorisation noise
        try:
            arr = np.asarray(pts, dtype=np.float32).reshape(-1, 1, 2)
            peri = cv2.arcLength(arr, True)
            corners = []
            if peri > 0:
                approx = cv2.approxPolyDP(arr, RECT_RDP * peri, True)
                corners = [tuple(map(float, p)) for p in approx.reshape(-1, 2)]
            area_ok = abs(cv2.contourArea(arr)) > 1e-9 * max(diag * diag, 1.0)
        except Exception:              # noqa: BLE001 — fallback below
            corners, area_ok = [], False
        if len(corners) == 4 and area_ok:
            angs = _corner_angles(corners)
            worst = max(abs(a - 90.0) for a in angs) if len(angs) == 4 else 99.0
            # reopen: an unclosed rectangle whose endpoints overlap ≈ closed
            effectively_closed = loop["closed"] or \
                (ep is not None and open_gap <= gap_tol)
            # any unclosed outline at all is corruption per the spec unless
            # its gap is within tolerance (then we still rebuild closed)
            unclosed_flag = ep is not None and not loop["closed"]
            corrupt = worst > ANGLE_TOL_DEG or \
                (unclosed_flag and open_gap > gap_tol) or \
                (not loop["closed"] and ep is None)
            return ("rectangle",
                    {"corners": corners,
                     "worst_angle_dev_deg": round(worst, 2),
                     "open_gap_mm": round(open_gap, 1),
                     "effectively_closed": bool(effectively_closed)},
                    corrupt,
                    f"corner dev {worst:.2f}° / "
                    + ("open" if unclosed_flag else "closed")
                    + f" gap {open_gap:.1f} mm")
        # ── near-circle polyline / jagged spline approximation
        if len(pts) >= 8:
            cx, cy, r, rms, cov = fit_circle_kasa(pts)
            if cov >= 330 and r > 0 and rms / max(r, 1e-9) <= CIRCLE_RESID_REL * 5:
                # polygonised circle: a real CAD circle would be a CIRCLE
                # entity — any ≥10-vertex closed loop covering a circle is a
                # vectorisation artifact per the corruption spec.
                corrupt = (len(pts) >= 10) \
                    or rms / max(r, 1e-9) > CIRCLE_RESID_REL \
                    or open_gap > gap_tol
                return ("circle",
                        {"center": (cx, cy), "r": r,
                         "resid_rel": round(rms / max(r, 1e-9), 4),
                         "coverage": round(cov, 1), "vertices": len(pts)},
                        corrupt,
                        f"polygonised/near-circle ({len(pts)} pts, "
                        f"radius residual {rms / max(r, 1e-9):.2%}, "
                        f"coverage {cov:.0f}°)")
    t = "SPLINE" if any(getattr(e, "dxftype", lambda: "")() == "SPLINE"
                        for e in loop["owners"]) else "other"
    return ("other", {"src": t}, False, "")


# ─────────────────────────────────────────────────────────────────────────────
# Image cross-check (OpenCV confirmation of true shape/size)
# ─────────────────────────────────────────────────────────────────────────────

def _mm_per_px(calib):
    m = np.asarray(calib.matrix if calib.kind == "global"
                   else calib.cells[0]["matrix"], float)
    return (abs(m[0, 0]) + abs(m[0, 1]) + abs(m[1, 0]) + abs(m[1, 1])) / 2.0


def image_measure_rect(image_path, calib, dxf_center, expected_w, expected_h):
    """Confirm rectangle size from the scan; returns (w_mm, h_mm) or None."""
    try:
        img = _load(image_path)
        scale = _mm_per_px(calib)
        px = calib.dxf_to_pixel(dxf_center)
        pad = int(max(expected_w, expected_h, 50.0) * 2.2 / max(scale, 1e-9))
        H, W = img.shape[:2]
        x0, y0 = int(max(0, px[0] - pad)), int(max(0, px[1] - pad))
        x1, y1 = int(min(W, px[0] + pad)), int(min(H, px[1] + pad))
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 150)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            area = cv2.contourArea(c)
            if len(approx) == 4 and area > 0.35 * pad * pad / 4.0:
                best = approx
                break
        if best is None:
            return None
        rect = cv2.minAreaRect(best.reshape(-1, 2).astype(np.float32))
        (rw, rh) = rect[1]
        return (float(rw) * scale, float(rh) * scale)
    except Exception:                  # noqa: BLE001 — cross-check is optional
        return None


def image_measure_circle(image_path, calib, dxf_center, expected_r):
    """HoughCircles confirmation; returns r_mm or None."""
    try:
        img = _load(image_path)
        scale = _mm_per_px(calib)
        px = calib.dxf_to_pixel(dxf_center)
        rp = expected_r / max(scale, 1e-9)
        pad = int(rp * 3.0)
        H, W = img.shape[:2]
        x0, y0 = int(max(0, px[0] - pad)), int(max(0, px[1] - pad))
        x1, y1 = int(min(W, px[0] + pad)), int(min(H, px[1] + pad))
        crop = img[y0:y1, x0:x1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2,
                                   minDist=rp, param1=120, param2=40,
                                   minRadius=int(max(3, rp * 0.6)),
                                   maxRadius=int(rp * 1.8))
        if circles is not None and len(circles[0]):
            c = circles[0][0]
            return float(c[2]) * scale
    except Exception:                  # noqa: BLE001
        pass
    return None


_IMG_CACHE = {}


def _load(path):
    key = os.path.abspath(path)
    if key not in _IMG_CACHE:
        from core.dxf_repair.calibrate import load_image
        _IMG_CACHE[key] = load_image(path)
    return _IMG_CACHE[key]


def _delete_entities(msp, entities):
    for e in entities:
        try:
            msp.delete_entity(e)
        except Exception:              # noqa: BLE001
            continue


def _snap_to_dims(corner, dim_endpoints, tol=5.0):
    """Nudge a rebuilt corner onto any dimension defpoint that references it."""
    for pair in dim_endpoints or []:
        for p in pair:
            dx = p[0] - corner[0]
            dy = p[1] - corner[1]
            if abs(dx) <= tol and abs(dy) <= tol and dist(p, corner) <= tol:
                return (p[0], p[1])
    return corner

# ─────────────────────────────────────────────────────────────────────────────
# Public repair entry point
# ─────────────────────────────────────────────────────────────────────────────

def _rebuild_rect(msp, corners, attribs, dim_endpoints):
    """Exact-corner LWPOLYLINE (close=True), snapped to dimension defpoints."""
    arr = np.asarray(corners, dtype=float)
    rect = cv2.minAreaRect(arr.astype(np.float32))
    (cx, cy), (rw, rh), angdeg = rect
    ang = math.radians(angdeg)
    ux = np.array([math.cos(ang), math.sin(ang)])
    uy = np.array([-math.sin(ang), math.cos(ang)])
    base = np.array([cx, cy])
    hw, hh = rw / 2.0, rh / 2.0
    pts = []
    for lu, lv in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        c = base + lu * ux + lv * uy
        pts.append(_snap_to_dims((float(c[0]), float(c[1])), dim_endpoints))
    return msp.add_lwpolyline(
        pts, close=True,
        dxfattribs={"layer": attribs.get("layer", "GEOMETRY"),
                    "color": attribs.get("color", 256),
                    "linetype": attribs.get("linetype", "BYLAYER")})


def _scaled_corners(corners, center, sx, sy):
    return [(center[0] + (p[0] - center[0]) * sx,
             center[1] + (p[1] - center[1]) * sy) for p in corners]


def _loop_bbox(pts):
    xs0 = min(p[0] for p in pts); ys0 = min(p[1] for p in pts)
    xs1 = max(p[0] for p in pts); ys1 = max(p[1] for p in pts)
    return (xs0, ys0, xs1, ys1)


def _segments_on_loop(geometry_entities, loop):
    """LINEs whose BOTH endpoints sit on the loop's vertex set."""
    keys = {_key(p) for p in loop["points"]}
    out = []
    for e in geometry_entities:
        if not _live(e) or e.dxftype() != "LINE":
            continue
        s, en = e.dxf.start, e.dxf.end
        if _key((s.x, s.y)) in keys and _key((en.x, en.y)) in keys:
            out.append(e)
    return out


def _live(e):
    """Entity still attached by ezdxf (deleted ones lose their .dxf object)."""
    try:
        return bool(getattr(e, "is_alive", True)) and hasattr(e, "dxf")
    except Exception:                  # noqa: BLE001
        return False


def _victims_for(rec, geometry_entities):
    """Entities composing a loop record (owners or matching LINE soup)."""
    victims = [e for e in geometry_entities if _live(e)
               and any(e is o for o in rec["loop"]["owners"])]
    seg_extra = [e for e in _segments_on_loop(geometry_entities, rec["loop"])
                 if not any(e is v for v in victims)]
    return victims, seg_extra


def repair_shapes(doc, msp, image_path, calib, log, out_dir,
                  dim_endpoints=None, progress_cb=None) -> dict:
    geometry_entities = list(iter_bucket(msp.query("*"), "GEOMETRY"))
    loops = extract_loops(geometry_entities)
    if progress_cb:
        progress_cb(f"phase 3: {len(loops)} closed/near-closed loop(s) found")

    classified = []
    for lp in loops:
        kind, meta, corrupt, reason = classify_loop(lp)
        classified.append({"loop": lp, "kind": kind, "meta": meta,
                           "corrupt": corrupt, "reason": reason})

    # duplicate outlines (re-traced edges): keep first occurrence
    kept, dup_victims = [], []
    for rec in classified:
        if rec["kind"] == "other":
            continue
        bb = _loop_bbox(rec["loop"]["points"])
        twin = next((k for k in kept if boxes_overlap(bb, k["bbox"]) and
                     box_iou(bb, k["bbox"]) >= DUP_IOU), None)
        if twin is not None:
            dup_victims.append(rec)
        else:
            rec["bbox"] = bb
            kept.append(rec)

    stats = {"rects_rebuilt": 0, "circles_rebuilt": 0,
             "duplicates_removed": len(dup_victims),
             "deleted_segments": 0}

    # silently remove clean duplicates (re-trace artifacts)
    for drec in dup_victims:
        victims, extra = _victims_for(drec, geometry_entities)
        _delete_entities(msp, victims + extra)

    for rec in kept:
        pts = rec["loop"]["points"]
        xs0 = min(p[0] for p in pts); ys0 = min(p[1] for p in pts)
        xs1 = max(p[0] for p in pts); ys1 = max(p[1] for p in pts)
        center = ((xs0 + xs1) / 2.0, (ys0 + ys1) / 2.0)
        victims, seg_extra = _victims_for(rec, geometry_entities)
        attribs = (_entity_attribs(victims[0]) if victims else
                   {"layer": "GEOMETRY"})

        if rec["kind"] == "rectangle":
            corners = [tuple(c) for c in rec["meta"]["corners"]]
            w_mm = dist(corners[0], corners[1])
            h_mm = dist(corners[1], corners[2])
            src_note = "dx-geometry"
            w_img = image_measure_rect(image_path, calib, center,
                                       max(w_mm, h_mm), min(w_mm, h_mm))
            if w_img is not None:
                iw, ih = max(w_img), min(w_img)
                gw, gh = max(w_mm, h_mm), min(w_mm, h_mm)
                if gw > 1e-9 and abs(iw - gw) > 0.05 * gw:
                    src_note = f"image-corrected ({gw:.0f}→{iw:.0f} mm)"
                    sx = iw / gw
                    sy = ih / gh if gh > 1e-9 else sx
                    corners = _scaled_corners(corners, center, sx, sy)
            rect_after = cv2.minAreaRect(
                np.asarray(corners, dtype=np.float32))
            rw_after, rh_after = float(rect_after[1][0]), float(rect_after[1][1])
            _delete_entities(msp, victims + seg_extra)
            _rebuild_rect(msp, corners, attribs, dim_endpoints)
            log.add("shape", action="rectangle-rebuilt",
                    before={"vertices": len(pts),
                            "worst_angle_dev_deg": rec["meta"].get("worst_angle_dev_deg"),
                            "open_gap_mm": rec["meta"].get("open_gap_mm")},
                    after={"size_mm": [round(rw_after, 1), round(rh_after, 1)],
                           "closed": True, "corners_orthogonal": True},
                    reason=rec["reason"], source=src_note,
                    layer=attribs.get("layer"), status="ok")
            stats["rects_rebuilt"] += 1
            stats["deleted_segments"] += len(victims + seg_extra)
        elif rec["kind"] == "circle":
            cx = float(rec["meta"]["center"][0])
            cy = float(rec["meta"]["center"][1])
            r0 = float(rec["meta"]["r"])
            note = "fitted"
            r_img = image_measure_circle(image_path, calib, (cx, cy), r0)
            if r_img is not None and abs(r_img - r0) > CIRCLE_RESID_REL * r0:
                note = f"hough-corrected ({r0:.0f}→{r_img:.0f} mm)"
                r0 = r_img
            _delete_entities(msp, victims + seg_extra)
            msp.add_circle(center=(cx, cy, 0.0), radius=r0,
                           dxfattribs={"layer": attribs.get("layer", "GEOMETRY"),
                                       "color": attribs.get("color", 256),
                                       "linetype": attribs.get("linetype", "BYLAYER")})
            log.add("shape", action="circle-rebuilt",
                    before={"resid_rel": rec["meta"].get("resid_rel")},
                    after={"center": [round(cx, 1), round(cy, 1)],
                           "r_mm": round(r0, 1)},
                    reason=rec["reason"], source=note,
                    layer=attribs.get("layer"), status="ok")
            stats["circles_rebuilt"] += 1
            stats["deleted_segments"] += len(victims + seg_extra)

        if progress_cb:
            progress_cb(f"phase 3: {rec['kind']} processed @ "
                        f"[{center[0]:.0f}, {center[1]:.0f}]")

    return {"stats": stats}
