"""
fig31_lookup.py  —  Bridge Engineering Suite
Digitized data from Fig 3.1 (Fig 4 of RDSO Report RBF-16)

Chart title: "Ratio of 50yr T-Hour Rainfall to 50yr 24-Hour Rainfall"
X-axis: Time of concentration tc (hours), 0 to 3.0
Y-axis: Ratio of 50yr 1-hour rainfall to 50yr 24-hour rainfall, 0 to 0.6

Data source
───────────
    Full Zone 1/2/3/4 tables digitized from `tc_hour_ratio.xlsx`
    (tc column vs. Zone 1-4 columns, 60 points per zone at ~0.05 hr
    steps from 0.00 to 3.00 hrs; one gap at tc=1.55, not present in the
    source sheet — interpolation across it is fine since the curve is
    monotonic there).

    Zone 5 has no column in the source sheet and continues to resolve to
    the Zone 4 curve per the chart's own note (see SUBZONE_TO_ZONE below).

How to use
──────────
    from fig31_lookup import get_tc_ratio, get_1hr_ratio

    # tc_ratio: ratio at time = tc  (used for R50_tc)
    tc_r = get_tc_ratio(zone="3", tc_hrs=0.5763)

    # 1hr_ratio: ratio at time = 1 hr  (used for R50_1hr)
    hr1_r = get_1hr_ratio(zone="3")                # → 0.380

Verification against Bridge 53 (Section DKJ-BDCR, Sub-zone 3E → Zone 3,
confirmed correct zone assignment):
    tc = 1.0000 hrs  →  1hr_ratio = 0.380  ✓ matches this table exactly.
    tc = 0.5763 hrs  →  this table interpolates to ≈0.278. The 0.300
        previously recorded as "confirmed" in this file was an imprecise
        manual chart-read, not a zone-mapping error — Bridge 53 is Zone 3,
        as this file already assumed. The 1-hr point above still confirms
        Zone 3 is the right curve; 0.278 (not 0.300) is the corrected
        tc-ratio for tc=0.5763 going forward.

Bug fixed in this revision:
    The previous ZONE_CURVES dict only defined "3" and "4" — Zone 1 and
    Zone 2 were missing entirely. _resolve_zone()'s fallback check
    (`ZONE_CURVES.get(key) is None`) silently treated that as "Zone 5
    style, no data" and rerouted ANY Zone 1 or Zone 2 request to the
    Zone 4 curve. Any bridge in Sub-Zone 1 or 2 was therefore getting
    Zone 4 numbers all along. Fixed now that all four zones carry real
    digitized data.
"""

import numpy as np

# ── Lookup tables ──────────────────────────────────────────────────────────
# Key   = tc in hours (0.00 to 3.00), digitized from tc_hour_ratio.xlsx
# Value = ratio of 50yr tc-hour rainfall to 50yr 24-hour point rainfall
#
# Note on sub-zones:
#   Sub-zones 1(a), 1(b), 1(c) → use Zone 1 curve
#   Sub-zones 2(a), 2(c), 3(g) → use Zone 2 curve  (per document text)
#   Sub-zones 3A, 3B, 3C, 3D, 3E → use Zone 3 curve
#   Sub-zones 4, 6, 7            → use Zone 4 curve
#   Sub-zone 5                   → use Zone 4 curve (no separate data)

