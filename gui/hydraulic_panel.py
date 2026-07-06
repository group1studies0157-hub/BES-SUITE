"""
hydraulic_panel.py  —  Bridge Engineering Suite
Hydraulic Calculations panel (RDSO RBF-16)

Two modes selectable at top:
  Option 1 — New Line        : RBF-16 catchment method
  Option 2 — Doubling/Tripling/Quadrupling : OHFL-based method (SS Code 4.8.1)
"""

import math
import os
import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QComboBox, QGridLayout,
    QMessageBox, QFileDialog, QSizePolicy, QStackedWidget, QButtonGroup,
    QSplitter
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QDoubleValidator

from gui.styles import COLORS
from gui.fig31_lookup import get_tc_ratio, get_1hr_ratio, get_scaling_k
from gui.smart_extract import SmartExtractWidget


# ──────────────────────────────────────────────────────────────────────────────
#  SHARED CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

SOIL_OPTIONS = [
    "Red Soil / Clayey Loam / Grey or Brown Alluvial / Cultivated plains / "
    "Barren / Submontanous and Plateau / Tall crops / Wooded Areas",
    "Sandy Soil / Sandy loam / Arid Areas",
    "Alluvial / Silty loam / Coastal area",
    "Black cotton / Clayey soil / Lightly covered / Light wooded / "
    "Plain and Barren / Submontanous & Plateau",
    "Hilly soil / Plateau & Barren",
]

SOIL_COEFF = {
    "Red Soil / Clayey Loam / Grey or Brown Alluvial / Cultivated plains / "
    "Barren / Submontanous and Plateau / Tall crops / Wooded Areas": ("c", 0.415),
    "Sandy Soil / Sandy loam / Arid Areas": ("a", 0.0249),
    "Alluvial / Silty loam / Coastal area": ("b", 0.332),
    "Black cotton / Clayey soil / Lightly covered / Light wooded / "
    "Plain and Barren / Submontanous & Plateau": ("d", 0.456),
    "Hilly soil / Plateau & Barren": ("e", 0.498),
}

SUB_ZONES = ["3E", "1", "2", "3A", "3B", "3C", "3D", "4", "5", "6", "7"]

STRUCTURE_TYPES = ["RCC BOX", "ARCH", "SLAB CULVERT", "PIPE CULVERT", "BRIDGE"]

SPAN_TYPES = ["RCC Box", "Arch Bridge", "RCC Slab", "PSC Girder",
              "Steel Girder", "Plate Girder", "Pipe Culvert", "Open Web Girder"]

PROPOSED_BY = ["CAO/C/SC", "CAO/C/BZA", "CAO/C/HYB", "CAO/C/GTL",
               "CAO/C/GNT", "CAO/C/NED", "RVNL/BZA", "RVNL/SC", "RVNL/HYB"]

DIVISIONS = ["SC", "BZA", "HYB", "GTL", "GNT", "NED", "MAS"]

BRIDGE_CATEGORIES = ["Minor Bridge", "Major Bridge", "Bridge", "Culvert"]

STD_FB = 1.000   # Standard freeboard (m) per SS Code 4.9.x


# ──────────────────────────────────────────────────────────────────────────────
#  OPTION 1: RBF-16 CALCULATION ENGINE (New Line)
# ──────────────────────────────────────────────────────────────────────────────

def _get_areal_reduction_factor(area_km2: float, tc_min: float) -> float:
    if tc_min < 30:   band = 0
    elif tc_min <= 60: band = 1
    else:              band = 2
    table = [
        (2.5,  [0.72, 0.81, 0.88]),
        (5.0,  [0.71, 0.80, 0.87]),
        (13.0, [0.70, 0.79, 0.86]),
        (25.0, [0.68, 0.78, 0.85]),
    ]
    for max_a, factors in table:
        if area_km2 <= max_a:
            return factors[band]
    return table[-1][1][band]


def compute_newline(inp: dict) -> dict:
    try:
        A        = float(inp["catchment_area"])
        L        = float(inp["stream_length"])
        H_f      = float(inp["farthest_height"])
        BL       = float(inp["bed_level"])
        OHFL     = float(inp["ohfl"])
        R50      = float(inp["r50"])
        FL       = float(inp["formation_level"])
        vel      = float(inp["velocity"])
        width    = float(inp["width"])
        soil     = inp["soil_type"]
        slab_thk = float(inp.get("slab_thickness", "0.350"))
    except (ValueError, KeyError) as e:
        return {"error": f"Invalid input: {e}"}

    if A > 25.0:
        return {"error": "RBF-16 applies only for catchment area ≤ 25 km²."}

    H_diff = H_f - BL
    if H_diff <= 0:
        return {"error": "Farthest point height must be greater than Bed Level."}

    tc_hrs = (L**3 / H_diff) ** 0.345
    tc_min = tc_hrs * 60.0
    F      = _get_areal_reduction_factor(A, tc_min)

    soil_label, k = SOIL_COEFF.get(soil, ("c", 0.415))
    C = k * (((R50 / 10.0) * F) ** 0.2)

    sub_zone      = inp.get("sub_zone", "3E")
    tc_ratio_fig4 = get_tc_ratio(sub_zone, tc_hrs)
    one_hr_ratio  = get_1hr_ratio(sub_zone)
    K_scale       = get_scaling_k(sub_zone, tc_hrs)

    R50_1hr = one_hr_ratio * R50
    R50_tc  = K_scale * R50_1hr
    I       = R50_tc / tc_hrs
    Q50     = 0.278 * C * I * A

    net_area_req = Q50 / vel
    depth_req    = net_area_req / width
    CHFL         = BL + depth_req
    min_FL_req   = CHFL + 1.000
    base_clr     = BL + depth_req + slab_thk + 0.300
    governing_FL = max(min_FL_req, base_clr)
    net_freeboard = FL - CHFL
    freeboard_ok  = net_freeboard >= 1.000

    return {
        "mode": "newline",
        "section": inp.get("section", ""), "bridge_no": inp.get("bridge_no", ""),
        "chainage": inp.get("chainage", ""), "existing_opening": inp.get("existing_opening", ""),
        "lat_lon": inp.get("lat_lon", ""),
        "catchment_area": A, "stream_length": L, "farthest_height": H_f,
        "bed_level": BL, "h_diff": H_diff, "soil_type": soil, "sub_zone": sub_zone,
        "ohfl": OHFL, "r50": R50, "formation_level": FL, "slab_thickness": slab_thk,
        "velocity": vel, "width": width, "structure_type": inp.get("structure_type", "RCC BOX"),
        "slope": H_diff / L, "tc_hrs": tc_hrs, "tc_min": tc_min, "F": F, "C": C,
        "soil_label": soil_label, "k_coeff": k,
        "tc_ratio_fig4": tc_ratio_fig4, "one_hr_ratio": one_hr_ratio, "K_scale": K_scale,
        "R50_1hr": R50_1hr, "R50_tc": R50_tc, "I": I, "Q50": Q50,
        "net_area_req": net_area_req, "depth_req": depth_req, "CHFL": CHFL,
        "min_FL_req": min_FL_req, "base_clr": base_clr, "governing_FL": governing_FL,
        "net_freeboard": net_freeboard, "freeboard_ok": freeboard_ok,
    }


# ──────────────────────────────────────────────────────────────────────────────
#  OPTION 2: Std.VC WWC ENGINE (Doubling / Tripling / Quadrupling)
# ──────────────────────────────────────────────────────────────────────────────

def _std_vc(Q: float, span_type: str) -> float:
    """Standard Vertical Clearance per SS Code 4.8.1."""
    if "box" in span_type.lower() or "pipe" in span_type.lower() or "slab" in span_type.lower():
        return 0.0   # Nil for closed sections
    if Q < 0.3:   return 0.15
    if Q < 3.0:   return 0.60
    if Q < 30.0:  return 0.90
    return 1.20


