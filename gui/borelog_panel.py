"""
Bore Log → DXF Panel — Bridge Engineering Suite

Converts bore-log reports (Excel / PDF) into AutoCAD DXF "BORE HOLE
DETAILS (NOT TO SCALE)" drawings, integrated as a panel inside the
main BES application.

Wraps bes_borelog/borelog_dxf/ functionality.
"""
from __future__ import annotations

import os
import sys
import traceback

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from gui.styles import COLORS

# ---------------------------------------------------------------------------
# Ensure bes_borelog/borelog_dxf is importable
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BORELOG_DIR = os.path.join(_ROOT, "bes_borelog")
if _BORELOG_DIR not in sys.path:
    sys.path.insert(0, _BORELOG_DIR)

from borelog_dxf.model import BoreholeRecord, SoilLayer, TestRecord  # noqa: E402
from borelog_dxf.dxf_builder import BoreLogDxfBuilder  # noqa: E402


# ---------------------------------------------------------------------------
# Background parser worker
# ---------------------------------------------------------------------------
class _ParseWorker(QThread):
    finished_ok = pyqtSignal(list, list)  # boreholes, warnings
    failed = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            ext = os.path.splitext(self.path)[1].lower()
            if ext in (".xls", ".xlsx"):
                from borelog_dxf.parser_xls import parse_workbook

                boreholes, warnings = parse_workbook(self.path)
            elif ext == ".pdf":
                from borelog_dxf.parser_pdf import parse_pdf

                boreholes, warnings = parse_pdf(self.path)
            else:
                self.failed.emit(f"Unsupported file type: {ext}")
                return
            self.finished_ok.emit(boreholes, warnings)
        except Exception:
            self.failed.emit(traceback.format_exc())