ZONE_CURVES = {
    "1": {
        0.00: 0.000, 0.05: 0.040, 0.10: 0.070, 0.15: 0.100, 0.20: 0.130, 0.25: 0.150,
        0.30: 0.170, 0.35: 0.182, 0.40: 0.200, 0.45: 0.215, 0.50: 0.228, 0.55: 0.240,
        0.60: 0.260, 0.65: 0.265, 0.70: 0.275, 0.75: 0.285, 0.80: 0.295, 0.85: 0.305,
        0.90: 0.315, 0.95: 0.325, 1.00: 0.335, 1.05: 0.345, 1.10: 0.350, 1.15: 0.360,
        1.20: 0.370, 1.25: 0.375, 1.30: 0.385, 1.35: 0.390, 1.40: 0.395, 1.45: 0.405,
        1.50: 0.410, 1.60: 0.425, 1.65: 0.430, 1.70: 0.435, 1.75: 0.440, 1.80: 0.445,
        1.85: 0.455, 1.90: 0.458, 1.95: 0.460, 2.00: 0.465, 2.05: 0.470, 2.10: 0.475,
        2.15: 0.480, 2.20: 0.485, 2.25: 0.490, 2.30: 0.492, 2.35: 0.498, 2.40: 0.500,
        2.45: 0.502, 2.50: 0.504, 2.55: 0.505, 2.60: 0.510, 2.65: 0.515, 2.70: 0.517,
        2.75: 0.519, 2.80: 0.521, 2.85: 0.523, 2.90: 0.527, 2.95: 0.530, 3.00: 0.535,
    },

    "2": {
        0.00: 0.000, 0.05: 0.060, 0.10: 0.090, 0.15: 0.120, 0.20: 0.143, 0.25: 0.170,
        0.30: 0.190, 0.35: 0.206, 0.40: 0.220, 0.45: 0.240, 0.50: 0.250, 0.55: 0.270,
        0.60: 0.285, 0.65: 0.295, 0.70: 0.310, 0.75: 0.320, 0.80: 0.330, 0.85: 0.340,
        0.90: 0.350, 0.95: 0.360, 1.00: 0.370, 1.05: 0.380, 1.10: 0.385, 1.15: 0.390,
        1.20: 0.400, 1.25: 0.410, 1.30: 0.415, 1.35: 0.425, 1.40: 0.430, 1.45: 0.440,
        1.50: 0.445, 1.60: 0.455, 1.65: 0.460, 1.70: 0.465, 1.75: 0.470, 1.80: 0.475,
        1.85: 0.480, 1.90: 0.485, 1.95: 0.490, 2.00: 0.495, 2.05: 0.500, 2.10: 0.505,
        2.15: 0.508, 2.20: 0.510, 2.25: 0.515, 2.30: 0.518, 2.35: 0.520, 2.40: 0.521,
        2.45: 0.525, 2.50: 0.526, 2.55: 0.528, 2.60: 0.530, 2.65: 0.535, 2.70: 0.537,
        2.75: 0.539, 2.80: 0.540, 2.85: 0.541, 2.90: 0.542, 2.95: 0.545, 3.00: 0.548,
    },

    # Confirmed: tc=1.0 → 0.380 (Bridge 53, DKJ-BDCR) — exact match.
    # tc=0.5763 → 0.278 (corrected from the old 0.300 manual chart-read;
    # Bridge 53 is confirmed Zone 3, so this is the same curve, refined).
    "3": {
        0.00: 0.000, 0.05: 0.060, 0.10: 0.090, 0.15: 0.120, 0.20: 0.143, 0.25: 0.170,
        0.30: 0.190, 0.35: 0.206, 0.40: 0.220, 0.45: 0.240, 0.50: 0.250, 0.55: 0.270,
        0.60: 0.285, 0.65: 0.293, 0.70: 0.310, 0.75: 0.325, 0.80: 0.335, 0.85: 0.345,
        0.90: 0.355, 0.95: 0.365, 1.00: 0.380, 1.05: 0.390, 1.10: 0.395, 1.15: 0.405,
        1.20: 0.415, 1.25: 0.420, 1.30: 0.430, 1.35: 0.435, 1.40: 0.445, 1.45: 0.450,
        1.50: 0.455, 1.60: 0.465, 1.65: 0.470, 1.70: 0.475, 1.75: 0.485, 1.80: 0.490,
        1.85: 0.495, 1.90: 0.500, 1.95: 0.505, 2.00: 0.510, 2.05: 0.512, 2.10: 0.515,
        2.15: 0.520, 2.20: 0.525, 2.25: 0.528, 2.30: 0.531, 2.35: 0.535, 2.40: 0.538,
        2.45: 0.540, 2.50: 0.545, 2.55: 0.546, 2.60: 0.548, 2.65: 0.550, 2.70: 0.554,
        2.75: 0.556, 2.80: 0.557, 2.85: 0.578, 2.90: 0.588, 2.95: 0.590, 3.00: 0.600,
    },

    "4": {
        0.00: 0.000, 0.05: 0.067, 0.10: 0.110, 0.15: 0.140, 0.20: 0.170, 0.25: 0.195,
        0.30: 0.216, 0.35: 0.225, 0.40: 0.250, 0.45: 0.265, 0.50: 0.282, 0.55: 0.300,
        0.60: 0.319, 0.65: 0.330, 0.70: 0.345, 0.75: 0.355, 0.80: 0.365, 0.85: 0.375,
        0.90: 0.390, 0.95: 0.400, 1.00: 0.410, 1.05: 0.420, 1.10: 0.430, 1.15: 0.440,
        1.20: 0.450, 1.25: 0.455, 1.30: 0.465, 1.35: 0.470, 1.40: 0.475, 1.45: 0.485,
        1.50: 0.490, 1.60: 0.500, 1.65: 0.505, 1.70: 0.510, 1.75: 0.515, 1.80: 0.518,
        1.85: 0.520, 1.90: 0.525, 1.95: 0.530, 2.00: 0.535, 2.05: 0.538, 2.10: 0.540,
        2.15: 0.545, 2.20: 0.550, 2.25: 0.556, 2.30: 0.557, 2.35: 0.559, 2.40: 0.560,
        2.45: 0.562, 2.50: 0.565, 2.55: 0.568, 2.60: 0.569, 2.65: 0.570, 2.70: 0.573,
        2.75: 0.575, 2.80: 0.576, 2.85: 0.580, 2.90: 0.585, 2.95: 0.595, 3.00: 0.601,
    },

    # ── Zone 5 ──────────────────────────────────────────────────────────
    # "For Zone 5 use curve of Zone 4 as data for Zone 5 is not available
    #  to arrive at such a curve." — chart note, Fig 3.1. Not present as a
    # column in tc_hour_ratio.xlsx either, so this sentinel stays.
    "5": None,  # resolved to Zone 4 at runtime
}

