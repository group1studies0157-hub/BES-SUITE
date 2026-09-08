"""
core/sheets_sync.py
--------------------
Silent, unattended read/write access to a Google Sheet for the Bridge
Engineering Suite (BES), using a Google service account.

Why a service account instead of "anyone with the link can edit":
    Sheet-level sharing permissions (view/comment/edit) only govern
    what a *browser user* can do. Software talking to the Sheets API
    always needs a credential — either a read-only API key, or an
    OAuth/service-account token for write access. A service account
    is the option that never shows a login prompt: you authenticate
    once by sharing the sheet with the service account's email
    address, and after that every read/write from BES is silent.

Setup (one-time, ~5 minutes):
    1. Go to https://console.cloud.google.com/ and create a project
       (or use an existing one).
    2. Enable the "Google Sheets API" for that project
       (APIs & Services -> Library -> search "Google Sheets API" -> Enable).
       Also enable "Google Drive API" (gspread uses it for lookups).
    3. Create a service account:
       IAM & Admin -> Service Accounts -> Create Service Account.
       Give it any name, e.g. "bes-sheets-sync". No special roles needed.
    4. Create a key for that service account:
       Service Accounts -> (your account) -> Keys -> Add Key -> Create
       new key -> JSON. This downloads a .json file — treat it like a
       password, do not commit it to version control.
    5. Open the downloaded JSON and copy the "client_email" value
       (looks like bes-sheets-sync@your-project.iam.gserviceaccount.com).
    6. Open your Google Sheet, click Share, paste that email address,
       give it Editor access. This is the step that actually grants
       write access — the "anyone with the link" setting is unrelated
       and can be turned back off if you like.
    7. Save the JSON key file somewhere on disk (e.g.
       G:\\BES\\secrets\\bes_service_account.json) and point
       SHEETS_CREDENTIALS_PATH at it below, or set the environment
       variable BES_SHEETS_CREDENTIALS to that path.

requirements.txt additions:
    gspread
    google-auth
"""

from __future__ import annotations

import os
from typing import Any

import gspread
from google.oauth2.service_account import Credentials


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to the service-account JSON key. Override via environment variable
# so the key never has to be hard-coded or committed to source control.
SHEETS_CREDENTIALS_PATH = os.environ.get(
    "BES_SHEETS_CREDENTIALS",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "secrets", "bes_service_account.json"),
)

# The spreadsheet this module talks to by default.
# From: https://docs.google.com/spreadsheets/d/1rj_hOPCON6KbMq0BE9M6rn0OIRG1EFhgnb-YvoXFmy8/edit?gid=1766497510
DEFAULT_SPREADSHEET_ID = "1rj_hOPCON6KbMq0BE9M6rn0OIRG1EFhgnb-YvoXFmy8"
DEFAULT_WORKSHEET_GID = 1766497510

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


class SheetsSyncError(RuntimeError):
    """Raised for any Sheets-sync configuration or API failure."""


class SheetsSync:
    """
    Thin wrapper around gspread for BES.

    Usage:
        sync = SheetsSync()                 # uses DEFAULT_SPREADSHEET_ID
        rows = sync.read_all_records()       # list[dict], header row as keys
        sync.append_row(["Br. No. 28", "Parbhani-Parli", "Pending"])
        sync.update_cell(2, 3, "Reviewed")
    """

    def __init__(
        self,
        spreadsheet_id: str = DEFAULT_SPREADSHEET_ID,
        worksheet_gid: int | None = DEFAULT_WORKSHEET_GID,
        credentials_path: str = SHEETS_CREDENTIALS_PATH,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_gid = worksheet_gid
        self.credentials_path = credentials_path
        self._client: gspread.Client | None = None
        self._sheet: gspread.Spreadsheet | None = None
        self._worksheet: gspread.Worksheet | None = None

    # -- connection ---------------------------------------------------

    def _connect(self) -> None:
        if self._worksheet is not None:
            return

        if not os.path.isfile(self.credentials_path):
            raise SheetsSyncError(
                f"Service-account key not found at '{self.credentials_path}'. "
                "See the setup steps at the top of core/sheets_sync.py, or set "
                "the BES_SHEETS_CREDENTIALS environment variable."
            )

        try:
            creds = Credentials.from_service_account_file(self.credentials_path, scopes=SCOPES)
            self._client = gspread.authorize(creds)
            self._sheet = self._client.open_by_key(self.spreadsheet_id)
        except Exception as exc:  # noqa: BLE001 - surface a clear BES-side error
            raise SheetsSyncError(f"Could not authenticate/open spreadsheet: {exc}") from exc

        try:
            if self.worksheet_gid is not None:
                self._worksheet = self._sheet.get_worksheet_by_id(self.worksheet_gid)
            else:
                self._worksheet = self._sheet.sheet1
        except Exception as exc:  # noqa: BLE001
            raise SheetsSyncError(
                f"Spreadsheet opened but worksheet (gid={self.worksheet_gid}) was not found: {exc}"
            ) from exc

    # -- reads ----------------------------------------------------------

    def read_all_records(self) -> list[dict[str, Any]]:
        """Return all rows as dicts keyed by the header row."""
        self._connect()
        return self._worksheet.get_all_records()

    def read_all_values(self) -> list[list[str]]:
        """Return the raw grid, including the header row."""
        self._connect()
        return self._worksheet.get_all_values()

    def read_cell(self, row: int, col: int) -> str:
        self._connect()
        return self._worksheet.cell(row, col).value

    # -- writes -----------------------------------------------------------

    def append_row(self, values: list[Any]) -> None:
        """Append a new row at the bottom of the sheet."""
        self._connect()
        self._worksheet.append_row(values, value_input_option="USER_ENTERED")

    def update_cell(self, row: int, col: int, value: Any) -> None:
        self._connect()
        self._worksheet.update_cell(row, col, value)

    def update_range(self, cell_range: str, values: list[list[Any]]) -> None:
        """e.g. update_range('A2:C2', [['Br. No. 28', 'Parbhani-Parli', 'Reviewed']])"""
        self._connect()
        self._worksheet.update(cell_range, values, value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# Quick manual test: `python core/sheets_sync.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sync = SheetsSync()
    try:
        records = sync.read_all_records()
        print(f"Connected OK. {len(records)} data row(s) found.")
        if records:
            print("First row:", records[0])
    except SheetsSyncError as e:
        print("Sheets sync failed:", e)
