"""
Shared logic for turning a 2-D grid of cell values (rows of columns)
into a BoreholeRecord, regardless of whether that grid came from an
Excel sheet or a table extracted from a PDF page.

This is the "South Central Railway style" bore-log table layout:

    Project : ...
    Br.No: ...
    Location Name: <ID>
    Started On ... Ended On ...
    <header row with keyword columns - see HEADER_KEYWORDS>
    ... data rows ...
    Bore Hole Terminated at a depth of X m ...
    Fig. n.nn Soil Profile at <ID> Location
"""
from __future__ import annotations
import re

from .model import BoreholeRecord, SoilLayer, TestRecord

HEADER_KEYWORDS = {
    'layer_boundary':  ['r.l of layer', 'rl of layer', 'layer boundary'],
    'gwt':             ['g.w.t', 'gwt'],
    'description':     ['engineering description'],
    'test_depth':      ['depth of spt', 'depth of test'],
    'blow_0_15':       ['0-15'],
    'blow_15_30':      ['15-30'],
    'blow_30_45':      ['30-45'],
    'n_value':         ['n-value', 'n value'],
    'density':         ['relative density', 'consistency'],
    'sample_type':     ['type of sample'],
}

# fallback column indices, taken from the reference workbook (533.xls)
FALLBACK_COLS = dict(layer_boundary=0, gwt=1, description=5, test_depth=6,
                      blow_0_15=7, blow_15_30=8, blow_30_45=9, n_value=10,
                      density=110, sample_type=112)


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        v = v.strip().replace(',', '')
        try:
            return float(v)
        except ValueError:
            return None
    return None


def find_header_columns(rows: list[list], fallback: dict | None = None) -> tuple[dict, int]:
    """Scan the first ~10 rows for header keywords and return
    ({field: column_index}, header_row_index). Falls back to
    `fallback` (or FALLBACK_COLS) for any field not found - so a
    slightly different layout degrades gracefully instead of
    crashing. header_row_index is the last row where a keyword was
    matched (i.e. the bottom of the header block), or -1 if nothing
    was found (grid doesn't look like our known layout at all)."""
    found = {}
    header_row_index = -1
    for r, row in enumerate(rows[:10]):
        for c, v in enumerate(row):
            if not isinstance(v, str) or not v.strip():
                continue
            low = v.lower()
            for field, keywords in HEADER_KEYWORDS.items():
                if any(k in low for k in keywords):
                    if field not in found:
                        found[field] = c
                    header_row_index = max(header_row_index, r)
    cols = dict(fallback or FALLBACK_COLS)
    cols.update(found)
    return cols, header_row_index


def parse_grid(name: str, rows: list[list], warnings: list[str],
                cols: dict | None = None) -> BoreholeRecord | None:
    """Core parser: turn a rectangular grid of cell values into a
    BoreholeRecord. `cols` may be pre-supplied (e.g. detected once for
    a whole PDF report); otherwise it is auto-detected per table."""
    if not rows:
        return None

    def cell(r, c):
        if r < len(rows) and c < len(rows[r]):
            v = rows[r][c]
            return v if v is not None else ''
        return ''

    project = str(cell(0, 0)).strip()
    br_no = str(cell(1, 0)).strip()
    loc_raw = str(cell(2, 0)).strip()
    location = re.sub(r'(?i)location\s*name\s*:?', '', loc_raw).strip()
    if not location or _num(location) is not None:
        location = name  # row 2 col 0 wasn't a real location label - fall back
    dates = str(cell(3, 0)).strip()

    if cols is None:
        cols, header_row_index = find_header_columns(rows)
    else:
        header_row_index = -1

    boundaries = []
    gwt_value = None
    for r, row in enumerate(rows):
        v = _num(cell(r, cols['layer_boundary']))
        if v is not None and v > 0:
            boundaries.append((r, v))
        g = _num(cell(r, cols['gwt']))
        if g is not None and g > 0:
            gwt_value = g

    if not boundaries:
        warnings.append(f"[{location}] Could not find any layer boundary depths "
                         f"(column {cols['layer_boundary']}) - soil layers will be empty")

    desc_rows = {}
    for r, row in enumerate(rows):
        v = cell(r, cols['description'])
        if isinstance(v, str) and v.strip():
            desc_rows[r] = v.strip()

    layers = []
    prev_depth = 0.0
    prev_row = header_row_index if header_row_index >= 0 else 5
    for (r, depth) in boundaries:
        frags = [desc_rows[rr] for rr in sorted(desc_rows) if prev_row < rr <= r]
        layers.append(SoilLayer(prev_depth, depth, ' '.join(frags)))
        prev_depth, prev_row = depth, r

    tests = []
    for r, row in enumerate(rows):
        depth = _num(cell(r, cols['test_depth']))
        if depth is None:
            continue
        c7, c8, c9 = cell(r, cols['blow_0_15']), cell(r, cols['blow_15_30']), cell(r, cols['blow_30_45'])
        c10 = cell(r, cols['n_value'])
        density = str(cell(r, cols['density']) or '').strip()
        sample_type = str(cell(r, cols['sample_type']) or '').strip()
        parts = []
        for label, val in (('0-15cm', c7), ('15-30cm', c8), ('30-45cm', c9)):
            if val in ('', None):
                continue
            n = _num(val)
            if n is None and isinstance(val, str):
                parts.append(val.strip())
            elif n is not None:
                parts.append(f"{label}:{int(n) if n.is_integer() else n}")
        n10 = _num(c10)
        if n10 is not None:
            parts.append(f"N={int(n10) if n10.is_integer() else n10}")
        elif isinstance(c10, str) and c10.strip():
            parts.append(c10.strip())
        note = ', '.join(parts)
        tests.append(TestRecord(depth, note, density, sample_type))

    termination_note, figure_ref = '', ''
    for row in rows:
        for v in row:
            if isinstance(v, str):
                if 'terminated' in v.lower():
                    termination_note = v.strip()
                elif v.strip().lower().startswith('fig.'):
                    figure_ref = v.strip()

    if not tests:
        warnings.append(f"[{location}] No SPT/RQD test rows found "
                         f"(column {cols['test_depth']})")

    return BoreholeRecord(
        location=location, project=project, br_no=br_no, dates=dates,
        gwt=gwt_value, layers=layers, tests=tests,
        termination_note=termination_note, figure_ref=figure_ref,
        source_sheet=name)
