#!/usr/bin/env python3
"""Extract piece lists from photos or PDFs of table-of-contents pages with Claude.

Usage:
    python3.11 tools/extract_toc.py input/toc_photos \
        --catalog-books books.csv --catalog-pieces pieces.csv --out output/

Input layout (one book per entry):
    input/toc_photos/
        burgmuller_op100.jpg          a single photo = one book
        clementi_op36/                a folder = one book; pages sorted by file name
            01.jpg
            02.jpg

Output (UTF-8 CSV, same columns as the catalogue so rows paste straight in):
    output/extracted_books.csv    one row per book; type and location are left blank for the reviewer
    output/extracted_pieces.csv   one row per piece; the notes column marks every row for human review

The review notes written into the notes column stay in Chinese because teachers read them.

IDs continue from the existing catalogue when --catalog-books/--catalog-pieces
are given (the CSVs exported from Google Sheets); otherwise they start at 1.

Every extracted row must be checked against the physical book before it goes
into the catalogue, then the whole catalogue re-checked with validate_catalog.py.

Requirements: Python 3.10+, `pip install -r tools/requirements.txt`, and Claude
API credentials: ANTHROPIC_API_KEY in .env (see .env.example), in the shell
environment, or an `ant auth login` profile. Setup: docs/08_api_and_credentials.md.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Pattern, Sequence, Tuple

import config
import schema as s

MODEL = "claude-opus-5-5"
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
PDF_TYPE = "application/pdf"
# Written into the notes column that teachers read, hence in Chinese.
REVIEW_NOTE = "AI 擷取，待校對"
UNSURE_NOTE = "AI 不確定，請特別確認"

# Structured output: the API guarantees the reply matches this schema.
TOC_SCHEMA = {
    "type": "object",
    "properties": {
        "book_title": {"type": "string", "description": "Title as printed on the page; empty if not shown"},
        "series": {"type": "string", "description": "Series or publisher if printed; otherwise empty"},
        "pieces": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "composer": {"type": "string"},
                    "page": {"type": "string", "description": "Start page digits only; empty if not shown"},
                    "unsure": {"type": "boolean", "description": "True if any field was hard to read"},
                },
                "required": ["title", "composer", "page", "unsure"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["book_title", "series", "pieces"],
    "additionalProperties": False,
}

PROMPT = """These pages come from one piano score book. They are either its table-of-contents
pages, or (for books without a contents page) the first page of each piece.
List every piece in the order printed.

Rules:
- Copy titles exactly as printed, in their original language. Keep opus and number
  (e.g. "Arabesque (Op. 100 No. 2)").
- composer: as printed next to the piece. If the whole book is by one composer named
  on the page, use that name for every piece. If no composer is shown, leave it empty.
- page: the starting page number, digits only. On a first page, use the page number
  printed in the corner. If not shown, leave it empty.
- A dash or ditto line in the composer column means "same composer as above".
- Never guess. If a word or number is hard to read, give your best reading and set
  unsure to true.
