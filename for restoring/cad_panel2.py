"""
CAD Process 2 — AI Bridge Drawing → Scaled AutoCAD DXF
Pipeline: Upload image/PDF → Claude Vision extracts all dims/levels →
          Build geometry → Interactive QGraphicsView elevation preview →
          Export 1:1 DXF with 10 named layers
"""

import os, json, base64, datetime, tempfile, shutil, math
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QProgressBar, QFileDialog, QLineEdit, QSizePolicy,
    QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsTextItem,
    QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsPathItem,
    QSplitter, QCheckBox, QGroupBox, QGridLayout, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QRectF, QPointF
from PyQt6.QtGui import (
    QFont, QPen, QColor, QBrush, QPainterPath, QTransform,
    QWheelEvent, QDragEnterEvent, QDropEvent, QKeyEvent
)

from gui.styles import COLORS

# ── Anthropic model — update here if API identifier changes ──────────────────
CLAUDE_MODEL = "claude-sonnet-4-6"

# ═══════════════════════════════════════════════════════════════════════════════
# LAYER DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════
LAYERS = {
    "DECK":        {"color": "#FFFFFF", "width": 2.0,  "label": "Deck / Outline",   "on": True },
    "PIER":        {"color": "#FFFFFF", "width": 1.5,  "label": "Pier / Column",    "on": True },
    "ABUTMENT":    {"color": "#FFFFFF", "width": 1.5,  "label": "Abutment / Wall",  "on": True },
    "DIMENSIONS":  {"color": "#FFFFFF", "width": 0.8,  "label": "Dimensions",       "on": True },
    "LEVELS":      {"color": "#FFFFFF", "width": 0.8,  "label": "RL Levels",        "on": True },
    "ANNOTATIONS": {"color": "#FFFFFF", "width": 0.8,  "label": "Annotations",      "on": True },
    "FOUNDATION":  {"color": "#FFFFFF", "width": 1.2,  "label": "Foundation",       "on": True },
    "BEARING":     {"color": "#FFFFFF", "width": 1.0,  "label": "Bearing",          "on": True },
    "CENTERLINE":  {"color": "#FFFFFF", "width": 0.7,  "label": "Centre Line",      "on": True,  "dash": True},
    "GRID":        {"color": "#FFFFFF", "width": 0.4,  "label": "Grid",             "on": False, "dash": True},
}

# ═══════════════════════════════════════════════════════════════════════════════
# GEOMETRY HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _dim_line(entities, layer, x1, y1, x2, y2, label, offset=400, text_h=210):
    """Draw a dimension line with ticks and a centred label."""
    entities.append({"type":"LINE","layer":layer,"x1":x1,"y1":y1,"x2":x2,"y2":y2})
    # ticks perpendicular to line
    if abs(x2 - x1) > abs(y2 - y1):           # horizontal dim
        for tx in (x1, x2):
            entities.append({"type":"LINE","layer":layer,"x1":tx,"y1":y1-offset*0.6,
                              "x2":tx,"y2":y1+offset*0.6})
        mx = (x1+x2)/2; my = y1 + offset*1.2
        entities.append({"type":"TEXT","layer":layer,"x":mx-len(label)*text_h*0.3,
                          "y":my,"text":label,"height":text_h})
    else:                                       # vertical dim
        for ty in (y1, y2):
            entities.append({"type":"LINE","layer":layer,"x1":x1-offset*0.6,"y1":ty,
                              "x2":x1+offset*0.6,"y2":ty})
        mx = x1 - offset*1.2; my = (y1+y2)/2
        entities.append({"type":"TEXT","layer":layer,"x":mx-len(label)*text_h*0.6,
                          "y":my,"text":label,"height":text_h})


# ═══════════════════════════════════════════════════════════════════════════════
# ELEVATION GEOMETRY  (longitudinal view)
# ═══════════════════════════════════════════════════════════════════════════════
def _build_elevation(data):
    """X = along bridge, Y = RL height. All units mm."""
    mm = 1000

    spans     = data.get("spans") or [data.get("totalSpan", 30)]
    deck_thk  = data.get("deckThickness",  0.8) * mm
    pier_h    = data.get("pierHeight",     6.0) * mm
    pier_w    = data.get("pierWidth",      1.2) * mm
    abut_w    = data.get("abutmentWidth",  1.5) * mm
    rl_deck   = data.get("rlDeck",        10.0) * mm
    rl_soffit = rl_deck - deck_thk
    rl_ground = data.get("rlGround",       0.0) * mm
    n_piers   = len(spans) - 1
    ents = []

    def L(lyr,x1,y1,x2,y2): ents.append({"type":"LINE","layer":lyr,"x1":x1,"y1":y1,"x2":x2,"y2":y2})
    def T(lyr,x,y,t,h=200): ents.append({"type":"TEXT","layer":lyr,"x":x,"y":y,"text":t,"height":h})
    def C(lyr,cx,cy,r):      ents.append({"type":"CIRCLE","layer":lyr,"cx":cx,"cy":cy,"r":r})

    x = 0.0
    # Left abutment
    L("ABUTMENT",x,rl_ground,x+abut_w,rl_ground)
    L("ABUTMENT",x,rl_ground,x,rl_soffit)
    L("ABUTMENT",x+abut_w,rl_ground,x+abut_w,rl_soffit)
    L("ABUTMENT",x,rl_soffit,x+abut_w,rl_soffit)
    T("ANNOTATIONS",x+60,rl_ground-450,"ABUTMENT A1",180)
    x += abut_w

    for i, span_m in enumerate(spans):
        sp = span_m * mm
        mx = x + sp/2
        L("DECK",x,rl_soffit,x+sp,rl_soffit)
        L("DECK",x,rl_deck,  x+sp,rl_deck)
        _dim_line(ents,"DIMENSIONS",x,rl_deck+450,x+sp,rl_deck+450,
                  f"S{i+1}: {span_m:.0f}mm")
        x += sp
        if i < n_piers:
            px = x - pier_w/2
            L("PIER",px,rl_ground,px+pier_w,rl_ground)
            L("PIER",px,rl_ground,px,rl_soffit)
            L("PIER",px+pier_w,rl_ground,px+pier_w,rl_soffit)
            L("PIER",px,rl_soffit,px+pier_w,rl_soffit)
            cap=250
            L("PIER",px-cap,rl_soffit,px+pier_w+cap,rl_soffit)
            L("PIER",px-cap,rl_soffit+320,px+pier_w+cap,rl_soffit+320)
            L("PIER",px-cap,rl_soffit,px-cap,rl_soffit+320)
            L("PIER",px+pier_w+cap,rl_soffit,px+pier_w+cap,rl_soffit+320)
            L("FOUNDATION",x,rl_ground,x,rl_ground-2800)
            C("FOUNDATION",x,rl_ground-2800,380)
            T("ANNOTATIONS",px,rl_ground-450,f"P{i+1}",180)

    # Right abutment
    L("ABUTMENT",x,rl_ground,x+abut_w,rl_ground)
    L("ABUTMENT",x,rl_ground,x,rl_soffit)
    L("ABUTMENT",x+abut_w,rl_ground,x+abut_w,rl_soffit)
    L("ABUTMENT",x,rl_soffit,x+abut_w,rl_soffit)
    T("ANNOTATIONS",x+60,rl_ground-450,"ABUTMENT A2",180)
    x += abut_w; total_x = x

    L("DECK",abut_w,rl_soffit,abut_w,rl_deck)
    L("DECK",total_x-abut_w,rl_soffit,total_x-abut_w,rl_deck)
    _dim_line(ents,"DIMENSIONS",0,rl_deck+1500,total_x,rl_deck+1500,
              f"TOTAL: {data.get('totalSpan',sum(spans)):.0f}mm",600,260)
    L("CENTERLINE",0,rl_deck+900,total_x,rl_deck+900)
    T("CENTERLINE",total_x/2-300,rl_deck+1100,"CL",170)

    for rv,lbl in [(rl_deck,   f"RL {data.get('rlDeck',10.0):.3f}m"),
                   (rl_soffit, f"RL {(data.get('rlDeck',10.0)-data.get('deckThickness',0.8)):.3f}m"),
                   (rl_ground, f"RL {data.get('rlGround',0.0):.3f}m")]:
        L("LEVELS",-5000,rv,-500,rv)
        T("LEVELS",-4900,rv+120,lbl,210)

    T("ANNOTATIONS",0,rl_ground-2000,
      f"BRIDGE ELEVATION  —  AI GENERATED  |  1:1  |  mm  |  {datetime.date.today()}",280)

    bounds={"xMin":-6000,"xMax":total_x+2000,"yMin":rl_ground-3500,"yMax":rl_deck+2500}
    return ents, bounds, {"rl_deck":rl_deck,"rl_soffit":rl_soffit,"rl_ground":rl_ground,
                          "total_x":total_x,"abut_w":abut_w}


