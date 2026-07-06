"""
CAD Process Panel — v6 (LISP-First)
Pipeline: Upload → AI/OpenCV Analysis → Generate AutoLISP → Write DXF → Download both
"""

import os, datetime, shutil
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QProgressBar, QFileDialog, QLineEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QColor, QDragEnterEvent, QDropEvent

from gui.styles import COLORS
from core.cad_engine import CADEngine


# ── Worker ────────────────────────────────────────────────────────────────────
class CADWorker(QThread):
    step_update = pyqtSignal(int, str)       # index, status: active|done|error
    progress    = pyqtSignal(int)
    log_msg     = pyqtSignal(str)
    finished    = pyqtSignal(bool, str, str, str)  # ok, msg, dxf_path, lsp_path

    STEPS = [
        "Load & prepare file",
        "AI Vision: analyse shapes, text, dimensions, patterns",
        "Extract all dimensions and annotations",
        "Build and deduplicate layers",
        "Generate AutoLISP drawing script",
        "Write DXF file (direct open in AutoCAD)",
    ]

    def __init__(self, file_path, api_key=""):
        super().__init__()
        self.file_path = file_path
        self.api_key   = api_key

    def run(self):
        engine = CADEngine(api_key=self.api_key)
        dxf_path = lsp_path = ""
        try:
            # Step 0
            self.step_update.emit(0,"active"); self.progress.emit(5)
            engine.load_file(self.file_path)
            self.log_msg.emit(f"Loaded: {os.path.basename(self.file_path)}  ({engine.img_w}×{engine.img_h}px)")
            self.step_update.emit(0,"done")

            # Step 1
            self.step_update.emit(1,"active"); self.progress.emit(15)
            engine.detect_geometry()
            if engine.ai_data:
                mode = "Claude Vision AI"
                self.log_msg.emit(f"Detection: {mode}")
                self.log_msg.emit(f"Drawing type: {engine.ai_data.get('drawing_type','—')}  Scale: {engine.ai_data.get('scale_note','—')}")
            else:
                mode = "OpenCV contour tracing (AI fallback)" if self.api_key else "OpenCV contour tracing"
                self.log_msg.emit(f"Detection: {mode}")
            self.log_msg.emit(
                f"Geometry: {len(engine.lines)} lines  {len(engine.rectangles)} rects  "
                f"{len(engine.circles)} circles  {len(engine.arcs)} arcs  {len(engine.polygons)} polygons"
            )
            self.step_update.emit(1,"done")

            # Step 2
            self.step_update.emit(2,"active"); self.progress.emit(35)
            engine.extract_dimensions()
            self.log_msg.emit(
                f"Extracted: {len(engine.dimensions)} dims  {len(engine.annotations)} annotations  "
                f"{len(engine.elevations)} elevations  {len(engine.hatching)} hatch regions"
            )
            self.step_update.emit(2,"done")

            # Step 3
            self.step_update.emit(3,"active"); self.progress.emit(50)
            engine.build_layers()
            self.log_msg.emit(f"After dedup: {len(engine.lines)} clean lines  {len(engine.polygons)} polygons")
            self.step_update.emit(3,"done")

            # Step 4 — Generate LISP
            self.step_update.emit(4,"active"); self.progress.emit(65)
            lsp_path = engine.generate_lisp()
            lsp_size = os.path.getsize(lsp_path) // 1024
            self.log_msg.emit(f"AutoLISP generated: {os.path.basename(lsp_path)}  ({lsp_size} KB)")
            # Count LISP commands
            with open(lsp_path, "r", encoding="utf-8") as f:
                lisp_lines = f.readlines()
            cmd_count = sum(1 for l in lisp_lines if "(command" in l or "(BES-" in l)
            self.log_msg.emit(f"LISP script: {len(lisp_lines)} lines  {cmd_count} drawing commands")
            self.step_update.emit(4,"done")

            # Step 5 — Write DXF
            self.step_update.emit(5,"active"); self.progress.emit(82)
            dxf_path = engine.write_dxf()
            dxf_size = os.path.getsize(dxf_path) // 1024
            self.log_msg.emit(f"DXF written: {os.path.basename(dxf_path)}  ({dxf_size} KB)")
            self.step_update.emit(5,"done")

            self.progress.emit(100)
            self.finished.emit(True, "Both files generated successfully", dxf_path, lsp_path)

        except Exception as e:
            import traceback
            self.log_msg.emit(f"ERROR: {str(e)}")
            self.log_msg.emit(traceback.format_exc()[:500])
            self.finished.emit(False, str(e), "", "")


