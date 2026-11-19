#!/usr/bin/env python3
"""Create the catalogue in Google Sheets and verify that its formulas work.

Usage:
    python3.11 tools/setup_google_sheet.py [--name NAME] [--share a@x.com b@y.com]

Steps:
  1. Upload system/piano_catalog.xlsx to Google Drive, converted to a Google Sheet.
  2. Add the search sheet and its formula.
  3. Verify, by reading the computed values back:
       - the lookup columns in the pieces sheet show the example book's title and location
       - the search sheet finds the example piece
       - the level column still has its dropdown after conversion
  4. Optionally share the sheet with the teachers as editors.

Each run creates a new spreadsheet. Exit status 1 if any check fails.
The spreadsheet's default name stays in Chinese because teachers see it.

Google sign-in uses OAuth with the narrow drive.file scope, so the script can
only see files it created itself. Setup steps: docs/08_api_and_credentials.md.
Requirements: Python 3.10+, `pip install -r tools/requirements.txt`.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Dict, List

import config
import schema as s

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
TEMPLATE = config.ROOT / "system" / "piano_catalog.xlsx"


# --- Pure helpers (unit-tested) ---------------------------------------------

def sample_rows() -> tuple:
    def first(name: str) -> Dict[str, str]:
        with (config.ROOT / "sample" / name).open(newline="", encoding="utf-8-sig") as f:
            return dict(next(csv.DictReader(f)))
    return first("books.csv"), first("pieces.csv")


def expected_search_row(book: Dict[str, str], piece: Dict[str, str]) -> List[str]:
    """What the search sheet should show for the template's example piece."""
    derived = {s.PIECE_BOOK_TITLE: book[s.BOOK_TITLE], s.PIECE_BOOK_LOCATION: book[s.BOOK_LOCATION]}
    return [derived.get(c, piece.get(c, "")) for c in s.SEARCH_COLUMNS]


def pad(row: List[str], width: int) -> List[str]:
    """The Sheets API drops trailing empty cells; pad them back for comparison."""
    return list(row) + [""] * (width - len(row))


# --- Google API -------------------------------------------------------------

def get_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_file = config.secret_path("GOOGLE_OAUTH_CLIENT_FILE", "google_oauth_client.json")
    token_file = config.secret_path("GOOGLE_TOKEN_FILE", "google_token.json")

    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES) if token_file.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not client_file.exists():
            sys.exit(f"{client_file} not found. See docs/08_api_and_credentials.md for setup.")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
        creds = flow.run_local_server(port=0)  # opens the browser for sign-in
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    os.chmod(token_file, 0o600)  # the token grants access to the account; owner-only
    return creds


class Checker:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, label: str, actual, expected) -> None:
        ok = actual == expected
        self.failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}: {label}")
        if not ok:
            print(f"    expected: {expected}\n    actual:   {actual}")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the catalogue in Google Sheets and verify it.")
    parser.add_argument("--name", default="鋼琴教材目錄", help="spreadsheet name shown to teachers")
    parser.add_argument("--share", nargs="*", default=[], metavar="EMAIL", help="teachers to add as editors")
    args = parser.parse_args(argv)

    config.load_env()
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)
    values = sheets.spreadsheets().values()

    print("1. Upload the template and convert it to a Google Sheet")
    created = drive.files().create(
        body={"name": args.name, "mimeType": SHEET_MIME},
        media_body=MediaFileUpload(str(TEMPLATE), mimetype=XLSX_MIME),
        fields="id,webViewLink",
    ).execute()
    sid = created["id"]
    print(f"  {created['webViewLink']}")

    print("2. Create the search sheet")
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=sid,
        body={"requests": [{"addSheet": {"properties": {"title": s.SEARCH_SHEET, "index": 0}}}]},
    ).execute()
    values.update(
        spreadsheetId=sid,
        range=f"{s.SEARCH_SHEET}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [[s.SEARCH_LABEL, ""], s.SEARCH_COLUMNS, [s.search_formula()]]},
    ).execute()

    print("3. Verify the formulas")
    book, piece = sample_rows()
    checker = Checker()
    last = s.column_letter(len(s.PIECE_COLUMNS))
    first_derived = s.column_letter(len(s.PIECE_INPUT_COLUMNS) + 1)
    lookup = values.get(spreadsheetId=sid, range=f"{s.PIECE_SHEET}!{first_derived}2:{last}2").execute()
    checker.check(
        "pieces sheet looks up the book title and location",
        pad(lookup.get("values", [[]])[0], 2),
        [book[s.BOOK_TITLE], book[s.BOOK_LOCATION]],
    )

    keyword = piece[s.PIECE_COMPOSER]
    values.update(
        spreadsheetId=sid, range=f"{s.SEARCH_SHEET}!B1",
        valueInputOption="RAW", body={"values": [[keyword]]},
    ).execute()
    width = len(s.SEARCH_COLUMNS)
    found = values.get(
        spreadsheetId=sid, range=f"{s.SEARCH_SHEET}!A3:{s.column_letter(width)}3"
    ).execute()
    checker.check(
        f"searching for \"{keyword}\" finds the example piece",
        pad(found.get("values", [[]])[0], width),
        expected_search_row(book, piece),
    )
    values.clear(spreadsheetId=sid, range=f"{s.SEARCH_SHEET}!B1").execute()

    level_col = s.column_letter(s.PIECE_COLUMNS.index(s.PIECE_LEVEL) + 1)
    grid = sheets.spreadsheets().get(
        spreadsheetId=sid,
        ranges=[f"{s.PIECE_SHEET}!{level_col}2"],
        includeGridData=True,
        fields="sheets.data.rowData.values.dataValidation.condition.type",
    ).execute()
    cell = grid["sheets"][0]["data"][0].get("rowData", [{}])[0].get("values", [{}])[0]
    checker.check(
        "level column keeps its dropdown",
        cell.get("dataValidation", {}).get("condition", {}).get("type"),
        "ONE_OF_RANGE",
    )

    if args.share:
        print("4. Share with the teachers")
        for email in args.share:
            drive.permissions().create(
                fileId=sid,
                body={"type": "user", "role": "writer", "emailAddress": email},
                sendNotificationEmail=True,
            ).execute()
            print(f"  added editor: {email}")

    print(f"\nDone: {checker.failures} check(s) failed. Spreadsheet: {created['webViewLink']}")
    return 1 if checker.failures else 0


if __name__ == "__main__":
    sys.exit(main())