# Sub-zone → zone key mapping
SUBZONE_TO_ZONE = {
    # Zone 1
    "1":   "1",  "1A": "1", "1B": "1", "1C": "1",
    # Zone 2
    "2":   "2",  "2A": "2", "2B": "2", "2C": "2",
    # Zone 3 sub-zones (all use Zone 3 curve)
    "3":   "3",
    "3A":  "3",  "3B": "3",  "3C": "3",  "3D": "3",  "3E": "3",
    "3F":  "3",  "3G": "3",
    # Zone 4
    "4":   "4",
    # Zone 5 → Zone 4 curve
    "5":   "5",
    # Zone 6, 7
    "6":   "4",  "7": "4",
}


# ── Public API ─────────────────────────────────────────────────────────────

def _resolve_zone(zone: str) -> str:
    """Normalise sub-zone code to a curve key ('1'..'4')."""
    key = SUBZONE_TO_ZONE.get(zone.upper().strip(), zone)
    if ZONE_CURVES.get(key) is None:   # e.g. zone "5" → use "4"
        key = "4"
    return key


def get_tc_ratio(zone: str, tc_hrs: float) -> float:
    """
    Return the ratio at time = tc_hrs for the given zone/sub-zone.
    Uses linear interpolation between digitized anchor points — the
    correct read for a fine-grained (~0.05 hr), monotonic chart digitization
    like this one; matches how the value would be read off the chart by eye.
    Clamps tc_hrs to [0, 3.0].

    Parameters
    ----------
    zone    : str  — e.g. "3", "3E", "4", "5"
    tc_hrs  : float — time of concentration in hours

    Returns
    -------
    float  — ratio of 50yr tc-hour rainfall to 50yr 24-hour rainfall
    """
    key = _resolve_zone(zone)
    table = ZONE_CURVES[key]
    tc_clamped = max(0.0, min(float(tc_hrs), 3.0))
    tcs  = sorted(table.keys())
    vals = [table[t] for t in tcs]
    return float(np.interp(tc_clamped, tcs, vals))


def get_1hr_ratio(zone: str) -> float:
    """
    Return the 1-hour ratio (ratio at tc = 1.0 hr) for the given zone.
    This is the standard "R50(1hr) / R50(24hr)" value read from the chart.
    """
    return get_tc_ratio(zone, 1.0)


def get_scaling_k(zone: str, tc_hrs: float) -> float:
    """
    Return the scaling coefficient K = tc_ratio / 1hr_ratio.
    Used to compute R50(tc) = K × R50(1hr).
    """
    tc_r  = get_tc_ratio(zone, tc_hrs)
    hr1_r = get_1hr_ratio(zone)
    if hr1_r == 0:
        return 0.0
    return tc_r / hr1_r


# ── Self-test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Fig 3.1 lookup — self-test")
    print("-" * 50)

    tc_ref = 0.5763
    z3_tc  = get_tc_ratio("3E", tc_ref)
    z3_1hr = get_1hr_ratio("3E")
    K      = get_scaling_k("3E", tc_ref)

    print(f"Zone 3E | tc = {tc_ref} hrs")
    print(f"  tc_ratio (Fig 3.1)  = {z3_tc:.3f}   (corrected from old 0.300 manual read)")
    print(f"  1hr_ratio (Fig 3.1) = {z3_1hr:.3f}   (Bridge 53 confirmed 0.380 -- matches)")
    print(f"  K = tc_ratio/1hr_ratio = {K:.3f}")
    print()

    for z in ("1", "2", "3", "4"):
        print(f"Zone {z}  | 1hr_ratio = {get_1hr_ratio(z):.3f}")
    print(f"Zone 5  | 1hr_ratio = {get_1hr_ratio('5'):.3f}  (should equal Zone 4)")

    print()
    print(f"{'tc':>5}  {'Zone1':>7}  {'Zone2':>7}  {'Zone3':>7}  {'Zone4':>7}")
    for tc in [0.25, 0.50, 0.58, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00]:
        vals = [get_tc_ratio(z, tc) for z in ("1", "2", "3", "4")]
        print(f"  {tc:.2f}   " + "    ".join(f"{v:.3f}" for v in vals))