def compute_doubling(inp: dict) -> dict:
    try:
        # Existing bridge
        L_exg    = float(inp["l_exg"])           # Existing linear waterway (m)
        OHFL     = float(inp["ohfl"])             # Observed HFL (m)
        BL       = float(inp["bl"])              # Bed Level (m)
        BOS_exg  = float(inp["bos_exg"])         # Bottom of slab - existing (m)
        FL_exg   = float(inp["fl_exg"])          # Formation level - existing (m)
        RL_exg   = float(inp.get("rl_exg", "0") or "0")

        # Proposed bridge
        L_prop   = float(inp["l_prop"])          # Proposed linear waterway (m)
        BOS_prop = float(inp["bos_prop"])        # Bottom of slab - proposed (m)
        FL_prop  = float(inp["fl_prop"])         # Formation level - proposed (m)
        RL_prop  = float(inp.get("rl_prop", "0") or "0")
        n_spans_prop = int(float(inp.get("n_spans_prop", "1") or "1"))

        span_type_prop = inp.get("span_type_prop", "RCC Box")
        velocity = 2.44   # Standard assumed velocity

        # U/S bridge CHFL (if applicable)
        us_ohfl_str = inp.get("us_ohfl", "").strip()
        us_ohfl = float(us_ohfl_str) if us_ohfl_str else None

    except (ValueError, KeyError) as e:
        return {"error": f"Invalid input: {e}"}

    # ── Calculations ──────────────────────────────────────────────────────
    # 1. Existing lineal waterway
    exg_lw = L_exg

    # 2. Existing area of waterway up to OHFL
    exg_area = L_exg * (OHFL - BL)

    # 3. OHFL discharge
    Q = exg_area * velocity

    # 4. Standard VC for Q
    std_vc = _std_vc(Q, span_type_prop)

    # 5. Existing VC
    exg_vc = BOS_exg - OHFL

    # 6. Required VC for proposed bridge
    req_vc = std_vc   # (0.0 for RCC Box)

    # 7. Existing freeboard
    exg_fb = FL_exg - OHFL

    # 8. Required area (OHFL condition)
    req_area = exg_area

    # 9. Proposed lineal waterway
    prop_lw = L_prop

    # 10. Depth of flow
    depth_d = req_area / prop_lw

    # 11. CHFL
    CHFL = BL + depth_d
    adopted_CHFL = CHFL
    us_note = ""
    if us_ohfl is not None and us_ohfl > CHFL:
        adopted_CHFL = us_ohfl
        us_note = f"Adopted CHFL = {us_ohfl:.3f} m (U/S bridge OHFL governs)"

    # 12. Proposed VC
    prop_vc_val = BOS_prop - adopted_CHFL
    prop_vc_nil = "box" in span_type_prop.lower() or "pipe" in span_type_prop.lower()
    prop_vc_str = "--Nil-- (RCC Box)" if prop_vc_nil else f"{prop_vc_val:.3f} m"

    # 13. Proposed FB
    prop_fb = FL_prop - adopted_CHFL
    fb_ok = prop_fb >= STD_FB

    # 14. Proposed area with Std.FB
    prop_area_fb = prop_lw * (FL_prop - BL - STD_FB)
    area_ok = prop_area_fb > req_area

    adequate = fb_ok and area_ok

    return {
        "mode": "doubling",
        # Header
        "bridge_no":       inp.get("bridge_no", ""),
        "section":         inp.get("section", ""),
        "chainage":        inp.get("chainage", ""),
        "between_stns":    inp.get("between_stns", ""),
        "division":        inp.get("division", "SC"),
        "proposed_by":     inp.get("proposed_by", "CAO/C/SC"),
        "bridge_cat":      inp.get("bridge_cat", "Minor Bridge"),
        "vlist":           inp.get("vlist", "--"),
        "past_history":    inp.get("past_history", "--"),
        # Existing
        "exg_span_desc":   inp.get("exg_span_desc", ""),
        "n_spans_exg":     inp.get("n_spans_exg", "1"),
        "span_type_exg":   inp.get("span_type_exg", "Arch Bridge"),
        "l_exg":           L_exg, "rl_exg": RL_exg,
        "fl_exg":          FL_exg, "bos_exg": BOS_exg,
        "ohfl":            OHFL, "bl":  BL,
        # Proposed
        "prop_span_desc":  inp.get("prop_span_desc", ""),
        "n_spans_prop":    n_spans_prop,
        "span_type_prop":  span_type_prop,
        "l_prop":          L_prop, "rl_prop": RL_prop,
        "fl_prop":         FL_prop, "bos_prop": BOS_prop,
        # Computed
        "exg_lw":          exg_lw,
        "exg_area":        exg_area,
        "Q":               Q,
        "std_vc":          std_vc,
        "exg_vc":          exg_vc,
        "req_vc":          req_vc,
        "exg_fb":          exg_fb,
        "req_area":        req_area,
        "prop_lw":         prop_lw,
        "depth_d":         depth_d,
        "CHFL":            CHFL,
        "adopted_CHFL":    adopted_CHFL,
        "us_ohfl":         us_ohfl,
        "us_note":         us_note,
        "prop_vc_str":     prop_vc_str,
        "prop_vc_nil":     prop_vc_nil,
        "prop_vc_val":     prop_vc_val,
        "prop_fb":         prop_fb,
        "fb_ok":           fb_ok,
        "prop_area_fb":    prop_area_fb,
        "area_ok":         area_ok,
        "adequate":        adequate,
        "velocity":        velocity,
    }


# ──────────────────────────────────────────────────────────────────────────────
#  PDF GENERATORS
# ──────────────────────────────────────────────────────────────────────────────

def _pdf_styles():
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors as rc
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    BASE = getSampleStyleSheet()
    def S(name, **kw): return ParagraphStyle(name, parent=BASE["Normal"], **kw)
    teal  = rc.HexColor("#006666")
    lgrey = rc.HexColor("#f5f5f5")
    mgrey = rc.HexColor("#dddddd")
    green = rc.HexColor("#006400")
    return S, teal, lgrey, mgrey, green, rc, TA_CENTER, TA_LEFT


def _pdf_header(story, res, teal, hdr_style, W, M, subtitle="As per RDSO's Report No: RBF - 16"):
    from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
    hdr_data = [[Paragraph(
        f"SOUTH CENTRAL RAILWAY | BRIDGE ENGINEERING  Water Way Calculations<br/>"
        f"Section: {res.get('section','')} | Bridge No. {res.get('bridge_no','')} | "
        f"Chainage: {res.get('chainage','')}",
        hdr_style
    )]]
    ht = Table(hdr_data, colWidths=[W - 2*M])
    ht.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), teal),
        ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),8),
    ]))
    story.append(ht)
    story.append(Spacer(1, 5))