# ── Drop Zone ─────────────────────────────────────────────────────────────────
class DropZone(QFrame):
    file_dropped = pyqtSignal(str)
    EXTS = {'.jpg','.jpeg','.png','.tiff','.tif','.bmp','.pdf'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setMinimumHeight(140)
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.setSpacing(6)
        self.icon = QLabel("⬆")
        self.icon.setFont(QFont("Segoe UI",24))
        self.icon.setStyleSheet(f"color:{COLORS['text_muted']};border:none;")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icon)
        self.main_lbl = QLabel("Click to upload or drag & drop")
        self.main_lbl.setFont(QFont("Segoe UI",12,QFont.Weight.Bold))
        self.main_lbl.setStyleSheet(f"color:{COLORS['text_secondary']};border:none;")
        self.main_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.main_lbl)
        self.fmt_lbl = QLabel("JPEG  ·  JPG  ·  PNG  ·  TIFF  ·  BMP  ·  PDF")
        self.fmt_lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;letter-spacing:1px;border:none;")
        self.fmt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.fmt_lbl)

    def set_file(self, path):
        self.icon.setText("✓"); self.icon.setStyleSheet(f"color:{COLORS['accent']};border:none;font-size:24px;")
        self.main_lbl.setText(f"📄  {os.path.basename(path)}")
        self.fmt_lbl.setText(f"Ready — {os.path.splitext(path)[1].upper()}")
        self.setObjectName("dropZoneActive"); self.style().unpolish(self); self.style().polish(self)

    def reset(self):
        self.icon.setText("⬆"); self.icon.setStyleSheet(f"color:{COLORS['text_muted']};border:none;font-size:24px;")
        self.main_lbl.setText("Click to upload or drag & drop")
        self.fmt_lbl.setText("JPEG  ·  JPG  ·  PNG  ·  TIFF  ·  BMP  ·  PDF")
        self.setObjectName("dropZone"); self.style().unpolish(self); self.style().polish(self)

    def mousePressEvent(self, e):
        path,_ = QFileDialog.getOpenFileName(self,"Select Drawing","","Drawing Files (*.jpg *.jpeg *.png *.tiff *.tif *.bmp *.pdf)")
        if path: self.file_dropped.emit(path)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            ext = os.path.splitext(e.mimeData().urls()[0].toLocalFile())[1].lower()
            if ext in self.EXTS:
                e.acceptProposedAction()
                self.setObjectName("dropZoneActive"); self.style().unpolish(self); self.style().polish(self)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self.setObjectName("dropZone"); self.style().unpolish(self); self.style().polish(self)

    def dropEvent(self, e: QDropEvent):
        path = e.mimeData().urls()[0].toLocalFile()
        if os.path.splitext(path)[1].lower() in self.EXTS:
            self.file_dropped.emit(path)
        e.acceptProposedAction()


