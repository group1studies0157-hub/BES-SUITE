"""
Draws a "BORE HOLE DETAILS (NOT TO SCALE)" sheet from a list of
BoreholeRecord objects - the same layout style used in South Central
Railway GAD bore-log sheets.

Two output styles are available:

  - "schematic" (default): clean profile-only columns with a small
    tick at each test depth and a single underlined label below each
    column - matches the reference "BORE HOLE DETAILS (NOT TO SCALE)"
    sheets used for the general drawing / GAD, where the point is to
    show the soil/rock character at a glance, not tabulate every SPT
    reading on the sheet itself.
  - "detailed": every depth, SPT/RQD note, density and sample type
    printed alongside the column - useful as a working / QC drawing
    when you need the full data visible, not just the profile shape.

This module has no knowledge of Excel or PDF - it only consumes the
model in model.py, so it can be reused for any input format.
"""
from __future__ import annotations
from typing import Sequence

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .model import BoreholeRecord
from .soil_classify import classify_and_style, HATCH_STYLE

LAYER_DEFS = {
    'BOREHOLE-OUTLINE':          {'color': 7},
    'BOREHOLE-HATCH-OVERBURDEN': {'color': 3},
    'BOREHOLE-HATCH-GRAVEL':     {'color': 3},
    'BOREHOLE-HATCH-SAND':       {'color': 2},
    'BOREHOLE-HATCH-SILT':       {'color': 8},
    'BOREHOLE-HATCH-CLAY':       {'color': 5},
    'BOREHOLE-HATCH-WEATHERED':  {'color': 2},
    'BOREHOLE-HATCH-SOFTROCK':   {'color': 4},
    'BOREHOLE-HATCH-ROCK':       {'color': 4},
    'BOREHOLE-HATCH-HARDROCK':   {'color': 6},
    'BOREHOLE-TEXT':             {'color': 7},
    'BOREHOLE-TICKS':            {'color': 7},
    'BOREHOLE-TERMINATION':      {'color': 1},
    'BOREHOLE-TITLE':            {'color': 1},
    'BOREHOLE-HEADER':           {'color': 7},
    'BOREHOLE-BORDER':           {'color': 7},
    'BOREHOLE-GWT':              {'color': 5},
    'BOREHOLE-LABEL':            {'color': 1},
}

_HATCH_LAYER_BY_CATEGORY = {
    'overburden': 'BOREHOLE-HATCH-OVERBURDEN',
    'gravel': 'BOREHOLE-HATCH-GRAVEL',
    'sand': 'BOREHOLE-HATCH-SAND',
    'silt': 'BOREHOLE-HATCH-SILT',
    'clay': 'BOREHOLE-HATCH-CLAY',
    'weathered_rock': 'BOREHOLE-HATCH-WEATHERED',
    'soft_rock': 'BOREHOLE-HATCH-SOFTROCK',
    'rock': 'BOREHOLE-HATCH-ROCK',
    'hard_rock': 'BOREHOLE-HATCH-HARDROCK',
}

# rough width-per-character-height ratio for the default ezdxf/AutoCAD
# simplex-style font, used only to size the underline below a label
_CHAR_WIDTH_FACTOR = 0.62


