"""SQLite storage for the agent: ETL from the spreadsheet CSV export, plus connections.

DESIGN DECISIONS
- ETL boundary: Chinese headers and dropdown labels are translated to English
  columns and codes here (see vocab.py). Empty cells become NULL.
- The database enforces its own rules (NOT NULL, CHECK, FOREIGN KEY) instead
  of trusting the CSV. Note `TEXT PRIMARY KEY` alone allows NULL in SQLite, so
  the IDs say NOT NULL explicitly.
- Atomic rebuild: write to a temporary file, then os.replace() it over the
  old one. Readers never see a half-built database.
- Two kinds of connection. The agent's query tools get read-only connections
  (`mode=ro` plus `PRAGMA query_only`). Only the approved-onboarding write
  path opens a writable one.
"""

from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

import aiosqlite

from agent import vocab as v
from tools import schema as s

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "agent" / ".data"
DEFAULT_DB = DATA_DIR / "catalog.db"
DEMO_DIR = ROOT / "sample" / "demo"


def _in(values: List[str]) -> str:
    return ", ".join(f"'{x}'" for x in values)


SCHEMA_SQL = f"""
CREATE TABLE books (
    book_id   TEXT PRIMARY KEY NOT NULL CHECK (book_id GLOB 'B[0-9][0-9][0-9][0-9]'),
    title     TEXT NOT NULL,
    series    TEXT,
    book_type TEXT NOT NULL CHECK (book_type IN ({_in(list(v.BOOK_TYPE_CODES.values()))})),
    location  TEXT CHECK (location GLOB '[A-Z]-[0-9]*-[0-9][0-9]'),
    file_link TEXT,
    notes     TEXT,
    CHECK (location IS NOT NULL OR file_link IS NOT NULL)
);
CREATE TABLE pieces (
    piece_id  TEXT PRIMARY KEY NOT NULL CHECK (piece_id GLOB 'P[0-9][0-9][0-9][0-9][0-9]'),
    book_id   TEXT NOT NULL REFERENCES books (book_id),
    title     TEXT NOT NULL,
    composer  TEXT NOT NULL,
    page      INTEGER NOT NULL CHECK (page > 0),
    level     INTEGER CHECK (level BETWEEN {v.LEVEL_MIN} AND {v.LEVEL_MAX}),
    exam      TEXT,
    period    TEXT CHECK (period IN ({_in(list(v.PERIOD_CODES.values()))})),
    style     TEXT CHECK (style IN ({_in(list(v.STYLE_CODES.values()))})),
    technique TEXT,
    demo_url  TEXT,
    notes     TEXT
);
CREATE INDEX pieces_book ON pieces (book_id);
CREATE INDEX pieces_composer ON pieces (composer);
CREATE INDEX pieces_level ON pieces (level);

-- One row per piece with its book's title and whereabouts. The text-to-SQL
-- tool is told to prefer this view, so the model rarely needs to write a join.
CREATE VIEW catalogue AS
SELECT p.piece_id, p.title, p.composer, p.page, p.level, p.period, p.style,
       p.technique, p.demo_url, p.book_id, b.title AS book_title, b.book_type,
       b.location, b.file_link
FROM pieces p JOIN books b USING (book_id);
"""


def fold(text: Optional[str]) -> Optional[str]:
    """Case- and accent-insensitive key: 'Burgmüller' and 'burgmuller' match."""
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _read(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (val or "").strip() for k, val in row.items()} for row in csv.DictReader(f)]


def _null(value: str) -> Optional[str]:
    return value or None


def book_row(row: Dict[str, str]) -> Dict[str, Optional[str]]:
    return {
        "book_id": row[s.BOOK_ID], "title": row[s.BOOK_TITLE], "series": _null(row[s.BOOK_SERIES]),
        "book_type": v.BOOK_TYPE_CODES[row[s.BOOK_TYPE]], "location": _null(row[s.BOOK_LOCATION]),
        "file_link": _null(row[s.BOOK_LINK]), "notes": _null(row[s.BOOK_NOTES]),
    }


def piece_row(row: Dict[str, str]) -> Dict[str, object]:
    return {
        "piece_id": row[s.PIECE_ID], "book_id": row[s.PIECE_BOOK_ID], "title": row[s.PIECE_TITLE],
        "composer": row[s.PIECE_COMPOSER], "page": int(row[s.PIECE_PAGE]),
        "level": v.level_to_int(row[s.PIECE_LEVEL]), "exam": _null(row[s.PIECE_EXAM]),
        "period": v.PERIOD_CODES[row[s.PIECE_PERIOD]] if row[s.PIECE_PERIOD] else None,
        "style": v.STYLE_CODES[row[s.PIECE_STYLE]] if row[s.PIECE_STYLE] else None,
        "technique": _null(row[s.PIECE_TECHNIQUE]), "demo_url": _null(row[s.PIECE_AUDIO]),
        "notes": _null(row[s.PIECE_NOTES]),
    }


BOOK_FIELDS = ["book_id", "title", "series", "book_type", "location", "file_link", "notes"]
PIECE_FIELDS = ["piece_id", "book_id", "title", "composer", "page", "level", "exam", "period",
                "style", "technique", "demo_url", "notes"]


def insert_sql(table: str, fields: List[str]) -> str:
    return f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join(':' + f for f in fields)})"


def build_database(books_csv: Path, pieces_csv: Path, db_path: Path = DEFAULT_DB) -> Dict[str, int]:
    """Rebuild the database from CSV exports. Returns row counts."""
    books = [book_row(r) for r in _read(books_csv) if any(r.values())]
    # Exported piece sheets carry many formula-only rows; skip rows with no ID.
    pieces = [piece_row(r) for r in _read(pieces_csv) if r.get(s.PIECE_ID)]

    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=db_path.parent, suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        conn = sqlite3.connect(tmp)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA_SQL)
            with conn:  # one transaction for all rows
                conn.executemany(insert_sql("books", BOOK_FIELDS), books)
                conn.executemany(insert_sql("pieces", PIECE_FIELDS), pieces)
        finally:
            conn.close()
        os.replace(tmp, db_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return {"books": len(books), "pieces": len(pieces)}


async def _prepare(conn: aiosqlite.Connection) -> None:
    conn.row_factory = aiosqlite.Row
    await conn.create_function("fold", 1, fold, deterministic=True)


@asynccontextmanager
async def connect_readonly(db_path: Path = DEFAULT_DB) -> AsyncIterator[aiosqlite.Connection]:
    """Read-only connection for the agent's query tools."""
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} not found; run `python -m agent.build` first")
    conn = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        await _prepare(conn)
        await conn.execute("PRAGMA query_only = ON")  # second lock, in case mode=ro is ever dropped
        yield conn
    finally:
        await conn.close()


@asynccontextmanager
async def connect_writable(db_path: Path = DEFAULT_DB) -> AsyncIterator[aiosqlite.Connection]:
    """Writable connection. Used ONLY by the approved-onboarding write node."""
    conn = await aiosqlite.connect(db_path)
    try:
        await _prepare(conn)
        await conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        await conn.close()