# ---------------------------------------------------------------------------
# Panel widget
# ---------------------------------------------------------------------------
class BoreLogPanel(QWidget):
    """Embeddable panel for bore-log → DXF conversion inside BES."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boreholes: list[BoreholeRecord] = []
        self.warnings: list[str] = []
        self.current_path: str | None = None
        self._loading_row = -1
        self._build_ui()

    # -- UI ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # Top action bar
        top = QHBoxLayout()
        self.open_btn = QPushButton("Open Excel / PDF Bore-Log Report...")
        self.open_btn.setObjectName("primaryBtn")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self._on_open)
        self.path_label = QLabel("No file loaded")
        self.path_label.setStyleSheet(f"color:{COLORS['text_muted']};")
        top.addWidget(self.open_btn)
        top.addWidget(self.path_label, 1)
        outer.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)

        # Main splitter: borehole list | detail editor
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # -- Left: borehole list --
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(4, 4, 4, 4)
        left_l.addWidget(QLabel("Boreholes found:"))
        self.bh_list = QListWidget()
        self.bh_list.currentRowChanged.connect(self._on_select_borehole)
        left_l.addWidget(self.bh_list, 1)
        splitter.addWidget(left)

        # -- Right: editable detail view --
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(4, 4, 4, 4)

        meta_box = QGroupBox("Borehole info")
        meta_form = QFormLayout(meta_box)
        self.loc_edit = QLineEdit()
        self.loc_edit.editingFinished.connect(self._on_meta_edited)
        self.dates_edit = QLineEdit()
        self.dates_edit.editingFinished.connect(self._on_meta_edited)
        meta_form.addRow("Location / BH ID:", self.loc_edit)
        meta_form.addRow("Dates:", self.dates_edit)
        right_l.addWidget(meta_box)

        right_l.addWidget(QLabel("Soil / rock layers (double-click to edit):"))
        self.layers_table = QTableWidget(0, 3)
        self.layers_table.setHorizontalHeaderLabels(["From (m)", "To (m)", "Description"])
        self.layers_table.itemChanged.connect(self._on_layer_edited)
        right_l.addWidget(self.layers_table, 1)

        layer_btns = QHBoxLayout()
        add_layer_btn = QPushButton("+ Add layer")
        add_layer_btn.clicked.connect(self._on_add_layer)
        del_layer_btn = QPushButton("- Remove selected layer")
        del_layer_btn.clicked.connect(self._on_remove_layer)
        layer_btns.addWidget(add_layer_btn)
        layer_btns.addWidget(del_layer_btn)
        right_l.addLayout(layer_btns)

        right_l.addWidget(QLabel("SPT / RQD test rows:"))
        self.tests_table = QTableWidget(0, 4)
        self.tests_table.setHorizontalHeaderLabels(["Depth (m)", "Note", "Density/Consistency", "Sample type"])
        self.tests_table.itemChanged.connect(self._on_test_edited)
        right_l.addWidget(self.tests_table, 1)

        test_btns = QHBoxLayout()
        add_test_btn = QPushButton("+ Add test row")
        add_test_btn.clicked.connect(self._on_add_test)
        del_test_btn = QPushButton("- Remove selected test row")
        del_test_btn.clicked.connect(self._on_remove_test)
        test_btns.addWidget(add_test_btn)
        test_btns.addWidget(del_test_btn)
        right_l.addLayout(test_btns)

        right_l.addWidget(QLabel("Parser warnings (review before generating DXF):"))
        self.warnings_box = QTextEdit()
        self.warnings_box.setReadOnly(True)
        self.warnings_box.setMaximumHeight(120)
        right_l.addWidget(self.warnings_box)

        splitter.addWidget(right)
        splitter.setSizes([260, 900])

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Output style:"))
        self.style_combo = QComboBox()
        self.style_combo.addItem(
            "Schematic — clean profile + labels (standard GAD sheet look)", "schematic"
        )
        self.style_combo.addItem(
            "Detailed — full depths/SPT/RQD data on sheet (working/QC drawing)", "detailed"
        )
        bottom.addWidget(self.style_combo)
        bottom.addStretch(1)
        self.generate_btn = QPushButton("Generate DXF…")
        self.generate_btn.setObjectName("primaryBtn")
        self.generate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.generate_btn.setEnabled(False)
        self.generate_btn.clicked.connect(self._on_generate_dxf)
        bottom.addWidget(self.generate_btn)
        outer.addLayout(bottom)

    # -- Open / parse --------------------------------------------------------
    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open bore-log report",
            "",
            "Bore-log reports (*.xls *.xlsx *.pdf);;All files (*)",
        )
        if not path:
            return
        self.current_path = path
        self.path_label.setText(os.path.basename(path))
        self.progress.show()
        self.open_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)

        self._worker = _ParseWorker(path)
        self._worker.finished_ok.connect(self._on_parsed)
        self._worker.failed.connect(self._on_parse_failed)
        self._worker.start()

    def _on_parsed(self, boreholes, warnings):
        self.progress.hide()
        self.open_btn.setEnabled(True)
        self.boreholes = boreholes
        self.warnings = warnings

        self.bh_list.clear()
        for bh in self.boreholes:
            item = QListWidgetItem(f"{bh.location}  ({bh.total_depth:.2f} m)")
            self.bh_list.addItem(item)

        self.warnings_box.setPlainText("\n".join(warnings) if warnings else "(none)")

        if not boreholes:
            QMessageBox.warning(
                self,
                "No boreholes found",
                "The parser could not find any usable borehole data in this file. "
                "Check the warnings panel for details.",
            )
        else:
            self.bh_list.setCurrentRow(0)
            self.generate_btn.setEnabled(True)

    def _on_parse_failed(self, msg):
        self.progress.hide()
        self.open_btn.setEnabled(True)
        QMessageBox.critical(self, "Failed to parse file", msg)

    # -- Borehole selection / editing ----------------------------------------
    def _on_select_borehole(self, row: int):
        if row < 0 or row >= len(self.boreholes):
            return
        self._loading_row = row
        bh = self.boreholes[row]

        self.loc_edit.setText(bh.location)
        self.dates_edit.setText(bh.dates)

        self.layers_table.blockSignals(True)
        self.layers_table.setRowCount(len(bh.layers))
        for r, layer in enumerate(bh.layers):
            self.layers_table.setItem(r, 0, QTableWidgetItem(f"{layer.from_depth:.2f}"))
            self.layers_table.setItem(r, 1, QTableWidgetItem(f"{layer.to_depth:.2f}"))
            self.layers_table.setItem(r, 2, QTableWidgetItem(layer.description))
        self.layers_table.blockSignals(False)

        self.tests_table.blockSignals(True)
        self.tests_table.setRowCount(len(bh.tests))
        for r, t in enumerate(bh.tests):
            self.tests_table.setItem(r, 0, QTableWidgetItem(f"{t.depth:.2f}"))
            self.tests_table.setItem(r, 1, QTableWidgetItem(t.note))
            self.tests_table.setItem(r, 2, QTableWidgetItem(t.density))
            self.tests_table.setItem(r, 3, QTableWidgetItem(t.sample_type))
        self.tests_table.blockSignals(False)

        self._loading_row = -1

    def _current_bh(self) -> BoreholeRecord | None:
        row = self.bh_list.currentRow()
        if row < 0 or row >= len(self.boreholes):
            return None
        return self.boreholes[row]

    def _on_meta_edited(self):
        bh = self._current_bh()
        if not bh:
            return
        bh.location = self.loc_edit.text().strip() or bh.location
        bh.dates = self.dates_edit.text().strip()
        row = self.bh_list.currentRow()
        self.bh_list.item(row).setText(f"{bh.location}  ({bh.total_depth:.2f} m)")

    def _on_layer_edited(self, item):
        bh = self._current_bh()
        if not bh or self._loading_row != -1:
            return
        r = item.row()
        if r >= len(bh.layers):
            return
        try:
            frm = float(self.layers_table.item(r, 0).text())
            to = float(self.layers_table.item(r, 1).text())
        except (ValueError, AttributeError):
            return
        desc = self.layers_table.item(r, 2).text() if self.layers_table.item(r, 2) else ""
        bh.layers[r] = SoilLayer(frm, to, desc)
        self.bh_list.item(self.bh_list.currentRow()).setText(
            f"{bh.location}  ({bh.total_depth:.2f} m)"
        )

    def _on_test_edited(self, item):
        bh = self._current_bh()
        if not bh or self._loading_row != -1:
            return
        r = item.row()
        if r >= len(bh.tests):
            return
        try:
            depth = float(self.tests_table.item(r, 0).text())
        except (ValueError, AttributeError):
            return
        note = self.tests_table.item(r, 1).text() if self.tests_table.item(r, 1) else ""
        density = self.tests_table.item(r, 2).text() if self.tests_table.item(r, 2) else ""
        sample_type = self.tests_table.item(r, 3).text() if self.tests_table.item(r, 3) else ""
        bh.tests[r] = TestRecord(depth, note, density, sample_type)

    def _on_add_layer(self):
        bh = self._current_bh()
        if not bh:
            return
        last_to = bh.layers[-1].to_depth if bh.layers else 0.0
        bh.layers.append(SoilLayer(last_to, last_to + 1.0, "New layer"))
        self._on_select_borehole(self.bh_list.currentRow())

    def _on_remove_layer(self):
        bh = self._current_bh()
        if not bh:
            return
        r = self.layers_table.currentRow()
        if 0 <= r < len(bh.layers):
            del bh.layers[r]
            self._on_select_borehole(self.bh_list.currentRow())

    def _on_add_test(self):
        bh = self._current_bh()
        if not bh:
            return
        bh.tests.append(TestRecord(0.0, ""))
        self._on_select_borehole(self.bh_list.currentRow())

    def _on_remove_test(self):
        bh = self._current_bh()
        if not bh:
            return
        r = self.tests_table.currentRow()
        if 0 <= r < len(bh.tests):
            del bh.tests[r]
            self._on_select_borehole(self.bh_list.currentRow())

    # -- DXF generation ------------------------------------------------------
    def _on_generate_dxf(self):
        if not self.boreholes:
            return
        default_name = "BoreHole_Details.dxf"
        if self.current_path:
            base = os.path.splitext(os.path.basename(self.current_path))[0]
            default_name = f"{base}_BoreHole_Details.dxf"
        path, _ = QFileDialog.getSaveFileName(self, "Save DXF", default_name, "DXF files (*.dxf)")
        if not path:
            return
        try:
            project_line = self.boreholes[0].project if self.boreholes[0].project else ""
            style = self.style_combo.currentData()
            builder = BoreLogDxfBuilder(project_line=project_line, style=style)
            builder.save(self.boreholes, path)
        except Exception:
            QMessageBox.critical(self, "Failed to generate DXF", traceback.format_exc())
            return
        QMessageBox.information(self, "Done", f"DXF saved to:\n{path}")