# ═══════════════════════════════════════════════════════════════════════════════
# PLAN GEOMETRY  (top view — complete drawing, all elements, no hatching)
# ═══════════════════════════════════════════════════════════════════════════════
def _build_plan(data):
    """
    X = transverse (across bridge width)  — origin at left outer edge
    Y = longitudinal (along track/flow)   — origin at bottom (drop wall end)
    All spacing from extracted mm values.  No hatching — outlines only.
    """
    ents = []
    FONT = 190   # uniform text height throughout

    def L(lyr,x1,y1,x2,y2):
        ents.append({"type":"LINE","layer":lyr,"x1":float(x1),"y1":float(y1),
                     "x2":float(x2),"y2":float(y2)})
    def T(lyr,x,y,t,h=None):
        ents.append({"type":"TEXT","layer":lyr,"x":float(x),"y":float(y),
                     "text":str(t),"height":float(h or FONT)})
    def R(lyr,x1,y1,x2,y2):   # rectangle helper
        L(lyr,x1,y1,x2,y1); L(lyr,x2,y1,x2,y2)
        L(lyr,x2,y2,x1,y2); L(lyr,x1,y2,x1,y1)
    def arrow_down(lyr,x,y,length=500):
        L(lyr,x,y+length,x,y)
        L(lyr,x,y,x-120,y+200); L(lyr,x,y,x+120,y+200)
    def arrow_up(lyr,x,y,length=500):
        L(lyr,x,y,x,y+length)
        L(lyr,x,y+length,x-120,y+length-200)
        L(lyr,x,y+length,x+120,y+length-200)
    def tick_left(lyr,x,y): L(lyr,x,y,x-200,y)
    def tick_right(lyr,x,y): L(lyr,x,y,x+200,y)

    # ── Pull extracted dimensions ────────────────────────────────────
    t_sp     = data.get("transverseSpacings") or []
    l_dims   = data.get("longitudinalDims")   or []
    lyr_dims = data.get("layerDims")          or []
    off_dims = data.get("offsetDims")         or []
    pier_w   = data.get("pierWidth",    600)          # single pier wall thickness mm
    if isinstance(pier_w, float) and pier_w < 10:
        pier_w = pier_w * 1000                        # convert m→mm if needed

    # Fallbacks
    if not t_sp:
        dw = data.get("deckWidth", 3.9)
        if dw < 50: dw *= 1000
        t_sp = [dw]
    if not l_dims:
        ts = data.get("totalSpan", 9.776)
        if ts < 50: ts *= 1000
        l_dims = [ts]

    total_w = sum(t_sp)   # e.g. 900+600+900+600+900 = 3900
    total_l = sum(l_dims) # e.g. 3576+6200 = 9776

    # Longitudinal zone boundaries (Y positions, bottom = 0)
    y_zones = []
    yy = 0.0
    for d in l_dims:
        y_zones.append(yy)
        yy += d
    y_zones.append(total_l)  # top edge

    # Zone names: bottom zone = drop wall area, top zone = curtain wall area
    # For 2-zone drawing: y_zones[0..1] = drop wall zone, y_zones[1..2] = main pier zone
    y_drop_bot = y_zones[0]        # = 0
    y_drop_top = y_zones[1]        # = l_dims[0]  e.g. 3576
    y_main_top = y_zones[-1]       # = total_l    e.g. 9776

    # ── 1. OUTER BOUNDARY (main pier table area) ─────────────────────
    R("DECK", 0, y_drop_top, total_w, y_main_top)

    # ── 2. LOWER EXTENSION (drop wall / toe wall zone) ───────────────
    # Narrower box below main table — inset by pier wall thickness each side
    inset = t_sp[0] if t_sp else 900   # first spacing = outer wing
    R("ABUTMENT", inset, y_drop_bot, total_w - inset, y_drop_top)

    # ── 3. UPPER EXTENSION (curtain wall zone) ───────────────────────
    # Same width as main table, projects above
    curtain_h = l_dims[0] if len(l_dims) > 1 else total_l * 0.25
    R("ABUTMENT", inset, y_main_top, total_w - inset, y_main_top + curtain_h)

    # ── 4. TRANSVERSE COLUMN LINES (pier walls across width) ─────────
    x_cur = 0.0
    col_xs = [0.0]
    for i, sp in enumerate(t_sp):
        x_cur += sp
        col_xs.append(x_cur)
        if 0 < i < len(t_sp)-1:  # interior lines only
            L("PIER", x_cur, y_drop_top, x_cur, y_main_top)

    # Pier wall thickness lines (double lines for wall thickness)
    # Draw inner wall lines offset by pier wall thickness
    pw = min(pier_w, t_sp[1] if len(t_sp) > 1 else 200)  # pier thickness
    for cx in col_xs[1:-1]:   # interior column positions
        L("PIER", cx - pw/2, y_drop_top, cx - pw/2, y_main_top)
        L("PIER", cx + pw/2, y_drop_top, cx + pw/2, y_main_top)

    # ── 5. LONGITUDINAL ZONE DIVIDER LINE ────────────────────────────
    for i, yz in enumerate(y_zones[1:-1]):
        L("ABUTMENT", 0, yz, total_w, yz)

    # ── 6. WING WALL CURVES (curtain + toe walls) ────────────────────
    # Curtain wall: arc at top connecting left outer to pier gap
    # Represented as diagonal lines (no arc entity needed for plan)
    # Left wing diagonal  — top
    L("ABUTMENT", inset,     y_main_top,          inset,     y_main_top + curtain_h*0.5)
    L("ABUTMENT", inset,     y_main_top + curtain_h*0.5, 0,  y_main_top + curtain_h)
    # Right wing diagonal — top
    L("ABUTMENT", total_w-inset, y_main_top,              total_w-inset, y_main_top + curtain_h*0.5)
    L("ABUTMENT", total_w-inset, y_main_top + curtain_h*0.5, total_w, y_main_top + curtain_h)

    # Toe wall: arc at bottom
    toe_h = curtain_h
    L("ABUTMENT", inset,     y_drop_bot,             inset,     y_drop_bot - toe_h*0.5)
    L("ABUTMENT", inset,     y_drop_bot - toe_h*0.5, 0,         y_drop_bot - toe_h)
    L("ABUTMENT", total_w-inset, y_drop_bot,             total_w-inset, y_drop_bot - toe_h*0.5)
    L("ABUTMENT", total_w-inset, y_drop_bot - toe_h*0.5, total_w,       y_drop_bot - toe_h)

    # Drop wall at very bottom (horizontal beam)
    drop_wall_t = lyr_dims[0] if lyr_dims else 300
    R("DECK", 0, y_drop_bot - toe_h - drop_wall_t, total_w, y_drop_bot - toe_h)

    # ── 7. REBAR / REINFORCEMENT SYMBOLS on wing walls ───────────────
    # Small X marks at regular intervals — outline only (no hatching)
    sym_spacing = max(400, (y_main_top - y_drop_top) // 8)
    for yw in range(int(y_drop_top + sym_spacing), int(y_main_top), int(sym_spacing)):
        # left wing
        for xw in [inset/2 - 80, inset/2 + 80]:
            L("ANNOTATIONS", xw-80, yw-80, xw+80, yw+80)
            L("ANNOTATIONS", xw+80, yw-80, xw-80, yw+80)
        # right wing
        for xw in [total_w - inset/2 - 80, total_w - inset/2 + 80]:
            L("ANNOTATIONS", xw-80, yw-80, xw+80, yw+80)
            L("ANNOTATIONS", xw+80, yw-80, xw-80, yw+80)

    # ── 8. SECTION CUT LINE A-A (horizontal, across full width + beyond) ──
    cl_y_track = y_drop_top + (y_main_top - y_drop_top) * 0.5  # midpoint
    section_y  = cl_y_track  # A-A cuts at CL of track
    L("CENTERLINE", -600, section_y, total_w + 600, section_y)
    # Section marks at each end
    for sx, lbl in [(-600, "A"), (total_w + 600, "A")]:
        T("ANNOTATIONS", sx - 80, section_y + 120, lbl, 220)
        arrow_down("ANNOTATIONS", sx, section_y - 100, 400)
        arrow_up("ANNOTATIONS",   sx, section_y + 100, 400)

    # ── 9. CENTRELINE OF TRACK (longitudinal, dashed) ────────────────
    cl_x = total_w / 2
    L("CENTERLINE", cl_x, y_drop_bot - toe_h - drop_wall_t - 600,
                    cl_x, y_main_top + curtain_h + 600)
    T("ANNOTATIONS", cl_x + 120, section_y - 80, "C OF TRACK", FONT)

    # ── 10. TRANSVERSE DIMENSION CHAIN (below outer boundary) ─────────
    dim_y = y_drop_top - 600
    x_cur = 0.0
    for i, sp in enumerate(t_sp):
        mid_x = x_cur + sp/2
        L("DIMENSIONS", x_cur, dim_y, x_cur+sp, dim_y)
        L("DIMENSIONS", x_cur, dim_y-120, x_cur, dim_y+120)
        L("DIMENSIONS", x_cur+sp, dim_y-120, x_cur+sp, dim_y+120)
        T("DIMENSIONS", mid_x - len(str(int(sp)))*55, dim_y - 320, f"{sp:.0f}", FONT)
        x_cur += sp
    # Total width dim
    _dim_line(ents, "DIMENSIONS", 0, dim_y-700, total_w, dim_y-700,
              f"TOTAL WIDTH: {total_w:.0f}mm", 350, FONT)

    # ── 11. LONGITUDINAL DIMENSION CHAIN (left of boundary) ───────────
    dim_x = -800
    y_cur = y_drop_top
    for i, ld in enumerate(l_dims):
        mid_y = y_cur + ld/2
        L("DIMENSIONS", dim_x, y_cur, dim_x, y_cur+ld)
        L("DIMENSIONS", dim_x-120, y_cur, dim_x+120, y_cur)
        L("DIMENSIONS", dim_x-120, y_cur+ld, dim_x+120, y_cur+ld)
        T("DIMENSIONS", dim_x - 800, mid_y - 80, f"{ld:.0f}", FONT)
        y_cur += ld
    # Total length dim
    _dim_line(ents, "DIMENSIONS", dim_x-1400, y_drop_top, dim_x-1400, y_main_top,
              f"TOTAL: {total_l:.0f}mm", 350, FONT)

    # ── 12. OFFSET DIM from CL (e.g. 1800) ───────────────────────────
    for od in off_dims:
        ox = cl_x + od
        _dim_line(ents, "DIMENSIONS", cl_x, section_y + 200, ox, section_y + 200,
                  f"{od:.0f}", 250, FONT)

    # ── 13. RIGHT-SIDE STACKED LAYER DIMS ────────────────────────────
    if lyr_dims:
        rx  = total_w + 600
        ry  = 0.0
        tot = sum(lyr_dims)
        for ld in lyr_dims:
            L("LEVELS", total_w+50, ry,      rx+400, ry)
            L("LEVELS", total_w+50, ry+ld,   rx+400, ry+ld)
            L("LEVELS", rx+400,    ry,        rx+400, ry+ld)
            T("LEVELS", rx+500,    ry+ld/2-80, f"{ld:.0f}", FONT)
            ry += ld
        L("LEVELS", rx+900, 0, rx+900, tot)
        L("LEVELS", rx+700, 0, rx+1100, 0)
        L("LEVELS", rx+700, tot, rx+1100, tot)
        T("LEVELS", rx+1150, tot/2-80, f"{tot:.0f} (TOTAL)", FONT)

    # ── 14. FLOW ARROW ───────────────────────────────────────────────
    arrow_down("ANNOTATIONS", cl_x, y_drop_bot - toe_h - drop_wall_t - 900, 700)
    T("ANNOTATIONS", cl_x + 150, y_drop_bot - toe_h - drop_wall_t - 600, "FLOW", FONT)

    # ── 15. DIRECTION ARROWS (KRA ←  BDCR →) ────────────────────────
    kra  = data.get("leftLabel",  "KRA")
    bdcr = data.get("rightLabel", "BDCR")
    L("ANNOTATIONS", -1800, section_y, -600, section_y)
    L("ANNOTATIONS", -1800, section_y, -1500, section_y+120)
    L("ANNOTATIONS", -1800, section_y, -1500, section_y-120)
    T("ANNOTATIONS", -1700, section_y+200, kra, FONT)
    L("ANNOTATIONS", total_w+600, section_y, total_w+1800, section_y)
    L("ANNOTATIONS", total_w+1800, section_y, total_w+1500, section_y+120)
    L("ANNOTATIONS", total_w+1800, section_y, total_w+1500, section_y-120)
    T("ANNOTATIONS", total_w+650, section_y+200, bdcr, FONT)

    # ── 16. REGION LABELS ────────────────────────────────────────────
    cw  = data.get("curtainWallLabel", "CURTAIN WALL")
    tw  = data.get("toeWallLabel",     "TOE WALL")
    dw2 = data.get("dropWallLabel",    "DROP WALL")

    # Curtain wall — diagonal label in top zone
    T("ANNOTATIONS", inset + 100, y_main_top + curtain_h*0.55, cw, FONT)

    # Toe wall — diagonal label in lower left
    T("ANNOTATIONS", inset + 100, y_drop_bot - toe_h*0.45, tw, FONT)

    # Drop wall — at bottom of drop wall box
    T("ANNOTATIONS", total_w/2 - 400,
      y_drop_bot - toe_h - drop_wall_t + 100, dw2, FONT)

    # ── 17. TITLE BLOCK ──────────────────────────────────────────────
    title_y = y_drop_bot - toe_h - drop_wall_t - 1800
    T("ANNOTATIONS", 0, title_y,
      f"DRAWING TYPE: Plan", FONT)
    T("ANNOTATIONS", 0, title_y - 280,
      f"SOURCE: {data.get('bridgeType','Bridge')}  |  SCALE: {data.get('scale','1:50')}  "
      f"|  DATE: {datetime.date.today()}  |  UNITS: mm", FONT)

    ymin = y_drop_bot - toe_h - drop_wall_t - 2500
    ymax = y_main_top + curtain_h + 1500
    bounds = {"xMin": -3500, "xMax": total_w + 4000,
              "yMin": ymin,  "yMax": ymax}
    return ents, bounds, {"rl_deck": 0, "rl_soffit": 0, "rl_ground": 0,
                          "total_x": total_w, "abut_w": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-SECTION GEOMETRY  (transverse cut view)
# ═══════════════════════════════════════════════════════════════════════════════
def _build_section(data):
    """
    X = transverse width, Y = depth/height.
    Uses layerDims as vertical stack, transverseSpacings as horizontal cells.
    """
    ents = []

    def L(lyr,x1,y1,x2,y2): ents.append({"type":"LINE","layer":lyr,"x1":x1,"y1":y1,"x2":x2,"y2":y2})
    def T(lyr,x,y,t,h=200): ents.append({"type":"TEXT","layer":lyr,"x":x,"y":y,"text":t,"height":h})

    t_sp     = data.get("transverseSpacings", [])
    lyr_dims = data.get("layerDims", [])

    if not t_sp:
        t_sp = [data.get("deckWidth", 5.0) * 1000]
    if not lyr_dims:
        thk = data.get("deckThickness", 0.8) * 1000
        lyr_dims = [thk]

    total_w  = sum(t_sp)
    total_h  = sum(lyr_dims)

    # Outer box
    L("DECK",0,0,total_w,0)
    L("DECK",0,total_h,total_w,total_h)
    L("DECK",0,0,0,total_h)
    L("DECK",total_w,0,total_w,total_h)

    # Vertical dividers at each transverse spacing
    x_cur = 0.0
    for i, sp in enumerate(t_sp):
        mid = x_cur + sp/2
        T("DIMENSIONS",mid-len(str(int(sp)))*80,-350,f"{sp:.0f}",190)
        x_cur += sp
        if i < len(t_sp)-1:
            L("PIER",x_cur,0,x_cur,total_h)

    # Horizontal dividers at each layer dim
    y_cur = 0.0
    for i, ld in enumerate(lyr_dims):
        T("LEVELS",total_w+200,y_cur+ld/2-80,f"{ld:.0f}",200)
        y_cur += ld
        if i < len(lyr_dims)-1:
            L("ABUTMENT",0,y_cur,total_w,y_cur)

    # CL
    L("CENTERLINE",total_w/2,-800,total_w/2,total_h+800)
    T("CENTERLINE",total_w/2+80,total_h+900,"CL",190)

    # Total width + height dims
    _dim_line(ents,"DIMENSIONS",0,-700,total_w,-700,f"WIDTH: {total_w:.0f}mm",400,220)
    _dim_line(ents,"DIMENSIONS",-900,0,-900,total_h,f"DEPTH: {total_h:.0f}mm",400,220)

    T("ANNOTATIONS",0,-1700,
      f"BRIDGE SECTION  —  AI GENERATED  |  1:1 MODEL SPACE  |  UNITS: mm  |  {datetime.date.today()}",280)

    bounds={"xMin":-2000,"xMax":total_w+3000,"yMin":-2000,"yMax":total_h+2000}
    return ents, bounds, {"rl_deck":total_h,"rl_soffit":0,"rl_ground":0,
                          "total_x":total_w,"abut_w":0}


# ═══════════════════════════════════════════════════════════════════════════════
# DISPATCHER  — routes to the right builder based on drawingType
# ═══════════════════════════════════════════════════════════════════════════════
def build_bridge_geometry(data):
    dtype = data.get("drawingType", "elevation").lower().strip()
    if "plan" in dtype:
        ents, bounds, meta = _build_plan(data)
    elif any(k in dtype for k in ("section", "cross", "transverse")):
        ents, bounds, meta = _build_section(data)
    else:                              # elevation (default)
        ents, bounds, meta = _build_elevation(data)
    meta["data"] = data
    return ents, bounds, meta


# ═══════════════════════════════════════════════════════════════════════════════
# DXF WRITER  (ezdxf)
# ═══════════════════════════════════════════════════════════════════════════════
def write_dxf(entities, output_path):
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()

    # All layers white (color 7) for consistent AutoCAD output
    for name in ["DECK","PIER","ABUTMENT","DIMENSIONS","LEVELS",
                 "ANNOTATIONS","FOUNDATION","BEARING","CENTERLINE","GRID"]:
        if name not in doc.layers:
            lyr = doc.layers.add(name, color=7)   # 7 = white in AutoCAD
            if name == "CENTERLINE":
                lyr.dxf.linetype = "DASHED"

    # Uniform text style
    if "CADSTYLE" not in doc.styles:
        doc.styles.add("CADSTYLE", font="romans.shx")

    for e in entities:
        layer = e.get("layer", "ANNOTATIONS")
        if e["type"] == "LINE":
            msp.add_line((e["x1"], e["y1"]), (e["x2"], e["y2"]),
                         dxfattribs={"layer": layer})
        elif e["type"] == "TEXT":
            msp.add_text(e["text"], dxfattribs={
                "layer":  layer,
                "height": e.get("height", 190),
                "insert": (e["x"], e["y"]),
                "style":  "CADSTYLE",
            })
        elif e["type"] == "CIRCLE":
            msp.add_circle((e["cx"], e["cy"]), e["r"],
                           dxfattribs={"layer": layer})

    doc.saveas(output_path)


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER THREAD
# ═══════════════════════════════════════════════════════════════════════════════
class CAD2Worker(QThread):
    log_msg     = pyqtSignal(str, str)           # message, level (info/ok/warn/err)
    step_done   = pyqtSignal(int)                # step index completed
    step_active = pyqtSignal(int)
    progress    = pyqtSignal(int)
    finished    = pyqtSignal(bool, str, object, object, str)
    # ok, msg, entities, bounds_meta, dxf_path

    STEPS = [
        "Load & encode file",
        "Send to Claude Vision AI",
        "Parse extracted dimensions & RL levels",
        "Build scaled bridge geometry",
        "Write DXF file (ezdxf)",
    ]

    def __init__(self, file_path, api_key=""):
        super().__init__()
        self.file_path = file_path
        self.api_key   = api_key

    def run(self):
        entities = bounds = meta = dxf_path = None
        try:
            # ── Step 0: Load & normalise ──────────────────────────────
            self.step_active.emit(0)
            ext = os.path.splitext(self.file_path)[1].lower()

            # Claude Vision only accepts: jpeg, png, gif, webp, pdf
            # Everything else (tiff, bmp, tga, ppm, ico, …) → convert to PNG via Pillow
            SUPPORTED_MIME = {
                ".jpg":  "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png":  "image/png",
                ".gif":  "image/gif",
                ".webp": "image/webp",
                ".pdf":  "application/pdf",
            }

            if ext in SUPPORTED_MIME:
                # Read directly — no conversion needed
                with open(self.file_path, "rb") as f:
                    raw = f.read()
                mime = SUPPORTED_MIME[ext]
                self.log_msg.emit(
                    f"Loaded: {os.path.basename(self.file_path)}  ({len(raw)//1024} KB)", "info"
                )
            else:
                # Unsupported format → convert to PNG in memory via Pillow
                self.log_msg.emit(
                    f"Format {ext.upper()} not natively supported — converting to PNG via Pillow…", "warn"
                )
                from PIL import Image as _PILImage
                import io as _io
                pil_img = _PILImage.open(self.file_path)
                # Convert CMYK / palette modes that PNG doesn't handle cleanly
                if pil_img.mode not in ("RGB", "RGBA", "L"):
                    pil_img = pil_img.convert("RGBA" if "transparency" in pil_img.info else "RGB")
                buf = _io.BytesIO()
                pil_img.save(buf, format="PNG")
                raw  = buf.getvalue()
                mime = "image/png"
                self.log_msg.emit(
                    f"Converted to PNG: {len(raw)//1024} KB  ({pil_img.width}×{pil_img.height}px)", "ok"
                )

            b64 = base64.b64encode(raw).decode()
            self.step_done.emit(0); self.progress.emit(15)

            # ── Step 1: AI Vision ─────────────────────────────────────
            self.step_active.emit(1)
            self.log_msg.emit("Sending to Claude Vision AI...", "info")

            import anthropic as _anthropic
            client = _anthropic.Anthropic(api_key=self.api_key)

            system_prompt = (
                "You are a senior bridge engineer and technical drawing interpreter. "
                "Analyse the uploaded drawing carefully and extract ALL dimensional data. "
                "Return ONLY a valid JSON object — no markdown, no explanation, no code fences.\n\n"

                "STEP 1 — Identify the drawing type:\n"
                "  'elevation'   : longitudinal side view showing spans, piers, abutments, RL levels\n"
                "  'plan'        : top/bird's-eye view showing bridge width, column grid, wing walls\n"
                "  'section'     : cross-section or transverse cut showing depth layers and widths\n\n"

                "STEP 2 — Extract dimensions IN MILLIMETRES (convert if shown in metres):\n\n"

                "FOR ALL TYPES:\n"
                "  drawingType          : 'elevation' | 'plan' | 'section'\n"
                "  bridgeType           : e.g. 'RC T-Beam', 'PSC Box', 'Steel Composite'\n"
                "  scale                : e.g. '1:100'\n"
                "  chainage             : chainage string if shown\n"
                "  notes                : key annotations, labels, special features\n\n"

                "FOR ELEVATION views:\n"
                "  totalSpan            : total bridge length in mm\n"
                "  spans                : [span1_mm, span2_mm, ...] — each individual span\n"
                "  numSpans             : integer count\n"
                "  numPiers             : integer count\n"
                "  deckThickness        : mm\n"
                "  deckWidth            : mm\n"
                "  pierHeight           : mm\n"
                "  pierWidth            : mm\n"
                "  abutmentWidth        : mm\n"
                "  abutmentHeight       : mm\n"
                "  rlDeck               : Reduced Level of deck top in metres\n"
                "  rlSoffit             : Reduced Level of soffit in metres\n"
                "  rlGround             : Reduced Level of ground/bed in metres\n"
                "  bearingType          : string\n\n"

                "FOR PLAN views:\n"
                "  transverseSpacings   : [s1_mm, s2_mm, ...] ALL spacings across the width "
                                         "exactly as dimensioned in the drawing "
                                         "(e.g. [900,600,900,600,900] for a 5-cell pier arrangement). "
                                         "READ EVERY NUMBER IN THE DIMENSION CHAIN ACROSS THE WIDTH.\n"
                "  longitudinalDims     : [d1_mm, d2_mm, ...] ALL dimensions along the track/flow "
                                         "direction (e.g. [3576,6200] from the left-side dim chain). "
                                         "READ EVERY NUMBER IN THE LONGITUDINAL CHAIN.\n"
                "  layerDims            : [l1_mm, l2_mm, ...] stacked dimensions shown on the right "
                                         "side (e.g. [300,250,245,450,555,300] summing to 2100). "
                                         "INCLUDE EVERY NUMBER IN THE STACK.\n"
                "  offsetDims           : [o1_mm, ...] any offset dimensions from CL (e.g. [1800])\n"
                "  deckWidth            : total transverse width in mm (sum of transverseSpacings)\n"
                "  curtainWallLabel     : label text if present\n"
                "  toeWallLabel         : label text if present\n"
                "  dropWallLabel        : label text if present\n"
                "  leftLabel            : direction label on left (e.g. 'KRA')\n"
                "  rightLabel           : direction label on right (e.g. 'BDCR')\n\n"

                "FOR SECTION/CROSS-SECTION views:\n"
                "  transverseSpacings   : [s1_mm, ...] horizontal cell widths across the section\n"
                "  layerDims            : [l1_mm, ...] vertical layer thicknesses top to bottom\n"
                "  deckWidth            : total width in mm\n"
                "  deckThickness        : total depth in mm\n\n"

                "CRITICAL RULES:\n"
                "  - All dimensions must be in MILLIMETRES. Convert metres × 1000.\n"
                "  - Read EVERY individual number in each dimension chain — do not sum or skip any.\n"
                "  - If a value is not shown, set it to null (not zero, not estimated).\n"
                "  - Return raw JSON only — no markdown fences."
            )

            if mime == "application/pdf":
                content = [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                    {"type": "text", "text": "Extract all bridge engineering data from this drawing PDF."}
                ]
            else:
                content = [
                    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                    {"type": "text", "text": "Extract all bridge engineering data from this drawing."}
                ]

            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": content}]
            )
            raw_text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            self.log_msg.emit("AI response received.", "ok")
            self.step_done.emit(1); self.progress.emit(50)

            # ── Step 2: Parse JSON ────────────────────────────────────
            self.step_active.emit(2)
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"): cleaned = cleaned[4:]
            data = json.loads(cleaned.strip())

            if not data.get("spans"):
                ns = int(data.get("numSpans") or 1)
                ts = float(data.get("totalSpan") or 30)
                data["spans"] = [round(ts / ns, 3)] * ns

            dtype = data.get("drawingType", "elevation").lower()
            if "plan" in dtype:
                t_sp  = data.get("transverseSpacings") or []
                l_dim = data.get("longitudinalDims") or []
                self.log_msg.emit(
                    f"Drawing type: PLAN  |  Transverse cells: {len(t_sp)}  "
                    f"|  Total width: {sum(t_sp):.0f}mm  |  Total length: {sum(l_dim):.0f}mm", "ok"
                )
                self.log_msg.emit(f"Transverse: {t_sp}", "info")
                self.log_msg.emit(f"Longitudinal: {l_dim}", "info")
                lyr = data.get("layerDims") or []
                if lyr:
                    self.log_msg.emit(f"Layer dims: {lyr}  (total {sum(lyr):.0f}mm)", "info")
            elif any(k in dtype for k in ("section","cross")):
                t_sp  = data.get("transverseSpacings") or []
                lyr_d = data.get("layerDims") or []
                self.log_msg.emit(
                    f"Drawing type: SECTION  |  Width: {sum(t_sp):.0f}mm  "
                    f"|  Depth layers: {lyr_d}", "ok"
                )
            else:
                self.log_msg.emit(
                    f"Drawing type: ELEVATION  |  Spans: {len(data.get('spans',[]))}  "
                    f"|  Total: {data.get('totalSpan','?')}mm  "
                    f"|  RL Deck: {data.get('rlDeck','?')}m", "ok"
                )
            self.log_msg.emit(
                f"Bridge type: {data.get('bridgeType','—')}  |  Scale: {data.get('scale','—')}", "info"
            )
            self.step_done.emit(2); self.progress.emit(65)

            # ── Step 3: Build geometry ────────────────────────────────
            self.step_active.emit(3)
            entities, bounds, meta = build_bridge_geometry(data)
            meta["data"] = data
            self.log_msg.emit(f"Geometry: {len(entities)} entities across {len(LAYERS)} layers", "ok")
            self.step_done.emit(3); self.progress.emit(82)

            # ── Step 4: Write DXF ─────────────────────────────────────
            self.step_active.emit(4)
            tmp = tempfile.mkstemp(suffix=".dxf")[1]
            write_dxf(entities, tmp)
            dxf_size = os.path.getsize(tmp) // 1024
            self.log_msg.emit(f"DXF written: {dxf_size} KB  |  1:1 model space  |  units: mm", "ok")
            self.step_done.emit(4); self.progress.emit(100)

            self.finished.emit(True, "Success", entities, (bounds, meta), tmp)

        except json.JSONDecodeError as e:
            self.log_msg.emit(f"JSON parse error: {e}", "err")
            self.log_msg.emit("Using default 30m single-span bridge geometry.", "warn")
            default_data = {"totalSpan": 30, "spans": [30], "deckThickness": 0.8,
                            "pierHeight": 6, "pierWidth": 1.2, "abutmentWidth": 1.5,
                            "rlDeck": 10, "rlGround": 0, "bridgeType": "RC Bridge"}
            entities, bounds, meta = build_bridge_geometry(default_data)
            meta["data"] = default_data
            tmp = tempfile.mkstemp(suffix=".dxf")[1]
            write_dxf(entities, tmp)
            self.finished.emit(True, "Used default geometry (AI parse failed)", entities, (bounds, meta), tmp)
        except Exception as e:
            import traceback
            self.log_msg.emit(f"ERROR: {e}", "err")
            self.log_msg.emit(traceback.format_exc()[:600], "err")
            self.finished.emit(False, str(e), None, None, "")


# ═══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE GRAPHICS VIEW
# ═══════════════════════════════════════════════════════════════════════════════
class BridgeGraphicsView(QGraphicsView):
    """Pan (middle-click drag / left-drag), Zoom (wheel), layer toggle."""

    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setRenderHint(self.renderHints().Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor("#080E14")))
        self.setStyleSheet("border: none;")
        self._items_by_layer = {}   # layer -> [QGraphicsItem]
        self._layer_visible  = {k: v["on"] for k, v in LAYERS.items()}

    def load_entities(self, entities, bounds):
        self.scene.clear()
        self._items_by_layer = {k: [] for k in LAYERS}
        y_max = bounds["yMax"]

        for e in entities:
            layer = e.get("layer", "ANNOTATIONS")
            cfg   = LAYERS.get(layer, {"color": "#ffffff", "width": 1.0, "dash": False})
            color = QColor(cfg["color"])
            w     = cfg.get("width", 1.0)
            pen   = QPen(color, w)
            pen.setCosmetic(True)
            if cfg.get("dash"):
                pen.setStyle(Qt.PenStyle.DashLine)

            item = None
            # Flip Y for screen (Qt y-down, DXF y-up)
            if e["type"] == "LINE":
                item = self.scene.addLine(
                    e["x1"], y_max - e["y1"], e["x2"], y_max - e["y2"], pen
                )
            elif e["type"] == "CIRCLE":
                r = e["r"]
                item = self.scene.addEllipse(
                    e["cx"] - r, y_max - e["cy"] - r, 2*r, 2*r,
                    pen, QBrush(Qt.BrushStyle.NoBrush)
                )
            elif e["type"] == "TEXT":
                txt = QGraphicsTextItem(e["text"])
                # Uniform font: Courier New, size scaled from DXF height units
                # DXF height 190 → ~6pt at typical zoom; keep consistent
                fs = max(6, int(e.get("height", 190) * 0.50))
                font = QFont("Courier New", fs)
                font.setStyleHint(QFont.StyleHint.Monospace)
                font.setWeight(QFont.Weight.Normal)
                txt.setFont(font)
                txt.setDefaultTextColor(color)
                txt.setPos(e["x"], y_max - e["y"])
                self.scene.addItem(txt)
                item = txt

            if item and layer in self._items_by_layer:
                self._items_by_layer[layer].append(item)
                item.setVisible(self._layer_visible.get(layer, True))

        # Fit scene
        pad = (bounds["xMax"] - bounds["xMin"]) * 0.04
        rect = QRectF(bounds["xMin"] - pad, 0, bounds["xMax"] - bounds["xMin"] + pad*2,
                      y_max - bounds["yMin"] + pad)
        self.setSceneRect(rect)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def set_layer_visible(self, layer, visible):
        self._layer_visible[layer] = visible
        for item in self._items_by_layer.get(layer, []):
            item.setVisible(visible)

    def wheelEvent(self, e: QWheelEvent):
        factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key.Key_F:
            rect = self.sceneRect()
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        super().keyPressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
# DROP ZONE
# ═══════════════════════════════════════════════════════════════════════════════
class DropZone2(QFrame):
    file_dropped = pyqtSignal(str)
    EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp",
            ".tiff", ".tif", ".bmp", ".tga", ".ppm", ".pgm",
            ".ico", ".dib", ".pcx", ".pdf"}

    def __init__(self):
        super().__init__()
        self.setObjectName("dropZone")
        self.setMinimumHeight(130)
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(6)
        self.icon_lbl = QLabel("⬆")
        self.icon_lbl.setFont(QFont("Segoe UI", 22))
        self.icon_lbl.setStyleSheet(f"color:{COLORS['text_muted']};border:none;")
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icon_lbl)
        self.main_lbl = QLabel("Click or drag a bridge drawing here")
        self.main_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.main_lbl.setStyleSheet(f"color:{COLORS['text_secondary']};border:none;")
        self.main_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.main_lbl)
        self.fmt_lbl = QLabel("JPEG  ·  PNG  ·  GIF  ·  WEBP  ·  TIFF  ·  BMP  ·  TGA  ·  PDF  ·  and more")
        self.fmt_lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;border:none;")
        self.fmt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.fmt_lbl)

    def set_file(self, path):
        self.icon_lbl.setText("✓")
        self.icon_lbl.setStyleSheet(f"color:{COLORS['accent']};border:none;font-size:22px;")
        self.main_lbl.setText(f"📄  {os.path.basename(path)}")
        self.fmt_lbl.setText(f"Ready — {os.path.splitext(path)[1].upper()}")
        self.setObjectName("dropZoneActive")
        self.style().unpolish(self); self.style().polish(self)

    def reset(self):
        self.icon_lbl.setText("⬆")
        self.icon_lbl.setStyleSheet(f"color:{COLORS['text_muted']};border:none;font-size:22px;")
        self.main_lbl.setText("Click or drag a bridge drawing here")
        self.fmt_lbl.setText("JPEG  ·  PNG  ·  GIF  ·  WEBP  ·  TIFF  ·  BMP  ·  TGA  ·  PDF  ·  and more")
        self.setObjectName("dropZone")
        self.style().unpolish(self); self.style().polish(self)

    def mousePressEvent(self, e):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Bridge Drawing", "",
            "Drawing Files (*.jpg *.jpeg *.png *.gif *.webp *.tiff *.tif *.bmp *.tga *.ppm *.pgm *.ico *.pdf)"
        )
        if path: self.file_dropped.emit(path)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            ext = os.path.splitext(e.mimeData().urls()[0].toLocalFile())[1].lower()
            if ext in self.EXTS:
                e.acceptProposedAction()
                self.setObjectName("dropZoneActive")
                self.style().unpolish(self); self.style().polish(self)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self.setObjectName("dropZone")
        self.style().unpolish(self); self.style().polish(self)

    def dropEvent(self, e: QDropEvent):
        path = e.mimeData().urls()[0].toLocalFile()
        if os.path.splitext(path)[1].lower() in self.EXTS:
            self.file_dropped.emit(path)
        e.acceptProposedAction()


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE STEP WIDGET
# ═══════════════════════════════════════════════════════════════════════════════
class Step2(QWidget):
    def __init__(self, n, desc):
        super().__init__()
        self._n = n
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2); lay.setSpacing(10)
        self.num = QLabel(str(n))
        self.num.setFixedSize(24, 24)
        self.num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.num.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._idle()
        lay.addWidget(self.num)
        self.desc = QLabel(desc)
        self.desc.setStyleSheet(f"color:{COLORS['text_secondary']};font-size:12px;")
        self.desc.setWordWrap(True)
        lay.addWidget(self.desc, 1)
        self.tag = QLabel()
        self.tag.setVisible(False)
        lay.addWidget(self.tag)

    def _idle(self):
        self.num.setStyleSheet(f"background:{COLORS['border']};color:{COLORS['text_muted']};border-radius:12px;")
    def set_active(self):
        self.num.setStyleSheet(f"background:{COLORS['accent_glow']};color:{COLORS['accent']};border:1px solid {COLORS['accent']};border-radius:12px;")
        self.tag.setText("running"); self.tag.setObjectName("tagWarning")
        self.tag.style().unpolish(self.tag); self.tag.style().polish(self.tag)
        self.tag.setVisible(True)
    def set_done(self):
        self.num.setText("✓")
        self.num.setStyleSheet(f"background:{COLORS['success_bg']};color:{COLORS['success']};border-radius:12px;")
        self.tag.setText("done"); self.tag.setObjectName("tagSuccess")
        self.tag.style().unpolish(self.tag); self.tag.style().polish(self.tag)
        self.tag.setVisible(True)
    def set_error(self):
        self.num.setText("✗")
        self.num.setStyleSheet(f"background:{COLORS['error_bg']};color:{COLORS['error']};border-radius:12px;")
        self.tag.setText("error"); self.tag.setObjectName("tagWarning")
        self.tag.style().unpolish(self.tag); self.tag.style().polish(self.tag)
        self.tag.setVisible(True)
    def reset(self):
        self.num.setText(str(self._n)); self._idle(); self.tag.setVisible(False)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER TOGGLE PANEL
