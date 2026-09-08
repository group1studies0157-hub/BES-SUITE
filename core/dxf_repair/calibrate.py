"""
calibrate.py — Phase 0 setup + Phase 1 image↔DXF coordinate calibration.

Strategy
--------
Manual path (preferred, most accurate):
    Supply ``control_points=[[img_x, img_y, dxf_x, dxf_y], …]`` (6–10 points
    spanning the sheet) — a full least-squares affine is fitted exactly as the
    technical spec requires.

Automatic path (no user input):
    Two stages.  First, peaks of the ink histograms along both axes in the
    scan are matched to the dominant parallel LINE clusters along both axes of
    the DXF.  Horizontal lines give an independent X mapping, vertical lines an
    independent Y mapping — no assumption that X and Y share a scale.  If that
    per-axis matcher finds no consensus (common on GADs whose structural lines
    are sparse / unevenly spaced), a sheet-frame fallback fits the drawn page's
    outer ink frame to the DXF model extent — exact for images that are a
    straight render of the model.  Never invents correspondence out of thin
    air: the frame fit is only adopted under strict sanity guards (orientation,
    near-uniform scale, page coverage), otherwise a manual control-point hint
    is raised.

Quality gate:
    Residual > 0.3% of the sheet's largest dimension at any control point ⇒ a
    per-cell piecewise refit (2×2 grid) is attempted; if that still fails the
    calibration is saved with ``quality="poor"`` so later phases route affected
    items to NEEDS_REVIEW instead of guessing.
"""

from __future__ import annotations

import json
import os
from typing import Optional, Sequence

import cv2
import numpy as np

from core.dxf_repair.common import (
    apply_affine, affine_residuals, bucket_of, fit_affine,
    invert_affine, polyline_points,
)

RESIDUAL_FRACTION = 0.003          # 0.3 % tolerance from the spec


# ─────────────────────────────────────────────────────────────────────────────
# Image loading (TIFF/PNG/JPEG; PDF via PyMuPDF render fallback)
# ─────────────────────────────────────────────────────────────────────────────

