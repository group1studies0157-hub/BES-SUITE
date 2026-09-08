"""
common.py — Phase 0 helpers: buckets, layers, change-log, small geometry math.

Entity buckets (by dxftype):
    GEOMETRY    = LINE, LWPOLYLINE, POLYLINE, ARC, CIRCLE, SPLINE, INSERT
    ANNOTATION  = MTEXT, TEXT, DIMENSION, LEADER, MLEADER
    HATCH       = HATCH, SOLID
"""

from __future__ import annotations

import json
import math
import os
from typing import Iterable, Optional, Sequence

import numpy as np

from core.dxf_repair import ARCHIVE_LAYER, REVIEW_LAYER

GEOMETRY_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "SPLINE", "INSERT"}
ANNOTATION_TYPES = {"MTEXT", "TEXT", "DIMENSION", "LEADER", "MLEADER"}
HATCH_TYPES = {"HATCH", "SOLID"}

# ─────────────────────────────────────────────────────────────────────────────
# Bucketing / archiving (Phase 0)
# ─────────────────────────────────────────────────────────────────────────────

def entity_alive(entity) -> bool:
    """True when an entity is still attached & hasn't been destroyed by ezdxf.
    Deleted entities lose their .dxf attribute object, so a later phase that
    stumbles on an already-removed entity (shared across clusters) can crash.
    """
    try:
        return bool(getattr(entity, "is_alive", True)) and hasattr(entity, "dxf")
    except Exception:                  # noqa: BLE001
        return False


def keep_alive(entities) -> list:
    """Filter to entities that are still alive/attached (see entity_alive)."""
    return [e for e in entities if entity_alive(e)]


def bucket_of(entity) -> str:
    """Classify an entity into GEOMETRY / ANNOTATION / HATCH."""
    t = entity.dxftype()
    if t in HATCH_TYPES:
        return "HATCH"
    if t in ANNOTATION_TYPES:
        return "ANNOTATION"
    if t in GEOMETRY_TYPES:
        return "GEOMETRY"
    return "OTHER"


def bucket_counts(entities: Iterable) -> dict:
    counts: dict = {}
    for e in entities:
        b = bucket_of(e)
        counts[b] = counts.get(b, 0) + 1
    counts["TOTAL"] = sum(v for k, v in counts.items() if k != "TOTAL")
    return counts


def ensure_layer(doc, name: str, color: Optional[int] = None,
                 frozen: bool = False, locked: bool = False):
    """Create layer if missing; never crash on attribute quirks."""
    try:
        if name in doc.layers:
            lyr = doc.layers.get(name)
        else:
            attribs: dict = {}
            if color is not None:
                attribs["color"] = int(color)
            if frozen:
                attribs["frozen"] = 1
            if locked:
                attribs["locked"] = 1
            try:
                lyr = doc.layers.add(name, dxfattribs=attribs)
            except TypeError:            # older ezdxf signature
                lyr = doc.layers.add(name)
                for k, v in attribs.items():
                    try:
                        lyr.set_dxf_attrib(k, v)
                    except Exception:  # noqa: BLE001
                        pass
        if frozen or locked:
            for attr, val in (("frozen", frozen), ("locked", locked)):
                try:
                    if val:
                        lyr.set_dxf_attrib(attr, 1)
                except Exception:      # noqa: BLE001
                    pass
        return lyr
    except Exception:                  # noqa: BLE001 — layer problems must not abort repair
        return None


def archive_hatch_entities(doc, msp, progress_cb=None) -> int:
    """
    Move every HATCH-bucket entity onto the dedicated ARCHIVE layer
    (frozen + locked).  Phase 1–4 processing skips that layer everywhere;
    the final save restores it (nothing else to do — entities stay put),
    so hatch visuals remain untouched while analysis loops never see them.
    Returns archived entity count.
    """
    ensure_layer(doc, ARCHIVE_LAYER, color=253, frozen=True, locked=True)
    n = 0
    for e in list(msp.query("*")):
        if bucket_of(e) == "HATCH" and e.dxf.layer != ARCHIVE_LAYER:
            try:
                e.dxf.layer = ARCHIVE_LAYER
                n += 1
            except Exception:          # noqa: BLE001
                continue
    if progress_cb:
        progress_cb(f"hatch archive: moved {n} entities to {ARCHIVE_LAYER} (frozen/locked)")
    return n


def iter_bucket(entities: Iterable, want: str,
                exclude_archive: bool = True) -> Iterable:
    for e in entities:
        if exclude_archive and getattr(e.dxf, "layer", "") == ARCHIVE_LAYER:
            continue
        if bucket_of(e) == want:
            yield e


# ─────────────────────────────────────────────────────────────────────────────
# Change log (traceability requirement)
# ─────────────────────────────────────────────────────────────────────────────