# ═══════════════════════════════════════════════════════════════════════════════
class LayerPanel(QFrame):
    layer_toggled = pyqtSignal(str, bool)

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setFixedWidth(195)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12); lay.setSpacing(4)
        hdr = QLabel("LAYERS")
        hdr.setStyleSheet(f"color:{COLORS['text_muted']};font-size:10px;font-weight:700;letter-spacing:1.5px;")
        lay.addWidget(hdr)
        self._checks = {}
        for layer, cfg in LAYERS.items():
            row = QHBoxLayout(); row.setSpacing(6)
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{cfg['color']};font-size:10px;border:none;")
            row.addWidget(dot)
            cb = QCheckBox(cfg["label"])
            cb.setChecked(cfg["on"])
            cb.setStyleSheet(f"font-size:11px;color:{COLORS['text_primary']};")
            cb.stateChanged.connect(lambda state, l=layer: self.layer_toggled.emit(l, bool(state)))
            row.addWidget(cb, 1)
            lay.addLayout(row)
            self._checks[layer] = cb

        lay.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        all_on = QPushButton("All On"); all_on.setObjectName("secondaryBtn")
        all_on.setFixedHeight(28)
        all_on.clicked.connect(lambda: [cb.setChecked(True) for cb in self._checks.values()])
        all_off = QPushButton("All Off"); all_off.setObjectName("secondaryBtn")
        all_off.setFixedHeight(28)
        all_off.clicked.connect(lambda: [cb.setChecked(False) for cb in self._checks.values()])
        btn_row.addWidget(all_on); btn_row.addWidget(all_off)
        lay.addLayout(btn_row)
        lay.addStretch()

        hint = QLabel("Scroll  ·  Zoom\nDrag   ·  Pan\nF key  ·  Fit view")
        hint.setStyleSheet(f"color:{COLORS['text_muted']};font-size:10px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hint)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════
class CAD2Panel(QWidget):
    def __init__(self):
        super().__init__()
        self.current_file = None
        self.dxf_tmp      = None
        self.worker       = None
        self.settings     = QSettings("BES", "BridgeEngineeringSuite")
        self._log_lines   = []
        self._entities    = []
        self._bounds      = None
        self._extracted   = {}
        self._build()

    # ──────────────────────────────────────────────────────────────────────────
    def _build(self):
        # Root: left panel (upload/controls) + right (viewer)
        # We use a QSplitter so user can resize
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #E2E8F0; }")
        outer.addWidget(splitter)

        # ── LEFT scroll panel ─────────────────────────────────────────
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setMinimumWidth(380)
        left_scroll.setMaximumWidth(480)
        left_w = QWidget()
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(28, 28, 20, 28); left_lay.setSpacing(0)
        left_scroll.setWidget(left_w)

        # Header
        t = QLabel("CAD Process 2")
        t.setObjectName("panelTitle")
        left_lay.addWidget(t)
        s = QLabel("Upload a bridge drawing (image or PDF) — Claude Vision AI extracts all "
                   "dimensions and RL levels, then generates a scaled DXF with 10 named layers "
                   "and an interactive elevation preview.")
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        left_lay.addWidget(s)
        left_lay.addSpacing(20)

        # ── API key card ──────────────────────────────────────────────
        kc = QFrame(); kc.setObjectName("card")
        kl = QVBoxLayout(kc); kl.setContentsMargins(18, 14, 18, 14); kl.setSpacing(8)
        kh = QHBoxLayout()
        kt = QLabel("Anthropic API Key"); kt.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        kh.addWidget(kt); kh.addStretch()
        self.key_status = QLabel("● Not set")
        self.key_status.setStyleSheet(f"color:{COLORS['warning']};font-size:11px;")
        kh.addWidget(self.key_status); kl.addLayout(kh)
        kr = QHBoxLayout(); kr.setSpacing(6)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("sk-ant-api03-...")
        saved = self.settings.value("api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
        if saved: self.key_input.setText(saved); self._upd_key(saved)
        self.key_input.textChanged.connect(lambda t: self._upd_key(t.strip()))
        kr.addWidget(self.key_input)
        tb = QPushButton("Show"); tb.setObjectName("secondaryBtn"); tb.setFixedWidth(52)
        tb.clicked.connect(lambda: self._toggle_vis(tb)); kr.addWidget(tb)
        sb = QPushButton("Save"); sb.setObjectName("primaryBtn"); sb.setFixedWidth(60)
        sb.clicked.connect(self._save_key); kr.addWidget(sb)
        kl.addLayout(kr)
        left_lay.addWidget(kc); left_lay.addSpacing(12)

        # ── Upload card ───────────────────────────────────────────────
        uc = QFrame(); uc.setObjectName("accentCard")
        ul = QVBoxLayout(uc); ul.setContentsMargins(18, 14, 18, 14); ul.setSpacing(8)
        ut = QLabel("Upload Bridge Drawing"); ut.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        ul.addWidget(ut)
        self.drop_zone = DropZone2(); self.drop_zone.file_dropped.connect(self._on_file)
        ul.addWidget(self.drop_zone)
        ubr = QHBoxLayout(); ubr.setSpacing(8)
        self.proc_btn = QPushButton("▶   Analyse & Generate DXF")
        self.proc_btn.setObjectName("primaryBtn"); self.proc_btn.setFixedHeight(42)
        self.proc_btn.setEnabled(False); self.proc_btn.clicked.connect(self._start)
        ubr.addWidget(self.proc_btn)
        self.clr_btn = QPushButton("Clear"); self.clr_btn.setObjectName("secondaryBtn")
        self.clr_btn.setFixedHeight(42); self.clr_btn.setEnabled(False)
        self.clr_btn.clicked.connect(self._clear); ubr.addWidget(self.clr_btn)
        ubr.addStretch(); ul.addLayout(ubr)
        left_lay.addWidget(uc); left_lay.addSpacing(12)

        # ── Progress card ─────────────────────────────────────────────
        self.prog_card = QFrame(); self.prog_card.setObjectName("card")
        self.prog_card.setVisible(False)
        pg = QVBoxLayout(self.prog_card); pg.setContentsMargins(18, 14, 18, 14); pg.setSpacing(8)
        ph = QHBoxLayout()
        ph.addWidget(self._bold("Processing pipeline")); ph.addStretch()
        self.pct = QLabel("0%")
        self.pct.setStyleSheet(f"color:{COLORS['accent']};font-weight:600;font-size:13px;")
        ph.addWidget(self.pct); pg.addLayout(ph)
        self.prog_bar = QProgressBar(); self.prog_bar.setFixedHeight(6); self.prog_bar.setRange(0, 100)
        pg.addWidget(self.prog_bar)
        self.steps = []
        for i, desc in enumerate(CAD2Worker.STEPS, 1):
            st = Step2(i, desc); pg.addWidget(st); self.steps.append(st)
        pg.addWidget(QLabel("Live log").setParent(None) or
                     self._muted("Live log"))
        self.log_box = QLabel(); self.log_box.setWordWrap(True)
        self.log_box.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.log_box.setStyleSheet(
            f"background:{COLORS['input_bg']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;padding:8px;font-size:11px;color:{COLORS['text_secondary']};"
            f"font-family:'Consolas','Courier New',monospace;min-height:70px;"
        )
        pg.addWidget(self.log_box)
        left_lay.addWidget(self.prog_card); left_lay.addSpacing(12)

        # ── Result / download card ────────────────────────────────────
        self.res_card = QFrame(); self.res_card.setObjectName("card")
        self.res_card.setVisible(False)
        rl2 = QVBoxLayout(self.res_card); rl2.setContentsMargins(18, 14, 18, 14); rl2.setSpacing(10)
        rh = QHBoxLayout()
        ri = QLabel("✓"); ri.setFont(QFont("Segoe UI", 18))
        ri.setStyleSheet(f"color:{COLORS['success']};"); rh.addWidget(ri)
        self.res_title = QLabel("Files ready")
        self.res_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold)); rh.addWidget(self.res_title)
        rh.addStretch(); rl2.addLayout(rh)
        self.res_desc = QLabel(); self.res_desc.setWordWrap(True)
        self.res_desc.setStyleSheet(f"color:{COLORS['text_secondary']};font-size:12px;")
        rl2.addWidget(self.res_desc)

        # Extracted data grid
        self.data_grid = QFrame(); self.data_grid.setObjectName("card")
        self.data_grid.setVisible(False)
        dg_lay = QGridLayout(self.data_grid)
        dg_lay.setContentsMargins(12, 10, 12, 10); dg_lay.setSpacing(4)
        self.data_labels = {}
        fields = [
            ("Bridge Type", "bridgeType"), ("Total Span", "totalSpan"),
            ("No. of Spans", "numSpans"), ("RL Deck", "rlDeck"),
            ("RL Soffit", "rlSoffit"), ("RL Ground", "rlGround"),
            ("Deck Thickness", "deckThickness"), ("Pier Height", "pierHeight"),
            ("Drawing Scale", "scale"), ("Bearing", "bearingType"),
        ]
        for row, (label, key) in enumerate(fields):
            lbl = QLabel(label + ":"); lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;")
            val = QLabel("—"); val.setStyleSheet(f"color:{COLORS['text_primary']};font-size:11px;font-weight:600;")
            dg_lay.addWidget(lbl, row, 0); dg_lay.addWidget(val, row, 1)
            self.data_labels[key] = val
        rl2.addWidget(self.data_grid)

        dxf_btn = QPushButton("⬇   Save DXF File"); dxf_btn.setObjectName("primaryBtn")
        dxf_btn.setFixedHeight(40); dxf_btn.clicked.connect(self._save_dxf)
        rl2.addWidget(dxf_btn)
        new_btn = QPushButton("Process another file"); new_btn.setObjectName("secondaryBtn")
        new_btn.setFixedHeight(36); new_btn.clicked.connect(self._reset)
        rl2.addWidget(new_btn)
        left_lay.addWidget(self.res_card)
        left_lay.addStretch()

        splitter.addWidget(left_scroll)

        # ── RIGHT: layer panel + graphics view ───────────────────────
        right_w = QWidget()
        right_w.setStyleSheet("background:#080E14;")
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(0, 0, 0, 0); right_lay.setSpacing(0)

        # Top bar
        top_bar = QFrame()
        top_bar.setStyleSheet(f"background:{COLORS['navy']};border-bottom:1px solid {COLORS['navy_border']};")
        top_bar.setFixedHeight(38)
        tb_lay = QHBoxLayout(top_bar)
        tb_lay.setContentsMargins(14, 0, 14, 0)
        vw_lbl = QLabel("BRIDGE ELEVATION VIEWER")
        vw_lbl.setStyleSheet(f"color:{COLORS['accent']};font-size:10px;font-weight:700;letter-spacing:2px;")
        tb_lay.addWidget(vw_lbl)
        tb_lay.addStretch()
        hint_lbl = QLabel("Scroll = Zoom  ·  Drag = Pan  ·  F = Fit  ·  1:1 Model Space")
        hint_lbl.setStyleSheet(f"color:{COLORS['navy_border']};font-size:10px;")
        tb_lay.addWidget(hint_lbl)
        right_lay.addWidget(top_bar)

        # View area
        view_row = QHBoxLayout(); view_row.setSpacing(0); view_row.setContentsMargins(0, 0, 0, 0)

        self.layer_panel = LayerPanel()
        self.layer_panel.layer_toggled.connect(self._on_layer_toggle)
        self.layer_panel.setStyleSheet(f"background:{COLORS['off_white']};border-right:1px solid {COLORS['border']};border-radius:0;")
        view_row.addWidget(self.layer_panel)

        self.gfx_view = BridgeGraphicsView()
        view_row.addWidget(self.gfx_view, 1)
        right_lay.addLayout(view_row, 1)

        # Bottom status bar
        self.status_bar = QLabel("  No drawing loaded — upload a file and click Analyse")
        self.status_bar.setFixedHeight(26)
        self.status_bar.setStyleSheet(
            f"background:{COLORS['navy']};color:{COLORS['navy_border']};"
            f"font-size:10px;font-family:'Consolas','Courier New',monospace;"
            f"border-top:1px solid {COLORS['navy_border']};padding-left:10px;"
        )
        right_lay.addWidget(self.status_bar)
        splitter.addWidget(right_w)

        splitter.setSizes([420, 800])

    # ──────────────────────────────────────────────────────────────────────────
    def _bold(self, t):
        l = QLabel(t); l.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold)); return l

    def _muted(self, t):
        l = QLabel(t); l.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;font-weight:600;margin-top:4px;"); return l

    def _upd_key(self, key):
        if key.startswith("sk-ant"):
            self.key_status.setText("● Claude Vision active")
            self.key_status.setStyleSheet(f"color:{COLORS['success']};font-size:11px;")
        else:
            self.key_status.setText("● Not set")
            self.key_status.setStyleSheet(f"color:{COLORS['warning']};font-size:11px;")

    def _toggle_vis(self, btn):
        if self.key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Normal); btn.setText("Hide")
        else:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Password); btn.setText("Show")

    def _save_key(self):
        key = self.key_input.text().strip()
        self.settings.setValue("api_key", key); os.environ["ANTHROPIC_API_KEY"] = key
        self._upd_key(key)

    def _get_key(self):
        return self.key_input.text().strip() or os.environ.get("ANTHROPIC_API_KEY", "")

    def _on_file(self, path):
        self.current_file = path; self.drop_zone.set_file(path)
        self.proc_btn.setEnabled(True); self.clr_btn.setEnabled(True)

    def _clear(self):
        self.current_file = None; self.drop_zone.reset()
        self.proc_btn.setEnabled(False); self.clr_btn.setEnabled(False)

    def _log(self, msg, level="info"):
        prefix = {"info": "  ", "ok": "✓ ", "warn": "⚠ ", "err": "✗ "}.get(level, "  ")
        self._log_lines.append(prefix + msg)
        if len(self._log_lines) > 12: self._log_lines = self._log_lines[-12:]
        self.log_box.setText("\n".join(self._log_lines))

    def _start(self):
        if not self.current_file: return
        self.proc_btn.setEnabled(False); self.clr_btn.setEnabled(False)
        self.res_card.setVisible(False); self.prog_card.setVisible(True)
        self.prog_bar.setValue(0); self.pct.setText("0%")
        self._log_lines = []; self.log_box.setText("")
        for st in self.steps: st.reset()
        key = self._get_key()
        self._log(f"Mode: {'Claude Vision AI' if key else 'No API key — aborting'}", "info")
        if not key:
            self._log("Please enter your Anthropic API key above.", "err")
            self.proc_btn.setEnabled(True); self.clr_btn.setEnabled(True)
            return
        self.status_bar.setText("  ⏳ Processing drawing…")
        self.worker = CAD2Worker(self.current_file, key)
        self.worker.log_msg.connect(self._log)
        self.worker.step_active.connect(lambda i: self.steps[i].set_active() if i < len(self.steps) else None)
        self.worker.step_done.connect(lambda i: self.steps[i].set_done() if i < len(self.steps) else None)
        self.worker.progress.connect(lambda p: (self.prog_bar.setValue(p), self.pct.setText(f"{p}%")))
        self.worker.finished.connect(self._on_done)
        self.worker.start()

    def _on_done(self, ok, msg, entities, bounds_meta, dxf_tmp):
        self.prog_card.setVisible(False)
        if ok and entities:
            self._entities = entities
            bounds, meta = bounds_meta
            self._bounds = bounds
            self._extracted = meta.get("data", {})
            self.dxf_tmp = dxf_tmp

            # Load into viewer
            self.gfx_view.load_entities(entities, bounds)

            # Populate extracted data grid
            self.data_grid.setVisible(True)
            for key, lbl in self.data_labels.items():
                val = self._extracted.get(key)
                if val is not None:
                    if isinstance(val, float): lbl.setText(f"{val:.3f}")
                    else: lbl.setText(str(val))
                else: lbl.setText("—")

            dxf_kb = os.path.getsize(dxf_tmp) // 1024 if dxf_tmp and os.path.exists(dxf_tmp) else 0
            self.res_title.setText("DXF Generated Successfully")
            self.res_desc.setText(
                f"{len(entities)} entities  ·  10 named layers  ·  {dxf_kb} KB  ·  1:1 model space\n"
                f"Open the elevation viewer on the right to inspect. "
                f"Scroll to zoom, drag to pan, F to fit view."
            )
            self.status_bar.setText(
                f"  ✓  {len(entities)} entities  |  "
                f"{self._extracted.get('bridgeType','—')}  |  "
                f"Total {self._extracted.get('totalSpan','—')}m  |  "
                f"RL Deck {self._extracted.get('rlDeck','—')}m"
            )
        else:
            self.res_title.setText("Processing Error")
            self.res_desc.setText(f"{msg}\n\nCheck your API key or try a cleaner image.")
            self.status_bar.setText("  ✗  Error — see log above")
            self.proc_btn.setEnabled(True); self.clr_btn.setEnabled(True)

        self.res_card.setVisible(True)

    def _on_layer_toggle(self, layer, visible):
        self.gfx_view.set_layer_visible(layer, visible)

    def _save_dxf(self):
        if not self.dxf_tmp or not os.path.exists(self.dxf_tmp): return
        base = os.path.splitext(os.path.basename(self.current_file or "bridge"))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Save DXF File", f"{base}_AI.dxf", "AutoCAD DXF (*.dxf)"
        )
        if path:
            shutil.copy2(self.dxf_tmp, path)
            self._log(f"DXF saved: {path}", "ok")

    def _reset(self):
        self.res_card.setVisible(False)
        self.data_grid.setVisible(False)
        self._clear()
        self.dxf_tmp = None
        self.gfx_view.scene.clear()
        self.status_bar.setText("  No drawing loaded — upload a file and click Analyse")
