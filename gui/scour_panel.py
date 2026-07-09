"""
scour_panel.py  —  Bridge Engineering Suite
Scour Depth Calculations panel (Lacey's Formula)

Autofilled from Hydraulic Calculations output (Q, B, HFL/CHFL).
User inputs: silt factor (f), soil type.
C coefficient default = 2.67 (editable).
Separate PDF download — not bundled with waterway calc.

Reference: Br. 302 Scour Depth Excel (confirmed all formulas).
"""

import math
import os
import sys

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QComboBox, QGridLayout,
    QMessageBox, QFileDialog, QSizePolicy, QButtonGroup,
    QRadioButton, QGroupBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QDoubleValidator

from gui.styles import COLORS


# ══════════════════════════════════════════════════════════════════════════════
#  CALCULATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

SOIL_TYPES = {
    "1": ("Ordinary Soil",  1.75),
    "2": ("SDR (Sand/Decomposed Rock)", 1.50),
    "3": ("Hard Rock",      0.30),
}


def compute_scour(inp: dict) -> dict:
    """
    inp keys:
      q      — Design discharge (cumecs)   [from hydraulic calc]
      b      — Width of opening (m)         [from proposed bridge]
      hfl    — HFL / CHFL (m)              [from proposed bridge CHFL]
      f      — Silt factor
      c      — Coefficient C (default 2.67)
      soil   — "1" | "2" | "3"
      bridge_no, section, chainage         [passthrough for PDF header]
    """
    try:
        Q    = float(inp["q"])
        B    = float(inp["b"])
        HFL  = float(inp["hfl"])
        f    = float(inp["f"])
        C    = float(inp.get("c", "2.67") or "2.67")
        soil = str(inp.get("soil", "2"))
    except (ValueError, KeyError) as e:
        return {"error": f"Invalid input: {e}"}

    if Q <= 0:  return {"error": "Discharge Q must be > 0"}
    if B <= 0:  return {"error": "Width B must be > 0"}
    if f <= 0:  return {"error": "Silt factor f must be > 0"}
    if C <= 0:  return {"error": "Coefficient C must be > 0"}

    # a) Lacey's Regime Width
    Pw = 1.811 * C * math.sqrt(Q)

    # b) Design discharge for foundation
    Qf = 1.30 * Q
    qf = Qf / B

    # c) Scour depth
    D_case_i  = 0.473 * (Qf / f) ** (1 / 3)      # B >= Pw
    D_case_ii = 1.338 * (qf ** 2 / f) ** (1 / 3)  # B <  Pw

    if B >= Pw:
        D     = D_case_i
        case  = "i"
        case_label = f"B ({B:.3f} m) ≥ Pw ({Pw:.3f} m) → Case i governs"
    else:
        D     = D_case_ii
        case  = "ii"
        case_label = f"B ({B:.3f} m) < Pw ({Pw:.3f} m) → Case ii governs"

    # d) Pier & Abutment scour depths
    D_pier = 2.00 * D
    D_abut = 1.25 * D

    # e) Scour levels
    SL_pier = HFL - D_pier
    SL_abut = HFL - D_abut

    # f) Foundation levels
    soil_label, fd = SOIL_TYPES.get(soil, ("SDR", 1.50))
    FL_pier = SL_pier - fd
    FL_abut = SL_abut - fd

    # ── IRS BSF Code checks ──────────────────────────────────────────────────
    # Cl. 6.1(iv): Foundation depth shall not be less than 1.75m below scour level
    min_fd_soil      = 1.75   # m (soil strata)
    pier_fd_ok       = (SL_pier - FL_pier) >= min_fd_soil
    abut_fd_ok       = (SL_abut - FL_abut) >= min_fd_soil

    # Cl. 6.9.1: Foundation depth from HFL ≥ 1.33 × max scour depth
    req_depth_pier   = 1.33 * D_pier    # required depth below HFL for piers
    req_depth_abut   = 1.33 * D_abut    # required depth below HFL for abutments
    act_depth_pier   = HFL - FL_pier    # actual depth of foundation below HFL
    act_depth_abut   = HFL - FL_abut
    pier_depth_ok    = act_depth_pier >= req_depth_pier
    abut_depth_ok    = act_depth_abut >= req_depth_abut

    return {
        # Passthrough
        "bridge_no":   inp.get("bridge_no", ""),
        "section":     inp.get("section", ""),
        "chainage":    inp.get("chainage", ""),
        "span_desc":   inp.get("span_desc", ""),
        # Inputs
        "Q": Q, "B": B, "HFL": HFL, "f": f, "C": C,
        "soil": soil, "soil_label": soil_label, "fd": fd,
        # Intermediate
        "Pw": Pw, "Qf": Qf, "qf": qf,
        "D_case_i":  D_case_i,
        "D_case_ii": D_case_ii,
        "D": D, "case": case, "case_label": case_label,
        # Results
        "D_pier": D_pier, "D_abut": D_abut,
        "SL_pier": SL_pier, "SL_abut": SL_abut,
        "FL_pier": FL_pier, "FL_abut": FL_abut,
        # IRS BSF Code checks
        "min_fd_soil":    min_fd_soil,
        "pier_fd_ok":     pier_fd_ok,
        "abut_fd_ok":     abut_fd_ok,
        "req_depth_pier": req_depth_pier,
        "req_depth_abut": req_depth_abut,
        "act_depth_pier": act_depth_pier,
        "act_depth_abut": act_depth_abut,
        "pier_depth_ok":  pier_depth_ok,
        "abut_depth_ok":  abut_depth_ok,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PDF GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def generate_scour_pdf(res: dict, path: str):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors as rc
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    W, H = A4
    M = 14 * mm
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=M, rightMargin=M,
                            topMargin=M, bottomMargin=M)

    BASE = getSampleStyleSheet()
    def S(name, **kw): return ParagraphStyle(name, parent=BASE["Normal"], **kw)

    teal  = rc.HexColor("#006666")
    lgrey = rc.HexColor("#f5f5f5")
    mgrey = rc.HexColor("#dddddd")
    green = rc.HexColor("#006400")
    amber = rc.HexColor("#b8860b")

    hdr_s  = S("h",  fontSize=8,  textColor=rc.white,
               fontName="Helvetica-Bold", alignment=TA_CENTER)
    ttl_s  = S("t",  fontSize=13, textColor=teal,
               fontName="Helvetica-Bold", alignment=TA_CENTER)
    sub_s  = S("s",  fontSize=8,  textColor=rc.HexColor("#444"),
               alignment=TA_CENTER)
    sec_s  = S("sc", fontSize=9,  fontName="Helvetica-Bold",
               textColor=rc.white)
    lbl_s  = S("l",  fontSize=8.5)
    val_s  = S("v",  fontSize=8.5, fontName="Helvetica-Bold")
    note_s = S("n",  fontSize=7.5, textColor=rc.HexColor("#555"),
               alignment=TA_CENTER)
    res_s  = S("r",  fontSize=10, fontName="Helvetica-Bold",
               textColor=teal, alignment=TA_CENTER)

    def sec_hdr(letter, text):
        t = Table([[Paragraph(f" {letter}  {text}", sec_s)]],
                  colWidths=[W - 2*M])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), teal),
            ("TOPPADDING",    (0,0),(-1,-1), 4),
            ("BOTTOMPADDING", (0,0),(-1,-1), 4),
            ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ]))
        return t

    CW = [8*mm, 100*mm, W - 2*M - 108*mm]

    def dtbl(rows):
        t = Table(rows, colWidths=CW)
        t.setStyle(TableStyle([
            ("BOX",           (0,0),(-1,-1), 0.5, mgrey),
            ("INNERGRID",     (0,0),(-1,-1), 0.3, mgrey),
            ("BACKGROUND",    (0,0),(0,-1),  lgrey),
            ("TOPPADDING",    (0,0),(-1,-1), 2.5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 2.5),
            ("LEFTPADDING",   (0,0),(-1,-1), 5),
        ]))
        return t

    def r3(sl, desc, val):
        return [Paragraph(str(sl), lbl_s),
                Paragraph(desc, lbl_s),
                Paragraph(str(val), val_s)]

    story = []

    # ── Banner ──
    hdr_data = [[Paragraph(
        f"SOUTH CENTRAL RAILWAY | BRIDGE ENGINEERING  —  Scour Depth Calculations<br/>"
        f"Section: {res['section']}  |  Bridge No. {res['bridge_no']}  |  "
        f"Chainage: {res['chainage']}",
        hdr_s
    )]]
    ht = Table(hdr_data, colWidths=[W - 2*M])
    ht.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), teal),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
    ]))
    story.append(ht)
    story.append(Spacer(1, 5))
    story.append(Paragraph("SCOUR DEPTH CALCULATIONS FOR BRIDGE FOUNDATIONS", ttl_s))
    story.append(Paragraph("Based on Lacey's Regime Theory  (IS: 3955)", sub_s))
    if res['span_desc']:
        story.append(Paragraph(f"Proposed Span: {res['span_desc']}", sub_s))
    story.append(Spacer(1, 8))

    # ── Input Data ──
    story.append(sec_hdr("A", "INPUT DATA"))
    story.append(dtbl([
        r3("1)", "Design Discharge (Q)",
           f"{res['Q']:.3f} cumecs"),
        r3("2)", "Width of Opening / Linear Waterway (B)",
           f"{res['B']:.3f} m"),
        r3("3)", "Silt Factor (f)",
           f"{res['f']:.3f}"),
        r3("4)", "Coefficient C",
           f"{res['C']:.2f}"),
        r3("5)", "Highest Flood Level / CHFL",
           f"{res['HFL']:.3f} m"),
        r3("6)", "Type of Soil Below Scour Level", res['soil_label']),
    ]))
    story.append(Spacer(1, 6))

    # ── Calculations ──
    story.append(sec_hdr("B", "CALCULATIONS  [Ref: IRS Bridge Sub-Structures & Foundation Code, 2013]"))

    # ── B1: Lacey regime + Qf ──
    story.append(Paragraph(
        "<b>B1. Lacey's Regime Width &amp; Design Discharge for Foundations</b>  "
        "<i>(Cl. 4.5.3 &amp; 4.4, IRS BSF Code)</i>",
        S("sh", fontSize=8.5, textColor=teal, fontName="Helvetica-Bold")
    ))
    story.append(dtbl([
        r3("a)", "Lacey's Regime Width  [Pw = 1.811 × C × √Q]  "
                 "(C = {:.2f}; normal alluvial conditions, range 2.5–3.5 as per Cl. 4.5.3)".format(res["C"]),
           f"1.811 × {res['C']:.2f} × √{res['Q']:.3f} = {res['Pw']:.3f} m"),
        r3("b)", "Design Discharge for Foundation  [Qf = 1.30 × Q]  "
                 "(Catchment ≤ 500 km² → 30% increase, Cl. 4.4, IRS BSF Code)",
           f"1.30 × {res['Q']:.3f} = {res['Qf']:.3f} cumecs"),
        r3("",   "Discharge Intensity per metre width  [qf = Qf / B]",
           f"{res['Qf']:.3f} / {res['B']:.3f} = {res['qf']:.3f} cumecs/m"),
    ]))
    story.append(Spacer(1, 5))

    # ── B2: Case determination ──
    story.append(Paragraph(
        "<b>B2. Normal Scour Depth  (Lacey's Formula)</b>  "
        "<i>(Cl. 4.6.3 &amp; 4.6.4, IRS BSF Code)</i>",
        S("sh2", fontSize=8.5, textColor=teal, fontName="Helvetica-Bold")
    ))
    story.append(dtbl([
        r3("c)", "Case Determination  [Compare B vs Pw]",
           res['case_label']),
        r3("",   "Case i   (B ≥ Pw) — Natural channel, width ≥ Lacey regime width  "
                 "[D = 0.473 × (Qf/f)^(1/3)]  (Cl. 4.6.3)",
           f"0.473 × ({res['Qf']:.3f} / {res['f']:.3f})^(1/3) = {res['D_case_i']:.3f} m"),
        r3("",   "Case ii  (B < Pw) — Constricted waterway, width < Lacey regime width  "
                 "[D = 1.338 × (qf²/f)^(1/3)]  (Cl. 4.6.4)",
           f"1.338 × ({res['qf']:.3f}² / {res['f']:.3f})^(1/3) = {res['D_case_ii']:.3f} m"),
        r3("",   f"GOVERNING Normal Scour Depth D  (Case {res['case']} governs)",
           f"{res['D']:.3f} m"),
    ]))
    story.append(Spacer(1, 5))

    # ── B3: Cl.4.6.6 multiplier table ──
    story.append(Paragraph(
        "<b>B3. Maximum Scour Depth — River Condition Multipliers</b>  "
        "<i>(Cl. 4.6.6, IRS BSF Code)</i>",
        S("sh3", fontSize=8.5, textColor=teal, fontName="Helvetica-Bold")
    ))

    # Reference table
    cl466_hdr = [
        Paragraph("Nature of River / Location", S("th", fontSize=7.5, fontName="Helvetica-Bold",
                  textColor=rc.white, alignment=TA_CENTER)),
        Paragraph("Multiplier", S("th2", fontSize=7.5, fontName="Helvetica-Bold",
                  textColor=rc.white, alignment=TA_CENTER)),
        Paragraph("Adopted", S("th3", fontSize=7.5, fontName="Helvetica-Bold",
                  textColor=rc.white, alignment=TA_CENTER)),
    ]
    cl466_rows = [
        cl466_hdr,
        [Paragraph("In a straight reach", lbl_s),
         Paragraph("1.25 D", lbl_s), Paragraph("—", lbl_s)],
        [Paragraph("At moderate bend / along apron of guide bund", lbl_s),
         Paragraph("1.50 D", lbl_s), Paragraph("—", lbl_s)],
        [Paragraph("At a severe bend", lbl_s),
         Paragraph("1.75 D", lbl_s), Paragraph("—", lbl_s)],
        [Paragraph("<b>At right angle bend or nose of piers</b>", lbl_s),
         Paragraph("<b>2.00 D</b>", val_s),
         Paragraph("<b>← Piers</b>", val_s)],
        [Paragraph("<b>In a straight reach (abutments)</b>", lbl_s),
         Paragraph("<b>1.25 D</b>", val_s),
         Paragraph("<b>← Abutments</b>", val_s)],
        [Paragraph("In severe swirls (mole head of guide bund)", lbl_s),
         Paragraph("2.50D to 2.75D", lbl_s), Paragraph("—", lbl_s)],
    ]
    cw466 = [100*mm, 28*mm, W-2*M-128*mm]
    tbl466 = Table(cl466_rows, colWidths=cw466)
    tbl466.setStyle(TableStyle([
        ("BOX",        (0,0),(-1,-1), 0.5, mgrey),
        ("INNERGRID",  (0,0),(-1,-1), 0.3, mgrey),
        ("BACKGROUND", (0,0),(-1,0),  teal),
        ("BACKGROUND", (0,4),(-1,4),  rc.HexColor("#e0f5ef")),
        ("BACKGROUND", (0,5),(-1,5),  rc.HexColor("#e0f5ef")),
        ("TOPPADDING",    (0,0),(-1,-1), 2.5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2.5),
        ("LEFTPADDING",   (0,0),(-1,-1), 5),
    ]))
    story.append(tbl466)
    story.append(Spacer(1, 4))

    story.append(dtbl([
        r3("d)", "Maximum Scour Depth for Piers  [2.00 × D]  "
                 "(Nose of piers — Cl. 4.6.6, IRS BSF Code)",
           f"2.00 × {res['D']:.3f} = {res['D_pier']:.3f} m"),
        r3("",   "Maximum Scour Depth for Abutments  [1.25 × D]  "
                 "(Straight reach — Cl. 4.6.6, IRS BSF Code)",
           f"1.25 × {res['D']:.3f} = {res['D_abut']:.3f} m"),
    ]))
    story.append(Spacer(1, 6))

    # ── Scour Levels ──
    story.append(sec_hdr("C", "SCOUR LEVELS  (HFL / CHFL − Scour Depth)"))
    story.append(dtbl([
        r3("i)",  "Scour Level — Piers",
           f"{res['HFL']:.3f} − {res['D_pier']:.3f} = {res['SL_pier']:.3f} m"),
        r3("ii)", "Scour Level — Abutments",
           f"{res['HFL']:.3f} − {res['D_abut']:.3f} = {res['SL_abut']:.3f} m"),
    ]))
    story.append(Spacer(1, 6))

    # ── Foundation Levels ──
    story.append(sec_hdr("D", f"FOUNDATION LEVELS  (Scour Level − {res['fd']:.2f} m for {res['soil_label']})"))
    story.append(dtbl([
        r3("i)",  "Foundation Level — Piers",
           f"{res['SL_pier']:.3f} − {res['fd']:.2f} = {res['FL_pier']:.3f} m"),
        r3("ii)", "Foundation Level — Abutments",
           f"{res['SL_abut']:.3f} − {res['fd']:.2f} = {res['FL_abut']:.3f} m"),
    ]))
    story.append(Spacer(1, 8))

    # ── Summary Table ──
    story.append(sec_hdr("E", "SUMMARY"))
    sum_hdr_row = [
        Paragraph(h, S("sh", fontSize=8, fontName="Helvetica-Bold",
                       textColor=rc.white, alignment=TA_CENTER))
        for h in ["Parameter", "Piers", "Abutments"]
    ]
    cw2 = [90*mm, (W - 2*M - 90*mm) / 2, (W - 2*M - 90*mm) / 2]
    sum_rows = [
        sum_hdr_row,
        [Paragraph("Scour Depth (m)",       lbl_s),
         Paragraph(f"{res['D_pier']:.3f}",  val_s),
         Paragraph(f"{res['D_abut']:.3f}",  val_s)],
        [Paragraph("Scour Level (m)",       lbl_s),
         Paragraph(f"{res['SL_pier']:.3f}", val_s),
         Paragraph(f"{res['SL_abut']:.3f}", val_s)],
        [Paragraph("Foundation Level (m)",  lbl_s),
         Paragraph(f"{res['FL_pier']:.3f}", val_s),
         Paragraph(f"{res['FL_abut']:.3f}", val_s)],
    ]
    sum_tbl = Table(sum_rows, colWidths=cw2)
    sum_tbl.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.5, mgrey),
        ("INNERGRID",     (0,0),(-1,-1), 0.3, mgrey),
        ("BACKGROUND",    (0,0),(-1,0),  teal),
        ("BACKGROUND",    (0,1),(0,-1),  lgrey),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("ALIGN",         (1,0),(-1,-1), "CENTER"),
    ]))
    story.append(sum_tbl)
    story.append(Spacer(1, 8))

    # ── Section E: IRS BSF Code Compliance Checks ──
    story.append(sec_hdr("E", "CODE COMPLIANCE CHECKS  [IRS Bridge Sub-Structures & Foundation Code, 2013]"))

    def _ok(val): return ("✓  PASS" if val else "✗  FAIL — REVIEW REQUIRED")
    def _ok_color(val): return green if val else rc.red
    def _check_row(ref, desc, computed, required, ok):
        return [
            Paragraph(ref, lbl_s),
            Paragraph(desc, lbl_s),
            Paragraph(computed, lbl_s),
            Paragraph(required, lbl_s),
            Paragraph(_ok(ok), S("ok", fontSize=8, fontName="Helvetica-Bold",
                                 textColor=_ok_color(ok))),
        ]

    chk_hdr = [
        Paragraph(h, S("ch"+str(i), fontSize=7.5, fontName="Helvetica-Bold",
                   textColor=rc.white, alignment=TA_CENTER))
        for i,h in enumerate(["Ref.", "Check Description",
                               "Computed", "Minimum Required", "Status"])
    ]
    cw_chk = [18*mm, 75*mm, 28*mm, 28*mm, W-2*M-149*mm]

    chk_rows = [
        chk_hdr,
        # Cl.6.1(iv): min 1.75m below scour for soil
        _check_row(
            "Cl. 6.1(iv)",
            "Min. foundation depth below scour level — Piers\n"
            "(≥ 1.75m for soil strata)",
            f"{res['SL_pier']:.3f} − {res['FL_pier']:.3f} = "
            f"{res['SL_pier']-res['FL_pier']:.3f} m",
            f"≥ {res['min_fd_soil']:.2f} m",
            res["pier_fd_ok"]
        ),
        _check_row(
            "Cl. 6.1(iv)",
            "Min. foundation depth below scour level — Abutments\n"
            "(≥ 1.75m for soil strata)",
            f"{res['SL_abut']:.3f} − {res['FL_abut']:.3f} = "
            f"{res['SL_abut']-res['FL_abut']:.3f} m",
            f"≥ {res['min_fd_soil']:.2f} m",
            res["abut_fd_ok"]
        ),
        # Cl.6.9.1: Foundation depth from HFL ≥ 1.33 × max scour depth
        _check_row(
            "Cl. 6.9.1",
            "Foundation depth from HFL — Piers\n"
            "(≥ 1.33 × Max. Scour Depth)",
            f"{res['HFL']:.3f} − {res['FL_pier']:.3f} = "
            f"{res['act_depth_pier']:.3f} m",
            f"≥ 1.33 × {res['D_pier']:.3f} = {res['req_depth_pier']:.3f} m",
            res["pier_depth_ok"]
        ),
        _check_row(
            "Cl. 6.9.1",
            "Foundation depth from HFL — Abutments\n"
            "(≥ 1.33 × Max. Scour Depth)",
            f"{res['HFL']:.3f} − {res['FL_abut']:.3f} = "
            f"{res['act_depth_abut']:.3f} m",
            f"≥ 1.33 × {res['D_abut']:.3f} = {res['req_depth_abut']:.3f} m",
            res["abut_depth_ok"]
        ),
    ]

    chk_tbl = Table(chk_rows, colWidths=cw_chk)
    chk_tbl.setStyle(TableStyle([
        ("BOX",        (0,0),(-1,-1), 0.5, mgrey),
        ("INNERGRID",  (0,0),(-1,-1), 0.3, mgrey),
        ("BACKGROUND", (0,0),(-1,0),  teal),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 4),
        ("BACKGROUND", (0,1),(-1,1),
         rc.HexColor("#f0fff8") if res["pier_fd_ok"] else rc.HexColor("#fff0f0")),
        ("BACKGROUND", (0,2),(-1,2),
         rc.HexColor("#f0fff8") if res["abut_fd_ok"] else rc.HexColor("#fff0f0")),
        ("BACKGROUND", (0,3),(-1,3),
         rc.HexColor("#f0fff8") if res["pier_depth_ok"] else rc.HexColor("#fff0f0")),
        ("BACKGROUND", (0,4),(-1,4),
         rc.HexColor("#f0fff8") if res["abut_depth_ok"] else rc.HexColor("#fff0f0")),
    ]))
    story.append(chk_tbl)
    story.append(Spacer(1, 5))

    # ── Code references ──
    refs_data = [[Paragraph(
        "<b>Code References:</b>  "
        "IRS Bridge Sub-Structures &amp; Foundation Code (BSF Code), Second Revision 2013 "
        "(incorporating ACS 11 dtd. 25.04.2024), RDSO, Lucknow  |  "
        "Cl. 4.4 (Design discharge for foundations)  |  "
        "Cl. 4.5.3 (Lacey's regime width)  |  "
        "Cl. 4.6.3 &amp; 4.6.4 (Scour depth formulae)  |  "
        "Cl. 4.6.5 (Silt factor)  |  "
        "Cl. 4.6.6 (Depth multipliers)  |  "
        "Cl. 6.1(iv) &amp; 6.9.1 (Foundation depth criteria)  |  "
        "IS:3955-1967 (Well Foundation Design)",
        S("refs", fontSize=7, textColor=rc.HexColor("#333"))
    )]]
    refs_tbl = Table(refs_data, colWidths=[W-2*M])
    refs_tbl.setStyle(TableStyle([
        ("BOX",     (0,0),(-1,-1), 0.5, mgrey),
        ("BACKGROUND", (0,0),(-1,-1), lgrey),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
    ]))
    story.append(refs_tbl)
    story.append(Spacer(1, 8))

    story.append(Paragraph(
        f"Prepared for: South Central Railway | Bridge Engineering Dept. | Section: {res['section']}",
        note_s
    ))

    doc.build(story)


