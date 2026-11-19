#!/usr/bin/env python3
"""Build the catalogue workbook that is imported into Google Sheets.

Usage:
    python3 tools/build_template.py [--rows 3000] [--out system/piano_catalog.xlsx]

The workbook has four sheets (tab names are in Chinese, see schema.py):
  guide     legend: which cells to edit, which are automatic
  books     one row per book, with a dropdown for the book type
  pieces    one row per piece, with dropdowns for level/period/style and two
            lookup columns that pull the book title and location from books
  options   the dropdown lists; staff may add values here

All text written into the workbook stays in Chinese because teachers read it.

Example rows come from sample/ so the template and the sample data never drift.
Formulas use only INDEX/MATCH/IFERROR so they work in Excel and Google Sheets.
Requires openpyxl.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

import schema as s

ROOT = Path(__file__).resolve().parent.parent
FONT = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
AUTO_FILL = PatternFill("solid", fgColor="E7E6E6")      # grey: formula, do not edit
EXAMPLE_FILL = PatternFill("solid", fgColor="FFF2CC")   # yellow: example row, may delete
VOCAB_ROWS = 50  # room for staff to add dropdown values later

COLUMN_WIDTHS = {
    s.BOOK_ID: 11, s.BOOK_TITLE: 34, s.BOOK_SERIES: 16, s.BOOK_TYPE: 11,
    s.BOOK_LOCATION: 10, s.BOOK_LINK: 30, s.BOOK_NOTES: 20,
    s.PIECE_ID: 11, s.PIECE_TITLE: 34, s.PIECE_COMPOSER: 16, s.PIECE_PAGE: 7,
    s.PIECE_LEVEL: 8, s.PIECE_EXAM: 14, s.PIECE_PERIOD: 9, s.PIECE_STYLE: 11,
    s.PIECE_TECHNIQUE: 18, s.PIECE_AUDIO: 24, s.PIECE_NOTES: 18,
    s.PIECE_BOOK_TITLE: 30, s.PIECE_BOOK_LOCATION: 11,
}


def first_sample_row(name: str) -> Dict[str, str]:
    with (ROOT / "sample" / name).open(newline="", encoding="utf-8-sig") as f:
        return dict(next(csv.DictReader(f)))


def write_header(ws: Worksheet, columns: List[str]) -> None:
    for i, name in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=i, value=name)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = COLUMN_WIDTHS.get(name, 14)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}1"


def col(columns: List[str], name: str) -> str:
    return get_column_letter(columns.index(name) + 1)


def add_list_validation(ws: Worksheet, columns: List[str], name: str, vocab_col: str, last_row: int) -> None:
    source = f"{quote_sheetname(s.VOCAB_SHEET)}!${vocab_col}$2:${vocab_col}${VOCAB_ROWS + 1}"
    # OOXML stores validation formulas without the leading "=".
    dv = DataValidation(type="list", formula1=source, allow_blank=True, showErrorMessage=True)
    dv.errorTitle = "不在選項裡"
    dv.error = f"請從下拉選單選擇；要新增選項，請到「{s.VOCAB_SHEET}」表加在 {name} 欄。"
    letter = col(columns, name)
    dv.add(f"{letter}2:{letter}{last_row}")
    ws.add_data_validation(dv)


def build_vocab(wb: Workbook) -> dict:
    ws = wb.create_sheet(s.VOCAB_SHEET)
    fields = list(s.VOCAB)
    write_header(ws, fields)
    ws.auto_filter.ref = None
    letters = {}
    for i, name in enumerate(fields, start=1):
        letters[name] = get_column_letter(i)
        ws.column_dimensions[letters[name]].width = 14
        for r, value in enumerate(s.VOCAB[name], start=2):
            ws.cell(row=r, column=i, value=value).font = Font(name=FONT)
    return letters


def build_books(wb: Workbook, vocab_cols: dict, rows: int) -> None:
    ws = wb.create_sheet(s.BOOK_SHEET)
    cols = s.BOOK_COLUMNS
    write_header(ws, cols)
    example = first_sample_row("books.csv")
    for i, name in enumerate(cols, start=1):
        cell = ws.cell(row=2, column=i, value=example[name] or None)
        cell.font = Font(name=FONT)
        cell.fill = EXAMPLE_FILL
    add_list_validation(ws, cols, s.BOOK_TYPE, vocab_cols[s.BOOK_TYPE], rows + 1)


def build_pieces(wb: Workbook, vocab_cols: dict, rows: int) -> None:
    ws = wb.create_sheet(s.PIECE_SHEET)
    cols = s.PIECE_COLUMNS
    write_header(ws, cols)
    example = first_sample_row("pieces.csv")
    for i, name in enumerate(s.PIECE_INPUT_COLUMNS, start=1):
        value = example[name]
        if name == s.PIECE_PAGE and value.isdigit():
            value = int(value)
        cell = ws.cell(row=2, column=i, value=value if value != "" else None)
        cell.font = Font(name=FONT)
        cell.fill = EXAMPLE_FILL

    books = quote_sheetname(s.BOOK_SHEET)
    key = col(cols, s.PIECE_BOOK_ID)
    book_ids = f"{books}!${col(s.BOOK_COLUMNS, s.BOOK_ID)}:${col(s.BOOK_COLUMNS, s.BOOK_ID)}"
    lookups = {
        s.PIECE_BOOK_TITLE: (col(s.BOOK_COLUMNS, s.BOOK_TITLE), "找不到書籍"),
        s.PIECE_BOOK_LOCATION: (col(s.BOOK_COLUMNS, s.BOOK_LOCATION), ""),
    }
    for name, (source_col, missing_text) in lookups.items():
        c = cols.index(name) + 1
        target = f"{books}!${source_col}:${source_col}"
        for r in range(2, rows + 2):
            # Blank until a book ID is typed; then look the book up by ID.
            # &"" turns an empty source cell into "" instead of 0.
            formula = (
                f'=IF(${key}{r}="","",'
                f'IFERROR(INDEX({target},MATCH(${key}{r},{book_ids},0))&"","{missing_text}"))'
            )
            cell = ws.cell(row=r, column=c, value=formula)
            cell.font = Font(name=FONT, color="595959")
            cell.fill = AUTO_FILL

    last = rows + 1
    for name in (s.PIECE_LEVEL, s.PIECE_PERIOD, s.PIECE_STYLE):
        add_list_validation(ws, cols, name, vocab_cols[name], last)
    page = col(cols, s.PIECE_PAGE)
    dv = DataValidation(type="whole", operator="greaterThan", formula1="0", allow_blank=True, showErrorMessage=True)
    dv.errorTitle, dv.error = "頁碼", "頁碼請填正整數。"
    dv.add(f"{page}2:{page}{last}")
    ws.add_data_validation(dv)


def build_guide(wb: Workbook) -> None:
    ws = wb.active
    ws.title = s.GUIDE_SHEET
    lines = [
        ("鋼琴教材目錄：使用說明", True),
        ("", False),
        ("每張表的用途", True),
        (f"「{s.BOOK_SHEET}」：一本書（或一份 PDF）一列。位置格式為 櫃-層-位置，例如 A-2-05。", False),
        (f"「{s.PIECE_SHEET}」：書裡的每一首曲子一列。用「{s.PIECE_BOOK_ID}」連到書籍表。", False),
        (f"「{s.VOCAB_SHEET}」：下拉選單的選項。要新增程度、風格等選項時，加在這裡。", False),
        ("", False),
        ("哪些格子可以填", True),
        ("白色格子：手動填寫。", False),
        ("灰色格子：自動帶出書名和位置，請勿修改。", False),
        ("黃色列：範例資料，開始建檔後可以刪除。", False),
        ("", False),
        ("填寫規則", True),
        ("書籍編號依序為 B0001、B0002…；曲目編號依序為 P00001、P00002…，編號不重複使用。", False),
        ("每本書至少要填「位置」或「檔案連結」其中一個。", False),
        ("頁碼填該曲目的起始頁。", False),
        ("詳細說明請見 docs/06_teacher_guide.md 與 docs/04_admin_manual.md。", False),
    ]
    for r, (text, bold) in enumerate(lines, start=1):
        ws.cell(row=r, column=1, value=text or None).font = Font(name=FONT, bold=bold, size=14 if r == 1 else 11)
    ws.column_dimensions["A"].width = 90


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rows", type=int, default=3000, help="pre-filled rows in the pieces sheet")
    parser.add_argument("--out", type=Path, default=ROOT / "system" / "piano_catalog.xlsx")
    args = parser.parse_args()

    wb = Workbook()
    build_guide(wb)
    vocab_cols = build_vocab(wb)
    build_books(wb, vocab_cols, args.rows)
    build_pieces(wb, vocab_cols, args.rows)
    # Tabs were created guide, options, books, pieces; staff use options last.
    wb.move_sheet(s.VOCAB_SHEET, offset=2)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)
    print(f"Created {args.out} ({args.rows} rows pre-filled in the pieces sheet)")


if __name__ == "__main__":
    main()
