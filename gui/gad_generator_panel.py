"""
GAD Generator panel.

Turn a plain-language prompt (bridge number, span type, levels, dimensions)
into a draft General Arrangement Drawing, emitted as an AutoCAD-ready
AutoLISP script (load → type BES-GAD) plus a DXF you can open directly.

Parsing path:
  * "Generate with AI"  — Claude/Gemini (via gui.ai_provider) fills the
    structured GadInput schema, then the parametric template draws it.
  * "Generate (offline)" — deterministic regex parsing, no network needed.

Generation itself is always local and deterministic (core.gad_generator).
"""

from __future__ import annotations

import os
import traceback
from dataclasses import asdict

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)

from core.gad_generator import GadInput, generate
from gui.styles import COLORS
from core.gad_standards import SPAN_TYPES

# Phased view builders (one button per view; Elevation is phase 1)
from core.cell_sheet import GRID_COLS, GRID_ROWS, collect_grid
from core.gad_elevation import (
    LEVEL_FIELDS, elevation_from_file, elevation_from_sheet, extract_values_ai,
)

GAD_VIEWS = [
    # (key, button label, enabled/active)
    ("elevation", "Elevation", True),
    ("plan", "Plan", False),
    ("section", "Section", False),
    ("wing_return", "Wing and Return Wall", False),
    ("square_return", "Square Return", False),
]

# 10x4 grid — description cells prefilled (keys are (row, col)); the user
# types each value in the cell to the RIGHT of its label.  Linear Span gets
# its own label pair on row 1 (cols D/E) so no right-scan crosses labels.
_GAD_GRID_PREFILL = {
    (0, 0): "RL:",
    (0, 3): "Linear Span:",
    (1, 0): "FL:",
    (2, 0): "HFL:",
    (3, 0): "BED LEVEL(BL):",
}

_GRID_HINT = (
    "Type values against the prefilled descriptions (levels & span in METRES). "
    "Cells accept Excel-style formulas — e.g. =B1-0.762, =D1*1000, "
    "=SUM(B1:B2), =IF(B2>0, B2, B3). Only the computed value against each "
    "description is used for the drawing."
)

EXAMPLE_PROMPT = (
    "Bridge No 3KK at CH 17178.982 m, proposed to be extended on downstream side as\n"
    "(1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX.\n"
    "Rail Level 178.741, Formation Level 177.979, Bed Level 175.877, HFL 176.877.\n"
    "Two tracks, C/C track distance 9450.\n"
    "Loading 25T-2008. DORNAKAL - BHADRACHALAM ROAD SECTION, SECUNDERABAD DIVISION.\n"
    "Scale 1:100."
)

_HINT = (
    "Describe the bridge the way you would to a colleague, e.g.:\n"
    "  '3KK: (1x4.25+1x4.5+1x4.25)x1.50 m RCC BOX, RL 178.741, FL 177.979, "
    "BL 175.877, HFL 176.877, max scour 174.5, 2 tracks C/C 9450, 25T-2008'\n"
    "Dynamic inputs: RL/FL/BL/HFL/scour levels, any cell or span arrangement, "
    "1-3+ tracks, and span family (RCC box / PSC slab / PSC girder / box girder / "
    "steel girder / FOB). For many bridges at once, use batch_gad.py with a CSV/XLSX."
)


def _load_keys() -> tuple:
    """Mirror gad_panel._load_keys — QSettings first, env vars as fallback."""
    from PyQt6.QtCore import QSettings
    s = QSettings("BES", "BridgeEngineeringSuite")
    ck = s.value("anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    gk = s.value("gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
    return str(ck).strip(), str(gk).strip()


class _GenerateWorker(QThread):
    """Runs parsing + generation off the UI thread (AI calls can take 10-30 s)."""

    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, prompt: str, use_ai: bool, out_dir: str, type_key: str = "",
                 save_files: bool = True, parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.use_ai = use_ai
        self.out_dir = out_dir
        self.type_key = type_key
        self.save_files = save_files

    def run(self):
        try:
            inp = None
            ai = None
            if self.use_ai:
                ck, gk = _load_keys()
                if ck or gk:
                    from gui.ai_provider import AIProvider
                    ai = AIProvider.dual(gemini_key=gk, claude_key=ck)
                else:
                    raise RuntimeError(
                        "No API key set. Add one in Settings → API Keys, or use "
                        "'Generate (offline)'."
                    )
            if ai is not None:
                inp = GadInput.from_ai(self.prompt, ai)
            else:
                inp = GadInput.from_prompt(self.prompt)
            if self.type_key:
                inp.type_key = self.type_key
            if self.save_files:
                res = generate(inp, self.out_dir)
                res["saved"] = True
            else:
                # preview only — build the drawing but write nothing
                from core.gad_generator import build_entities, render_png
                ents = build_entities(inp)
                counts: dict = {}
                for e in ents:
                    counts[e["type"]] = counts.get(e["type"], 0) + 1
                res = {"dxf": "", "lsp": "", "preview_png": render_png(ents, width_px=2400),
                       "entities": counts, "total": len(ents), "input": asdict(inp),
                       "saved": False}
            res["prompt"] = self.prompt
            self.done.emit(res)
        except Exception as exc:  # noqa: BLE001 — surface everything to the UI
            self.failed.emit(f"{exc}\n{traceback.format_exc(limit=4)}")


class _AIExtractWorker(QThread):
    """AI vision extraction of the five values from an uploaded image/PDF."""

    done = pyqtSignal(dict, list)
    failed = pyqtSignal(str)

    def __init__(self, path: str, ai, parent=None):
        super().__init__(parent)
        self.path = path
        self.ai = ai

    def run(self):
        try:
            vals, warns = extract_values_ai(self.path, self.ai)
            self.done.emit(vals, warns)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Extraction failed: {exc}")


class _ElevationWorker(QThread):
    """Phase-1 elevation generation off the UI thread."""

    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, inp, out_dir: str, parent=None):
        super().__init__(parent)
        self.inp = inp
        self.out_dir = out_dir

    def run(self):
        try:
            from core.gad_elevation import generate_elevation
            res = generate_elevation(self.inp, self.out_dir)
            res["saved"] = True
            self.done.emit(res)
        except Exception as exc:  # noqa: BLE001 — surface everything
            self.failed.emit(f"{exc}\n{traceback.format_exc(limit=4)}")


class GadGeneratorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._elev_worker = None
        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        """Two-tab shell: [GAD Generator] [DXF Repair]."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("panelTabs")
        outer.addWidget(self.tabs, 1)

        # ── Tab 1 — original GAD Generator content, unchanged behaviour ────
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(14)
        gen_scroll = QScrollArea()
        gen_scroll.setWidgetResizable(True)
        gen_scroll.setFrameShape(QFrame.Shape.NoFrame)
        gen_scroll.setWidget(body)
        self._build_generator_ui(layout)
        self.tabs.addTab(gen_scroll, "GAD Generator")

        # ── Tab 2 — separate DXF-corruption-repair interface ───────────────
        self.repair_tab = DXFRepairTab()
        self.tabs.addTab(self.repair_tab, "DXF Repair")

    def _build_generator_ui(self, layout: QVBoxLayout):
        t = QLabel("GAD Generator")
        t.setObjectName("panelTitle")
        layout.addWidget(t)
        s = QLabel(
            "Give a prompt with dimensions — get a draft General Arrangement Drawing as "
            "AutoLISP (load in AutoCAD, run BES-GAD) and DXF. The inverse of CAD Process."
        )
        s.setObjectName("panelSubtitle")
        s.setWordWrap(True)
        layout.addWidget(s)

        # prompt card
        pc = QFrame(); pc.setObjectName("accentCard")
        pl = QVBoxLayout(pc); pl.setContentsMargins(18, 16, 18, 16); pl.setSpacing(10)
        ph = QHBoxLayout()
        ph.addWidget(self._bold("Describe the bridge"))
        ph.addStretch()
        example_btn = QPushButton("Load 3KK example")
        example_btn.setObjectName("secondaryBtn")
        example_btn.clicked.connect(lambda: self.prompt_box.setPlainText(EXAMPLE_PROMPT))
        ph.addWidget(example_btn)
        pl.addLayout(ph)
        st_row = QHBoxLayout()
        st_row.addWidget(QLabel("Span type"))
        self.span_combo = QComboBox()
        self.span_combo.addItem("Auto (from prompt)", "")
        for key in sorted(SPAN_TYPES, key=lambda k: SPAN_TYPES[k]["label"]):
            self.span_combo.addItem(SPAN_TYPES[key]["label"], key)
        self.span_combo.setToolTip("Overrides the span type detected from the prompt "
                                   "(RDSO catalogue defaults are applied)")
        st_row.addWidget(self.span_combo, 1)
        st_hint = QLabel("optional — overrides the prompt and applies RDSO defaults")
        st_hint.setObjectName("panelSubtitle")
        st_row.addWidget(st_hint, 1)
        pl.addLayout(st_row)
        self.prompt_box = QPlainTextEdit()
        self.prompt_box.setPlaceholderText(_HINT)
        self.prompt_box.setMinimumHeight(170)
        self.prompt_box.setPlainText(EXAMPLE_PROMPT)
        pl.addWidget(self.prompt_box)
        hint = QLabel(_HINT)
        hint.setObjectName("panelSubtitle")
        hint.setWordWrap(True)
        pl.addWidget(hint)
        layout.addWidget(pc)

        # output card
        oc = QFrame(); oc.setObjectName("card")
        ol = QVBoxLayout(oc); ol.setContentsMargins(18, 16, 18, 16); ol.setSpacing(10)
        ol.addWidget(self._bold("Output folder"))
        orow = QHBoxLayout()
        self.out_dir_edit = QLineEdit(os.path.join(os.path.expanduser("~"), "BES_GAD_Output"))
        browse = QPushButton("Browse…")
        browse.setObjectName("secondaryBtn")
        browse.clicked.connect(self._browse)
        orow.addWidget(self.out_dir_edit, 1)
        orow.addWidget(browse)
        ol.addLayout(orow)
        layout.addWidget(oc)

        # actions
        btns = QHBoxLayout()
        self.ai_btn = QPushButton("Generate with AI")
        self.ai_btn.setObjectName("primaryBtn")
        self.ai_btn.setFixedHeight(44)
        self.ai_btn.clicked.connect(lambda: self._generate(use_ai=True))
        self.off_btn = QPushButton("Generate (offline)")
        self.off_btn.setObjectName("secondaryBtn")
        self.off_btn.setFixedHeight(44)
        self.off_btn.clicked.connect(lambda: self._generate(use_ai=False))
        btns.addWidget(self.ai_btn)
        btns.addWidget(self.off_btn)
        btns.addStretch()
        self.save_check = QCheckBox("Save DXF + LISP files")
        self.save_check.setChecked(True)
        btns.addWidget(self.save_check)
        layout.addLayout(btns)

        # live preview card
        self.preview_card = QFrame(); self.preview_card.setObjectName("card")
        self.preview_card.setVisible(False)
        pvl = QVBoxLayout(self.preview_card)
        pvl.setContentsMargins(18, 14, 18, 14)
        pvl.setSpacing(8)
        ph = QHBoxLayout()
        ph.addWidget(self._bold("Preview"))
        ph.addStretch()
        ph.addWidget(QLabel("Zoom"))
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems(["Fit", "25%", "50%", "75%", "100%", "150%"])
        self.zoom_combo.setCurrentText("Fit")
        self.zoom_combo.currentTextChanged.connect(lambda _t: self._apply_zoom())
        ph.addWidget(self.zoom_combo)
        pvl.addLayout(ph)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setMinimumHeight(340)
        self.preview_lbl = QLabel("No preview yet — generate a GAD first.")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setStyleSheet(
            f"background:{COLORS['input_bg']}; color:{COLORS['text_secondary']};"
            f"border:1px solid {COLORS['card_border']};")
        self.preview_scroll.setWidget(self.preview_lbl)
        pvl.addWidget(self.preview_scroll)
        layout.addWidget(self.preview_card)

        # log card
        self.log_card = QFrame(); self.log_card.setObjectName("card"); self.log_card.setVisible(False)
        ll = QVBoxLayout(self.log_card); ll.setContentsMargins(18, 14, 18, 14); ll.setSpacing(8)
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("tagInfo")
        ll.addWidget(self.status_lbl)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150)
        ll.addWidget(self.log_box)
        layout.addWidget(self.log_card)

        # result card
        self.res_card = QFrame(); self.res_card.setObjectName("card"); self.res_card.setVisible(False)
        rl = QVBoxLayout(self.res_card); rl.setContentsMargins(18, 14, 18, 14); rl.setSpacing(10)
        rl.addWidget(self._bold("Generated files"))
        self.res_grid = QGridLayout()
        self.res_grid.setHorizontalSpacing(16)
        self.res_grid.setVerticalSpacing(6)
        rl.addLayout(self.res_grid)
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.setObjectName("secondaryBtn")
        self.open_btn.clicked.connect(self._open_folder)
        rl.addWidget(self.open_btn)
        layout.addWidget(self.res_card)

        # phased view builders — elevation first, then plan/section/…
        self._build_views_ui(layout)

        layout.addStretch()

    def _bold(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: 700;")
        return lbl

    # ── actions ─────────────────────────────────────────────────────────────
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output folder", self.out_dir_edit.text())
        if d:
            self.out_dir_edit.setText(d)

    def _set_busy(self, busy: bool):
        self.ai_btn.setEnabled(not busy)
        self.off_btn.setEnabled(not busy)
        self.prompt_box.setEnabled(not busy)

    def _generate(self, use_ai: bool):
        prompt = self.prompt_box.toPlainText().strip()
        if not prompt:
            self._show_log("error", "Type a prompt describing the bridge first.")
            return
        out_dir = self.out_dir_edit.text().strip() or os.path.join(os.path.expanduser("~"), "BES_GAD_Output")
        self.res_card.setVisible(False)
        self._set_busy(True)
        mode = "AI-assisted" if use_ai else "offline"
        self._show_log("info", f"Generating GAD ({mode})…")
        key = self.span_combo.currentData() if hasattr(self, "span_combo") else ""
        save_files = self.save_check.isChecked()
        self._worker = _GenerateWorker(prompt, use_ai, out_dir, key, save_files, self)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, res: dict):
        self._set_busy(False)
        saved = bool(res.get("saved", True))
        inp = res.get("input", {})
        rows = [
            ("Bridge", inp.get("bridge_no", "—")),
            ("Type", (inp.get("span_type") or "").replace("_", " ").upper()),
            ("Spans / cells (mm)", ", ".join(str(c) for c in inp.get("cells_mm", []))),
            ("RL / FL / BL / HFL", " / ".join(
                f"{inp.get(k, 0):g} m" for k in ("rail_level_m", "formation_level_m", "bed_level_m", "hfl_m"))),
            ("DXF", res.get("dxf", "") or "—"),
            ("AutoLISP", res.get("lsp", "") or "—"),
            ("Entities", f"{res.get('total', 0)} ({', '.join(f'{k}={v}' for k, v in (res.get('entities') or {}).items())})"),
        ]
        while self.res_grid.count():
            item = self.res_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for r, (k, v) in enumerate(rows):
            kl = QLabel(k); kl.setStyleSheet(f"font-weight: 600; color: {COLORS['text_muted']};")
            vl = QLabel(str(v)); vl.setWordWrap(True)
            self.res_grid.addWidget(kl, r, 0)
            self.res_grid.addWidget(vl, r, 1)
        self.res_card.setVisible(True)
        self.open_btn.setEnabled(saved)

        # show the rendered preview
        data = res.get("preview_png") or b""
        if data:
            pix = QPixmap()
            if pix.loadFromData(data):
                self._preview_pixmap = pix
                self.preview_card.setVisible(True)
                self._apply_zoom()

        if saved:
            self._show_log("success", "Done — inspect the preview, open the DXF in AutoCAD / BricsCAD, "
                                      "or load the LISP and run BES-GAD.")
        else:
            self._show_log("info", "Preview only — nothing saved yet. Tick \"Save DXF + LISP files\" "
                                    "and generate again to write files.")

    def _on_failed(self, msg: str):
        self._set_busy(False)
        self._show_log("error", msg.splitlines()[0] if msg else "Generation failed.")

    def _show_log(self, kind: str, text: str):
        self.log_card.setVisible(True)
        self.status_lbl.setText(text)
        self.status_lbl.setObjectName({
            "info": "tagInfo", "success": "tagSuccess", "error": "tagWarning",
        }.get(kind, "tagInfo"))
        self.status_lbl.style().unpolish(self.status_lbl)
        self.status_lbl.style().polish(self.status_lbl)
        self.log_box.setPlainText(text)

    def _open_folder(self):
        d = self.out_dir_edit.text().strip()
        if os.path.isdir(d):
            if os.name == "nt":
                os.startfile(d)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["open", d])

    def _apply_zoom(self):
        pix = getattr(self, "_preview_pixmap", None)
        if pix is None or pix.isNull():
            return
        mode = self.zoom_combo.currentText()
        try:
            if mode == "Fit":
                w = max(120, self.preview_scroll.viewport().width() - 14)
                target = pix.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
            else:
                f = float(mode.rstrip("%")) / 100.0
                target = pix.scaled(int(pix.width() * f), int(pix.height() * f),
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        except Exception:
            return
        self.preview_lbl.setPixmap(target)
        self.preview_lbl.setFixedSize(target.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "zoom_combo", None) and self.zoom_combo.currentText() == "Fit":
            self._apply_zoom()

    # ═══════════════════════════════════════════════════════════════════
    # Phased view builders — Elevation (phase 1) · Plan · Section ·
    # Wing & Return Wall · Square Return.  One shared input method:
    # a 10x4 excel-like grid (formulas allowed) or a file upload.
    # ═══════════════════════════════════════════════════════════════════

    def _build_views_ui(self, layout: QVBoxLayout):
        """View-builder buttons + shared 10x4 input grid + upload."""
        card = QFrame(); card.setObjectName("accentCard")
        vl = QVBoxLayout(card); vl.setContentsMargins(18, 16, 18, 16)
        vl.setSpacing(10)

        vl.addWidget(self._bold("View Builders — generate view by view"))
        note = QLabel(
            "The GAD is built in parts. All views use the SAME inputs — enter "
            "them once below. Elevation is active; the rest come online as "
            "their phases are completed.")
        note.setObjectName("panelSubtitle"); note.setWordWrap(True)
        vl.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(10)
        self._view_btns: dict = {}
        for key, label, active in GAD_VIEWS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setObjectName("secondaryBtn")
            b.setFixedHeight(36)
            b.setToolTip("Coming in a later phase" if not active else
                         "Phase 1 — draw the elevation from the values below")
            if active:
                b.setChecked(True)
                b.setStyleSheet(
                    f"QPushButton{{background:{COLORS['accent_bg']};"
                    f"color:{COLORS['text_primary']};border:1px solid {COLORS['accent']};}}"
                    f"QPushButton:hover{{border-color:{COLORS['accent_light']};}}")
            else:
                b.setStyleSheet(
                    f"QPushButton{{color:{COLORS['text_muted']};}}")
            b.clicked.connect(lambda _c, k=key: self._on_view_clicked(k))
            self._view_btns[key] = (b, active)
            row.addWidget(b)
        row.addStretch()
        vl.addLayout(row)

        # pending-phase message
        self.view_msg = QLabel("")
        self.view_msg.setObjectName("tagInfo")
        self.view_msg.setWordWrap(True)
        self.view_msg.setVisible(False)
        vl.addWidget(self.view_msg)

        # ── shared input: 10x4 excel-like grid ───────────────────────────
        vl.addWidget(self._bold("Inputs (shared by all views)"))
        gh = QHBoxLayout()
        gh.addWidget(QLabel("Input method"))
        self.input_method = QComboBox()
        self.input_method.addItem("Enter in cells", "grid")
        self.input_method.addItem("Upload file (Excel / PDF / image)", "file")
        self.input_method.currentIndexChanged.connect(
            lambda i: self.upload_btn.setVisible(i == 1))
        gh.addWidget(self.input_method, 1)
        self.upload_btn = QPushButton("Choose file…")
        self.upload_btn.setObjectName("secondaryBtn")
        self.upload_btn.clicked.connect(self._browse_input_file)
        self.upload_btn.setVisible(False)
        gh.addWidget(self.upload_btn)
        vl.addLayout(gh)

        self.input_stack_hint = QLabel(_GRID_HINT)
        self.input_stack_hint.setObjectName("panelSubtitle")
        self.input_stack_hint.setWordWrap(True)
        vl.addWidget(self.input_stack_hint)

        self.grid = QTableWidget(GRID_ROWS, GRID_COLS)
        self.grid.setObjectName("gadGrid")
        self.grid.horizontalHeader().setDefaultSectionSize(120)
        self.grid.verticalHeader().setDefaultSectionSize(30)
        self.grid.setMinimumHeight(150)
        self.grid.setMaximumHeight(190)
        for (r, c), label in _GAD_GRID_PREFILL.items():
            item = QTableWidgetItem(label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.grid.setItem(r, c, item)
        # friendly starting values (the sample from the reference drawing)
        self.grid.setItem(0, 1, QTableWidgetItem("178.741"))   # RL value
        self.grid.setItem(0, 4, QTableWidgetItem("4.25"))      # Linear Span
        self.grid.setItem(1, 1, QTableWidgetItem("177.979"))   # FL
        self.grid.setItem(2, 1, QTableWidgetItem("176.877"))   # HFL
        self.grid.setItem(3, 1, QTableWidgetItem("175.877"))   # BL
        vl.addWidget(self.grid)

        self.extracted_lbl = QLabel("")
        self.extracted_lbl.setObjectName("panelSubtitle")
        self.extracted_lbl.setWordWrap(True)
        vl.addWidget(self.extracted_lbl)

        # ── generate button for the active view ─────────────────────────
        gen_row = QHBoxLayout()
        self.elev_btn = QPushButton("Generate Elevation")
        self.elev_btn.setObjectName("primaryBtn")
        self.elev_btn.setFixedHeight(44)
        self.elev_btn.clicked.connect(self._generate_elevation)
        gen_row.addWidget(self.elev_btn)
        gen_row.addStretch()
        vl.addLayout(gen_row)

        layout.addWidget(card)

    # ── view-button + input handling ───────────────────────────────────
    def _on_view_clicked(self, key: str):
        for k, (btn, active) in self._view_btns.items():
            btn.setChecked(k == key and active)
            if k == key and not active:
                self.view_msg.setVisible(True)
                self.view_msg.setText(
                    "\u201c" + btn.text() + "\u201d generation arrives in a later "
                    "phase — the inputs you enter here are shared, so they "
                    "will be ready when its phase is implemented.")
            elif k == key:
                self.view_msg.setVisible(False)
        self.elev_btn.setVisible(key == "elevation")

    def _browse_input_file(self):
        filt = ("Data files (*.xlsx *.xlsm *.xls *.csv *.pdf *.png *.jpg "
                "*.jpeg *.tif *.tiff)")
        path, _ = QFileDialog.getOpenFileName(self, "Choose input file", "", filt)
        if not path:
            return
        self._show_log("info", f"Reading {os.path.basename(path)}…")
        ext = path.rsplit(".", 1)[-1].lower()
        try:
            if ext in ("png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"):
                self._extract_file_values_ai(path)
                return
            inp, warns = elevation_from_file(path)
            self._apply_extracted(inp, warns, source=os.path.basename(path))
        except Exception as exc:  # noqa: BLE001
            self._show_log("error", f"Could not read the file: {exc}")

    def _extract_file_values_ai(self, path: str):
        ck, gk = _load_keys()
        if not (ck or gk):
            self._show_log(
                "error",
                "Image/PDF-vision extraction needs an API key "
                "(Settings \u2192 API Keys) — or enter values in the grid.")
            return
        from gui.ai_provider import AIProvider
        ai = AIProvider.dual(gemini_key=gk, claude_key=ck)
        self._ai_file_worker = _AIExtractWorker(path, ai, self)
        self._ai_file_worker.done.connect(self._on_ai_extract_done)
        self._ai_file_worker.failed.connect(lambda m: self._show_log("error", m))
        self._ai_file_worker.start()

    def _on_ai_extract_done(self, vals: dict, warns: list):
        from core.gad_elevation import ElevationInput
        inp = ElevationInput(
            rail_level_m=vals.get("RL") or 0.0,
            formation_level_m=vals.get("FL") or 0.0,
            hfl_m=vals.get("HFL") or 0.0,
            bed_level_m=vals.get("BL") or 0.0,
            linear_span_m=vals.get("Linear Span") or 0.0,
        )
        self._apply_extracted(inp, warns, source="AI vision")

    def _apply_extracted(self, inp, warns: list, source: str):
        """Put extracted values into the grid so the user sees/edits them."""
        self._last_extracted = inp
        # values go to the right of their prefilled labels (see _GAD_GRID_PREFILL)
        def put(r, c, v):
            if v:
                self.grid.setItem(r, c, QTableWidgetItem(f"{v:g}"))
        put(0, 1, inp.rail_level_m)
        put(0, 4, inp.linear_span_m)
        put(1, 1, inp.formation_level_m)
        put(2, 1, inp.hfl_m)
        put(3, 1, inp.bed_level_m)
        msg = f"Values from {source} filled into the grid."
        if warns:
            msg += "  " + " ".join(warns)
        self.extracted_lbl.setText(msg)
        self._show_log("success" if not warns else "info",
                       f"Values extracted from {source}.")

    def _grid_sheet(self):
        vals = []
        for r in range(GRID_ROWS):
            row = []
            for c in range(GRID_COLS):
                it = self.grid.item(r, c)
                row.append(it.text() if it else "")
            vals.append(row)
        return collect_grid(vals)

    def _resolve_elevation_input(self):
        """Sheet -> ElevationInput, falling back to the last extraction."""
        sheet = self._grid_sheet()
        inp = elevation_from_sheet(sheet)
        if (inp.rail_level_m == 0 and inp.formation_level_m == 0
                and inp.bed_level_m == 0 and inp.linear_span_m == 0
                and getattr(self, "_last_extracted", None) is not None):
            inp = self._last_extracted
        return inp

    # ── elevation generation ───────────────────────────────────────────
    def _generate_elevation(self):
        inp = self._resolve_elevation_input()
        errs = inp.validate()
        if errs:
            self._show_log("error", "Fix the inputs: " + " ".join(errs))
            return
        out_dir = self.out_dir_edit.text().strip() or \
            os.path.join(os.path.expanduser("~"), "BES_GAD_Output")
        self.res_card.setVisible(False)
        self.elev_btn.setEnabled(False)
        self._show_log("info", "Drawing elevation (BL datum, mm at 1:1)…")
        self._elev_worker = _ElevationWorker(inp, out_dir, self)
        self._elev_worker.done.connect(self._on_elev_done)
        self._elev_worker.failed.connect(self._on_failed)
        self._elev_worker.start()

    def _on_elev_done(self, res: dict):
        self.elev_btn.setEnabled(True)
        inp = res.get("input", {})
        rows = [
            ("View", "Elevation (phase 1)"),
            ("RL / FL / BL / HFL", " / ".join(
                f"{inp.get(k, 0):g} m" for k in
                ("rail_level_m", "formation_level_m", "bed_level_m", "hfl_m"))),
            ("Linear Span", f"{inp.get('linear_span_m', 0):g} m"),
            ("BL line length", f"{5 * inp.get('linear_span_m', 0) * 1000:g} mm"),
            ("DXF", res.get("dxf", "\u2014")),
            ("AutoLISP", str(res.get("lsp", "\u2014")) + "  (command: BES-GAD-ELEV)"),
            ("Entities", f"{res.get('total', 0)}"),
        ]
        while self.res_grid.count():
            item = self.res_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for r, (k, v) in enumerate(rows):
            kl = QLabel(k); kl.setStyleSheet(
                f"font-weight: 600; color: {COLORS['text_muted']};")
            vl = QLabel(str(v)); vl.setWordWrap(True)
            self.res_grid.addWidget(kl, r, 0)
            self.res_grid.addWidget(vl, r, 1)
        self.res_card.setVisible(True)
        self.open_btn.setEnabled(True)

        data = res.get("preview_png") or b""
        if data:
            pix = QPixmap()
            if pix.loadFromData(data):
                self._preview_pixmap = pix
                self.preview_card.setVisible(True)
                self._apply_zoom()
        self._show_log("success", "Elevation drawn — open the DXF in AutoCAD "
                                  "or load the LISP and run BES-GAD-ELEV.")


# ═════════════════════════════════════════════════════════════════════════════
# DXF Repair — separate tab (Phase 0–4 pipeline from core.dxf_repair)
# ═════════════════════════════════════════════════════════════════════════════

class _RepairWorker(QThread):
    """Runs the full repair pipeline off the UI thread."""

    progress = pyqtSignal(str)
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, dxf_path: str, scan_path: str, out_dir: str,
                 arrow_style: str = "closed_filled", parent=None):
        super().__init__(parent)
        self.dxf_path = dxf_path
        self.scan_path = scan_path
        self.out_dir = out_dir
        self.arrow_style = arrow_style

    def run(self):
        try:
            ai = None
            try:
                ck, gk = _load_keys()
                if ck or gk:
                    from gui.ai_provider import AIProvider
                    ai = AIProvider.dual(gemini_key=gk, claude_key=ck)
            except Exception:          # noqa: BLE001 — vision check optional
                ai = None

            from core.dxf_repair.run_all import run_repair
            summary = run_repair(
                self.dxf_path, self.scan_path, self.out_dir,
                ai_provider=ai, arrow_style=self.arrow_style,
                progress_cb=lambda m: self.progress.emit(str(m)),
            )
            self.done.emit(summary)
        except Exception as exc:       # noqa: BLE001 — surface everything
            self.failed.emit(f"{exc}\n{traceback.format_exc(limit=4)}")


class DXFRepairTab(QWidget):
    """
    AutoCAD DXF corruption repair for railway-bridge GAD extractions.

    Source scan + corrupted extraction DXF → repaired DXF with true
    associative dimensions, clean shapes, archived hatches, and a full
    change log / needs-review evidence pack.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(14)
        scroll.setWidget(body)

        t = QLabel("AutoCAD DXF Repair")
        t.setObjectName("panelTitle")
        layout.addWidget(t)
        s = QLabel(
            "Repairs a corrupted image→DXF extraction of a scanned bridge GAD "
            "against its source scan: broken dimension text → real associative "
            "DIMENSION entities (values stay geometry-derived), rectangles / "
            "circles rebuilt cleanly on their original layers, hatch bloat "
            "archived out of every processing loop. Ambiguous values go to a "
            "NEEDS_REVIEW list — never guessed.")
        s.setObjectName("panelSubtitle")
        s.setWordWrap(True)
        layout.addWidget(s)

        # ── inputs card ────────────────────────────────────────────────
        ic = QFrame(); ic.setObjectName("accentCard")
        il = QVBoxLayout(ic); il.setContentsMargins(18, 16, 18, 16); il.setSpacing(10)
        il.addWidget(self._bold("Inputs"))
        self.scan_edit = QLineEdit()
        il.addLayout(self._file_row(
            "Source scan", self.scan_edit,
            "Drawing scans (*.tif *.tiff *.png *.jpg *.jpeg *.pdf)",
            self._browse_scan))
        scan_hint = QLabel("full-resolution original_scan.tif — ground truth for every value")
        scan_hint.setObjectName("panelSubtitle"); scan_hint.setWordWrap(True)
        il.addWidget(scan_hint)
        self.dxf_edit = QLineEdit()
        il.addLayout(self._file_row(
            "Corrupted DXF", self.dxf_edit,
            "AutoCAD DXF (*.dxf)", self._browse_dxf))
        dxf_hint = QLabel("extracted.dxf from vision extraction — never modified; "
                          "all output goes to the folder below")
        dxf_hint.setObjectName("panelSubtitle"); dxf_hint.setWordWrap(True)
        il.addWidget(dxf_hint)
        layout.addWidget(ic)

        # ── output card ────────────────────────────────────────────────
        oc = QFrame(); oc.setObjectName("card")
        ol = QVBoxLayout(oc); ol.setContentsMargins(18, 16, 18, 16); ol.setSpacing(10)
        ol.addWidget(self._bold("Output folder"))
        orow = QHBoxLayout()
        default_out = os.path.join(os.path.expanduser("~"), "BES_DXF_Repair")
        self.out_edit = QLineEdit(default_out)
        obrowse = QPushButton("Browse…")
        obrowse.setObjectName("secondaryBtn")
        obrowse.clicked.connect(self._browse_out)
        orow.addWidget(self.out_edit, 1)
        orow.addWidget(obrowse)
        ol.addLayout(orow)
        layout.addWidget(oc)

        # ── settings card ─────────────────────────────────────────────
        sc = QFrame(); sc.setObjectName("card")
        sl = QVBoxLayout(sc); sl.setContentsMargins(18, 16, 18, 16); sl.setSpacing(10)
        sl.addWidget(self._bold("Dimension Settings"))
        arrow_row = QHBoxLayout()
        arrow_row.addWidget(QLabel("Arrow style"))
        self.arrow_combo = QComboBox()
        self.arrow_combo.addItem("Oblique (default)", "oblique")
        self.arrow_combo.addItem("Closed filled", "closed_filled")
        self.arrow_combo.addItem("Closed outline", "closed")
        self.arrow_combo.addItem("Architectural tick", "architectural")
        self.arrow_combo.addItem("Dot", "dot")
        self.arrow_combo.addItem("No arrows", "none")
        self.arrow_combo.setToolTip(
            "Arrowhead style for rebuilt dimension lines.\n"
            "\"No arrows\" is useful for clean engineering prints.")
        arrow_row.addWidget(self.arrow_combo, 1)
        sl.addLayout(arrow_row)
        layout.addWidget(sc)

        # ── actions ────────────────────────────────────────────────────
        btns = QHBoxLayout()
        self.run_btn = QPushButton("Run Repair")
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.setFixedHeight(44)
        self.run_btn.clicked.connect(self._run_repair)
        btns.addWidget(self.run_btn)
        btns.addStretch()
        layout.addLayout(btns)

        # ── progress / log card ────────────────────────────────────────
        self.log_card = QFrame(); self.log_card.setObjectName("card")
        self.log_card.setVisible(False)
        ll = QVBoxLayout(self.log_card); ll.setContentsMargins(18, 14, 18, 14); ll.setSpacing(8)
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("tagInfo")
        ll.addWidget(self.status_lbl)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(220)
        ll.addWidget(self.log_box)
        layout.addWidget(self.log_card)

        # ── results card ───────────────────────────────────────────────
        self.res_card = QFrame(); self.res_card.setObjectName("card")
        self.res_card.setVisible(False)
        rl = QVBoxLayout(self.res_card); rl.setContentsMargins(18, 14, 18, 14); rl.setSpacing(10)
        rl.addWidget(self._bold("Repair report"))
        self.res_grid = QGridLayout()
        self.res_grid.setHorizontalSpacing(16)
        self.res_grid.setVerticalSpacing(6)
        rl.addLayout(self.res_grid)
        row = QHBoxLayout()
        row.addStretch()
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.setObjectName("secondaryBtn")
        self.open_btn.clicked.connect(self._open_folder)
        row.addWidget(self.open_btn)
        rl.addLayout(row)
        layout.addWidget(self.res_card)

        layout.addStretch()

    # ── helpers ─────────────────────────────────────────────────────────
    def _bold(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: 700;")
        return lbl

    def _file_row(self, label: str, edit: QLineEdit,
                  file_filter: str, browse_slot) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        edit.setPlaceholderText(f"choose {label.lower()} …")
        row.addWidget(edit, 1)
        btn = QPushButton("Browse…")
        btn.setObjectName("secondaryBtn")
        btn.clicked.connect(browse_slot)
        row.addWidget(btn)
        return row

    def _browse_scan(self):
        filt = "Drawing scans (*.tif *.tiff *.png *.jpg *.jpeg *.pdf)"
        path, _ = QFileDialog.getOpenFileName(self, "Choose source scan",
                                              "", filt)
        if path:
            self.scan_edit.setText(path)

    def _browse_dxf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose corrupted DXF",
                                              "", "AutoCAD DXF (*.dxf)")
        if path:
            self.dxf_edit.setText(path)

    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output folder",
                                             self.out_edit.text())
        if d:
            self.out_edit.setText(d)
    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output folder",
                                             self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    # ── actions ─────────────────────────────────────────────────────────
    def _show_status(self, kind: str, text: str):
        self.log_card.setVisible(True)
        self.status_lbl.setText(text)
        self.status_lbl.setObjectName({
            "info": "tagInfo", "success": "tagSuccess", "error": "tagWarning",
        }.get(kind, "tagInfo"))
        self.status_lbl.style().unpolish(self.status_lbl)
        self.status_lbl.style().polish(self.status_lbl)
        self.log_box.setPlainText(text)

    def _append_log(self, line: str):
        if not self.log_card.isVisible():
            self.log_card.setVisible(True)
        box = self.log_box
        box.setPlainText(box.toPlainText() + ("" if not box.toPlainText() else "\n")
                         + line)
        box.verticalScrollBar().setValue(box.verticalScrollBar().maximum())

    def _set_busy(self, busy: bool):
        self.run_btn.setEnabled(not busy)
        for w in (self.scan_edit, self.dxf_edit, self.out_edit):
            w.setEnabled(not busy)

    def _run_repair(self):
        scan = self.scan_edit.text().strip()
        dxf = self.dxf_edit.text().strip()
        out = self.out_edit.text().strip() or \
            os.path.join(os.path.expanduser("~"), "BES_DXF_Repair")
        if not scan or not os.path.isfile(scan):
            self._show_status("error",
                              "Choose the source scan first "
                              "(original_scan.tif / .png / .pdf).")
            return
        if not dxf or not os.path.isfile(dxf):
            self._show_status("error",
                              "Choose the corrupted extraction DXF first "
                              "(extracted.dxf).")
            return
        self.res_card.setVisible(False)
        self._set_busy(True)
        self._show_status("info", "Repairing DXF (phases 0–4)…")
        arrow_style = self.arrow_combo.currentData() if hasattr(self, "arrow_combo") else "closed_filled"
        self._worker = _RepairWorker(dxf, scan, out, arrow_style, self)
        self._worker.progress.connect(self._on_repair_progress)
        self._worker.done.connect(self._on_repair_done)
        self._worker.failed.connect(self._on_repair_failed)
        self._worker.start()

    def _on_repair_progress(self, msg: str):
        self._append_log(str(msg))

    def _on_repair_done(self, res: dict):
        self._set_busy(False)
        totals = res.get("totals", {})
        counts = res.get("counts_after", {})
        errs = res.get("errors") or []
        rows = [
            ("Repaired DXF", res.get("dxf", "—")),
            ("Dimensions rebuilt",
             f"{totals.get('dims_rebuilt', 0)} associative"),
            ("Level/grade annotations fixed",
             str(totals.get('annotations_fixed', 0))),
            ("Shapes rebuilt",
             f"{totals.get('shapes_fixed', 0)} rects/circles on original layers"),
            ("Hatches archived",
             f"{totals.get('hatches_archived', 0)} → frozen _HATCH_ARCHIVE"),
            ("NEEDS REVIEW", f"{res.get('needs_review', 0)} item(s)"
             + (f" — see {os.path.dirname(res.get('review_index'))}/_review"
                if res.get('review_index') else "")),
            ("Entities before → after",
             f"{totals.get('entities_before', 0)} → {totals.get('entities_after', 0)}"
             + ("" if not counts else
                f"  ({', '.join(f'{k}={v}' for k, v in counts.items())})")),
            ("Calibration", "see calibration.json"),
            ("Change log", res.get("change_log", "—")),
            ("Side-by-side diff", res.get("side_by_side", "") or "—"),
            ("Duration", f"{res.get('seconds', 0):.1f} s"),
        ] + ([("Warnings", "; ".join(errs))] if errs else [])
        while self.res_grid.count():
            item = self.res_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for r, (k, v) in enumerate(rows):
            kl = QLabel(k); kl.setStyleSheet(f"font-weight: 600; color: {COLORS['text_muted']};")
            vl = QLabel(str(v)); vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.res_grid.addWidget(kl, r, 0)
            self.res_grid.addWidget(vl, r, 1)
        self.res_card.setVisible(True)
        status = ("Done — repaired.dxf ready. Review NEEDS_REVIEW flags in "
                  "AutoCAD before sign-off."
                  if res.get("needs_review", 0) else
                  "Done — repaired.dxf ready; no items required human review.")
        self._show_status("success" if not errs else "info", status)

    def _on_repair_failed(self, msg: str):
        self._set_busy(False)
        self._show_status("error",
                          msg.splitlines()[0] if msg else "Repair failed.")

    def _open_folder(self):
        d = self.out_edit.text().strip()
        if os.path.isdir(d):
            if os.name == "nt":
                os.startfile(d)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["open", d])