# ── Pipeline Step ──────────────────────────────────────────────────────────────
class PipelineStep(QWidget):
    def __init__(self, number, desc):
        super().__init__()
        self._num = number
        lay = QHBoxLayout(self); lay.setContentsMargins(0,3,0,3); lay.setSpacing(12)
        self.num_lbl = QLabel(str(number))
        self.num_lbl.setFixedSize(26,26)
        self.num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.num_lbl.setFont(QFont("Segoe UI",9,QFont.Weight.Bold))
        self._apply("idle"); lay.addWidget(self.num_lbl)
        self.desc_lbl = QLabel(desc)
        self.desc_lbl.setStyleSheet(f"color:{COLORS['text_secondary']};font-size:12px;")
        self.desc_lbl.setWordWrap(True); lay.addWidget(self.desc_lbl,1)
        self.status_lbl = QLabel(); self.status_lbl.setVisible(False)
        lay.addWidget(self.status_lbl)

    def _apply(self, mode):
        s = {
            "idle":  f"background:{COLORS['border']};color:{COLORS['text_muted']};border-radius:13px;",
            "active":f"background:{COLORS['accent_glow']};color:{COLORS['accent']};border:1px solid {COLORS['accent']};border-radius:13px;",
            "done":  f"background:{COLORS['success_bg']};color:{COLORS['success']};border-radius:13px;",
            "error": f"background:{COLORS['error_bg']};color:{COLORS['error']};border-radius:13px;",
        }
        self.num_lbl.setStyleSheet(s.get(mode,""))

    def set_active(self):
        self._apply("active"); self.status_lbl.setText("running...")
        self.status_lbl.setObjectName("tagWarning")
        self.status_lbl.style().unpolish(self.status_lbl); self.status_lbl.style().polish(self.status_lbl)
        self.status_lbl.setVisible(True)

    def set_done(self):
        self._apply("done"); self.num_lbl.setText("✓")
        self.status_lbl.setText("done"); self.status_lbl.setObjectName("tagSuccess")
        self.status_lbl.style().unpolish(self.status_lbl); self.status_lbl.style().polish(self.status_lbl)
        self.status_lbl.setVisible(True)

    def set_error(self):
        self._apply("error"); self.num_lbl.setText("✗")
        self.status_lbl.setText("error"); self.status_lbl.setObjectName("tagWarning")
        self.status_lbl.style().unpolish(self.status_lbl); self.status_lbl.style().polish(self.status_lbl)
        self.status_lbl.setVisible(True)

    def reset(self):
        self.num_lbl.setText(str(self._num)); self._apply("idle"); self.status_lbl.setVisible(False)


