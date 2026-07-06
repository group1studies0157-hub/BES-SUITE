"""
CD Processing Panel
Consolidated CD workflow triggered by one button, asking for bridge numbers first
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QDialog, QLineEdit, QListWidget, QListWidgetItem,
    QComboBox, QScrollArea, QProgressBar, QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor
import time
import datetime

from gui.styles import COLORS


# ── Worker thread for CD processing ─────────────────────────────────────────
class CDWorker(QThread):
    progress = pyqtSignal(int, str)   # percent, step description
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, bridges, mode):
        super().__init__()
        self.bridges = bridges
        self.mode = mode

    def run(self):
        steps = [
            (5,  "Initialising CD pipeline..."),
            (15, "Loading bridge data records..."),
            (28, "Parsing construction drawings..."),
            (42, "Generating quantity schedules..."),
            (56, "Compiling specifications..."),
            (70, "Running cross-reference checks..."),
            (82, "Generating output documents..."),
            (92, "Packaging final deliverables..."),
            (100, "CD processing complete"),
        ]
        for pct, desc in steps:
            time.sleep(0.6)
            self.progress.emit(pct, desc)
        self.finished.emit(True, f"{self.mode} completed for {len(self.bridges)} bridge(s)")


# ── Bridge Number Dialog ─────────────────────────────────────────────────────
class BridgeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CD Processing — Setup")
        self.setModal(True)
        self.setFixedSize(480, 520)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self.bridges = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(0)

        title = QLabel("Configure CD Processing")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        sub = QLabel("Enter bridge numbers and choose a processing mode before starting.")
        sub.setObjectName("dialogSub")
        sub.setWordWrap(True)
        layout.addSpacing(4)
        layout.addWidget(sub)

        layout.addSpacing(20)

        # Bridge number entry
        lbl1 = QLabel("BRIDGE NUMBERS")
        lbl1.setObjectName("fieldLabel")
        layout.addWidget(lbl1)
        layout.addSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.bridge_input = QLineEdit()
        self.bridge_input.setPlaceholderText("e.g. BRG-2024-001")
        self.bridge_input.returnPressed.connect(self._add_bridge)
        row.addWidget(self.bridge_input)

        add_btn = QPushButton("+ Add")
        add_btn.setObjectName("secondaryBtn")
        add_btn.setFixedWidth(72)
        add_btn.clicked.connect(self._add_bridge)
        row.addWidget(add_btn)
        layout.addLayout(row)

        layout.addSpacing(8)

        self.bridge_list = QListWidget()
        self.bridge_list.setFixedHeight(140)
        layout.addWidget(self.bridge_list)

        layout.addSpacing(4)

        remove_btn = QPushButton("Remove selected")
        remove_btn.setObjectName("dangerBtn")
        remove_btn.clicked.connect(self._remove_bridge)
        remove_btn.setFixedWidth(130)
        layout.addWidget(remove_btn)

        layout.addSpacing(20)

        # Processing mode
        lbl2 = QLabel("PROCESSING MODE")
        lbl2.setObjectName("fieldLabel")
        layout.addWidget(lbl2)
        layout.addSpacing(6)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Full CD Workflow",
            "Drawings Only",
            "Quantities Only",
            "Specifications Only",
            "Cross-Reference Check Only",
        ])
        layout.addWidget(self.mode_combo)

        layout.addSpacing(24)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.start_btn = QPushButton("▶  Start Processing")
        self.start_btn.setObjectName("primaryBtn")
        self.start_btn.clicked.connect(self._start)
        btn_row.addWidget(self.start_btn)

        layout.addLayout(btn_row)

    def _add_bridge(self):
        val = self.bridge_input.text().strip()
        if not val:
            return
        # Check for duplicates
        existing = [self.bridge_list.item(i).text() for i in range(self.bridge_list.count())]
        if val in existing:
            self.bridge_input.clear()
            return
        item = QListWidgetItem(f"  ⬡  {val}")
        item.setData(Qt.ItemDataRole.UserRole, val)
        self.bridge_list.addItem(item)
        self.bridge_input.clear()

    def _remove_bridge(self):
        for item in self.bridge_list.selectedItems():
            self.bridge_list.takeItem(self.bridge_list.row(item))

    def _start(self):
        if self.bridge_list.count() == 0:
            self.bridge_input.setPlaceholderText("⚠ Add at least one bridge number")
            self.bridge_input.setStyleSheet(f"border-color: {COLORS['error']};")
            return
        self.bridges = [
            self.bridge_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.bridge_list.count())
        ]
        self.accept()

    def get_config(self):
        return self.bridges, self.mode_combo.currentText()


# ── CD Panel ─────────────────────────────────────────────────────────────────
class CDPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self._build()

    def _build(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(0)
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # ── Header ──
        title = QLabel("CD Processing")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        sub = QLabel("Run the complete construction document pipeline for your bridge projects.")
        sub.setObjectName("panelSubtitle")
        layout.addWidget(sub)

        layout.addSpacing(28)

        # ── Main action card ──
        action_card = QFrame()
        action_card.setObjectName("accentCard")
        card_layout = QVBoxLayout(action_card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(12)

        card_title = QLabel("Start CD Processing")
        card_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        card_layout.addWidget(card_title)

        card_desc = QLabel(
            "Clicking the button below will ask for bridge numbers and processing mode, "
            "then run the full consolidated workflow automatically."
        )
        card_desc.setWordWrap(True)
        card_desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        card_layout.addWidget(card_desc)

        card_layout.addSpacing(4)

        self.run_btn = QPushButton("⚙   Run CD Processing")
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.setFixedHeight(44)
        self.run_btn.setFixedWidth(200)
        self.run_btn.clicked.connect(self._launch_dialog)
        card_layout.addWidget(self.run_btn)

        layout.addWidget(action_card)
        layout.addSpacing(16)

        # ── Progress card (hidden initially) ──
        self.progress_card = QFrame()
        self.progress_card.setObjectName("card")
        self.progress_card.setVisible(False)
        prog_layout = QVBoxLayout(self.progress_card)
        prog_layout.setContentsMargins(24, 20, 24, 20)
        prog_layout.setSpacing(10)

        prog_header = QHBoxLayout()
        self.prog_title = QLabel("Processing...")
        self.prog_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        prog_header.addWidget(self.prog_title)
        prog_header.addStretch()
        self.prog_pct = QLabel("0%")
        self.prog_pct.setStyleSheet(f"color: {COLORS['accent']}; font-weight: 600;")
        prog_header.addWidget(self.prog_pct)
        prog_layout.addLayout(prog_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setRange(0, 100)
        prog_layout.addWidget(self.progress_bar)

        self.step_label = QLabel("Initialising...")
        self.step_label.setObjectName("stepLabel")
        prog_layout.addWidget(self.step_label)

        layout.addWidget(self.progress_card)
        layout.addSpacing(16)

        # ── Run history card ──
        history_card = QFrame()
        history_card.setObjectName("card")
        hist_layout = QVBoxLayout(history_card)
        hist_layout.setContentsMargins(24, 20, 24, 20)
        hist_layout.setSpacing(10)

        hist_header = QHBoxLayout()
        hist_title = QLabel("Run History")
        hist_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        hist_header.addWidget(hist_title)
        hist_header.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("dangerBtn")
        clear_btn.clicked.connect(self._clear_history)
        hist_header.addWidget(clear_btn)
        hist_layout.addLayout(hist_header)

        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(160)
        self.history_list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 4px; }}"
        )
        hist_layout.addWidget(self.history_list)

        layout.addWidget(history_card)
        layout.addSpacing(16)

        # ── Info card ──
        info_card = QFrame()
        info_card.setObjectName("card")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(24, 20, 24, 20)
        info_layout.setSpacing(8)

        info_title = QLabel("Pipeline steps")
        info_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        info_layout.addWidget(info_title)

        steps = [
            ("①", "Bridge data records loaded"),
            ("②", "Construction drawings parsed"),
            ("③", "Quantity schedules generated"),
            ("④", "Specifications compiled"),
            ("⑤", "Cross-references verified"),
            ("⑥", "Output documents packaged"),
        ]
        for num, text in steps:
            row = QHBoxLayout()
            num_lbl = QLabel(num)
            num_lbl.setStyleSheet(f"color: {COLORS['accent']}; font-weight: 600; min-width: 22px;")
            row.addWidget(num_lbl)
            txt_lbl = QLabel(text)
            txt_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
            row.addWidget(txt_lbl)
            row.addStretch()
            info_layout.addLayout(row)

        layout.addWidget(info_card)
        layout.addStretch()

    def _launch_dialog(self):
        dlg = BridgeDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            bridges, mode = dlg.get_config()
            self._start_processing(bridges, mode)

    def _start_processing(self, bridges, mode):
        self.run_btn.setEnabled(False)
        self.progress_card.setVisible(True)
        self.prog_title.setText(f"Running: {mode}")
        self.progress_bar.setValue(0)

        self.worker = CDWorker(bridges, mode)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(lambda ok, msg: self._on_finished(ok, msg, bridges, mode))
        self.worker.start()

    def _on_progress(self, pct, desc):
        self.progress_bar.setValue(pct)
        self.prog_pct.setText(f"{pct}%")
        self.step_label.setText(desc)

    def _on_finished(self, ok, msg, bridges, mode):
        self.run_btn.setEnabled(True)
        self.progress_card.setVisible(False)

        ts = datetime.datetime.now().strftime("%d %b %Y  %H:%M")
        bridges_str = ", ".join(bridges)
        item = QListWidgetItem(f"  ✓  {ts}  —  {mode}  |  {bridges_str}")
        item.setForeground(QColor(COLORS['success']))
        self.history_list.insertItem(0, item)

    def _clear_history(self):
        self.history_list.clear()
