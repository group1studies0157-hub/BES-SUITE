"""
BES Bore-Log to DXF - desktop app.

Workflow:
  1. Open an .xls / .xlsx / .pdf bore-log report.
  2. The app parses it (Excel: sheet-based table parser; PDF: table /
     free-text / OCR fallback chain) and lists every borehole found.
  3. Review & fix anything in the editable tables - this matters most
     for OCR'd scans, which can misread digits.
  4. Generate DXF.

Run with:  python -m borelog_dxf.gui
"""
from __future__ import annotations
import sys
import os
import traceback

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QSplitter, QTextEdit,
    QLineEdit, QFormLayout, QGroupBox, QProgressBar, QAbstractItemView,
    QComboBox,
)

from .model import BoreholeRecord, SoilLayer, TestRecord
from .dxf_builder import BoreLogDxfBuilder


# --------------------------------------------------------------------- worker
class ParseWorker(QThread):
    finished_ok = pyqtSignal(list, list)   # boreholes, warnings
    failed = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            ext = os.path.splitext(self.path)[1].lower()
            if ext in ('.xls', '.xlsx'):
                from .parser_xls import parse_workbook
                boreholes, warnings = parse_workbook(self.path)
            elif ext == '.pdf':
                from .parser_pdf import parse_pdf
                boreholes, warnings = parse_pdf(self.path)
            else:
                self.failed.emit(f"Unsupported file type: {ext}")
                return
            self.finished_ok.emit(boreholes, warnings)
        except Exception:
            self.failed.emit(traceback.format_exc())


