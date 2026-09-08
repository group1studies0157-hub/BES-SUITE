"""
Google Sheets Sync Panel
────────────────────────
Connects to the BES tracking spreadsheet via a Google service account
and lets the user pull / push project data without leaving the app.
"""

from __future__ import annotations

import traceback
from typing import Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.styles import COLORS
from gui.icons import icon, icon_label, styled_button


# ── Background worker ──────────────────────────────────────────────────
class _SyncWorker(QThread):
    """Run the Sheets API call off the main thread so the UI stays responsive."""

    finished = pyqtSignal(object)  # list[dict]  or  str on error

    def run(self):
        try:
            from core.sheets_sync import SheetsSync, SheetsSyncError

            sync = SheetsSync()
            records = sync.read_all_records()
            self.finished.emit(records)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(f"{exc}\n\n{traceback.format_exc()}")


# ── Panel widget ───────────────────────────────────────────────────────
class SheetsSyncPanel(QWidget):
    """Full-page panel that displays the Google Sheets tracking data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[dict[str, Any]] = []
        self._worker: _SyncWorker | None = None
        self._build_ui()

    # ── Layout ─────────────────────────────────────────────────────────
    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(42, 34, 42, 42)
        layout.setSpacing(18)
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # Title
        title = QLabel("Google Sheets Sync")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Pull live project tracking data from the shared Google Sheet "
            "into the Bridge Engineering Suite."
        )
        subtitle.setObjectName("panelSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # ── Status card ────────────────────────────────────────────────
        status_card = QFrame()
        status_card.setObjectName("card")
        sc_lay = QHBoxLayout(status_card)
        sc_lay.setContentsMargins(24, 18, 24, 18)
        sc_lay.setSpacing(16)

        self._status_icon = QLabel("Not connected")
        self._status_icon.setObjectName("tagInfo")
        sc_lay.addWidget(self._status_icon)

        sc_lay.addStretch()

        self._sync_btn = styled_button("Sync Data", "download", color="#FFFFFF")
        self._sync_btn.setObjectName("primaryBtn")
        self._sync_btn.setFixedHeight(38)
        self._sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_btn.clicked.connect(self._start_sync)
        sc_lay.addWidget(self._sync_btn)

        layout.addWidget(status_card)

        # ── Info card ──────────────────────────────────────────────────
        info_card = QFrame()
        info_card.setObjectName("card")
        ic_lay = QVBoxLayout(info_card)
        ic_lay.setContentsMargins(24, 18, 24, 18)
        ic_lay.setSpacing(8)

        info_header = icon_label("Connection Details", "info", text_size=13)
        ic_lay.addWidget(info_header)

        self._detail_label = QLabel(self._connection_detail_text())
        self._detail_label.setObjectName("panelSubtitle")
        self._detail_label.setWordWrap(True)
        ic_lay.addWidget(self._detail_label)

        layout.addWidget(info_card)

        # ── Data table ─────────────────────────────────────────────────
        table_card = QFrame()
        table_card.setObjectName("card")
        tc_lay = QVBoxLayout(table_card)
        tc_lay.setContentsMargins(24, 18, 24, 18)
        tc_lay.setSpacing(10)

        table_header_row = QHBoxLayout()
        self._table_title = icon_label("Fetched Data", "folder", text_size=13)
        table_header_row.addWidget(self._table_title)
        table_header_row.addStretch()

        self._row_count_label = QLabel("0 rows")
        self._row_count_label.setObjectName("panelSubtitle")
        table_header_row.addWidget(self._row_count_label)
        tc_lay.addLayout(table_header_row)

        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setMinimumHeight(200)
        tc_lay.addWidget(self._table, 1)

        layout.addWidget(table_card, 1)

        # ── Log area ───────────────────────────────────────────────────
        log_card = QFrame()
        log_card.setObjectName("card")
        lc_lay = QVBoxLayout(log_card)
        lc_lay.setContentsMargins(24, 18, 24, 18)
        lc_lay.setSpacing(8)

        log_header = icon_label("Activity Log", "clipboard", text_size=13)
        lc_lay.addWidget(log_header)

        self._log_label = QLabel("No activity yet. Click **Sync Data** to connect.")
        self._log_label.setObjectName("panelSubtitle")
        self._log_label.setWordWrap(True)
        lc_lay.addWidget(self._log_label)

        layout.addWidget(log_card)
        layout.addStretch()

    # ── Helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _connection_detail_text() -> str:
        from core.sheets_sync import (
            SHEETS_CREDENTIALS_PATH,
            DEFAULT_SPREADSHEET_ID,
            DEFAULT_WORKSHEET_GID,
        )

        return (
            f"**Credentials:** `{SHEETS_CREDENTIALS_PATH}`\n"
            f"**Spreadsheet ID:** `{DEFAULT_SPREADSHEET_ID}`\n"
            f"**Worksheet GID:** `{DEFAULT_WORKSHEET_GID}`"
        )

    def _set_status(self, text: str, tag: str = "tagInfo"):
        self._status_icon.setObjectName(tag)
        self._status_icon.setText(text)
        # Force style refresh
        self._status_icon.style().unpolish(self._status_icon)
        self._status_icon.style().polish(self._status_icon)

    def _populate_table(self, records: list[dict[str, Any]]):
        if not records:
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._row_count_label.setText("0 rows")
            return

        headers = list(records[0].keys())
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(records))

        for row_idx, row_data in enumerate(records):
            for col_idx, key in enumerate(headers):
                val = row_data.get(key, "")
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row_idx, col_idx, item)

        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._row_count_label.setText(f"{len(records)} rows")

    def _append_log(self, msg: str):
        self._log_label.setText(msg)

    # ── Sync logic ─────────────────────────────────────────────────────
    @pyqtSlot()
    def _start_sync(self):
        self._sync_btn.setEnabled(False)
        self._sync_btn.setText("Syncing…")
        self._sync_btn.setIcon(icon("refresh", "#FFFFFF", 18))
        self._set_status("Syncing…", "tagInfo")
        self._append_log("Connecting to Google Sheets…")

        self._worker = _SyncWorker()
        self._worker.finished.connect(self._on_sync_finished)
        self._worker.start()

    @pyqtSlot(object)
    def _on_sync_finished(self, result):
        self._sync_btn.setEnabled(True)
        self._sync_btn.setText("Sync Data")
        self._sync_btn.setIcon(icon("download", "#FFFFFF", 18))

        if isinstance(result, str):
            # Error
            self._set_status(" Sync failed — see log", "tagError")
            self._append_log(f"❌ Sync failed:\n{result}")
            return

        records = result
        self._records = records
        self._populate_table(records)
        self._set_status(f" Connected — {len(records)} row(s)", "tagSuccess")
        self._append_log(
            f"✅ Synced successfully — {len(records)} data row(s) loaded from Google Sheets."
        )