# ══════════════════════════════════════════════════════════════════════════════
#  SCOUR PANEL WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class ScourPanel(QWidget):
    """
    Embedded below the Hydraulic Calculate button.
    autofill(result_dict) is called by HydraulicPanel after calculation.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result   = None
        self._hydro_res = None
        self._build()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # ── Collapsible header ──────────────────────────────────────────
        self._toggle_btn = QPushButton("▼   Scour Depth Calculations  (click to expand)")
        self._toggle_btn.setObjectName("secondaryBtn")
        self._toggle_btn.setFixedHeight(34)
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)
        self._toggle_btn.clicked.connect(self._toggle)
        lay.addWidget(self._toggle_btn)

        # ── Collapsible body ────────────────────────────────────────────
        self._body = QWidget()
        self._body.setVisible(False)
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 4, 0, 0)
        body_lay.setSpacing(6)

        # ── Info banner ──
        info = QLabel(
            "Values below are autofilled from the Hydraulic Calculation. "
            "Edit if needed, then click  ⚡ Calculate Scour."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:11px; "
            f"font-style:italic; padding:4px 0px;")
        body_lay.addWidget(info)

        # ── Input grid (2 columns) ──────────────────────────────────────
        grid_frame = QFrame(); grid_frame.setObjectName("card")
        gf_lay = QVBoxLayout(grid_frame)
        gf_lay.setContentsMargins(12, 10, 12, 10)
        gf_lay.setSpacing(4)

        # Section label
        sec_lbl = QLabel("  INPUT DATA")
        sec_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        sec_lbl.setStyleSheet(
            f"background:{COLORS['accent']}; color:#0D1117; "
            f"padding:3px 8px; border-radius:4px;")
        gf_lay.addWidget(sec_lbl)

        two = QHBoxLayout(); two.setSpacing(12)

        # Left column: autofilled from hydraulic calc
        left = QFrame(); left.setObjectName("card")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 6, 8, 6)
        left_lay.setSpacing(3)
        auto_lbl = QLabel("Auto-filled from Hydraulic Calc")
        auto_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:9px; font-style:italic;")
        left_lay.addWidget(auto_lbl)

        lg = QGridLayout()
        lg.setHorizontalSpacing(6); lg.setVerticalSpacing(3)
        lg.setColumnStretch(0, 3); lg.setColumnStretch(1, 2)

        self.f_q   = self._field("Q (cumecs)",  "e.g. 5.05")
        self.f_b   = self._field("B (m)",        "e.g. 1.50")
        self.f_hfl = self._field("CHFL (m)",     "e.g. 441.686")
        self.f_bn  = self._field("Bridge No.",   "e.g. 53")
        self.f_sec = self._field("Section",      "e.g. DKJ-BDCR")
        self.f_ch  = self._field("Chainage",     "e.g. 272311.90 m")
        self.f_sp  = self._field("Span Desc.",   "e.g. 1x1.5x1.5m RCC BOX")

        for f in (self.f_q, self.f_b, self.f_hfl):
            f.setValidator(QDoubleValidator())

        auto_rows = [
            ("Q — Design Discharge", self.f_q,  "cumecs"),
            ("B — Linear Waterway",  self.f_b,  "m"),
            ("CHFL / HFL",           self.f_hfl,"m"),
            ("Bridge No.",           self.f_bn, ""),
            ("Section",              self.f_sec,""),
            ("Chainage",             self.f_ch, ""),
            ("Proposed Span",        self.f_sp, ""),
        ]
        for r, (lbl, wgt, unit) in enumerate(auto_rows):
            l = QLabel(lbl)
            l.setStyleSheet(
                f"color:{COLORS['text_secondary']}; font-size:11px;")
            lg.addWidget(l, r, 0)
            lg.addWidget(wgt, r, 1)
            if unit:
                u = QLabel(unit)
                u.setStyleSheet(
                    f"color:{COLORS['text_muted']}; font-size:9px;")
                lg.addWidget(u, r, 2)

        left_lay.addLayout(lg)
        two.addWidget(left, 3)

        # Right column: user inputs
        right = QFrame(); right.setObjectName("card")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 6, 8, 6)
        right_lay.setSpacing(3)
        user_lbl = QLabel("User Inputs")
        user_lbl.setStyleSheet(
            f"color:{COLORS['accent']}; font-size:9px; font-weight:bold;")
        right_lay.addWidget(user_lbl)

        rg = QGridLayout()
        rg.setHorizontalSpacing(6); rg.setVerticalSpacing(3)
        rg.setColumnStretch(0, 3); rg.setColumnStretch(1, 2)

        self.f_f = self._field("Silt Factor",   "e.g. 2.0")
        self.f_c = self._field("Coeff. C",      "2.67")
        self.f_c.setText("2.67")
        for f in (self.f_f, self.f_c):
            f.setValidator(QDoubleValidator())

        rg.addWidget(QLabel("Silt Factor (f)"), 0, 0)
        rg.addWidget(self.f_f, 0, 1)

        rg.addWidget(QLabel("Coefficient C"), 1, 0)
        rg.addWidget(self.f_c, 1, 1)

        # Soil type
        soil_lbl = QLabel("Soil Type")
        soil_lbl.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:11px;")
        rg.addWidget(soil_lbl, 2, 0)
        self.f_soil = QComboBox()
        self.f_soil.setFixedHeight(30)
        for k, (label, _) in SOIL_TYPES.items():
            self.f_soil.addItem(f"{k}  —  {label}", k)
        self.f_soil.setCurrentIndex(1)   # default SDR
        rg.addWidget(self.f_soil, 2, 1)

        # Style labels
        for r in range(3):
            item = rg.itemAtPosition(r, 0)
            if item and item.widget():
                item.widget().setStyleSheet(
                    f"color:{COLORS['text_secondary']}; font-size:11px;")

        right_lay.addLayout(rg)
        right_lay.addStretch()
        two.addWidget(right, 2)

        gf_lay.addLayout(two)
        body_lay.addWidget(grid_frame)

        # ── Action buttons ──────────────────────────────────────────────
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)

        self._calc_btn = QPushButton("⚡  Calculate Scour")
        self._calc_btn.setObjectName("primaryBtn")
        self._calc_btn.setFixedHeight(36)
        self._calc_btn.clicked.connect(self._calculate)
        btn_row.addWidget(self._calc_btn)

        self._dl_btn = QPushButton("⬇  Download Scour PDF")
        self._dl_btn.setObjectName("secondaryBtn")
        self._dl_btn.setFixedHeight(36)
        self._dl_btn.setEnabled(False)
        self._dl_btn.clicked.connect(self._download_pdf)
        btn_row.addWidget(self._dl_btn)

        btn_row.addStretch()
        body_lay.addLayout(btn_row)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:11px; font-style:italic;")
        body_lay.addWidget(self._status)

        # ── Results preview ─────────────────────────────────────────────
        self._result_frame = QFrame()
        self._result_frame.setObjectName("card")
        self._result_frame.setVisible(False)
        rf_lay = QVBoxLayout(self._result_frame)
        rf_lay.setContentsMargins(12, 8, 12, 8)
        rf_lay.setSpacing(4)

        res_hdr = QLabel("  RESULTS")
        res_hdr.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        res_hdr.setStyleSheet(
            f"background:{COLORS['accent']}; color:#0D1117; "
            f"padding:3px 8px; border-radius:4px;")
        rf_lay.addWidget(res_hdr)

        res_grid = QGridLayout()
        res_grid.setHorizontalSpacing(10)
        res_grid.setVerticalSpacing(4)

        # Column headers
        for col, txt in [(1,""), (2,"Piers"), (3,"Abutments")]:
            h = QLabel(txt)
            h.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            h.setStyleSheet(f"color:{COLORS['accent']}; border:none;")
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            res_grid.addWidget(h, 0, col)

        self._res_labels = {}
        rows_def = [
            ("Pw",    "Lacey's Regime Width (Pw)",  "",          ""),
            ("D",     "Governing Scour Depth (D)",  "Pier 2D",   "Abut 1.25D"),
            ("D_val", "Scour Depth",                "",          ""),
            ("SL",    "Scour Level",                "",          ""),
            ("FL",    "Foundation Level",           "",          ""),
        ]

        self._rw_pw    = self._res_row(res_grid, 1, "Lacey's Regime Width (Pw)")
        self._rw_case  = self._res_row(res_grid, 2, "Governing Case")
        self._rw_D     = self._res_row(res_grid, 3, "Basic Scour Depth D")
        self._rw_Dvals = self._res_row(res_grid, 4, "Scour Depth (2D / 1.25D)")
        self._rw_SL    = self._res_row(res_grid, 5, "Scour Level")
        self._rw_FL    = self._res_row(res_grid, 6, "Foundation Level")

        rf_lay.addLayout(res_grid)
        body_lay.addWidget(self._result_frame)

        lay.addWidget(self._body)

    def _field(self, label, placeholder=""):
        f = QLineEdit()
        f.setPlaceholderText(placeholder)
        f.setFixedHeight(28)
        f.setStyleSheet("font-size:11px;")
        return f

    def _res_row(self, grid, row, label):
        """Add a result row with label, pier value, abut value. Returns (pier_lbl, abut_lbl)."""
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:11px; border:none;")
        grid.addWidget(lbl, row, 1)

        pier = QLabel("—")
        pier.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        pier.setStyleSheet(f"color:{COLORS['accent']}; border:none;")
        pier.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(pier, row, 2)

        abut = QLabel("—")
        abut.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        abut.setStyleSheet(f"color:{COLORS['accent']}; border:none;")
        abut.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(abut, row, 3)

        return pier, abut

    # ── Toggle ────────────────────────────────────────────────────────────────

    def _toggle(self, checked):
        self._body.setVisible(checked)
        self._toggle_btn.setText(
            "▲   Scour Depth Calculations  (click to collapse)" if checked
            else "▼   Scour Depth Calculations  (click to expand)"
        )

    # ── Autofill from Hydraulic Calculation ───────────────────────────────────

    def autofill(self, hydro_res: dict):
        """
        Called by HydraulicPanel after Option 1 or Option 2 calculation.
        Extracts Q, B, CHFL from the appropriate result dict.
        """
        self._hydro_res = hydro_res
        mode = hydro_res.get("mode", "newline")

        if mode == "newline":
            Q    = hydro_res.get("Q50", "")
            B    = hydro_res.get("width", "")
            HFL  = hydro_res.get("CHFL", "")
            bn   = hydro_res.get("bridge_no", "")
            sec  = hydro_res.get("section", "")
            ch   = hydro_res.get("chainage", "")
            sp   = hydro_res.get("structure_type", "")
        else:   # doubling
            Q    = hydro_res.get("Q", "")
            B    = hydro_res.get("l_prop", "")
            HFL  = hydro_res.get("adopted_CHFL", hydro_res.get("CHFL", ""))
            bn   = hydro_res.get("bridge_no", "")
            sec  = hydro_res.get("section", "")
            ch   = hydro_res.get("chainage", "")
            sp   = hydro_res.get("prop_span_desc", "")

        def _set(field, val):
            if val not in ("", None):
                field.setText(f"{float(val):.3f}" if isinstance(val, float) else str(val))
                field.setStyleSheet(
                    f"border:1.5px solid {COLORS['accent']}; "
                    f"border-radius:4px; font-size:11px;")
            else:
                field.setStyleSheet("font-size:11px;")

        _set(self.f_q,   Q)
        _set(self.f_b,   B)
        _set(self.f_hfl, HFL)
        _set(self.f_bn,  bn)
        _set(self.f_sec, sec)
        _set(self.f_ch,  ch)
        _set(self.f_sp,  sp)

        # Expand the panel automatically
        self._toggle_btn.setChecked(True)
        self._toggle(True)
        self._status.setText(
            "✔  Values autofilled from hydraulic calculation — verify and click Calculate Scour.")
        self._status.setStyleSheet(
            f"color:{COLORS['accent']}; font-size:11px;")

    # ── Calculate ─────────────────────────────────────────────────────────────

    def _calculate(self):
        soil_key = self.f_soil.currentData() or "2"
        inp = {
            "q":         self.f_q.text().strip(),
            "b":         self.f_b.text().strip(),
            "hfl":       self.f_hfl.text().strip(),
            "f":         self.f_f.text().strip(),
            "c":         self.f_c.text().strip() or "2.67",
            "soil":      soil_key,
            "bridge_no": self.f_bn.text().strip(),
            "section":   self.f_sec.text().strip(),
            "chainage":  self.f_ch.text().strip(),
            "span_desc": self.f_sp.text().strip(),
        }

        if not inp["f"]:
            QMessageBox.warning(self, "Input Required",
                                "Please enter the Silt Factor (f) before calculating.")
            self.f_f.setFocus()
            return

        res = compute_scour(inp)
        if "error" in res:
            QMessageBox.warning(self, "Calculation Error", res["error"])
            return

        self._result = res
        self._update_results(res)
        self._dl_btn.setEnabled(True)
        self._status.setText(
            f"✔  Scour depth calculated — D = {res['D']:.3f} m "
            f"(Pier FL: {res['FL_pier']:.3f} m, Abut FL: {res['FL_abut']:.3f} m)")
        self._status.setStyleSheet(f"color:{COLORS['accent']}; font-size:11px;")

    def _update_results(self, res):
        self._result_frame.setVisible(True)

        def _set_row(pair, pier_val, abut_val=""):
            pair[0].setText(pier_val)
            if abut_val:
                pair[1].setText(abut_val)
            else:
                pair[1].setText(pier_val)

        # Pw — same for both columns
        pw_txt = f"{res['Pw']:.3f} m"
        self._rw_pw[0].setText(pw_txt)
        self._rw_pw[1].setText("")
        self._rw_pw[1].hide()

        # Case
        self._rw_case[0].setText(res['case_label'])
        self._rw_case[1].setText("")
        self._rw_case[1].hide()

        # D
        self._rw_D[0].setText(f"{res['D']:.3f} m")
        self._rw_D[1].setText("")
        self._rw_D[1].hide()

        # Scour depth values
        self._rw_Dvals[0].setText(f"{res['D_pier']:.3f} m")
        self._rw_Dvals[1].setText(f"{res['D_abut']:.3f} m")

        # Scour levels
        self._rw_SL[0].setText(f"{res['SL_pier']:.3f} m")
        self._rw_SL[1].setText(f"{res['SL_abut']:.3f} m")

        # Foundation levels
        self._rw_FL[0].setText(f"{res['FL_pier']:.3f} m")
        self._rw_FL[1].setText(f"{res['FL_abut']:.3f} m")

    # ── Download PDF ──────────────────────────────────────────────────────────

    def _download_pdf(self):
        if not self._result:
            return
        bridge = self._result.get("bridge_no", "bridge") or "bridge"
        default_name = f"Scour_Depth_BRG_{bridge}.pdf"

        import pathlib
        desktop = str(pathlib.Path.home() / "Desktop")
        default_path = os.path.join(desktop, default_name)

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Scour Depth PDF",
            default_path,
            "PDF Files (*.pdf);;All Files (*)"
        )
        if not path:
            return

        try:
            generate_scour_pdf(self._result, path)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                self._status.setText(
                    f"✔  Scour PDF saved: {os.path.basename(path)}")
                self._status.setStyleSheet(
                    f"color:{COLORS['accent']}; font-size:11px;")
                import subprocess
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
        except ImportError:
            QMessageBox.critical(
                self, "Missing Library",
                f"reportlab not installed in this environment.\n"
                f"Run:  {sys.executable} -m pip install reportlab"
            )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self, "PDF Error",
                f"Could not generate PDF:\n{e}\n\n{traceback.format_exc()[-400:]}"
            )