# ---------------------------------------------------------------------- GUI
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BES Bore-Log \u2192 DXF")
        self.resize(1280, 800)

        self.boreholes: list[BoreholeRecord] = []
        self.warnings: list[str] = []
        self.current_path: str | None = None

        self._build_ui()

    # -- UI construction -----------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # top bar
        top = QHBoxLayout()
        self.open_btn = QPushButton("Open Excel / PDF Bore-Log Report...")
        self.open_btn.clicked.connect(self.on_open)
        self.path_label = QLabel("No file loaded")
        self.path_label.setStyleSheet("color: #888;")
        top.addWidget(self.open_btn)
        top.addWidget(self.path_label, 1)
        outer.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # left: borehole list
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.addWidget(QLabel("Boreholes found:"))
        self.bh_list = QListWidget()
        self.bh_list.currentRowChanged.connect(self.on_select_borehole)
        left_l.addWidget(self.bh_list, 1)
        splitter.addWidget(left)

        # right: editable detail view + warnings
        right = QWidget()
        right_l = QVBoxLayout(right)

        meta_box = QGroupBox("Borehole info")
        meta_form = QFormLayout(meta_box)
        self.loc_edit = QLineEdit()
        self.loc_edit.editingFinished.connect(self.on_meta_edited)
        self.dates_edit = QLineEdit()
        self.dates_edit.editingFinished.connect(self.on_meta_edited)
        meta_form.addRow("Location / BH ID:", self.loc_edit)
        meta_form.addRow("Dates:", self.dates_edit)
        right_l.addWidget(meta_box)

        right_l.addWidget(QLabel("Soil / rock layers (double-click to edit):"))
        self.layers_table = QTableWidget(0, 3)
        self.layers_table.setHorizontalHeaderLabels(["From (m)", "To (m)", "Description"])
        self.layers_table.itemChanged.connect(self.on_layer_edited)
        right_l.addWidget(self.layers_table, 1)

        layer_btns = QHBoxLayout()
        add_layer_btn = QPushButton("+ Add layer")
        add_layer_btn.clicked.connect(self.on_add_layer)
        del_layer_btn = QPushButton("- Remove selected layer")
        del_layer_btn.clicked.connect(self.on_remove_layer)
        layer_btns.addWidget(add_layer_btn)
        layer_btns.addWidget(del_layer_btn)
        right_l.addLayout(layer_btns)

        right_l.addWidget(QLabel("SPT / RQD test rows:"))
        self.tests_table = QTableWidget(0, 4)
        self.tests_table.setHorizontalHeaderLabels(["Depth (m)", "Note", "Density/Consistency", "Sample type"])
        self.tests_table.itemChanged.connect(self.on_test_edited)
        right_l.addWidget(self.tests_table, 1)

        test_btns = QHBoxLayout()
        add_test_btn = QPushButton("+ Add test row")
        add_test_btn.clicked.connect(self.on_add_test)
        del_test_btn = QPushButton("- Remove selected test row")
        del_test_btn.clicked.connect(self.on_remove_test)
        test_btns.addWidget(add_test_btn)
        test_btns.addWidget(del_test_btn)
        right_l.addLayout(test_btns)

        right_l.addWidget(QLabel("Parser warnings (review before generating DXF):"))
        self.warnings_box = QTextEdit()
        self.warnings_box.setReadOnly(True)
        self.warnings_box.setMaximumHeight(120)
        right_l.addWidget(self.warnings_box)

        splitter.addWidget(right)
        splitter.setSizes([280, 1000])

        # bottom bar
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Output style:"))
        self.style_combo = QComboBox()
        self.style_combo.addItem("Schematic - clean profile + labels (standard GAD sheet look)", "schematic")
        self.style_combo.addItem("Detailed - full depths/SPT/RQD data on sheet (working/QC drawing)", "detailed")
        bottom.addWidget(self.style_combo)
        self.generate_btn = QPushButton("Generate DXF...")
        self.generate_btn.setEnabled(False)
        self.generate_btn.clicked.connect(self.on_generate_dxf)
        bottom.addStretch(1)
        bottom.addWidget(self.generate_btn)
        outer.addLayout(bottom)

        self._loading_row = -1  # guards against itemChanged firing during table repopulation

    # -- open / parse -----------------------------------------------------
    def on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open bore-log report", "",
            "Bore-log reports (*.xls *.xlsx *.pdf);;All files (*)")
        if not path:
            return
        self.current_path = path
        self.path_label.setText(path)
        self.progress.show()
        self.open_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)

        self.worker = ParseWorker(path)
        self.worker.finished_ok.connect(self.on_parsed)
        self.worker.failed.connect(self.on_parse_failed)
        self.worker.start()

    def on_parsed(self, boreholes, warnings):
        self.progress.hide()
        self.open_btn.setEnabled(True)
        self.boreholes = boreholes
        self.warnings = warnings

        self.bh_list.clear()
        for bh in self.boreholes:
            item = QListWidgetItem(f"{bh.location}  ({bh.total_depth:.2f} m)")
            self.bh_list.addItem(item)

        self.warnings_box.setPlainText('\n'.join(warnings) if warnings else "(none)")

        if not boreholes:
            QMessageBox.warning(self, "No boreholes found",
                                 "The parser could not find any usable borehole data in this "
                                 "file. Check the warnings panel for details.")
        else:
            self.bh_list.setCurrentRow(0)
            self.generate_btn.setEnabled(True)

    def on_parse_failed(self, msg):
        self.progress.hide()
        self.open_btn.setEnabled(True)
        QMessageBox.critical(self, "Failed to parse file", msg)

    # -- borehole selection / editing --------------------------------------
    def on_select_borehole(self, row: int):
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

    def on_meta_edited(self):
        bh = self._current_bh()
        if not bh:
            return
        bh.location = self.loc_edit.text().strip() or bh.location
        bh.dates = self.dates_edit.text().strip()
        row = self.bh_list.currentRow()
        self.bh_list.item(row).setText(f"{bh.location}  ({bh.total_depth:.2f} m)")

    def on_layer_edited(self, item):
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
        desc = self.layers_table.item(r, 2).text() if self.layers_table.item(r, 2) else ''
        bh.layers[r] = SoilLayer(frm, to, desc)
        self.bh_list.item(self.bh_list.currentRow()).setText(f"{bh.location}  ({bh.total_depth:.2f} m)")

    def on_test_edited(self, item):
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
        note = self.tests_table.item(r, 1).text() if self.tests_table.item(r, 1) else ''
        density = self.tests_table.item(r, 2).text() if self.tests_table.item(r, 2) else ''
        sample_type = self.tests_table.item(r, 3).text() if self.tests_table.item(r, 3) else ''
        bh.tests[r] = TestRecord(depth, note, density, sample_type)

    def on_add_layer(self):
        bh = self._current_bh()
        if not bh:
            return
        last_to = bh.layers[-1].to_depth if bh.layers else 0.0
        bh.layers.append(SoilLayer(last_to, last_to + 1.0, "New layer"))
        self.on_select_borehole(self.bh_list.currentRow())

    def on_remove_layer(self):
        bh = self._current_bh()
        if not bh:
            return
        r = self.layers_table.currentRow()
        if 0 <= r < len(bh.layers):
            del bh.layers[r]
            self.on_select_borehole(self.bh_list.currentRow())

    def on_add_test(self):
        bh = self._current_bh()
        if not bh:
            return
        bh.tests.append(TestRecord(0.0, ""))
        self.on_select_borehole(self.bh_list.currentRow())

    def on_remove_test(self):
        bh = self._current_bh()
        if not bh:
            return
        r = self.tests_table.currentRow()
        if 0 <= r < len(bh.tests):
            del bh.tests[r]
            self.on_select_borehole(self.bh_list.currentRow())

    # -- DXF generation -----------------------------------------------------
    def on_generate_dxf(self):
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


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