class ChangeLog:
    """Collects structured change records; persisted as JSON."""

    def __init__(self):
        self.entries: list = []
        self.warnings: list = []

    def add(self, kind: str, **record) -> None:
        rec = {"kind": kind}
        rec.update(record)
        self.entries.append(rec)

    def warn(self, message: str, **detail) -> None:
        rec = {"message": message}
        rec.update(detail)
        self.warnings.append(rec)

    @property
    def needs_review(self) -> list:
        return [e for e in self.entries if e.get("status") == "NEEDS_REVIEW"]

    def save(self, path: str) -> str:
        payload = {
            "changes": self.entries,
            "warnings": self.warnings,
            "needs_review_count": len(self.needs_review),
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return path


# ─────────────────────────────────────────────────────────────────────────────
# Small geometry helpers
# ─────────────────────────────────────────────────────────────────────────────

def dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def polyline_points(entity) -> list:
    """Best-effort vertex list for any LINE/LWPOLYLINE/POLYLINE."""
    t = entity.dxftype()
    if t == "LINE":
        return [(entity.dxf.start.x, entity.dxf.start.y),
                (entity.dxf.end.x, entity.dxf.end.y)]
    if t == "LWPOLYLINE":
        return [(p[0], p[1]) for p in entity.get_points("xy")]
    if t == "POLYLINE":
        try:
            return [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        except Exception:              # noqa: BLE001
            return []
    return []


def text_content(entity) -> str:
    try:
        if entity.dxftype() == "MTEXT":
            return entity.plain_text()
        if entity.dxftype() == "TEXT":
            return entity.dxf.text
        if entity.dxftype() == "DIMENSION":
            return entity.dxf.text or ""
    except Exception:                  # noqa: BLE001
        pass
    return ""


def entity_bbox_2d(entity) -> Optional[tuple]:
    """(minx, miny, maxx, maxy) for the primitive types we care about."""
    t = entity.dxftype()
    try:
        if t in ("CIRCLE", "ARC"):
            c, r = entity.dxf.center, entity.dxf.radius
            return (c.x - r, c.y - r, c.x + r, c.y + r)
        pts = polyline_points(entity)
        if not pts and t in ("MTEXT", "TEXT"):
            pos = entity.dxf.insert
            h = float(getattr(entity.dxf, "char_height", None)
                      or getattr(entity.dxf, "height", 200.0))
            txt = text_content(entity)
            wid = max(h * max(len(txt), 1), h * 1.2)
            return (pos.x, pos.y - h * 0.3, pos.x + wid, pos.y + h)
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            return (min(xs), min(ys), max(xs), max(ys))
        if t == "DIMENSION":
            dp = entity.dxf.get("defpoint", None)
            dp2 = entity.dxf.get("defpoint2", None)
            if dp is not None and dp2 is not None:
                xs = [dp.x, dp2.x]
                ys = [dp.y, dp2.y]
                pad = float(getattr(entity.dxf, "dimtxt", 200.0)) or 200.0
                return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    except Exception:                  # noqa: BLE001
        return None
    return None


def boxes_overlap(a: Sequence[float], b: Sequence[float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def box_center(b: Sequence[float]) -> tuple:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    aa = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    bb = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / min(aa, bb)


def collect_geometry_vertices(entities: Iterable,
                              exclude_layers=("DEFPOINTS",)) -> list:
    """All real vertex coordinates from the GEOMETRY bucket (for snapping)."""
    verts: list = []
    for e in entities:
        if bucket_of(e) != "GEOMETRY":
            continue
        if getattr(e.dxf, "layer", "") in exclude_layers:
            continue
        if e.dxftype() == "CIRCLE":
            c = e.dxf.center
            verts.append((float(c.x), float(c.y)))
            continue
        for p in polyline_points(e):
            verts.append((float(p[0]), float(p[1])))
    return verts


def snap_vertex(point: Sequence[float], pool: Sequence[tuple],
                radius: float) -> Optional[tuple]:
    """Nearest pooled vertex within radius, else None."""
    if not pool:
        return None
    pa = np.asarray(pool, dtype=float)
    d = np.hypot(pa[:, 0] - point[0], pa[:, 1] - point[1])
    i = int(np.argmin(d))
    return tuple(pool[i]) if d[i] <= radius else None


# ─────────────────────────────────────────────────────────────────────────────
# Affine transforms (pixel space ⇄ millimetre model space)
# ─────────────────────────────────────────────────────────────────────────────

def apply_affine(m: np.ndarray, pt: Sequence[float]) -> tuple:
    """Apply 2x3 affine [a b tx; c d ty] to (x, y)."""
    return (m[0, 0] * pt[0] + m[0, 1] * pt[1] + m[0, 2],
            m[1, 0] * pt[0] + m[1, 1] * pt[1] + m[1, 2])


def invert_affine(m: np.ndarray) -> np.ndarray:
    """Invert 2x3 affine so apply(inv, apply(m, p)) == p."""
    lin = m[:2, :2]
    trans = m[:2, 2].reshape(2, 1)
    lin_inv = np.linalg.inv(lin)
    out = np.eye(3, dtype=float)[:2, :]
    out[:2, :2] = lin_inv
    out[:2, 2:3] = -lin_inv @ trans
    return out


def fit_affine(src: Sequence[Sequence[float]],
               dst: Sequence[Sequence[float]]) -> np.ndarray:
    """Least-squares full 2x3 affine fit src→dst (numpy.linalg.lstsq)."""
    s = np.asarray(src, dtype=float)
    d = np.asarray(dst, dtype=float)
    ones = np.ones((len(s), 1))
    lhs = np.hstack([s, ones])                       # Nx3
    solx, *_ = np.linalg.lstsq(lhs, d[:, 0], rcond=None)
    soly, *_ = np.linalg.lstsq(lhs, d[:, 1], rcond=None)
    return np.vstack([solx, soly]).astype(float)     # 2x3


def affine_residuals(m: np.ndarray, src: Sequence[Sequence[float]],
                     dst: Sequence[Sequence[float]]) -> np.ndarray:
    s = np.asarray(src, dtype=float)
    d = np.asarray(dst, dtype=float)
    proj = np.hstack([s, np.ones((len(s), 1))]) @ m.T
    return np.hypot(proj[:, 0] - d[:, 0], proj[:, 1] - d[:, 1])