class BoreLogDxfBuilder:
    def __init__(self,
                 scale_units_per_metre: float = 15.0,
                 column_width: float = 36.0,
                 group_spacing: float = 90.0,
                 x_start: float = 40.0,
                 title: str = "BORE HOLE DETAILS",
                 project_line: str = "",
                 style: str = "schematic"):
        """
        style: "schematic" (clean, matches the reference GAD sheet -
               profile + tick marks + one label per hole, no on-sheet
               data dump) or "detailed" (every depth/SPT/RQD value
               printed next to the column, for working/QC drawings).
        """
        if style not in ("schematic", "detailed"):
            raise ValueError("style must be 'schematic' or 'detailed'")
        self.scale = scale_units_per_metre
        self.col_w = column_width
        self.spacing = group_spacing if style == "schematic" else max(group_spacing, 145.0)
        self.x_start = x_start
        self.title = title
        self.project_line = project_line
        self.style = style

    # -- geometry helpers -------------------------------------------------
    def _depth_to_y(self, depth: float) -> float:
        return -depth * self.scale

    def _add_text(self, msp, text, x, y, height, layer,
                   align=TextEntityAlignment.LEFT, rotation=0):
        t = msp.add_text(str(text), dxfattribs={'layer': layer, 'height': height})
        t.dxf.rotation = rotation
        t.set_placement((x, y), align=align)
        return t

    def _add_underlined_label(self, msp, text, xc, y, height, layer):
        """Centred text with a matching underline beneath it, mimicking
        the reference sheet's 'BORE HOLE AT <ID>' captions."""
        self._add_text(msp, text, xc, y, height, layer, align=TextEntityAlignment.MIDDLE_CENTER)
        half_w = len(text) * height * _CHAR_WIDTH_FACTOR / 2
        underline_y = y - height * 0.75
        msp.add_line((xc - half_w, underline_y), (xc + half_w, underline_y),
                      dxfattribs={'layer': layer})

    def _draw_hatched_column(self, msp, bh: BoreholeRecord, x0: float, top_col_y: float,
                              used_categories: set) -> float:
        """Draws the column outline + all soil/rock hatches for one
        borehole. Returns the column's bottom y-coordinate."""
        bottom_col_y = self._depth_to_y(bh.total_depth)
        msp.add_lwpolyline(
            [(x0, top_col_y), (x0 + self.col_w, top_col_y),
             (x0 + self.col_w, bottom_col_y), (x0, bottom_col_y), (x0, top_col_y)],
            dxfattribs={'layer': 'BOREHOLE-OUTLINE'})

        for layer in bh.layers:
            y_top = self._depth_to_y(layer.from_depth) if layer.from_depth > 0 else top_col_y
            y_bot = self._depth_to_y(layer.to_depth)
            cat_key, style = classify_and_style(layer.description)
            category_layer = _HATCH_LAYER_BY_CATEGORY.get(cat_key, 'BOREHOLE-HATCH-OVERBURDEN')
            used_categories.add(style['label'])
            poly_pts = [(x0, y_top), (x0 + self.col_w, y_top),
                        (x0 + self.col_w, y_bot), (x0, y_bot)]
            hatch = msp.add_hatch(dxfattribs={'layer': category_layer})
            hatch.set_pattern_fill(style['pattern'], color=7, scale=style['scale'])
            hatch.paths.add_polyline_path(poly_pts, is_closed=True)
            msp.add_line((x0, y_bot), (x0 + self.col_w, y_bot),
                          dxfattribs={'layer': 'BOREHOLE-OUTLINE'})
        return bottom_col_y

    # -- per-style borehole drawing -----------------------------------------
    def _draw_borehole_schematic(self, msp, bh: BoreholeRecord, x0: float, top_y: float,
                                  used_categories: set):
        xc = x0 + self.col_w / 2
        top_col_y = 0.0

        tri = [(x0 - 5, top_col_y + 6), (x0 + 5, top_col_y + 6),
               (x0, top_col_y + 11), (x0 - 5, top_col_y + 6)]
        msp.add_lwpolyline(tri, dxfattribs={'layer': 'BOREHOLE-OUTLINE'})
        msp.add_line((x0 - 6, top_col_y), (x0 + self.col_w, top_col_y),
                      dxfattribs={'layer': 'BOREHOLE-OUTLINE'})

        bottom_col_y = self._draw_hatched_column(msp, bh, x0, top_col_y, used_categories)

        # tick marks only - no per-tick text, matching the reference sheet
        for t in bh.tests:
            y = self._depth_to_y(t.depth)
            msp.add_line((x0 + self.col_w, y), (x0 + self.col_w + 2.5, y),
                          dxfattribs={'layer': 'BOREHOLE-TICKS'})
            msp.add_line((x0 - 2.5, y), (x0, y), dxfattribs={'layer': 'BOREHOLE-TICKS'})

        label = f"BORE HOLE AT {bh.location}"
        self._add_underlined_label(msp, label, xc, bottom_col_y - 9, 2.6, 'BOREHOLE-LABEL')
        return bottom_col_y - 9

    def _draw_borehole_detailed(self, msp, bh: BoreholeRecord, x0: float, top_y: float,
                                 used_categories: set):
        xc = x0 + self.col_w / 2

        self._add_text(msp, f"BH: {bh.location}", xc, top_y - 2, 4.0,
                        'BOREHOLE-HEADER', align=TextEntityAlignment.MIDDLE_CENTER)
        if bh.dates:
            self._add_text(msp, bh.dates, xc, top_y - 9, 2.0,
                            'BOREHOLE-HEADER', align=TextEntityAlignment.MIDDLE_CENTER)

        top_col_y = 0.0
        tri = [(x0 - 6, top_col_y + 8), (x0 + 6, top_col_y + 8),
               (x0, top_col_y + 14), (x0 - 6, top_col_y + 8)]
        msp.add_lwpolyline(tri, dxfattribs={'layer': 'BOREHOLE-OUTLINE'})
        self._add_text(msp, 'E.G.L', x0 - 9, top_col_y + 9, 2.2, 'BOREHOLE-TEXT',
                        align=TextEntityAlignment.MIDDLE_RIGHT)
        msp.add_line((x0 - 9, top_col_y), (x0 + self.col_w, top_col_y),
                      dxfattribs={'layer': 'BOREHOLE-OUTLINE'})

        bottom_col_y = self._draw_hatched_column(msp, bh, x0, top_col_y, used_categories)

        for layer in bh.layers:
            y_bot = self._depth_to_y(layer.to_depth)
            self._add_text(msp, f"{layer.to_depth:.2f}", x0 - 3, y_bot, 2.2,
                            'BOREHOLE-TEXT', align=TextEntityAlignment.MIDDLE_RIGHT)
            y_top = self._depth_to_y(layer.from_depth) if layer.from_depth > 0 else top_col_y
            mid_y = (y_top + y_bot) / 2
            if (y_top - y_bot) > 8 and layer.description:
                self._add_text(msp, layer.description, xc, mid_y, 1.7,
                                'BOREHOLE-TEXT', align=TextEntityAlignment.MIDDLE_CENTER,
                                rotation=90)

        self._add_text(msp, '0.00', x0 - 3, top_col_y, 2.2, 'BOREHOLE-TEXT',
                        align=TextEntityAlignment.MIDDLE_RIGHT)

        if bh.gwt is not None:
            y_gwt = self._depth_to_y(bh.gwt)
            msp.add_line((x0 - 6, y_gwt), (x0, y_gwt), dxfattribs={'layer': 'BOREHOLE-GWT'})
            self._add_text(msp, f"GWT {bh.gwt:.2f}m", x0 - 8, y_gwt, 1.8,
                            'BOREHOLE-GWT', align=TextEntityAlignment.MIDDLE_RIGHT)

        for t in bh.tests:
            y = self._depth_to_y(t.depth)
            msp.add_line((x0 + self.col_w, y), (x0 + self.col_w + 3, y),
                          dxfattribs={'layer': 'BOREHOLE-TICKS'})
            if t.note:
                label = f"{t.depth:.2f}m: {t.note}"
                if t.sample_type:
                    label += f" [{t.sample_type}]"
                self._add_text(msp, label, x0 + self.col_w + 4, y, 1.6,
                                'BOREHOLE-TEXT', align=TextEntityAlignment.MIDDLE_LEFT)
                if t.density:
                    self._add_text(msp, f"({t.density})", x0 + self.col_w + 4, y - 2.2,
                                    1.5, 'BOREHOLE-TEXT', align=TextEntityAlignment.MIDDLE_LEFT)

        bar_y = bottom_col_y - 4
        for dy in (-0.4, 0, 0.4):
            msp.add_line((x0, bar_y + dy), (x0 + self.col_w, bar_y + dy),
                          dxfattribs={'layer': 'BOREHOLE-TERMINATION', 'color': 1})
        self._add_text(msp, f"Total Depth: {bh.total_depth:.2f} m", xc, bar_y - 6, 2.0,
                        'BOREHOLE-TERMINATION', align=TextEntityAlignment.MIDDLE_CENTER)
        bottom_label_y = bar_y - 6
        if bh.figure_ref:
            self._add_text(msp, bh.figure_ref, xc, bar_y - 11, 1.8,
                            'BOREHOLE-HEADER', align=TextEntityAlignment.MIDDLE_CENTER)
            bottom_label_y = bar_y - 11
        return bottom_label_y

    # -- main entry point ---------------------------------------------------
    def build(self, boreholes: Sequence[BoreholeRecord]) -> "ezdxf.document.Drawing":
        boreholes = [b for b in boreholes if b.layers or b.tests]
        if not boreholes:
            raise ValueError("No boreholes with usable data were supplied")

        doc = ezdxf.new('R2010', setup=True)
        msp = doc.modelspace()
        for name, props in LAYER_DEFS.items():
            if name not in doc.layers:
                doc.layers.add(name=name, color=props['color'])

        n = len(boreholes)
        top_y = 40
        total_width = self.x_start + (n - 1) * self.spacing + self.col_w + \
            (30 if self.style == "schematic" else 60)

        draw_fn = (self._draw_borehole_schematic if self.style == "schematic"
                   else self._draw_borehole_detailed)

        used_categories = set()
        lowest_label_y = 0.0
        for i, bh in enumerate(boreholes):
            x0 = self.x_start + i * self.spacing
            label_y = draw_fn(msp, bh, x0, top_y, used_categories)
            lowest_label_y = min(lowest_label_y, label_y)

        bottom_y = lowest_label_y - 30

        # border + title block
        border_pts = [(0, top_y + 20), (total_width, top_y + 20),
                      (total_width, bottom_y), (0, bottom_y), (0, top_y + 20)]
        msp.add_lwpolyline(border_pts, dxfattribs={'layer': 'BOREHOLE-BORDER'})
        self._add_text(msp, self.title, total_width / 2, bottom_y + 18, 7.0,
                        'BOREHOLE-TITLE', align=TextEntityAlignment.MIDDLE_CENTER)
        self._add_text(msp, "(NOT TO SCALE)", total_width / 2, bottom_y + 8, 5.0,
                        'BOREHOLE-TITLE', align=TextEntityAlignment.MIDDLE_CENTER)
        if self.project_line:
            self._add_text(msp, self.project_line, total_width / 2, top_y + 10, 3.2,
                            'BOREHOLE-HEADER', align=TextEntityAlignment.MIDDLE_CENTER)

        # legend - only categories actually used, and only for the
        # detailed style (the schematic sheet deliberately stays bare,
        # same as the reference)
        if self.style == "detailed":
            legend_x = self.x_start
            legend_y = bottom_y + 8
            self._add_text(msp, 'LEGEND:', legend_x, legend_y, 3.0, 'BOREHOLE-HEADER')
            lx = legend_x + 22
            seen = set()
            for cat_key, style in HATCH_STYLE.items():
                if style['label'] not in used_categories or style['label'] in seen:
                    continue
                seen.add(style['label'])
                box = [(lx, legend_y - 1), (lx + 8, legend_y - 1),
                       (lx + 8, legend_y + 4), (lx, legend_y + 4)]
                category_layer = _HATCH_LAYER_BY_CATEGORY.get(cat_key, 'BOREHOLE-HATCH-OVERBURDEN')
                hatch = msp.add_hatch(dxfattribs={'layer': category_layer})
                hatch.set_pattern_fill(style['pattern'], color=7, scale=style['scale'])
                hatch.paths.add_polyline_path(box, is_closed=True)
                msp.add_lwpolyline(box + [box[0]], dxfattribs={'layer': 'BOREHOLE-OUTLINE'})
                self._add_text(msp, style['label'], lx + 10, legend_y + 1.5, 2.4,
                                'BOREHOLE-HEADER', align=TextEntityAlignment.MIDDLE_LEFT)
                lx += 55

        return doc

    def save(self, boreholes: Sequence[BoreholeRecord], out_path: str) -> str:
        doc = self.build(boreholes)
        doc.saveas(out_path)
        return out_path
