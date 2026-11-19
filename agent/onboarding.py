"""Onboarding a new book: validate a proposal, then write it after human approval.

The LLM can only *propose* (the propose_new_book tool). This module turns a
proposal into concrete rows, checks them, and later writes them. graph.py
decides when writing is allowed.

DESIGN DECISIONS
- IDs are assigned here, never by the model. The model can't pick B0001 and
  overwrite a book, and IDs stay sequential as the studio's rules require.
- Two kinds of finding. Errors block the proposal and go back to the model,
  so it can ask the user. Warnings ride along to the human reviewer (possible
  duplicate book, pieces without a level).
- prepare() is pure and deterministic given the database. That matters because
  LangGraph re-runs the review node from the top when the human answers the
  interrupt; prepare() must produce the same proposal both times.
- Approve exactly what was shown. The interrupt carries a fingerprint of the
  prepared rows, and an approval must echo it back. On resume, prepare() runs
  again; if the catalogue changed meanwhile, it can assign different IDs. The
  fingerprint then differs and nothing is written. (Found by
  test_catalogue_change_during_review_blocks_the_write. Without the
  fingerprint, the human approved B0032 and the code saved B0033.)
- write() re-checks inside a BEGIN IMMEDIATE transaction. Between "shown to the
  human" and "approved" the catalogue could change; if the IDs or the location
  are no longer free, the write is refused rather than clobbering anything.
- SQLite is the source of truth; the Qdrant index is derived. SQLite is
  committed first. If indexing fails afterwards, the book is saved but not
  yet semantically searchable, and `python -m agent.build --reindex` repairs it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient
from fastembed import TextEmbedding

from agent import db, index
from agent.vocab import BookType, Period, Style
from tools import schema as s


class NewPiece(BaseModel):
    title: str = Field(min_length=1, description="Title as printed, original language, with opus/number")
    composer: str = Field(min_length=1)
    page: int = Field(ge=1, description="Start page")
    level: Optional[int] = Field(default=None, ge=1, le=8, description="Studio level 1-8, if the user gave one")
    period: Optional[Period] = None
    style: Optional[Style] = None
    technique: Optional[str] = Field(default=None, description="Short technical focus, e.g. 'staccato, scales'")


class BookProposal(BaseModel):
    """Arguments of the propose_new_book tool."""
    title: str = Field(min_length=1, description="Book title as on the cover")
    book_type: BookType
    location: Optional[str] = Field(default=None, description="Shelf location like A-2-05; omit for PDFs")
    file_link: Optional[str] = Field(default=None, description="Link to the PDF; omit for paper books")
    series: Optional[str] = Field(default=None, description="Series or publisher")
    pieces: List[NewPiece] = Field(default_factory=list, description="Pieces in printed order")


class PreparedBook(TypedDict):
    book: Dict[str, Any]
    pieces: List[Dict[str, Any]]
    errors: List[str]
    warnings: List[str]


def _next_id(existing: List[str], prefix_len: int) -> int:
    numbers = [int(x[prefix_len:]) for x in existing if x[prefix_len:].isdigit()]
    return max(numbers, default=0) + 1


async def prepare(db_path: Path, proposal: BookProposal) -> PreparedBook:
    errors: List[str] = []
    warnings: List[str] = []
    location = (proposal.location or "").strip() or None
    file_link = (proposal.file_link or "").strip() or None

    if not location and not file_link:
        errors.append("a book needs a shelf location (e.g. A-2-05) or a file link")
    if location and not s.LOCATION_PATTERN.match(location):
        errors.append(f"location {location!r} must look like A-2-05")
    if not proposal.pieces:
        warnings.append("no pieces listed: the book will be catalogued at book level only")

    seen: Dict[tuple[str, str], int] = {}
    for i, p in enumerate(proposal.pieces, start=1):
        key = (db.fold(p.title) or "", db.fold(p.composer) or "")
        if key in seen:
            errors.append(f"piece {i} repeats piece {seen[key]} ({p.title})")
        seen.setdefault(key, i)
    unlevelled = sum(p.level is None for p in proposal.pieces)
    if unlevelled:
        warnings.append(f"{unlevelled} piece(s) have no level yet")

    async with db.connect_readonly(db_path) as conn:
        async with conn.execute("SELECT book_id FROM books") as cur:
            book_ids = [r[0] for r in await cur.fetchall()]
        async with conn.execute("SELECT piece_id FROM pieces") as cur:
            piece_ids = [r[0] for r in await cur.fetchall()]
        if location:
            async with conn.execute("SELECT book_id, title FROM books WHERE location = ?", [location]) as cur:
                taken = await cur.fetchone()
            if taken:
                errors.append(f"location {location} is already used by {taken[0]} ({taken[1]})")
        async with conn.execute(
            "SELECT book_id, title FROM books WHERE fold(title) = fold(?)", [proposal.title]
        ) as cur:
            same_title = await cur.fetchone()
        if same_title:
            warnings.append(f"a book with this title already exists: {same_title[0]} ({same_title[1]})")

    book_id = s.book_id(_next_id(book_ids, 1))
    first_piece = _next_id(piece_ids, 1)
    book = {"book_id": book_id, "title": proposal.title.strip(), "series": proposal.series,
            "book_type": proposal.book_type, "location": location, "file_link": file_link, "notes": None}
    pieces = [
        {"piece_id": s.piece_id(first_piece + i), "book_id": book_id, "title": p.title.strip(),
         "composer": p.composer.strip(), "page": p.page, "level": p.level, "exam": None,
         "period": p.period, "style": p.style, "technique": p.technique, "demo_url": None, "notes": None}
        for i, p in enumerate(proposal.pieces)
    ]
    return PreparedBook(book=book, pieces=pieces, errors=errors, warnings=warnings)


def fingerprint(prepared: PreparedBook) -> str:
    """Hash of exactly the rows that would be written."""
    payload = json.dumps({"book": prepared["book"], "pieces": prepared["pieces"]}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class WriteResult(TypedDict):
    saved: bool
    book_id: str
    piece_ids: List[str]
    indexed: bool
    message: str


async def write(
    db_path: Path, prepared: PreparedBook, qdrant: Optional[AsyncQdrantClient], embedder: Optional[TextEmbedding]
) -> WriteResult:
    book, pieces = prepared["book"], prepared["pieces"]
    ids = [p["piece_id"] for p in pieces]
    async with db.connect_writable(db_path) as conn:
        await conn.execute("BEGIN IMMEDIATE")  # take the write lock before re-checking
        try:
            clash = await (await conn.execute(
                f"SELECT 1 FROM books WHERE book_id = ? OR (location IS NOT NULL AND location = ?) "
                f"UNION ALL SELECT 1 FROM pieces WHERE piece_id IN ({','.join('?' * len(ids)) or 'NULL'})",
                [book["book_id"], book["location"], *ids],
            )).fetchone()
            if clash:
                await conn.rollback()
                return WriteResult(saved=False, book_id=book["book_id"], piece_ids=[], indexed=False,
                                   message="The catalogue changed since this proposal was reviewed; nothing was "
                                           "saved. Propose the book again.")
            await conn.execute(db.insert_sql("books", db.BOOK_FIELDS), book)
            await conn.executemany(db.insert_sql("pieces", db.PIECE_FIELDS), pieces)
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise

    indexed = False
    if qdrant is not None and embedder is not None and pieces:
        try:
            rows = [p | {"book_title": book["title"], "book_type": book["book_type"],
                         "location": book["location"], "file_link": book["file_link"]} for p in pieces]
            points = await asyncio.to_thread(index.piece_points, embedder, rows)
            await qdrant.upsert(index.PIECES, points)
            indexed = True
        except Exception:  # saved in SQLite already; report, don't pretend
            indexed = False
    elif not pieces:
        indexed = True  # nothing to index

    note = "" if indexed else " It is not in semantic search yet; run `python -m agent.build --reindex`."
    return WriteResult(saved=True, book_id=book["book_id"], piece_ids=ids, indexed=indexed,
                       message=f"Saved {book['book_id']} ({book['title']}) with {len(pieces)} piece(s).{note}")