# ── Download Button ────────────────────────────────────────────────────────────
class DownloadButton(QFrame):
    def __init__(self, title, subtitle, btn_text, color_key, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QHBoxLayout(self); lay.setContentsMargins(16,14,16,14); lay.setSpacing(14)
        icon_lbl = QLabel("⬇")
        icon_lbl.setFont(QFont("Segoe UI",22))
        icon_lbl.setStyleSheet(f"color:{COLORS.get(color_key, COLORS['accent'])};")
        lay.addWidget(icon_lbl)
        txt_col = QVBoxLayout(); txt_col.setSpacing(2)
        t = QLabel(title); t.setFont(QFont("Segoe UI",12,QFont.Weight.Bold))
        txt_col.addWidget(t)
        s = QLabel(subtitle); s.setStyleSheet(f"color:{COLORS['text_secondary']};font-size:12px;")
        s.setWordWrap(True); txt_col.addWidget(s)
        lay.addLayout(txt_col,1)
        self.btn = QPushButton(btn_text)
        self.btn.setObjectName("primaryBtn")
        self.btn.setFixedWidth(140); self.btn.setFixedHeight(38)
        lay.addWidget(self.btn)


# ── Main Panel ────────────────────────────────────────────────────────────────
class CADPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.current_file = None
        self.dxf_path     = None
        self.lsp_path     = None
        self.worker       = None
        self.settings     = QSettings("BES","BridgeEngineeringSuite")
        self._log_lines   = []
        self._build()

    def _build(self):
        scroll = QScrollArea(self); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container); layout.setContentsMargins(32,32,32,32); layout.setSpacing(0)
        scroll.setWidget(container)
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)

        # Header
        t = QLabel("CAD Process"); t.setObjectName("panelTitle"); layout.addWidget(t)
        s = QLabel("Upload any drawing — AI identifies every shape, dimension, text and pattern, "
                   "then generates an AutoLISP script + DXF file for AutoCAD.")
        s.setObjectName("panelSubtitle"); s.setWordWrap(True); layout.addWidget(s)
        layout.addSpacing(22)

        # ── API key status badge (key managed in Settings panel) ─────────
        key = self._get_key()
        self.key_status = QLabel(
            "● Claude Vision active" if key else "● No API key — OpenCV mode only  (add key in ⚙ Settings)"
        )
        self.key_status.setStyleSheet(
            f"color:{COLORS['success'] if key else COLORS['warning']};font-size:11px;"
        )
        layout.addWidget(self.key_status)
        layout.addSpacing(14)

        # ── Upload card ──────────────────────────────────────────────────
        uc = QFrame(); uc.setObjectName("accentCard")
        ul = QVBoxLayout(uc); ul.setContentsMargins(22,18,22,18); ul.setSpacing(10)
        ut = QLabel("Upload Drawing File"); ut.setFont(QFont("Segoe UI",13,QFont.Weight.Bold))
        ul.addWidget(ut)
        self.drop_zone = DropZone(); self.drop_zone.file_dropped.connect(self._on_file)
        ul.addWidget(self.drop_zone)
        ubr = QHBoxLayout(); ubr.setSpacing(10)
        self.proc_btn = QPushButton("▶   Analyse & Generate Files")
        self.proc_btn.setObjectName("primaryBtn"); self.proc_btn.setFixedHeight(44)
        self.proc_btn.setEnabled(False); self.proc_btn.clicked.connect(self._start)
        ubr.addWidget(self.proc_btn)
        self.clr_btn = QPushButton("Clear"); self.clr_btn.setObjectName("secondaryBtn")
        self.clr_btn.setFixedHeight(44); self.clr_btn.setEnabled(False)
        self.clr_btn.clicked.connect(self._clear); ubr.addWidget(self.clr_btn); ubr.addStretch()
        ul.addLayout(ubr); layout.addWidget(uc); layout.addSpacing(14)

        # ── Progress card ────────────────────────────────────────────────
        self.prog_card = QFrame(); self.prog_card.setObjectName("card"); self.prog_card.setVisible(False)
        pg = QVBoxLayout(self.prog_card); pg.setContentsMargins(22,18,22,18); pg.setSpacing(10)
        ph = QHBoxLayout()
        ph.addWidget(QLabel("Processing pipeline").setParent(None) or self._bold("Processing pipeline"))
        ph.addStretch()
        self.pct = QLabel("0%"); self.pct.setStyleSheet(f"color:{COLORS['accent']};font-weight:600;font-size:14px;")
        ph.addWidget(self.pct); pg.addLayout(ph)
        self.prog_bar = QProgressBar(); self.prog_bar.setFixedHeight(7); self.prog_bar.setRange(0,100)
        pg.addWidget(self.prog_bar)
        self.steps = []
        for i,desc in enumerate(CADWorker.STEPS,1):
            step = PipelineStep(i,desc); pg.addWidget(step); self.steps.append(step)
        log_hdr = QLabel("Live log"); log_hdr.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;font-weight:600;margin-top:6px;")
        pg.addWidget(log_hdr)
        self.log_box = QLabel(); self.log_box.setWordWrap(True)
        self.log_box.setAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft)
        self.log_box.setStyleSheet(
            f"background:{COLORS['input_bg']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;padding:8px;font-size:12px;color:{COLORS['text_secondary']};"
            f"font-family:'Consolas','Courier New',monospace;min-height:80px;"
        )
        pg.addWidget(self.log_box)
        layout.addWidget(self.prog_card); layout.addSpacing(14)

        # ── Result / download card ────────────────────────────────────────
        self.res_card = QFrame(); self.res_card.setObjectName("card"); self.res_card.setVisible(False)
        rl = QVBoxLayout(self.res_card); rl.setContentsMargins(22,18,22,18); rl.setSpacing(12)

        rh = QHBoxLayout()
        ri = QLabel("✓"); ri.setFont(QFont("Segoe UI",20)); ri.setStyleSheet(f"color:{COLORS['success']};")
        rh.addWidget(ri)
        self.res_title = QLabel("Files ready"); self.res_title.setFont(QFont("Segoe UI",13,QFont.Weight.Bold))
        rh.addWidget(self.res_title); rh.addStretch(); rl.addLayout(rh)

        self.res_desc = QLabel(); self.res_desc.setWordWrap(True)
        self.res_desc.setStyleSheet(f"color:{COLORS['text_secondary']};font-size:12px;")
        rl.addWidget(self.res_desc)

        rl.addSpacing(4)

        # DXF download row
        self.dxf_dl = DownloadButton(
            "AutoCAD DXF File",
            "Open directly in AutoCAD, BricsCAD, LibreCAD or FreeCAD. Fully editable with all layers.",
            "⬇  Save .DXF", "accent"
        )
        self.dxf_dl.btn.clicked.connect(self._save_dxf)
        rl.addWidget(self.dxf_dl)

        # LISP download row
        self.lsp_dl = DownloadButton(
            "AutoLISP Script  (.lsp)",
            "Load in AutoCAD with (load \"file.lsp\") then run (BES-DRAW) — redraws everything natively in AutoCAD.",
            "⬇  Save .LSP", "success"
        )
        self.lsp_dl.btn.clicked.connect(self._save_lsp)
        rl.addWidget(self.lsp_dl)

        new_btn = QPushButton("Process another file"); new_btn.setObjectName("secondaryBtn")
        new_btn.setFixedHeight(38); new_btn.clicked.connect(self._reset)
        rl.addWidget(new_btn)
        layout.addWidget(self.res_card); layout.addSpacing(14)

        # ── How it works card ─────────────────────────────────────────────
        ic = QFrame(); ic.setObjectName("card")
        il = QVBoxLayout(ic); il.setContentsMargins(22,18,22,18); il.setSpacing(8)
        il.addWidget(self._bold("How the LISP pipeline works"))
        rows = [
            ("Step 1", "Image/PDF loaded and resized for analysis"),
            ("Step 2", "Claude Vision AI identifies shapes, lines, circles, arcs, polygons, text and patterns"),
            ("Step 3", "Dimensions, annotations, elevation markers and hatch regions extracted"),
            ("Step 4", "Geometry deduplicated and assigned to named AutoCAD layers"),
            ("Step 5", "AutoLISP .lsp file generated — every entity becomes a native AutoCAD command"),
            ("Step 6", "DXF file written via ezdxf — open immediately without running any script"),
            ("Usage",  "Load .lsp in AutoCAD → type (BES-DRAW) → drawing appears. Or just open the .DXF directly."),
        ]
        for tag,desc in rows:
            row=QHBoxLayout()
            tl=QLabel(tag); tl.setObjectName("tagInfo"); tl.setFixedWidth(70); row.addWidget(tl)
            dl=QLabel(desc); dl.setStyleSheet(f"color:{COLORS['text_secondary']};font-size:12px;"); dl.setWordWrap(True)
            row.addWidget(dl,1); il.addLayout(row)
        layout.addWidget(ic); layout.addStretch()

    def _bold(self, txt):
        l = QLabel(txt); l.setFont(QFont("Segoe UI",12,QFont.Weight.Bold)); return l

    def _get_key(self):
        """Read Claude API key from the central QSettings (set in ⚙ Settings)."""
        return (self.settings.value("claude_api_key", "") or
                self.settings.value("api_key", "") or
                os.environ.get("ANTHROPIC_API_KEY", ""))

    def _upd_key_status(self, key=""):
        """Refresh the status badge. Called on showEvent so it reflects latest Settings."""
        key = key or self._get_key()
        if key:
            self.key_status.setText("● Claude Vision active")
            self.key_status.setStyleSheet(f"color:{COLORS['success']};font-size:11px;")
        else:
            self.key_status.setText("● No API key — OpenCV mode only  (add key in ⚙ Settings)")
            self.key_status.setStyleSheet(f"color:{COLORS['warning']};font-size:11px;")

    def showEvent(self, event):
        """Refresh key status every time panel becomes visible."""
        super().showEvent(event)
        self._upd_key_status()

    def _on_file(self, path):
        self.current_file=path; self.drop_zone.set_file(path)
        self.proc_btn.setEnabled(True); self.clr_btn.setEnabled(True)

    def _clear(self):
        self.current_file=None; self.drop_zone.reset()
        self.proc_btn.setEnabled(False); self.clr_btn.setEnabled(False)

    def _log(self, msg):
        self._log_lines.append(msg)
        if len(self._log_lines)>14: self._log_lines=self._log_lines[-14:]
        self.log_box.setText("\n".join(self._log_lines))

    def _start(self):
        if not self.current_file: return
        self.proc_btn.setEnabled(False); self.clr_btn.setEnabled(False)
        self.res_card.setVisible(False); self.prog_card.setVisible(True)
        self.prog_bar.setValue(0); self.pct.setText("0%")
        self._log_lines=[]; self.log_box.setText("")
        for s in self.steps: s.reset()
        key=self._get_key()
        self._log(f"Mode: {'Claude Vision AI' if key else 'OpenCV contour tracing'}")
        self.worker=CADWorker(self.current_file, key)
        self.worker.step_update.connect(self._on_step)
        self.worker.progress.connect(lambda p: (self.prog_bar.setValue(p), self.pct.setText(f"{p}%")))
        self.worker.log_msg.connect(self._log)
        self.worker.finished.connect(self._on_done)
        self.worker.start()

    def _on_step(self, idx, status):
        if idx<len(self.steps):
            if status=="active": self.steps[idx].set_active()
            elif status=="done": self.steps[idx].set_done()
            elif status=="error": self.steps[idx].set_error()

    def _on_done(self, ok, msg, dxf_path, lsp_path):
        self.prog_card.setVisible(False)
        if ok:
            self.dxf_path=dxf_path; self.lsp_path=lsp_path
            dxf_kb = os.path.getsize(dxf_path)//1024 if dxf_path and os.path.exists(dxf_path) else 0
            lsp_kb = os.path.getsize(lsp_path)//1024 if lsp_path and os.path.exists(lsp_path) else 0
            self.res_title.setText("Both files generated successfully")
            self.res_desc.setText(
                f"DXF: {os.path.basename(dxf_path)}  ({dxf_kb} KB)  —  open directly in any CAD software\n"
                f"LSP: {os.path.basename(lsp_path)}  ({lsp_kb} KB)  —  native AutoCAD drawing script\n\n"
                f"To use the LISP in AutoCAD:\n"
                f"  1. Open AutoCAD\n"
                f"  2. Type: (load \"{os.path.basename(lsp_path)}\")\n"
                f"  3. The drawing runs automatically (or type (BES-DRAW) manually)"
            )
        else:
            self.res_title.setText("Processing error")
            self.res_desc.setText(f"Error: {msg}\n\nCheck API key or try a cleaner image.")
            self.proc_btn.setEnabled(True); self.clr_btn.setEnabled(True)
        self.res_card.setVisible(True)

    def _save_dxf(self):
        if not self.dxf_path or not os.path.exists(self.dxf_path): return
        default = os.path.splitext(os.path.basename(self.current_file))[0]+".dxf"
        path,_=QFileDialog.getSaveFileName(self,"Save DXF File",default,"AutoCAD DXF (*.dxf)")
        if path: shutil.copy2(self.dxf_path, path); self._log(f"DXF saved: {path}")

    def _save_lsp(self):
        if not self.lsp_path or not os.path.exists(self.lsp_path): return
        default = os.path.splitext(os.path.basename(self.current_file))[0]+"_BES.lsp"
        path,_=QFileDialog.getSaveFileName(self,"Save AutoLISP Script",default,"AutoLISP Script (*.lsp)")
        if path: shutil.copy2(self.lsp_path, path); self._log(f"LSP saved: {path}")

    def _reset(self):
        self.res_card.setVisible(False); self._clear()
        self.dxf_path=None; self.lsp_path=None