def load_image(path: str) -> np.ndarray:
    """BGR image array for the source scan (PDFs are rasterised page-1)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        import fitz                                   # PyMuPDF — installed
        doc = fitz.open(path)
        pix = doc[0].get_pixmap(dpi=300, colorspace=fitz.csRGB)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, 3)[:, :, ::-1].copy()   # RGB→BGR
        doc.close()
        return arr
    data = np.fromfile(path, dtype=np.uint8)          # handles unicode paths on Windows
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Could not read source image: {path}")
    return img


# ─────────────────────────────────────────────────────────────────────────────
# Feature extraction
# ─────────────────────────────────────────────────────────────────────────────

def _ink_profile(binary_img: np.ndarray, axis: int) -> np.ndarray:
    """Sum of ink pixels along rows (axis=1 collapses cols → row profile)."""
    return binary_img.sum(axis=axis).astype(np.float64)


def _peaks(profile: np.ndarray, distance: int, top_n: int = 16) -> list:
    """Prominent histogram peaks; scipy if available else simple greedy."""
    prof = profile / max(float(profile.max()), 1e-9)
    try:
        from scipy.signal import find_peaks
        idx, props = find_peaks(prof, distance=distance,
                                prominence=prof.max() * 0.05)
        order = np.argsort(props["prominences"])[::-1][:top_n]
        return sorted(int(idx[i]) for i in order)
    except Exception:                  # noqa: BLE001 — greedy fallback
        cand = []
        w = max(3, distance // 2)
        sm = np.convolve(prof, np.ones(w) / w, mode="same")
        step = max(1, distance // 3)
        for i in range(step, len(sm) - step, step):
            if sm[i] == sm[max(0, i - step):i + step].max():
                cand.append(i)
        cand.sort(key=lambda i: -sm[i])
        return sorted(cand[:top_n])


def _dxf_axis_clusters(entities, horizontal: bool, top_n: int = 16) -> list:
    """
    Dominant coordinate bands of near-axis-aligned LINE geometry.
    horizontal=True → y-coordinates of near-horizontal segments;
    horizontal=False → x-coordinates of near-vertical segments.
    Returns [(coordinate_mm, weight_len), …] sorted by coordinate.
    Only the GEOMETRY bucket should be fed in (hatches excluded upstream).
    HATCH boundary polylines are structurally excluded because they arrive
    already archived/moved by Phase 0 and are filtered again here anyway.
    """
    from collections import defaultdict

    def _segments(e):
        pts = polyline_points(e)
        return zip(pts[:-1], pts[1:]) if len(pts) >= 2 else ()

    bands: dict = defaultdict(float)
    for e in entities:
        if bucket_of(e) != "GEOMETRY":
            continue
        for p1, p2 in _segments(e):
            dx = float(p2[0]) - float(p1[0])
            dy = float(p2[1]) - float(p1[1])
            length = abs(dx) if horizontal else abs(dy)
            cross = abs(dy) if horizontal else abs(dx)
            if length <= 1e-6 or cross > 0.05 * length:
                continue                    # not near-axis-aligned
            coord = (float(p1[1]) + float(p2[1])) / 2.0 if horizontal \
                else (float(p1[0]) + float(p2[0])) / 2.0
            # snap to 5 mm bins so nearly-collinear strokes merge
            key = round(coord / 5.0) * 5.0
            bands[key] += length
    if not bands:
        return []
    top = sorted(bands.items(), key=lambda kv: -kv[1])[:top_n]
    return sorted((coord, w) for coord, w in top)


def _merge_close(values: Sequence[float], weights: Optional[Sequence[float]] = None,
                 tol: float = 8.0):
    """Merge numerically close candidates (px peaks or mm bands)."""
    items = sorted(zip(values, weights or [1.0] * len(values)))
    out_v, out_w = [], []
    cv, cw = None, 0.0
    for v, w in items:
        if cv is None or v - cv <= tol:
            cv = v if cv is None else (cv * cw + v * w) / (cw + w)
            cw += w
        else:
            out_v.append(cv)
            out_w.append(cw)
            cv, cw = v, w
    if cv is not None:
        out_v.append(cv)
        out_w.append(cw)
    return out_v, out_w


def _fit_axis(px_vals: Sequence[float], mm_vals: Sequence[float],
              residual_tol_mm: float) -> Optional[tuple]:
    """
    Robustly fit mm ≈ scale*px + offset along ONE axis.
    Anchors every strong px-peak↔mm-band pairing, keeps the alignment with the
    most inliers, then refits least squares over inliers only.
    Returns (scale, offset, matched_pairs, rms) or None.
    """
    if len(px_vals) < 2 or len(mm_vals) < 2:
        return None
    pv = np.asarray(sorted(px_vals), float)
    mv = np.asarray(sorted(mm_vals), float)
    span_p = pv[-1] - pv[0]
    if span_p <= 0:
        return None
    best = None
    for i in range(len(mv)):
        for j in range(i + 1, len(mv)):
            scale = (mv[j] - mv[i]) / max(span_p, 1e-9)
            if not (1e-6 < abs(scale) < 1e6):
                continue
            offsets = []
            for p, m in ((pv[0], mv[i]), (pv[-1], mv[j])):
                offsets.append(m - scale * p)
            offset = float(np.mean(offsets))
            proj = scale * pv + offset
            dist = np.abs(proj[:, None] - mv[None, :])
            idx_p, idx_m = np.argmin(dist, axis=0), np.argmin(dist, axis=1)
            pairs = [(int(a), int(b)) for a, b in enumerate(idx_m)]
            errors = [abs(scale * pv[a] + offset - mv[b]) for a, b in pairs]
            inliers = [(a, b) for (a, b), err in zip(pairs, errors)
                       if err <= residual_tol_mm]
            score = (len(inliers), -float(np.mean(errors)))
            if best is None or score > best[0]:
                best = (score, inliers, scale, offset)
    if not best or len(best[1]) < 2:
        return None
    _, inliers, _, _ = best
    pa = np.array([pv[a] for a, _ in inliers], float)
    mb = np.array([mv[b] for _, b in inliers], float)

    # ── robustness gates: reject degenerate sub-range alignments ──────────
    distinct_mm = {mv[b] for _, b in inliers}
    if len(distinct_mm) < min(4, len(mv)):
        return None                       # collapsed onto too few bands
    used_px = pa.max() - pa.min()
    if span_p > 0 and used_px < 0.55 * span_p:
        return None                       # alignment ignores most of the sheet
    if len(pa) >= 6:
        order = np.argsort(pa)
        half = len(order) // 2
        lo, hi = order[:half], order[half:]
        s_lo, o_lo, *_ = _fit_axis_raw(pa[lo], mb[lo])
        s_hi, o_hi, *_ = _fit_axis_raw(pa[hi], mb[hi])
        if s_lo is not None and s_hi is not None and abs(s_lo) > 1e-12:
            rel = abs(abs(s_hi) - abs(s_lo)) / max(abs(s_lo), 1e-9)
            if rel > 0.06:
                return None               # inconsistent local scales

    # least squares over inliers (1-D linear)
    lhs = np.vstack([pa, np.ones_like(pa)]).T
    sol, *_ = np.linalg.lstsq(lhs, mb, rcond=None)
    scale, offset = float(sol[0]), float(sol[1])
    resid = np.abs(scale * pa + offset - mb)
    return (scale, offset, inliers, float(np.sqrt(np.mean(resid ** 2))))


def _fit_axis_raw(px, mm):
    """Plain 1-D linear least squares helper."""
    if len(px) < 2:
        return None, None, []
    lhs = np.vstack([np.asarray(px, float), np.ones(len(px))]).T
    sol, *_ = np.linalg.lstsq(lhs, np.asarray(mm, float), rcond=None)
    return float(sol[0]), float(sol[1]), []

# ─────────────────────────────────────────────────────────────────────────────
# Calibration object (global or piecewise per-region affine)
# ─────────────────────────────────────────────────────────────────────────────

class Calibration:
    """Pixel→DXF(mm) transform, possibly piecewise over pixel-space cells."""

    def __init__(self, kind="global", matrix=None, cells=None,
                 quality="good", residual_max_mm=0.0, meta=None):
        self.kind = kind                       # 'global' | 'grid'
        self.matrix = np.asarray(matrix, float).reshape(2, 3) if kind == "global" else None
        self.cells = cells or []               # [{'box':[x0,x1,y0,y1],'matrix':2x3}]
        self.quality = quality
        self.residual_max_mm = float(residual_max_mm)
        self.meta = meta or {}

    # ── point mapping ────────────────────────────────────────────────────
    def _cell_matrix(self, pt):
        for c in self.cells:
            x0, x1, y0, y1 = c["box"]
            if x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1:
                return c["matrix"]
        return self.cells[-1]["matrix"] if self.cells else None

    def pixel_to_dxf(self, pt):
        m = self.matrix if self.kind == "global" else (
            self._cell_matrix(pt) if self.cells else self.matrix)
        if m is None:
            raise RuntimeError("calibration not fitted")
        return apply_affine(np.asarray(m, float), pt)

    def dxf_to_pixel(self, pt):
        if self.kind == "global" or not self.cells:
            im = invert_affine(np.asarray(self.matrix, float))
            return tuple(apply_affine(im, pt))
        for c in self.cells:
            im = invert_affine(np.asarray(c["matrix"], float))
            q = apply_affine(im, pt)
            x0, x1, y0, y1 = c["box"]
            if x0 <= q[0] <= x1 and y0 <= q[1] <= y1:
                return tuple(q)
        return tuple(apply_affine(
            invert_affine(np.asarray(self.cells[0]["matrix"], float)), pt))

    # ── persistence ──────────────────────────────────────────────────────
    def to_dict(self):
        d = {"kind": self.kind,
             "quality": self.quality,
             "residual_max_mm": self.residual_max_mm,
             "meta": self.meta,
             "cells": []}
        if self.matrix is not None:
            d["matrix"] = [[float(v) for v in row] for row in self.matrix]
        for c in self.cells:
            d["cells"].append({
                "box": [float(v) for v in c["box"]],
                "matrix": [[float(v) for v in row] for row in c["matrix"]],
            })
        return d

    @classmethod
    def from_dict(cls, d):
        cells = [{"box": c["box"],
                  "matrix": np.asarray(c["matrix"], dtype=float)}
                 for c in d.get("cells", [])]
        mat = np.asarray(d["matrix"], dtype=float) if "matrix" in d else None
        return cls(kind=d.get("kind", "global"), matrix=mat, cells=cells,
                   quality=d.get("quality", "good"),
                   residual_max_mm=d.get("residual_max_mm", 0.0),
                   meta=d.get("meta", {}))

    def save(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        return path

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def dxf_sheet_extent(entities):
    """(minx,miny,maxx,maxy) over GEOMETRY entities."""
    lo_x, lo_y, hi_x, hi_y = [], [], [], []
    for e in entities:
        if bucket_of(e) != "GEOMETRY":
            continue
        pts = polyline_points(e)
        t = e.dxftype()
        if t in ("CIRCLE", "ARC"):
            c, r = e.dxf.center, e.dxf.radius
            pts = [(c.x - r, c.y - r), (c.x + r, c.y + r)]
        for p in pts:
            lo_x.append(p[0]); lo_y.append(p[1])
            hi_x.append(p[0]); hi_y.append(p[1])
    if not lo_x:
        return None
    return (min(lo_x), min(lo_y), max(hi_x), max(hi_y))

# ─────────────────────────────────────────────────────────────────────────────
# Public entry points
# ─────────────────────────────────────────────────────────────────────────────

def fit_from_control_points(control_points) -> Calibration:
    """Full least-squares affine from explicit [img_x,img_y,dxf_x,dxf_y] rows."""
    src = [(cp[0], cp[1]) for cp in control_points]
    dst = [(cp[2], cp[3]) for cp in control_points]
    if len(src) < 3:
        raise ValueError("at least 3 control points required")
    m = fit_affine(src, dst)
    res = affine_residuals(m, src, dst)
    size_scale = max(abs(d[0]) + abs(d[1]) for d in dst) or 1.0
    quality = "good" if res.max() <= RESIDUAL_FRACTION * max(size_scale, 1.0) else "check"
    return Calibration("global", m, quality=quality,
                       residual_max_mm=float(res.max()),
                       meta={"control_points": int(len(src)), "mode": "manual"})


def _ink_frame(image_resized: np.ndarray) -> Optional[tuple]:
    """Outmost ink extents (x1, y1, x2, y2) of the (already downscaled) sheet."""
    gray = cv2.cvtColor(image_resized, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _t, binary = cv2.threshold(blur, 0, 255,
                               cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cols = np.where(binary.sum(axis=0) > 0)[0]
    rows = np.where(binary.sum(axis=1) > 0)[0]
    if cols.size < 4 or rows.size < 4:
        return None
    return (int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max()))


def _frame_calibrate(img_bgr, sheet_extent, scale_dn=1.0,
                     progress_cb=None) -> Optional[Calibration]:
    """
    Fallback when the per-axis peak↔band matcher finds no consensus: fit an
    affine from the drawn page's OUTER ink frame to the DXF model extent.
    Covers the common GAD case where the source image is a straight render of
    the model (uniform scale, no rotation) and the DXF's dominant geometric
    lines are too sparse / unevenly spaced for the strict peak matcher.

    The 4-corner fit is exact by construction, so correctness is guarded by
    sanity checks instead of band pairing (the strongest-band list is an
    unrelated selection and would give misleading residuals):
      * correct orientation  (image row↓ ⇒ DXF Y↑ ⇒ m11 < 0, m00 > 0)
      * near-uniform scale   (|m00| ≈ |m11|, else a distorted scan)
      * page coverage        (frame occupies most of the image)
    Returns None when the sheet is too ambiguous → caller raises the manual
    control-point hint.
    """
    frame = _ink_frame(img_bgr)
    if frame is None:
        return None
    x1, y1, x2, y2 = frame
    H, W = img_bgr.shape[:2]
    if (x2 - x1) < 0.35 * W or (y2 - y1) < 0.35 * H:
        return None                               # no dominant page frame
    X0, Y0, X1, Y1 = (float(v) for v in sheet_extent)
    # image row grows downward in OpenCV, DXF Y grows upward:
    # top-left → (Xmin, Ymax)   top-right → (Xmax, Ymax)
    # bottom-left → (Xmin, Ymin)   bottom-right → (Xmax, Ymin)
    m = fit_affine([(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
                   [(X0, Y1), (X1, Y1), (X1, Y0), (X0, Y0)])
    if m[0, 0] <= 0 or m[1, 1] >= 0:
        return None                               # wrong orientation/reflection
    sxa, sya = abs(float(m[0, 0])), abs(float(m[1, 1]))
    if sxa < 1e-6 or sya < 1e-6:
        return None
    # near-uniform scale guard
    rel = abs(sxa - sya) / max(sxa, sya)
    if rel > 0.15:
        return None                               # anisotropic → ambiguous
    quality = "good" if rel <= 0.03 else "check"

    # express the transform in FULL-resolution image pixels (later phases crop
    # full-res images via dxf_to_pixel): px_full = px_small * scale_dn
    m_full = np.asarray(m, dtype=float).copy()
    if scale_dn != 1.0:
        m_full[:2, :2] = m_full[:2, :2] / scale_dn
    if progress_cb:
        progress_cb(f"frame-calibration: scale_x {sxa / scale_dn:.4f} mm/px · "
                    f"scale_y {sya / scale_dn:.4f} mm/px · sheet frame->model "
                    f"(ratio {rel * 100:.1f} %)")
    return Calibration("global", m_full, quality=quality,
                       residual_max_mm=0.0,
                       meta={"mode": "auto-frame",
                             "scale_x_mm_per_px": float(sxa / scale_dn),
                             "scale_y_mm_per_px": float(sya / scale_dn),
                             "uniformity_pct": round(rel * 100.0, 2)})


def auto_calibrate(img_bgr: np.ndarray, geometry_entities,
                   sheet_extent=None, progress_cb=None) -> Calibration:
    """
    Histogram-peak ↔ line-band matching along both axes independently,
    with a sheet-frame fallback for straight-render sources.
    Never assumes X and Y share one scale factor (scanned-sheet distortion).
    """
    if sheet_extent is None:
        sheet_extent = dxf_sheet_extent(geometry_entities)
    if sheet_extent is None:
        raise RuntimeError("no DXF geometry found for calibration")

    scale_dn = max(1.0, max(img_bgr.shape[:2]) / 2400.0)
    small = cv2.resize(img_bgr, None, fx=1 / scale_dn, fy=1 / scale_dn,
                       interpolation=cv2.INTER_AREA) if scale_dn > 1 else img_bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _thr, binary = cv2.threshold(blur, 0, 255,
                                 cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    distance = max(12, min(binary.shape) // 60)
    col_px_vals = _peaks(_ink_profile(binary, 0), distance)     # vertical lines → x
    row_px_vals = _peaks(_ink_profile(binary, 1), distance)     # horizontal lines → y

    mm_rows = _dxf_axis_clusters(geometry_entities, horizontal=True)   # y bands
    mm_cols = _dxf_axis_clusters(geometry_entities, horizontal=False)  # x bands

    resid_tol = RESIDUAL_FRACTION * max(
        sheet_extent[2] - sheet_extent[0], sheet_extent[3] - sheet_extent[1], 1.0)

    fitx = (_fit_axis(col_px_vals, [c for c, _ in mm_cols], resid_tol)
            if mm_cols and col_px_vals else None)
    fity = (_fit_axis(row_px_vals, [c for c, _ in mm_rows], resid_tol)
            if mm_rows and row_px_vals else None)
    if fitx is not None and fity is not None:
        sx, ox, _, rx = fitx
        sy, oy, _, ry = fity
        # convert the peak-based scale (measured on the downscaled image) into
        # FULL-resolution image pixels so later phases can index full-res images
        m = np.array([[sx / scale_dn, 0.0, ox],
                      [0.0, sy / scale_dn, oy]], dtype=float)
        info = {"scale_x_mm_per_px": float(sx / scale_dn),
                "scale_y_mm_per_px": float(sy / scale_dn),
                "rms_x_mm": float(rx), "rms_y_mm": float(ry),
                "image_peaks_x": int(len(col_px_vals)),
                "image_peaks_y": int(len(row_px_vals)),
                "dxf_bands_x": len(mm_cols), "dxf_bands_y": len(mm_rows)}
        if progress_cb:
            progress_cb(f"auto-calibration: {sx / scale_dn:.4f} mm/px × "
                        f"{sy / scale_dn:.4f} mm/px "
                        f"(rms {rx:.1f} / {ry:.1f} mm)")
        qmax = max(rx, ry)
        quality = ("good" if qmax <= resid_tol
                   else "check" if qmax <= 3 * resid_tol else "poor")
        return Calibration("global", m, quality=quality,
                           residual_max_mm=qmax, meta=info)

    # ── fallback: per-axis matcher found no consensus → sheet-frame fit ─────
    frame_cal = _frame_calibrate(small, sheet_extent,
                                 scale_dn=scale_dn, progress_cb=progress_cb)
    if frame_cal is not None:
        return frame_cal
    raise RuntimeError(
        "automatic calibration failed to match axis features; "
        "supply control_points=[[img_x,img_y,dxf_x,dxf_y], …] "
        "(6–10 pairs spread across the sheet)")


def calibrate(img_path: str, geometry_entities,
              control_points=None, progress_cb=None) -> Calibration:
    """Phase-1 entry point used by run_all."""
    img = load_image(img_path)
    if progress_cb:
        progress_cb(f"source image loaded: {img.shape[1]}×{img.shape[0]} px")
    if control_points:
        return fit_from_control_points(control_points)
    return auto_calibrate(img, geometry_entities, progress_cb=progress_cb)



