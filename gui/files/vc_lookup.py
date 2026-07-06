"""
Vertical Clearance Lookup — IRS Bridge Rules / Substructure Code
GAD Review System — Indian Railways Bridge Drawing Review
-----------------------------------------------------------------
Single source of truth for the discharge -> VC required (mm) table.
Used by:
  - gui/gad_panel.py        (Scrutiny tab manual calculator)
  - core/param_extractor.py (auto cross-check during GAD parameter extraction)
  - core/rule_engine.py     (MB_H6 / MJ_H3 rule checks)

Table:
    Discharge (cumecs)     Vertical Clearance (mm)
    0 - 30                 600   (flat)
    31 - 300                600 - 1200  (pro-rata, linear)
    301 - 3000              1500  (flat)
    Above 3000               1800  (flat)
"""

from __future__ import annotations


def compute_vc_required_mm(discharge_cumecs: float) -> tuple[int, str]:
    """
    Returns (vc_required_mm, explanation_string) for a given discharge.

    Pro-rata band (31-300 cumecs) is linearly interpolated between
    600mm (at 31 cumecs) and 1200mm (at 300 cumecs), per the standard
    IRS Bridge Rules / Substructure Code VC table. Result for the
    pro-rata band is rounded to the nearest 10mm.
    """
    d = discharge_cumecs

    if d is None:
        return None, "Discharge not available — cannot compute VC."

    if d < 0:
        return None, "Discharge cannot be negative."

    if d <= 30:
        return 600, f"Discharge {d:g} cumecs is in 0–30 band → flat VC = 600 mm."

    if d <= 300:
        lo_d, hi_d   = 31, 300
        lo_vc, hi_vc = 600, 1200
        frac = (d - lo_d) / (hi_d - lo_d)
        vc   = lo_vc + frac * (hi_vc - lo_vc)
        vc_rounded = int(round(vc / 10.0) * 10)
        return vc_rounded, (
            f"Discharge {d:g} cumecs is in 31–300 band (pro-rata).\n"
            f"VC = 600 + [({d:g} − 31) / (300 − 31)] × (1200 − 600)\n"
            f"VC = 600 + {frac:.4f} × 600 = {vc:.1f} mm  →  rounded to {vc_rounded} mm"
        )

    if d <= 3000:
        return 1500, f"Discharge {d:g} cumecs is in 301–3000 band → flat VC = 1500 mm."

    return 1800, f"Discharge {d:g} cumecs is above 3000 cumecs → flat VC = 1800 mm."
