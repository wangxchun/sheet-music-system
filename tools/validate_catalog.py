#!/usr/bin/env python3
"""Validate the catalogue after exporting each sheet from Google Sheets as CSV.

Usage:
    python3 tools/validate_catalog.py 書籍.csv 曲目.csv 選項.csv

Errors (exit status 1):
  - a required column is missing, or a required cell is empty
  - a book or piece ID is duplicated or badly formatted (B0001 / P00001)
  - a piece points to a book ID that does not exist
  - a dropdown field holds a value that is not in the 選項 sheet
  - a page number is not a positive integer
  - a book has neither a location (A-2-05) nor a file link, or the location is malformed
  - the same title appears twice in the same book

Warnings (reported, exit status unaffected):
  - a piece has no level yet (levels are added after the first cataloguing pass)

Rows whose input columns are all blank are skipped: the pieces sheet carries
pre-filled formula columns, so a CSV export contains many such rows.
Standard library only; runs on Python 3.9+.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Pattern, Set, Tuple

import schema as s

Row = Dict[str, str]
NumberedRows = List[Tuple[int, Row]]  # (line number in the CSV, row)


@dataclass
class Report:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    n_books: int = 0
    n_pieces: int = 0

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"[錯誤] {where}：{msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"[提醒] {where}：{msg}")


def read_rows(path: Path) -> Tuple[List[str], NumberedRows]:
    """Return the header and numbered rows; line 1 is the header."""
    # utf-8-sig drops the byte-order mark that spreadsheet exports often add.
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        rows = [
            (line, {(k or "").strip(): (v or "").strip() for k, v in raw.items()})
            for line, raw in enumerate(reader, start=2)
        ]
    return header, rows


def load_vocab(path: Path) -> Dict[str, Set[str]]:
    """The 選項 sheet has one column per field, with values listed downwards."""
    header, rows = read_rows(path)
    return {col: {row[col] for _, row in rows if row.get(col)} for col in header if col}


def drop_blank(rows: NumberedRows, columns: List[str]) -> NumberedRows:
    return [(line, row) for line, row in rows if any(row.get(c) for c in columns)]


def check_header(sheet: str, header: List[str], expected: List[str], report: Report) -> bool:
    missing = [c for c in expected if c not in header]
    if missing:
        report.error(sheet, f"缺少欄位 {', '.join(missing)}")
    return not missing


def check_required_and_ids(
    sheet: str, rows: NumberedRows, required: List[str], id_col: str, pattern: Pattern[str], report: Report
) -> None:
    for line, row in rows:
        for col in required:
            if not row[col]:
                report.error(f"{sheet} 第 {line} 列", f"「{col}」是空的")
        value = row[id_col]
        if value and not pattern.match(value):
            report.error(f"{sheet} 第 {line} 列", f"{id_col}「{value}」格式不對")
    counts = Counter(row[id_col] for _, row in rows if row[id_col])
    for value, n in sorted(counts.items()):
        if n > 1:
            report.error(sheet, f"{id_col}「{value}」重複 {n} 次")


def check_books(rows: NumberedRows, report: Report) -> None:
    for line, row in rows:
        where = f"{s.BOOK_SHEET} 第 {line} 列（{row[s.BOOK_ID]}）"
        location, link = row[s.BOOK_LOCATION], row[s.BOOK_LINK]
        if not location and not link:
            report.error(where, "要填「位置」或「檔案連結」其中一個")
        if location and not s.LOCATION_PATTERN.match(location):
            report.error(where, f"位置「{location}」格式應為 A-2-05")


def normalise(text: str) -> str:
    return " ".join(text.lower().split())


def check_pieces(rows: NumberedRows, book_ids: Set[str], report: Report) -> None:
    first_seen: Dict[Tuple[str, str, str], int] = {}
    for line, row in rows:
        where = f"{s.PIECE_SHEET} 第 {line} 列（{row[s.PIECE_ID]}）"
        book = row[s.PIECE_BOOK_ID]
        if book and book not in book_ids:
            report.error(where, f"書籍編號「{book}」不存在於書籍表")
        page = row[s.PIECE_PAGE]
        if page and not (page.isdigit() and int(page) > 0):
            report.error(where, f"頁碼「{page}」不是正整數")
        if not row[s.PIECE_LEVEL]:
            report.warn(where, "還沒有填程度")
        if row[s.PIECE_TITLE]:
            # Case- and spacing-insensitive, so "Minuet  in G" matches "minuet in g".
            # The composer is part of the key: an album may hold Haydn's "C major"
            # and Mozart's "C major" as two different pieces.
            key = (book, normalise(row[s.PIECE_TITLE]), normalise(row[s.PIECE_COMPOSER]))
            if key in first_seen:
                report.error(where, f"與第 {first_seen[key]} 列是同一本書裡的同一首曲子")
            else:
                first_seen[key] = line


def check_vocab(sheets: Dict[str, NumberedRows], vocab: Dict[str, Set[str]], report: Report) -> None:
    for sheet, col in s.VOCAB_FIELDS:
        allowed = vocab.get(col, set())
        for line, row in sheets[sheet]:
            value = row[col]
            if value and value not in allowed:
                report.error(f"{sheet} 第 {line} 列", f"{col}「{value}」不在選項表裡")


def validate(books_path: Path, pieces_path: Path, vocab_path: Path) -> Report:
    report = Report()
    book_header, books = read_rows(books_path)
    piece_header, pieces = read_rows(pieces_path)
    vocab = load_vocab(vocab_path)

    books_ok = check_header(s.BOOK_SHEET, book_header, s.BOOK_COLUMNS, report)
    pieces_ok = check_header(s.PIECE_SHEET, piece_header, s.PIECE_INPUT_COLUMNS, report)
    if not (books_ok and pieces_ok):
        return report  # row checks would fail on the missing columns

    books = drop_blank(books, s.BOOK_COLUMNS)
    pieces = drop_blank(pieces, s.PIECE_INPUT_COLUMNS)
    report.n_books, report.n_pieces = len(books), len(pieces)

    check_required_and_ids(s.BOOK_SHEET, books, s.BOOK_REQUIRED, s.BOOK_ID, s.BOOK_ID_PATTERN, report)
    check_required_and_ids(s.PIECE_SHEET, pieces, s.PIECE_REQUIRED, s.PIECE_ID, s.PIECE_ID_PATTERN, report)
    check_books(books, report)
    check_pieces(pieces, {row[s.BOOK_ID] for _, row in books}, report)
    check_vocab({s.BOOK_SHEET: books, s.PIECE_SHEET: pieces}, vocab, report)
    return report


def main(argv: List[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    report = validate(*(Path(a) for a in argv[1:]))
    for line in report.errors + report.warnings:
        print(line)
    print(
        f"\n書籍 {report.n_books} 筆、曲目 {report.n_pieces} 筆："
        f"錯誤 {len(report.errors)} 個、提醒 {len(report.warnings)} 個"
    )
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