- Do not list section headings, prefaces or indexes as pieces. If the contents page
  lists the same pieces a second time in another order (for example a "progressive
  order" list), list each piece only once, from the main list."""


@dataclass
class BookSource:
    name: str            # file or folder name, kept in the notes column for traceability
    pages: List[Path]


@dataclass
class Extraction:
    source: BookSource
    data: Dict          # validated against TOC_SCHEMA by the API


# --- Pure helpers (unit-tested, no API) ------------------------------------

def collect_sources(input_dir: Path) -> List[BookSource]:
    """A file is a one-page book; a folder is a book whose pages sort by name."""
    def usable(p: Path) -> bool:
        return p.is_file() and (p.suffix.lower() in IMAGE_TYPES or p.suffix.lower() == ".pdf")

    sources = []
    for entry in sorted(input_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            pages = sorted(p for p in entry.iterdir() if usable(p))
            if pages:
                sources.append(BookSource(entry.name, pages))
        elif usable(entry):
            sources.append(BookSource(entry.name, [entry]))
    return sources


def next_number(ids: Iterable[str], pattern: Pattern[str]) -> int:
    """Next free number after the highest well-formed ID (1 if there are none)."""
    numbers = [int(m.group(1)) for i in ids if (m := pattern.match(i.strip()))]
    return max(numbers, default=0) + 1


def read_ids(path: Optional[Path], column: str) -> List[str]:
    if path is None:
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [row.get(column, "") or "" for row in csv.DictReader(f)]


def to_rows(
    extractions: Sequence[Extraction], first_book: int, first_piece: int
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Turn API results into catalogue rows with fresh IDs."""
    books, pieces = [], []
    b, p = first_book, first_piece
    for ex in extractions:
        bid = s.book_id(b)
        note = f"{REVIEW_NOTE}（來源：{ex.source.name}）"
        books.append({c: "" for c in s.BOOK_COLUMNS} | {
            s.BOOK_ID: bid,
            s.BOOK_TITLE: ex.data["book_title"].strip() or ex.source.name,
            s.BOOK_SERIES: ex.data["series"].strip(),
            s.BOOK_NOTES: note,
        })
        for item in ex.data["pieces"]:
            page = "".join(ch for ch in item["page"] if ch.isdigit())
            pieces.append({c: "" for c in s.PIECE_INPUT_COLUMNS} | {
                s.PIECE_ID: s.piece_id(p),
                s.PIECE_BOOK_ID: bid,
                s.PIECE_TITLE: item["title"].strip(),
                s.PIECE_COMPOSER: item["composer"].strip(),
                s.PIECE_PAGE: page,
                s.PIECE_NOTES: UNSURE_NOTE if item["unsure"] else REVIEW_NOTE,
            })
            p += 1
        b += 1
    return books, pieces


def write_csv(path: Path, columns: List[str], rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel opens the Chinese text correctly; Google Sheets ignores the BOM.
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


# --- Claude API call --------------------------------------------------------

def page_block(path: Path) -> Dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    if path.suffix.lower() == ".pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": PDF_TYPE, "data": data}}
    media_type = IMAGE_TYPES[path.suffix.lower()]
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def extract_book(client, source: BookSource) -> Extraction:
    content = [page_block(p) for p in source.pages] + [{"type": "text", "text": PROMPT}]
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        # If a request is declined, the API retries it on a fallback model in the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": TOC_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("the request was declined")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("the reply was cut off; split the book into fewer pages per folder")
    text = next(block.text for block in response.content if block.type == "text")
    return Extraction(source, json.loads(text))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Extract piece lists from TOC photos or PDFs with Claude.")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--catalog-books", type=Path, help="current books sheet exported as CSV")
    parser.add_argument("--catalog-pieces", type=Path, help="current pieces sheet exported as CSV")
    parser.add_argument("--out", type=Path, default=Path("output"))
    args = parser.parse_args(argv)

    sources = collect_sources(args.input_dir)
    if not sources:
        print(f"No photos or PDFs to process in {args.input_dir}.")
        return 1

    import anthropic  # imported here so the pure helpers are testable without the SDK

    config.load_env()  # ANTHROPIC_API_KEY from .env, unless already set in the shell
    client = anthropic.Anthropic()
    extractions, failed = [], []
    for i, source in enumerate(sources, start=1):
        print(f"[{i}/{len(sources)}] {source.name} ({len(source.pages)} page(s))")
        try:
            extractions.append(extract_book(client, source))
        except (anthropic.APIError, RuntimeError, json.JSONDecodeError) as exc:
            # Keep going: one unreadable book should not stop a batch of fifty.
            print(f"  failed: {exc}")
            failed.append(source.name)

    first_book = next_number(read_ids(args.catalog_books, s.BOOK_ID), s.BOOK_ID_PATTERN)
    first_piece = next_number(read_ids(args.catalog_pieces, s.PIECE_ID), s.PIECE_ID_PATTERN)
    books, pieces = to_rows(extractions, first_book, first_piece)
    write_csv(args.out / "extracted_books.csv", s.BOOK_COLUMNS, books)
    write_csv(args.out / "extracted_pieces.csv", s.PIECE_INPUT_COLUMNS, pieces)

    print(f"\nDone: {len(books)} book(s), {len(pieces)} piece(s), written to {args.out}/")
    if failed:
        print(f"{len(failed)} book(s) to redo: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
