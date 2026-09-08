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

LAYER_DEFS = {
    'BOREHOLE-OUTLINE':          {'color': 7},
    'BOREHOLE-TEXT':             {'color': 7},
    'BOREHOLE-TICKS':            {'color': 7},
    'BOREHOLE-TERMINATION':      {'color': 1},
    'BOREHOLE-TITLE':            {'color': 1},
    'BOREHOLE-HEADER':           {'color': 7},
    'BOREHOLE-BORDER':           {'color': 7},
    'BOREHOLE-GWT':              {'color': 5},
    'BOREHOLE-LABEL':            {'color': 1},
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

    @staticmethod
    def _wrap_text(text: str, text_height: float, available_width: float) -> list[str]:
        """Wrap *text* into lines that fit within *available_width* DXF units,
        given the font metrics (_CHAR_WIDTH_FACTOR).  Tries to break on
        word boundaries; falls back to hard-breaking a single long word
        when one token is wider than the column."""
        if not text or not text.strip():
            return []
        char_w = text_height * _CHAR_WIDTH_FACTOR
        max_chars = max(1, int(available_width / char_w))
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            # test if appending this word fits on the current line
            candidate = f"{current} {word}".strip() if current else word
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                # if the word itself is too long, hard-break it
                while len(word) > max_chars:
                    lines.append(word[:max_chars])
                    word = word[max_chars:]
                current = word
        if current:
            lines.append(current)
        return lines or [text]

    def _draw_wrapped_text(self, msp, text: str, x_center: float,
                           y_top: float, y_bot: float, text_height: float,
                           layer: str) -> None:
        """Draw *text* horizontally, word-wrapped, centred vertically
        between *y_top* and *y_bot*.  Reduces *text_height* automatically
        when the wrapped block is taller than the cell."""
        if not text or not text.strip():
            return
        available_w = self.col_w - 4  # leave a small margin inside the cell
        cell_h = abs(y_top - y_bot)
        line_spacing = text_height * 1.35

        # try with requested text_height first, shrink if needed
        for attempt_h in (text_height, max(1.0, text_height * 0.85),
                          max(0.8, text_height * 0.7)):
            lines = self._wrap_text(text, attempt_h, available_w)
            block_h = len(lines) * attempt_h * 1.35
            if block_h <= cell_h - 1.0:          # leave ~0.5 margin top+bottom
                break
        else:
            # even at the smallest size it doesn't fully fit – draw what we can
            lines = self._wrap_text(text, attempt_h, available_w)

        total_block_h = len(lines) * attempt_h * 1.35
        # centre vertically in the cell
        y_start = (y_top + y_bot) / 2 + total_block_h / 2 - attempt_h
        for i, line in enumerate(lines):
            y = y_start - i * attempt_h * 1.35
            self._add_text(msp, line, x_center, y, attempt_h, layer,
                           align=TextEntityAlignment.MIDDLE_CENTER)

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
        """Draws the column outline + soil description text for one
        borehole (hatching replaced with text labels). Returns the
        column's bottom y-coordinate."""
        bottom_col_y = self._depth_to_y(bh.total_depth)
        msp.add_lwpolyline(
            [(x0, top_col_y), (x0 + self.col_w, top_col_y),
             (x0 + self.col_w, bottom_col_y), (x0, bottom_col_y), (x0, top_col_y)],
            dxfattribs={'layer': 'BOREHOLE-OUTLINE'})

        xc = x0 + self.col_w / 2
        for layer in bh.layers:
            y_top = self._depth_to_y(layer.from_depth) if layer.from_depth > 0 else top_col_y
            y_bot = self._depth_to_y(layer.to_depth)
            msp.add_line((x0, y_bot), (x0 + self.col_w, y_bot),
                          dxfattribs={'layer': 'BOREHOLE-OUTLINE'})
            layer_thickness = abs(y_top - y_bot)
            if layer.description:
                # choose a text height that fits the cell, then word-wrap
                txt_h = min(2.8, max(1.2, layer_thickness * 0.35))
                self._draw_wrapped_text(msp, layer.description, xc,
                                        y_top, y_bot, txt_h, 'BOREHOLE-TEXT')
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

        # depth numbers on the left side at each layer boundary
        self._add_text(msp, '0.00', x0 - 8, top_col_y, 1.8, 'BOREHOLE-TEXT',
                        align=TextEntityAlignment.MIDDLE_RIGHT)
        for layer in bh.layers:
            y_bot = self._depth_to_y(layer.to_depth)
            self._add_text(msp, f"{layer.to_depth:.2f}", x0 - 8, y_bot, 1.8,
                            'BOREHOLE-TEXT', align=TextEntityAlignment.MIDDLE_RIGHT)

        # tick marks only - no per-tick text, matching the reference sheet
        for t in bh.tests:
            y = self._depth_to_y(t.depth)
            msp.add_line((x0 + self.col_w, y), (x0 + self.col_w + 2.5, y),
                          dxfattribs={'layer': 'BOREHOLE-TICKS'})
            msp.add_line((x0 - 1.5, y), (x0, y), dxfattribs={'layer': 'BOREHOLE-TICKS'})

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
            if layer.description:
                self._draw_wrapped_text(msp, layer.description, xc,
                                        y_top, y_bot, 1.7, 'BOREHOLE-TEXT')

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

        return doc

    def save(self, boreholes: Sequence[BoreholeRecord], out_path: str) -> str:
        doc = self.build(boreholes)
        doc.saveas(out_path)
        return out_path