def generate_pdf_newline(res: dict, path: str):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    W, H = A4; M = 14*mm
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=M)
    S, teal, lgrey, mgrey, green, rc, TA_CENTER, TA_LEFT = _pdf_styles()

    hdr_s  = S("h", fontSize=8, textColor=rc.white, fontName="Helvetica-Bold", alignment=TA_CENTER)
    ttl_s  = S("t", fontSize=13, textColor=teal, fontName="Helvetica-Bold", alignment=TA_CENTER)
    sub_s  = S("s", fontSize=8, textColor=rc.HexColor("#444"), alignment=TA_CENTER)
    sec_s  = S("sc", fontSize=9, fontName="Helvetica-Bold", textColor=rc.white)
    lbl_s  = S("l", fontSize=8.5)
    val_s  = S("v", fontSize=8.5, fontName="Helvetica-Bold")
    note_s = S("n", fontSize=7.5, textColor=rc.HexColor("#555"), alignment=TA_CENTER)

    def sec_hdr(letter, text):
        t = Table([[Paragraph(f" {letter}  {text}", sec_s)]], colWidths=[W-2*M])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),teal),
                               ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
                               ("LEFTPADDING",(0,0),(-1,-1),6)]))
        return t

    def dtbl(rows, col_w=None):
        col_w = col_w or [8*mm, 90*mm, W-2*M-98*mm]
        t = Table(rows, colWidths=col_w)
        t.setStyle(TableStyle([("BOX",(0,0),(-1,-1),0.5,mgrey),
                               ("INNERGRID",(0,0),(-1,-1),0.3,mgrey),
                               ("BACKGROUND",(0,0),(0,-1),lgrey),
                               ("TOPPADDING",(0,0),(-1,-1),2.5),
                               ("BOTTOMPADDING",(0,0),(-1,-1),2.5),
                               ("LEFTPADDING",(0,0),(-1,-1),5)]))
        return t

    def r3(sl, desc, val):
        return [Paragraph(str(sl),lbl_s), Paragraph(desc,lbl_s), Paragraph(str(val),val_s)]

    story = []
    _pdf_header(story, res, teal, hdr_s, W, M)
    story.append(Paragraph("WATER WAY CALCULATIONS", ttl_s))
    story.append(Paragraph("As per RDSO's Report No: RBF - 16", sub_s))
    story.append(Spacer(1, 6))

    # A: Data Profile
    story.append(sec_hdr("A", "DATA PROFILE"))
    story.append(dtbl([
        r3(1,"Section",res['section']), r3(2,"Bridge No.",res['bridge_no']),
        r3(3,"Chainage (Rly Km)",res['chainage']),
        r3(4,"Existing Opening",res['existing_opening']),
        r3(5,"Latitude / Longitude",res['lat_lon']),
        r3(6,"Catchment Area (A)",f"{res['catchment_area']:.4f} km²"),
        r3(7,"Length of Longest Stream (L)",f"{res['stream_length']:.4f} km"),
        r3(8,"Height of Farthest Point Above POI",f"{res['farthest_height']:.3f} m"),
        r3(9,"Bed Level",f"{res['bed_level']:.3f} m"),
        r3(10,"Vertical Height Difference (H)",f"{res['h_diff']:.3f} m"),
        r3(11,"Nature of Soil",res['soil_type'].split("/")[0].strip()),
        r3(12,"Sub-Zone",res.get('sub_zone','3E')),
        r3(13,"O.H.F.L.",f"{res['ohfl']:.3f} m"),
        r3(14,"50 Year - 24 Hour Rainfall (R50)",f"{res['r50']:.3f} mm"),
        r3(15,"Adopted Formation Level",f"{res['formation_level']:.3f} m"),
    ]))
    story.append(Spacer(1,5))

    # B: Formula
    story.append(sec_hdr("B","IMPROVED RATIONAL FORMULA FRAMEWORK"))
    b_tbl = Table([[Paragraph(
        "Q<sub>50</sub> = 0.278 × C × I × A   |   C = Runoff coefficient   |   "
        "I = 50-yr rainfall intensity (mm/h) for t<sub>c</sub>   |   A = Catchment Area (km²)", lbl_s
    )]], colWidths=[W-2*M])
    b_tbl.setStyle(TableStyle([("BOX",(0,0),(-1,-1),0.5,mgrey),("BACKGROUND",(0,0),(-1,-1),lgrey),
                               ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
                               ("LEFTPADDING",(0,0),(-1,-1),8)]))
    story.append(b_tbl)
    story.append(Spacer(1,5))

    # C: Runoff table (abbreviated)
    story.append(sec_hdr("C","RUNOFF COEFFICIENT (C) EVALUATION"))
    c_rows = [
        [Paragraph("Sl.",lbl_s),Paragraph("Description of Catchment",lbl_s),Paragraph("Formula for C",lbl_s)],
        [Paragraph("a",lbl_s),Paragraph("Sandy Soil / Sandy loam / Arid Areas",lbl_s),Paragraph("C = 0.0249 × (R×F)^0.2",lbl_s)],
        [Paragraph("b",lbl_s),Paragraph("Alluvial / Silty loam / Coastal area",lbl_s),Paragraph("C = 0.332 × (R×F)^0.2",lbl_s)],
        [Paragraph("c",lbl_s),Paragraph("Red Soil / Clayey Loam / Grey or Brown Alluvial / Cultivated plains / Barren / Submontanous and Plateau / Tall crops / Wooded Areas",lbl_s),Paragraph("C = 0.415 × (R×F)^0.2",lbl_s)],
        [Paragraph("d",lbl_s),Paragraph("Black cotton / Clayey soil / Lightly covered / Light wooded / Plain and Barren / Submontanous & Plateau",lbl_s),Paragraph("C = 0.456 × (R×F)^0.2",lbl_s)],
        [Paragraph("e",lbl_s),Paragraph("Hilly soil / Plateau & Barren",lbl_s),Paragraph("C = 0.498 × (R×F)^0.2",lbl_s)],
    ]
    idx = ["a","b","c","d","e"].index(res['soil_label'])
    c_tbl = Table(c_rows, colWidths=[8*mm,115*mm,W-2*M-123*mm])
    c_tbl.setStyle(TableStyle([
        ("BOX",(0,0),(-1,-1),0.5,mgrey),("INNERGRID",(0,0),(-1,-1),0.3,mgrey),
        ("BACKGROUND",(0,0),(-1,0),teal),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,0),(-1,0),rc.white),
        ("TOPPADDING",(0,0),(-1,-1),2.5),("BOTTOMPADDING",(0,0),(-1,-1),2.5),
        ("LEFTPADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,idx+1),(-1,idx+1),rc.HexColor("#e0f5ef")),
    ]))
    story.append(c_tbl)
    story.append(Spacer(1,5))

    # D: Hydrology
    story.append(sec_hdr("D","HYDROLOGICAL RUNOFF & CONCENTRATION ANALYSIS"))
    story.append(dtbl([
        r3("","Topographical Slope H/L", f"{res['slope']:.4f}"),
        r3("","Time of Concentration (tc)", f"{res['tc_hrs']:.4f} hrs  ({res['tc_min']:.2f} min)"),
        r3("","Rainfall Depth (R) — 50-Year 24-hr",f"{res['r50']:.0f} mm"),
        r3("","Areal Reduction Factor (F)", f"{res['F']:.3f}"),
        r3("","Runoff Coefficient (C)", f"{res['C']:.4f}"),
    ]))
    story.append(Spacer(1,5))

    # E: Discharge
    story.append(sec_hdr("E","RAINFALL INTENSITY & DISCHARGE SYNTHESIS"))
    story.append(dtbl([
        r3("","tc hour ratio (Fig. 3.1 of RBF-16)",f"{res['tc_ratio_fig4']:.3f}"),
        r3("","1 hour ratio (Fig. 3.1 of RBF-16)",f"{res['one_hr_ratio']:.3f}"),
        r3("","Scaling Coefficient K", f"{res['K_scale']:.3f}"),
        r3("","R50 (1-hr rainfall)", f"{res['R50_1hr']:.2f} mm"),
        r3("","R50 (tc)", f"{res['R50_tc']:.2f} mm"),
        r3("","Critical Rainfall Intensity (I)", f"{res['I']:.3f} mm/hr"),
        r3("","Design Flood Discharge (Q50)", f"{res['Q50']:.2f} m³/sec"),
    ]))
    story.append(Spacer(1,3))
    q_tbl = Table([[Paragraph(
        f"Design Flood Discharge — 50 Year Return Period :  Q50 = {res['Q50']:.2f} m³/sec",
        S("qh",fontSize=9,textColor=teal,fontName="Helvetica-Bold",alignment=TA_CENTER)
    )]], colWidths=[W-2*M])
    q_tbl.setStyle(TableStyle([("BOX",(0,0),(-1,-1),1,teal),
                               ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story.append(q_tbl)
    story.append(Spacer(1,5))

    # F: Adequacy
    story.append(sec_hdr("F","WATERWAY ADEQUACY & FREEBOARD VERIFICATION AUDIT"))
    fb_str = "ADEQUATE" if res['freeboard_ok'] else "INADEQUATE — REVIEW REQUIRED"
    story.append(dtbl([
        [Paragraph("a",lbl_s),Paragraph("Design Volume Discharge (Q)",lbl_s),Paragraph(f"{res['Q50']:.2f} m³/sec",val_s)],
        [Paragraph("b",lbl_s),Paragraph("Assumed Peak Velocity (V)",lbl_s),Paragraph(f"{res['velocity']:.2f} m/sec",val_s)],
        [Paragraph("c",lbl_s),Paragraph("Calculated Net Waterway Area Required",lbl_s),
         Paragraph(f"{res['net_area_req']:.3f} m²",val_s)],
        [Paragraph("d",lbl_s),Paragraph("Structural Opening Type",lbl_s),Paragraph(res['structure_type'],val_s)],
        [Paragraph("e",lbl_s),Paragraph("Design Water Flow Depth Required",lbl_s),
         Paragraph(f"{res['depth_req']:.3f} m",val_s)],
        [Paragraph("f",lbl_s),Paragraph("Bed Level (BL)",lbl_s),Paragraph(f"{res['bed_level']:.3f} m",val_s)],
        [Paragraph("g",lbl_s),Paragraph("Observed Highest Flood Level (O.H.F.L.)",lbl_s),Paragraph(f"{res['ohfl']:.3f} m",val_s)],
        [Paragraph("h",lbl_s),Paragraph("Calculated Highest Flood Level (C.H.F.L.)",lbl_s),
         Paragraph(f"{res['CHFL']:.3f} m",val_s)],
        [Paragraph("i",lbl_s),Paragraph("Sub-structure Clearance (Slab Thickness)",lbl_s),Paragraph(f"{res['slab_thickness']:.3f} m",val_s)],
        [Paragraph("j",lbl_s),Paragraph("Minimum Formation Level Required",lbl_s),
         Paragraph(f"{res['min_FL_req']:.3f} m",val_s)],
        [Paragraph("k",lbl_s),Paragraph("Mandatory Freeboard Margin",lbl_s),Paragraph("1.000 m",val_s)],
        [Paragraph("l",lbl_s),Paragraph("Governing Minimum Formation Level",lbl_s),Paragraph(f"{res['governing_FL']:.3f} m",val_s)],
        [Paragraph("m",lbl_s),Paragraph("Net Freeboard Available",lbl_s),
         Paragraph(f"{res['net_freeboard']:.3f} m  [{fb_str}]",val_s)],
        [Paragraph("n",lbl_s),Paragraph("Design Adopted Formation Level",lbl_s),Paragraph(f"{res['formation_level']:.3f} m",val_s)],
    ], col_w=[8*mm,105*mm,W-2*M-113*mm]))
    story.append(Spacer(1,5))

    vcolor = green if res['freeboard_ok'] else rc.red
    vtext  = (f"OK   Proposed BR. No. {res['bridge_no']} — {res['structure_type']} is STRUCTURALLY ADEQUATE"
              if res['freeboard_ok'] else
              f"WARNING   BR. No. {res['bridge_no']} — Freeboard insufficient. Review design.")
    v_tbl = Table([[Paragraph(vtext, S("vd",fontSize=9,fontName="Helvetica-Bold",textColor=vcolor,alignment=TA_CENTER))]],
                  colWidths=[W-2*M])
    v_tbl.setStyle(TableStyle([("BOX",(0,0),(-1,-1),1.2,vcolor),
                               ("BACKGROUND",(0,0),(-1,-1),rc.HexColor("#f0fff8") if res['freeboard_ok'] else rc.HexColor("#fff0f0")),
                               ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    story.append(v_tbl)
    story.append(Spacer(1,4))
    story.append(Paragraph("Design discharge accommodated with standard freeboard margins as per RDSO RBF-16 norms.", note_s))
    story.append(Spacer(1,6))
    story.append(Paragraph(f"Prepared by: Bridge Engineering Dept. | South Central Railway | Section: {res['section']}", note_s))
    doc.build(story)


def generate_pdf_doubling(res: dict, path: str):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    W, H = A4; M = 14*mm
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=M)
    S, teal, lgrey, mgrey, green, rc, TA_CENTER, TA_LEFT = _pdf_styles()

    hdr_s  = S("h",fontSize=8,textColor=rc.white,fontName="Helvetica-Bold",alignment=TA_CENTER)
    ttl_s  = S("t",fontSize=13,textColor=teal,fontName="Helvetica-Bold",alignment=TA_CENTER)
    sub_s  = S("s",fontSize=8,textColor=rc.HexColor("#444"),alignment=TA_CENTER)
    sec_s  = S("sc",fontSize=9,fontName="Helvetica-Bold",textColor=rc.white)
    lbl_s  = S("l",fontSize=8.5)
    val_s  = S("v",fontSize=8.5,fontName="Helvetica-Bold")
    note_s = S("n",fontSize=7.5,textColor=rc.HexColor("#555"),alignment=TA_CENTER)

    def sec_hdr(letter, text):
        t = Table([[Paragraph(f" {letter}  {text}", sec_s)]], colWidths=[W-2*M])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),teal),
                               ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
                               ("LEFTPADDING",(0,0),(-1,-1),6)]))
        return t

    def dtbl_2col(rows):
        t = Table(rows, colWidths=[8*mm, 110*mm, W-2*M-118*mm])
        t.setStyle(TableStyle([("BOX",(0,0),(-1,-1),0.5,mgrey),("INNERGRID",(0,0),(-1,-1),0.3,mgrey),
                               ("BACKGROUND",(0,0),(0,-1),lgrey),
                               ("TOPPADDING",(0,0),(-1,-1),2.5),("BOTTOMPADDING",(0,0),(-1,-1),2.5),
                               ("LEFTPADDING",(0,0),(-1,-1),5)]))
        return t

    def r3(sl, desc, val):
        return [Paragraph(str(sl),lbl_s), Paragraph(desc,lbl_s), Paragraph(str(val),val_s)]

    story = []
    _pdf_header(story, res, teal, hdr_s, W, M, subtitle="Waterway Calculations — Doubling/Tripling/Quadrupling")
    story.append(Paragraph("WATER WAY CALCULATIONS", ttl_s))
    story.append(Paragraph("For Doubling / Tripling / Quadrupling of Railway Line", sub_s))
    story.append(Paragraph("As per Sub-Structure Code Para 4.8.1 to 4.9.4", sub_s))
    story.append(Spacer(1,6))

    # Header info table
    info = Table([
        [Paragraph("Bridge No.",lbl_s), Paragraph(res['bridge_no'],val_s),
         Paragraph("Section",lbl_s), Paragraph(res['section'],val_s),
         Paragraph("Division",lbl_s), Paragraph(res['division'],val_s)],
        [Paragraph("Chainage",lbl_s), Paragraph(res['chainage'],val_s),
         Paragraph("Between Stns",lbl_s), Paragraph(res['between_stns'],val_s),
         Paragraph("Proposed By",lbl_s), Paragraph(res['proposed_by'],val_s)],
        [Paragraph("Exg. Span",lbl_s), Paragraph(res['exg_span_desc'],val_s),
         Paragraph("Prop. Span",lbl_s), Paragraph(res['prop_span_desc'],val_s),
         Paragraph("Bridge Category",lbl_s), Paragraph(res['bridge_cat'],val_s)],
    ], colWidths=[22*mm,38*mm,22*mm,38*mm,28*mm,W-2*M-148*mm])
    info.setStyle(TableStyle([("BOX",(0,0),(-1,-1),0.5,mgrey),("INNERGRID",(0,0),(-1,-1),0.3,mgrey),
                              ("BACKGROUND",(0,0),(0,-1),lgrey),("BACKGROUND",(2,0),(2,-1),lgrey),
                              ("BACKGROUND",(4,0),(4,-1),lgrey),
                              ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
                              ("LEFTPADDING",(0,0),(-1,-1),4)]))
    story.append(info)
    story.append(Spacer(1,6))

    # A: Hydraulic Particulars table
    story.append(sec_hdr("A","HYDRAULIC PARTICULARS — EXISTING & PROPOSED BRIDGES"))
    part_rows = [
        [Paragraph("S.No.",lbl_s),Paragraph("Description",lbl_s),
         Paragraph("Existing Bridge",lbl_s),Paragraph("Proposed Bridge",lbl_s)],
        [Paragraph("1",lbl_s),Paragraph("Total No. of Spans",lbl_s),
         Paragraph(str(res['n_spans_exg']),val_s),Paragraph(str(res['n_spans_prop']),val_s)],
        [Paragraph("2",lbl_s),Paragraph("Span Type",lbl_s),
         Paragraph(res['span_type_exg'],val_s),Paragraph(res['span_type_prop'],val_s)],
        [Paragraph("3",lbl_s),Paragraph("Total Linear Waterway (m)",lbl_s),
         Paragraph(f"{res['l_exg']:.3f}",val_s),Paragraph(f"{res['l_prop']:.3f}",val_s)],
        [Paragraph("4",lbl_s),Paragraph("Rail Level (RL) (m)",lbl_s),
         Paragraph(f"{res['rl_exg']:.3f}",val_s),Paragraph(f"{res['rl_prop']:.3f}",val_s)],
        [Paragraph("5",lbl_s),Paragraph("Formation Level (FL) (m)",lbl_s),
         Paragraph(f"{res['fl_exg']:.3f}",val_s),Paragraph(f"{res['fl_prop']:.3f}",val_s)],
        [Paragraph("6",lbl_s),Paragraph("Bottom of Slab (BOS) (m)",lbl_s),
         Paragraph(f"{res['bos_exg']:.3f}",val_s),Paragraph(f"{res['bos_prop']:.3f}",val_s)],
        [Paragraph("7",lbl_s),Paragraph("OHFL / CHFL (m)",lbl_s),
         Paragraph(f"{res['ohfl']:.3f} (OHFL)",val_s),Paragraph(f"{res['adopted_CHFL']:.3f} (CHFL)",val_s)],
        [Paragraph("8",lbl_s),Paragraph("Bed Level / Avg. BL (m)",lbl_s),
         Paragraph(f"{res['bl']:.3f}",val_s),Paragraph(f"{res['bl']:.3f}",val_s)],
    ]
    part_tbl = Table(part_rows, colWidths=[10*mm,70*mm,(W-2*M-80*mm)/2,(W-2*M-80*mm)/2])
    part_tbl.setStyle(TableStyle([
        ("BOX",(0,0),(-1,-1),0.5,mgrey),("INNERGRID",(0,0),(-1,-1),0.3,mgrey),
        ("BACKGROUND",(0,0),(-1,0),teal),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,0),(-1,0),rc.white),
        ("TOPPADDING",(0,0),(-1,-1),2.5),("BOTTOMPADDING",(0,0),(-1,-1),2.5),
        ("LEFTPADDING",(0,0),(-1,-1),4),
    ]))
    story.append(part_tbl)
    story.append(Spacer(1,6))

    # D: Existing Bridge
    story.append(sec_hdr("D","EXISTING BRIDGE — HYDRAULIC ANALYSIS"))
    story.append(dtbl_2col([
        r3("1.","Existing Lineal Waterway",f"{res['exg_lw']:.3f} m"),
        r3("2.","Existing Area of Waterway up to OHFL", f"{res['exg_area']:.3f} m²"),
        r3("3.","OHFL Discharge (Q)", f"{res['Q']:.3f} Cumecs"),
        r3("4.","Standard Vertical Clearance (SS Code 4.8.1)",
           f"{res['std_vc']:.2f} m" if res['std_vc'] > 0 else "--Nil-- (RCC Box / Closed section)"),
        r3("5.","Existing Vertical Clearance (VC)", f"{res['exg_vc']:.3f} m"),
        r3("6.","Required VC for Proposed Bridge",
           f"{res['req_vc']:.2f} m" if res['req_vc'] > 0 else "--Nil-- (Since RCC Box)"),
        r3("7.","Existing Freeboard (FB)", f"{res['exg_fb']:.3f} m"),
    ]))
    story.append(Spacer(1,5))

    # E: Proposed Bridge
    story.append(sec_hdr("E","PROPOSED BRIDGE — HYDRAULIC ADEQUACY"))
    chfl_note = res['us_note'] if res['us_note'] else f"BL + d = {res['bl']:.3f} + {res['depth_d']:.3f} = {res['CHFL']:.3f} m"
    fb_str = "ADEQUATE" if res['fb_ok'] else "INADEQUATE"
    area_str = "ADEQUATE" if res['area_ok'] else "INADEQUATE"
    story.append(dtbl_2col([
        r3("8.","Required Area of Waterway (OHFL condition)",f"{res['req_area']:.3f} m²"),
        r3("9.","Proposed Lineal Waterway",f"{res['prop_lw']:.3f} m"),
        r3("10.","Depth of Flow (d)", f"{res['depth_d']:.3f} m"),
        r3("11.","Calculated Highest Flood Level (CHFL)", f"{res['adopted_CHFL']:.3f} m" + (f"  (U/S OHFL governs)" if res['us_note'] else "")),
        r3("12.","Proposed Vertical Clearance (VC)", res['prop_vc_str']),
        r3("13.","Proposed Freeboard (FB)", f"{res['prop_fb']:.3f} m  [{fb_str}]"),
        r3("14.","Proposed Area of Waterway (with Std.FB)", f"{res['prop_area_fb']:.3f} m²  [{area_str}]"),
    ]))
    story.append(Spacer(1,5))

    # F: Summary table
    story.append(sec_hdr("F","SUMMARY — HYDRAULIC PARTICULARS OF PROPOSED BRIDGE"))
    sum_hdr = ["Catchment\nArea (km²)","Discharge\n(Cumecs)","FB\nRequired (m)",
               "FB\nProvided (m)","VC\nRequired (m)","VC\nProposed (m)",
               "Exg. L/W\n(m)","Prop. L/W\n(m)","Exg. Area\n(m²)","Prop. Area\nStd.FB (m²)","Req. Area\n(m²)"]
    sum_vals = ["--", f"{res['Q']:.3f}", "1.000", f"{res['prop_fb']:.3f}",
                f"{res['std_vc']:.2f}" if res['std_vc'] > 0 else "--",
                "--" if res['prop_vc_nil'] else f"{res['prop_vc_val']:.3f}",
                f"{res['l_exg']:.3f}", f"{res['l_prop']:.3f}",
                f"{res['exg_area']:.3f}", f"{res['prop_area_fb']:.3f}", f"{res['req_area']:.3f}"]
    cw = [(W-2*M)/11]*11
    sum_tbl = Table(
        [[Paragraph(h, S("sh",fontSize=7,fontName="Helvetica-Bold",textColor=rc.white,alignment=TA_CENTER)) for h in sum_hdr],
         [Paragraph(v, S("sv",fontSize=7.5,fontName="Helvetica-Bold",alignment=TA_CENTER)) for v in sum_vals]],
        colWidths=cw
    )
    sum_tbl.setStyle(TableStyle([
        ("BOX",(0,0),(-1,-1),0.5,mgrey),("INNERGRID",(0,0),(-1,-1),0.3,mgrey),
        ("BACKGROUND",(0,0),(-1,0),teal),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),2),
    ]))
    story.append(sum_tbl)
    story.append(Spacer(1,4))

    # Verdict
    vcolor = green if res['adequate'] else rc.red
    vtext  = (f"OK   Proposed {res['prop_span_desc']} is STRUCTURALLY ADEQUATE (Std. FB & VC)"
              if res['adequate'] else
              f"WARNING   Proposed {res['prop_span_desc']} is INADEQUATE — Review required")
    v_tbl = Table([[Paragraph(vtext, S("vd",fontSize=9,fontName="Helvetica-Bold",textColor=vcolor,alignment=TA_CENTER))]],
                  colWidths=[W-2*M])
    v_tbl.setStyle(TableStyle([("BOX",(0,0),(-1,-1),1.2,vcolor),
                               ("BACKGROUND",(0,0),(-1,-1),rc.HexColor("#f0fff8") if res['adequate'] else rc.HexColor("#fff0f0")),
                               ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    story.append(v_tbl)
    story.append(Spacer(1,4))
    story.append(Paragraph(f"Prepared by: Bridge Engineering Dept. | South Central Railway | Section: {res['section']}", note_s))
    doc.build(story)


# ──────────────────────────────────────────────────────────────────────────────
#  PREVIEW WIDGET
# ──────────────────────────────────────────────────────────────────────────────

class PreviewWidget(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.placeholder = QLabel("Fill in the inputs and click  ⚡ Calculate  to see results.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-style:italic; padding:40px;")
        lay.addWidget(self.placeholder)
        self.content = QWidget()
        self.content.setVisible(False)
        self.content_lay = QVBoxLayout(self.content)
        self.content_lay.setContentsMargins(0, 0, 0, 0)
        self.content_lay.setSpacing(5)
        lay.addWidget(self.content)

    def _clear(self):
        while self.content_lay.count():
            item = self.content_lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def _section(self, letter, title):
        lbl = QLabel(f"  {letter}   {title}")
        lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl.setStyleSheet(f"background:{COLORS['accent']}; color:#0D1117; padding:4px 8px; border-radius:4px;")
        self.content_lay.addWidget(lbl)

    def _row(self, label, value, highlight=False, ok=None):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background:{COLORS.get('hover_bg', COLORS['navy_light'])}; "
            f"border-radius:4px; border:1px solid {COLORS['border']}; }}")
        r = QHBoxLayout(frame)
        r.setContentsMargins(10, 3, 10, 3)
        lw = QLabel(label)
        lw.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px; border:none;")
        lw.setWordWrap(True)
        if ok is True:
            color = COLORS['accent']
        elif ok is False:
            color = COLORS.get('error', '#FF6B6B')
        elif highlight:
            color = COLORS['accent']
        else:
            color = COLORS['text_primary']
        vw = QLabel(str(value))
        vw.setStyleSheet(f"font-weight:bold; font-size:12px; color:{color}; border:none;")
        vw.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        r.addWidget(lw, 3)
        r.addWidget(vw, 2)
        self.content_lay.addWidget(frame)

    def update_newline(self, res):
        self._clear()
        self.placeholder.setVisible(False)
        self.content.setVisible(True)
        self._section("D", "HYDROLOGICAL ANALYSIS")
        self._row("tc", f"{res['tc_hrs']:.4f} hrs  =  {res['tc_min']:.2f} min")
        self._row("Areal Reduction Factor (F)", f"{res['F']:.3f}")
        self._row("Runoff Coefficient (C)", f"{res['C']:.4f}", highlight=True)
        self._section("E", "DISCHARGE SYNTHESIS")
        self._row("tc ratio (Fig 3.1)", f"{res['tc_ratio_fig4']:.3f}")
        self._row("1-hr ratio (Fig 3.1)", f"{res['one_hr_ratio']:.3f}")
        self._row("R50(tc)", f"{res['R50_tc']:.2f} mm")
        self._row("Critical Intensity (I)", f"{res['I']:.3f} mm/hr")
        self._row("Design Flood Discharge Q50", f"{res['Q50']:.2f} m³/sec", highlight=True)
        self._section("F", "WATERWAY ADEQUACY")
        self._row("Net Waterway Area Required", f"{res['net_area_req']:.3f} m²")
        self._row("Flow Depth Required", f"{res['depth_req']:.3f} m")
        self._row("C.H.F.L.", f"{res['CHFL']:.3f} m")
        self._row("Min. Formation Level Required", f"{res['min_FL_req']:.3f} m")
        self._row("Adopted Formation Level", f"{res['formation_level']:.3f} m")
        fb_ok = res['freeboard_ok']
        self._row("Net Freeboard",
                  f"{res['net_freeboard']:.3f} m  ({'✔ ADEQUATE' if fb_ok else '✘ INADEQUATE'})",
                  ok=fb_ok)

    def update_doubling(self, res):
        self._clear()
        self.placeholder.setVisible(False)
        self.content.setVisible(True)
        self._section("D", "EXISTING BRIDGE")
        self._row("Existing Lineal Waterway", f"{res['exg_lw']:.3f} m")
        self._row("Existing Area up to OHFL", f"{res['exg_area']:.3f} m²")
        self._row("OHFL Discharge (Q)", f"{res['Q']:.3f} Cumecs", highlight=True)
        self._row("Std. Vertical Clearance", f"{res['std_vc']:.2f} m" if res['std_vc'] > 0 else "--Nil--")
        self._row("Existing Freeboard", f"{res['exg_fb']:.3f} m")
        self._section("E", "PROPOSED BRIDGE")
        self._row("Required Area (OHFL condition)", f"{res['req_area']:.3f} m²")
        self._row("Depth of Flow (d)", f"{res['depth_d']:.3f} m")
        self._row("Calculated HFL (C.H.F.L.)", f"{res['CHFL']:.3f} m")
        if res['us_note']:
            self._row("Adopted CHFL", f"{res['adopted_CHFL']:.3f} m (U/S governs)")
        self._row("Proposed Freeboard",
                  f"{res['prop_fb']:.3f} m  ({'✔ ADEQUATE' if res['fb_ok'] else '✘ INADEQUATE'})",
                  ok=res['fb_ok'])
        self._row("Proposed Area (Std.FB)",
                  f"{res['prop_area_fb']:.3f} m²  ({'✔ > Req.' if res['area_ok'] else '✘ < Req.'})",
                  ok=res['area_ok'])
        self._row("Overall Verdict",
                  "✔  ADEQUATE" if res['adequate'] else "✘  INADEQUATE — Review",
                  ok=res['adequate'])

    def reset(self):
        self._clear()
        self.placeholder.setVisible(True)
        self.content.setVisible(False)


# ──────────────────────────────────────────────────────────────────────────────
#  HELPER: labelled field factory
# ──────────────────────────────────────────────────────────────────────────────

def _field(placeholder=""):
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    f.setFixedHeight(32)
    return f

def _combo(items):
    c = QComboBox()
    c.addItems(items)
    c.setFixedHeight(32)
    return c

def _add_grid_row(grid, row, sl, label, widget, unit=""):
    sl_lbl = QLabel(str(sl))
    sl_lbl.setStyleSheet(f"color:{COLORS['accent']}; font-weight:600; min-width:22px;")
    grid.addWidget(sl_lbl, row, 0)
    lbl = QLabel(label); lbl.setWordWrap(True)
    grid.addWidget(lbl, row, 1)
    grid.addWidget(widget, row, 2)
    if unit:
        u = QLabel(unit)
        u.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
        grid.addWidget(u, row, 3)


# ──────────────────────────────────────────────────────────────────────────────
#  MODE SELECTOR WIDGET
# ──────────────────────────────────────────────────────────────────────────────

class ModeSelectorWidget(QWidget):
    """Landing card shown at the top — choose New Line or Doubling."""

    def __init__(self, on_select):
        super().__init__()
        self._on_select = on_select
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("Hydraulic Calculations")
        title.setObjectName("panelTitle")
        lay.addWidget(title)

        sub = QLabel("Select the type of waterway calculation to perform:")
        sub.setObjectName("panelSubtitle")
        lay.addWidget(sub)

        lay.addSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)

        self.btn_newline  = self._mode_btn(
            "🛤️  New Line",
            "RBF-16 Catchment Method\nFor new railway lines where\nno existing bridge data available",
            "1"
        )
        self.btn_doubling = self._mode_btn(
            "🔀  Doubling / Tripling / Quadrupling",
            "Std. VC Method (SS Code 4.8.1)\nBased on OHFL of existing bridge\nFor reconstruction / gauge conversion",
            "2"
        )

        btn_row.addWidget(self.btn_newline)
        btn_row.addWidget(self.btn_doubling)
        lay.addLayout(btn_row)

    def _mode_btn(self, label, desc, mode):
        btn = QFrame()
        btn.setObjectName("card")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(120)
        lay = QVBoxLayout(btn)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        top_lbl = QLabel(label)
        top_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        top_lbl.setStyleSheet(f"color:{COLORS['accent']};")
        lay.addWidget(top_lbl)

        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:11px;")
        desc_lbl.setWordWrap(True)
        lay.addWidget(desc_lbl)

        def click(ev, m=mode, b=btn):
            self._select(m, b)
        btn.mousePressEvent = click
        return btn

    def _select(self, mode, btn):
        accent = COLORS['accent']
        for b in (self.btn_newline, self.btn_doubling):
            b.setStyleSheet("")
        btn.setStyleSheet(
            f"QFrame {{ border:2px solid {accent}; border-radius:8px; "
            f"background:{COLORS.get('hover_bg', COLORS['navy_light'])}; }}"
        )
        self._on_select(mode)


# ──────────────────────────────────────────────────────────────────────────────
#  OPTION 1 FORM
# ──────────────────────────────────────────────────────────────────────────────

class NewLineForm(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # ── Smart Extract drop zone ──────────────────────────────────
        extract_hdr = QLabel("  🤖  Smart Extract — Drop Drawing / PDF / Excel")
        extract_hdr.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        extract_hdr.setStyleSheet(
            f"background:{COLORS.get('navy_mid','#1e3a5f')}; color:#e0e0e0; "
            f"padding:3px 8px; border-radius:4px;")
        lay.addWidget(extract_hdr)

        self.extract_zone = QWidget()
        self.extract_zone.setFixedHeight(90)
        lay.addWidget(self.extract_zone)

        # ── Section header ───────────────────────────────────────────
        hdr = QLabel("  A   DATA PROFILE  —  New Line (RBF-16)")
        hdr.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        hdr.setStyleSheet(f"background:{COLORS['accent']}; color:#0D1117; padding:3px 8px; border-radius:4px;")
        lay.addWidget(hdr)

        # ── Compact 2-column grid ─────────────────────────────────────
        self.f_section   = _field("DKJ-BDCR")
        self.f_bridge    = _field("53")
        self.f_chainage  = _field("272311.90 m")
        self.f_opening   = _field("1×1.22 m ARCH")
        self.f_latlon    = _field("18°52'50\" N / 76°33'30\" E")
        self.f_area      = _field("0.2410")
        self.f_length    = _field("0.7000")
        self.f_hfarthest = _field("442.000")
        self.f_bedlevel  = _field("440.305")
        self.f_ohfl      = _field("441.600")
        self.f_r50       = _field("200.000")
        self.f_fl        = _field("444.618")
        self.f_velocity  = _field("2.44")
        self.f_width     = _field("1.50")
        self.f_slab      = _field("0.350")
        self.f_soil      = _combo(SOIL_OPTIONS)
        self.f_subzone   = _combo(SUB_ZONES)
        self.f_struct    = _combo(STRUCTURE_TYPES)

        for f in (self.f_area, self.f_length, self.f_hfarthest, self.f_bedlevel,
                  self.f_ohfl, self.f_r50, self.f_fl, self.f_velocity, self.f_width, self.f_slab):
            f.setValidator(QDoubleValidator())

        # 2-column layout: left column = text/ID fields, right column = numeric fields
        two_col = QHBoxLayout()
        two_col.setSpacing(6)

        def _mini_section(title, rows_data):
            """Build a compact card with label:field rows."""
            frm = QFrame(); frm.setObjectName("card")
            fl = QVBoxLayout(frm)
            fl.setContentsMargins(8, 6, 8, 6)
            fl.setSpacing(3)
            t = QLabel(title)
            t.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            t.setStyleSheet(f"color:{COLORS['accent']}; font-size:10px;")
            fl.addWidget(t)
            g = QGridLayout()
            g.setHorizontalSpacing(6)
            g.setVerticalSpacing(3)
            g.setColumnStretch(0, 3)
            g.setColumnStretch(1, 2)
            for r, (lbl_text, widget, unit) in enumerate(rows_data):
                lbl = QLabel(lbl_text)
                lbl.setStyleSheet("color: " + COLORS['text_secondary'] + "; font-size: 11px;")
                g.addWidget(lbl, r, 0)
                g.addWidget(widget, r, 1)
                if unit:
                    u = QLabel(unit)
                    u.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:10px;")
                    g.addWidget(u, r, 2)
            fl.addLayout(g)
            return frm

        # Left mini-card: ID fields
        left_card = _mini_section("IDENTIFICATION", [
            ("Section",           self.f_section,   ""),
            ("Bridge No.",        self.f_bridge,    ""),
            ("Chainage",          self.f_chainage,  ""),
            ("Existing Opening",  self.f_opening,   ""),
            ("Lat / Lon",         self.f_latlon,    ""),
            ("Soil Type",         self.f_soil,      ""),
            ("Sub-Zone",          self.f_subzone,   ""),
            ("Structure Type",    self.f_struct,    ""),
        ])

        # Right mini-card: numeric fields
        right_card = _mini_section("HYDROLOGY INPUTS", [
            ("Catchment Area (A)", self.f_area,      "km²"),
            ("Stream Length (L)",  self.f_length,    "km"),
            ("Farthest Ht. (POI)", self.f_hfarthest, "m"),
            ("Bed Level",          self.f_bedlevel,  "m"),
            ("O.H.F.L.",           self.f_ohfl,      "m"),
            ("R50 (24hr)",         self.f_r50,       "mm"),
            ("Formation Level",    self.f_fl,        "m"),
            ("Peak Velocity",      self.f_velocity,  "m/s"),
            ("Opening Width",      self.f_width,     "m"),
            ("Slab Thickness",     self.f_slab,      "m"),
        ])

        two_col.addWidget(left_card, 1)
        two_col.addWidget(right_card, 1)
        lay.addLayout(two_col)
        lay.addStretch()

    def get_inputs(self):
        return {
            "section": self.f_section.text().strip(),
            "bridge_no": self.f_bridge.text().strip(),
            "chainage": self.f_chainage.text().strip(),
            "existing_opening": self.f_opening.text().strip(),
            "lat_lon": self.f_latlon.text().strip(),
            "catchment_area": self.f_area.text().strip() or "0",
            "stream_length": self.f_length.text().strip() or "0",
            "farthest_height": self.f_hfarthest.text().strip() or "0",
            "bed_level": self.f_bedlevel.text().strip() or "0",
            "ohfl": self.f_ohfl.text().strip() or "0",
            "r50": self.f_r50.text().strip() or "0",
            "formation_level": self.f_fl.text().strip() or "0",
            "velocity": self.f_velocity.text().strip() or "2.44",
            "width": self.f_width.text().strip() or "1.5",
            "slab_thickness": self.f_slab.text().strip() or "0.35",
            "soil_type": self.f_soil.currentText(),
            "sub_zone": self.f_subzone.currentText(),
            "structure_type": self.f_struct.currentText(),
        }

    def clear(self):
        for f in (self.f_section, self.f_bridge, self.f_chainage, self.f_opening,
                  self.f_latlon, self.f_area, self.f_length, self.f_hfarthest,
                  self.f_bedlevel, self.f_ohfl, self.f_r50, self.f_fl,
                  self.f_velocity, self.f_width, self.f_slab):
            f.clear()


# ──────────────────────────────────────────────────────────────────────────────
#  OPTION 2 FORM
# ──────────────────────────────────────────────────────────────────────────────

class DoublingForm(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # ── Smart Extract drop zone ──────────────────────────────────
        extract_hdr = QLabel("  🤖  Smart Extract — Drop Drawing / PDF / Excel")
        extract_hdr.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        extract_hdr.setStyleSheet(
            f"background:{COLORS.get('navy_mid','#1e3a5f')}; color:#e0e0e0; "
            f"padding:3px 8px; border-radius:4px;")
        lay.addWidget(extract_hdr)

        self.extract_zone = QWidget()
        self.extract_zone.setFixedHeight(90)
        lay.addWidget(self.extract_zone)

        # ── Section header ───────────────────────────────────────────
        hdr1 = QLabel("  A   DATA PROFILE  —  Doubling / Tripling / Quadrupling")
        hdr1.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        hdr1.setStyleSheet(f"background:{COLORS['accent']}; color:#0D1117; padding:3px 8px; border-radius:4px;")
        lay.addWidget(hdr1)

        # ── All fields declared ──────────────────────────────────────
        self.f_bridge         = _field("25MB")
        self.f_section        = _field("BDCR-DKJ")
        self.f_chainage       = _field("15387.027m")
        self.f_between        = _field("Station names")
        self.f_division       = _combo(DIVISIONS)
        self.f_proposed_by    = _combo(PROPOSED_BY)
        self.f_bridge_cat     = _combo(BRIDGE_CATEGORIES)
        self.f_vlist          = _field("--")
        self.f_history        = _field("--")
        self.f_exg_desc       = _field("1x0.91m ARCH")
        self.f_prop_desc      = _field("1x1.00x1.20m RCC BOX")
        self.f_n_spans_exg    = _field("1")
        self.f_span_type_exg  = _combo(SPAN_TYPES)
        self.f_l_exg          = _field("0.91")
        self.f_rl_exg         = _field("173.095")
        self.f_fl_exg         = _field("172.407")
        self.f_bos_exg        = _field("171.301")
        self.f_ohfl           = _field("171.010")
        self.f_bl             = _field("170.551")
        self.f_n_spans_prop   = _field("1")
        self.f_span_type_prop = _combo(SPAN_TYPES)
        self.f_l_prop         = _field("1.00")
        self.f_rl_prop        = _field("186.152")
        self.f_fl_prop        = _field("173.095")
        self.f_bos_prop       = _field("172.333")
        self.f_us_ohfl        = _field("U/S OHFL (optional)")

        for f in (self.f_l_exg, self.f_rl_exg, self.f_fl_exg, self.f_bos_exg,
                  self.f_ohfl, self.f_bl, self.f_l_prop, self.f_rl_prop,
                  self.f_fl_prop, self.f_bos_prop):
            f.setValidator(QDoubleValidator())

        # ── Compact 3-column layout ──────────────────────────────────
        def _card(title, color, rows_data):
            frm = QFrame(); frm.setObjectName("card")
            fl = QVBoxLayout(frm)
            fl.setContentsMargins(6, 5, 6, 5)
            fl.setSpacing(2)
            t = QLabel(title)
            t.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            t.setStyleSheet(f"color:{color}; font-size:10px;")
            fl.addWidget(t)
            g = QGridLayout()
            g.setHorizontalSpacing(4); g.setVerticalSpacing(2)
            g.setColumnStretch(0, 3); g.setColumnStretch(1, 2)
            for r, (lbl_text, widget, unit) in enumerate(rows_data):
                lbl = QLabel(lbl_text)
                lbl.setStyleSheet("color:" + COLORS['text_secondary'] + "; font-size:10px;")
                g.addWidget(lbl, r, 0)
                g.addWidget(widget, r, 1)
                if unit:
                    u = QLabel(unit)
                    u.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:9px;")
                    g.addWidget(u, r, 2)
            fl.addLayout(g)
            fl.addStretch()
            return frm

        three_col = QHBoxLayout()
        three_col.setSpacing(6)

        gen_card = _card("GENERAL INFO", COLORS['accent'], [
            ("Bridge No.",   self.f_bridge,      ""),
            ("Section",      self.f_section,      ""),
            ("Chainage",     self.f_chainage,     ""),
            ("Between Stns", self.f_between,      ""),
            ("Division",     self.f_division,     ""),
            ("Proposed By",  self.f_proposed_by,  ""),
            ("Category",     self.f_bridge_cat,   ""),
            ("V-List",       self.f_vlist,        ""),
            ("Past History", self.f_history,      ""),
            ("Exg. Span",    self.f_exg_desc,     ""),
            ("Prop. Span",   self.f_prop_desc,    ""),
        ])

        exg_card = _card("EXISTING BRIDGE", COLORS.get('navy_mid','#1e3a5f'), [
            ("No. Spans",  self.f_n_spans_exg,  ""),
            ("Span Type",  self.f_span_type_exg, ""),
            ("L/Waterway", self.f_l_exg,        "m"),
            ("RL",         self.f_rl_exg,       "m"),
            ("FL",         self.f_fl_exg,       "m"),
            ("BOS",        self.f_bos_exg,      "m"),
            ("OHFL",       self.f_ohfl,         "m"),
            ("Bed Level",  self.f_bl,           "m"),
        ])
        exg_card.setStyleSheet(
            "QFrame#card { border:1.5px solid " + COLORS.get('navy_mid','#1e3a5f') + "; }"
        )

        prop_card = _card("PROPOSED BRIDGE", "#e05050", [
            ("No. Spans",  self.f_n_spans_prop,  ""),
            ("Span Type",  self.f_span_type_prop, ""),
            ("L/Waterway", self.f_l_prop,        "m"),
            ("RL",         self.f_rl_prop,       "m"),
            ("FL",         self.f_fl_prop,       "m"),
            ("BOS",        self.f_bos_prop,      "m"),
            ("U/S OHFL",   self.f_us_ohfl,       "m"),
        ])
        prop_card.setStyleSheet(
            "QFrame#card { border:1.5px solid #e05050; }"
        )

        three_col.addWidget(gen_card,  3)
        three_col.addWidget(exg_card,  2)
        three_col.addWidget(prop_card, 2)
        lay.addLayout(three_col)
        lay.addStretch()

    def get_inputs(self):
        return {
            "bridge_no":      self.f_bridge.text().strip(),
            "section":        self.f_section.text().strip(),
            "chainage":       self.f_chainage.text().strip(),
            "between_stns":   self.f_between.text().strip(),
            "division":       self.f_division.currentText(),
            "proposed_by":    self.f_proposed_by.currentText(),
            "bridge_cat":     self.f_bridge_cat.currentText(),
            "vlist":          self.f_vlist.text().strip() or "--",
            "past_history":   self.f_history.text().strip() or "--",
            "exg_span_desc":  self.f_exg_desc.text().strip(),
            "prop_span_desc": self.f_prop_desc.text().strip(),
            "n_spans_exg":    self.f_n_spans_exg.text().strip() or "1",
            "span_type_exg":  self.f_span_type_exg.currentText(),
            "l_exg":          self.f_l_exg.text().strip() or "0",
            "rl_exg":         self.f_rl_exg.text().strip() or "0",
            "fl_exg":         self.f_fl_exg.text().strip() or "0",
            "bos_exg":        self.f_bos_exg.text().strip() or "0",
            "ohfl":           self.f_ohfl.text().strip() or "0",
            "bl":             self.f_bl.text().strip() or "0",
            "n_spans_prop":   self.f_n_spans_prop.text().strip() or "1",
            "span_type_prop": self.f_span_type_prop.currentText(),
            "l_prop":         self.f_l_prop.text().strip() or "0",
            "rl_prop":        self.f_rl_prop.text().strip() or "0",
            "fl_prop":        self.f_fl_prop.text().strip() or "0",
            "bos_prop":       self.f_bos_prop.text().strip() or "0",
            "us_ohfl":        self.f_us_ohfl.text().strip(),
        }

    def clear(self):
        for f in (self.f_bridge, self.f_section, self.f_chainage, self.f_between,
                  self.f_vlist, self.f_history, self.f_exg_desc, self.f_prop_desc,
                  self.f_n_spans_exg, self.f_l_exg, self.f_rl_exg, self.f_fl_exg,
                  self.f_bos_exg, self.f_ohfl, self.f_bl,
                  self.f_n_spans_prop, self.f_l_prop, self.f_rl_prop,
                  self.f_fl_prop, self.f_bos_prop, self.f_us_ohfl):
            f.clear()


# ──────────────────────────────────────────────────────────────────────────────
#  MAIN PANEL
# ──────────────────────────────────────────────────────────────────────────────

class HydraulicPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._result  = None
        self._mode    = None   # "1" or "2"
        self._build()

    def _build(self):
        # Top-level vertical: toolbar + splitter
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Toolbar: preview toggle button ────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(34)
        toolbar.setStyleSheet(
            f"background:{COLORS.get('navy_light','#1a2540')}; "
            f"border-bottom:1px solid {COLORS['border']};"
        )
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(12, 0, 12, 0)
        tb_lay.addStretch()

        self._toggle_btn = QPushButton("⬅  Hide Preview")
        self._toggle_btn.setObjectName("secondaryBtn")
        self._toggle_btn.setFixedHeight(24)
        self._toggle_btn.setFixedWidth(150)
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setToolTip("Hide/show the calculation preview panel")
        self._toggle_btn.clicked.connect(self._toggle_preview)
        tb_lay.addWidget(self._toggle_btn)
        outer.addWidget(toolbar)

        # ── Splitter: left form | right preview ──────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(5)
        self._splitter.setChildrenCollapsible(True)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background: " + COLORS["border"] + "; }"
            "QSplitter::handle:hover { background: " + COLORS["accent"] + "; }"
        )
        outer.addWidget(self._splitter)

        # ── LEFT pane ────────────────────────────────────────────────────
        left_container = QWidget()
        left_outer = QVBoxLayout(left_container)
        left_outer.setContentsMargins(0, 0, 0, 0)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)

        left_widget = QWidget()
        self._left_lay = QVBoxLayout(left_widget)
        self._left_lay.setContentsMargins(20, 20, 14, 20)
        self._left_lay.setSpacing(0)
        left_scroll.setWidget(left_widget)
        left_outer.addWidget(left_scroll)
        self._splitter.addWidget(left_container)

        # Mode selector
        self._mode_sel = ModeSelectorWidget(self._on_mode_selected)
        self._left_lay.addWidget(self._mode_sel)
        self._left_lay.addSpacing(12)

        self._form_sep = QFrame()
        self._form_sep.setFrameShape(QFrame.Shape.HLine)
        self._form_sep.setStyleSheet(f"color:{COLORS['border']};")
        self._form_sep.setVisible(False)
        self._left_lay.addWidget(self._form_sep)
        self._left_lay.addSpacing(8)

        self._form_stack = QStackedWidget()
        self._form_stack.setVisible(False)
        self._form_newline  = NewLineForm()
        self._form_doubling = DoublingForm()
        self._form_stack.addWidget(self._form_newline)
        self._form_stack.addWidget(self._form_doubling)
        self._left_lay.addWidget(self._form_stack)
        self._left_lay.addSpacing(12)

        self._btn_area = QWidget()
        self._btn_area.setVisible(False)
        btn_row = QHBoxLayout(self._btn_area)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)

        self._calc_btn = QPushButton("⚡  Calculate")
        self._calc_btn.setObjectName("primaryBtn")
        self._calc_btn.setFixedHeight(40)
        self._calc_btn.clicked.connect(self._calculate)
        btn_row.addWidget(self._calc_btn)

        self._dl_btn = QPushButton("⬇  Download PDF")
        self._dl_btn.setObjectName("secondaryBtn")
        self._dl_btn.setFixedHeight(40)
        self._dl_btn.setEnabled(False)
        self._dl_btn.clicked.connect(self._download_pdf)
        btn_row.addWidget(self._dl_btn)

        self._clear_btn = QPushButton("✕  Clear")
        self._clear_btn.setObjectName("dangerBtn")
        self._clear_btn.setFixedHeight(40)
        self._clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(self._clear_btn)

        btn_row.addStretch()
        self._left_lay.addWidget(self._btn_area)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px; font-style:italic;")
        self._status_lbl.setVisible(False)
        self._left_lay.addWidget(self._status_lbl)
        self._left_lay.addStretch()

        # ── RIGHT pane: preview ──────────────────────────────────────────
        self._right_container = QWidget()
        right_outer = QVBoxLayout(self._right_container)
        right_outer.setContentsMargins(0, 0, 0, 0)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)

        right_widget = QWidget()
        right_lay = QVBoxLayout(right_widget)
        right_lay.setContentsMargins(18, 20, 20, 20)
        right_lay.setSpacing(0)
        right_scroll.setWidget(right_widget)

        prev_hdr = QLabel("Calculation Preview")
        prev_hdr.setObjectName("panelTitle")
        right_lay.addWidget(prev_hdr)

        prev_sub = QLabel(
            "Results appear here after Calculate. "
            "Drag the divider or click Hide Preview to get full width."
        )
        prev_sub.setObjectName("panelSubtitle")
        prev_sub.setWordWrap(True)
        right_lay.addWidget(prev_sub)

        right_lay.addSpacing(12)
        self._preview = PreviewWidget()
        right_lay.addWidget(self._preview)
        right_lay.addStretch()

        right_outer.addWidget(right_scroll)
        self._splitter.addWidget(self._right_container)

        # Default: 55% form, 45% preview
        self._splitter.setSizes([560, 440])

    # ── Preview toggle ────────────────────────────────────────────────────────

    def _toggle_preview(self, checked: bool):
        """Hide preview pane so form gets full width; show it again on toggle."""
        if checked:
            # Hide: collapse right pane, give all space to left
            self._right_container.setVisible(False)
            self._splitter.setSizes([1, 0])
            self._toggle_btn.setText("➡  Show Preview")
        else:
            # Show: restore 55/45 split
            self._right_container.setVisible(True)
            self._splitter.setSizes([560, 440])
            self._toggle_btn.setText("⬅  Hide Preview")

    # ── Mode selection ────────────────────────────────────────────────────────

    def _on_mode_selected(self, mode: str):
        self._mode = mode
        self._form_stack.setCurrentIndex(0 if mode == "1" else 1)
        self._form_stack.setVisible(True)
        self._form_sep.setVisible(True)
        self._btn_area.setVisible(True)
        self._status_lbl.setVisible(True)
        self._dl_btn.setEnabled(False)
        self._status_lbl.setText(
            "New Line (RBF-16)" if mode == "1"
            else "Doubling / Tripling / Quadrupling (Std.VC)"
        )
        self._preview.reset()
        self._result = None

        # Inject SmartExtractWidget into the active form's extract_zone
        form = self._form_newline if mode == "1" else self._form_doubling
        zone = form.extract_zone

        # Remove any previously injected widget
        old_layout = zone.layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        else:
            from PyQt6.QtWidgets import QVBoxLayout as _VBL
            _VBL(zone).setContentsMargins(0, 0, 0, 0)

        extractor = SmartExtractWidget(mode=mode, parent_form=form, parent=zone)
        zone.layout().addWidget(extractor)

    # ── Calculate ─────────────────────────────────────────────────────────────

    def _calculate(self):
        if not self._mode:
            QMessageBox.information(self, "Select Mode", "Please select a calculation mode first.")
            return

        if self._mode == "1":
            inp = self._form_newline.get_inputs()
            res = compute_newline(inp)
        else:
            inp = self._form_doubling.get_inputs()
            res = compute_doubling(inp)

        if "error" in res:
            QMessageBox.warning(self, "Input Error", res["error"])
            return

        self._result = res

        if self._mode == "1":
            self._preview.update_newline(res)
        else:
            self._preview.update_doubling(res)

        self._dl_btn.setEnabled(True)
        self._status_lbl.setText("Calculate complete — review preview before downloading.")
        self._status_lbl.setStyleSheet(f"color:{COLORS['accent']}; font-size:11px;")

    # ── Download PDF ──────────────────────────────────────────────────────────

    def _download_pdf(self):
        if not self._result:
            QMessageBox.warning(self, "No Results", "Please run Calculate first.")
            return

        bridge = self._result.get("bridge_no", "bridge") or "bridge"
        mode_tag = "NL" if self._mode == "1" else "DT"
        default_name = f"WaterWay_{mode_tag}_BRG_{bridge}.pdf"

        # Use desktop as default save location so dialog is easy to find
        import pathlib
        desktop = str(pathlib.Path.home() / "Desktop")
        default_path = os.path.join(desktop, default_name)

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Waterway Calculation PDF",
            default_path,
            "PDF Files (*.pdf);;All Files (*)"
        )
        if not path:
            self._status_lbl.setText("PDF download cancelled.")
            self._status_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
            return

        self._status_lbl.setText("Generating PDF...")
        self._status_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")

        try:
            if self._mode == "1":
                generate_pdf_newline(self._result, path)
            else:
                generate_pdf_doubling(self._result, path)

            if os.path.exists(path) and os.path.getsize(path) > 0:
                self._status_lbl.setText(
                    f"PDF saved ({os.path.getsize(path)//1024 + 1} KB): {os.path.basename(path)}"
                )
                self._status_lbl.setStyleSheet(f"color:{COLORS['accent']}; font-size:11px;")
                # Auto-open the PDF
                import subprocess
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            else:
                QMessageBox.critical(self, "PDF Error", "PDF file was not created. Check disk space.")

        except ImportError:
            QMessageBox.critical(
                self, "Missing Library",
                "reportlab is not installed in this Python environment.\n\n"
                f"Run this command in your terminal:\n"
                f"  {sys.executable} -m pip install reportlab\n\n"
                f"Then restart BES."
            )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self, "PDF Error",
                f"Could not generate PDF:\n{e}\n\n"
                f"Details:\n{traceback.format_exc()[-500:]}"
            )

    # ── Clear ─────────────────────────────────────────────────────────────────

    def _clear(self):
        self._form_newline.clear()
        self._form_doubling.clear()
        self._result = None
        self._dl_btn.setEnabled(False)
        self._status_lbl.setText("")
        self._preview.reset()
