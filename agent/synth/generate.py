"""Generate the synthetic demo catalogue in the spreadsheet's CSV export format.

Usage:
    python -m agent.synth.generate [--seed 2026] [--out sample/demo]

DESIGN DECISIONS
- Output uses the exact layout teachers export from Google Sheets (Chinese
  headers and dropdown labels). The agent's ETL therefore exercises the same
  path real data would take, and tools/validate_catalog.py can check the result.
- A fixed seed makes the output reproducible. The eval set's expected answers
  are derived from this data, so regenerating with the same seed must not
  change them. tests/test_agent_data.py pins this.
- No images are involved: the agent only reads tabular data and docs.
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agent import vocab as v
from agent.synth.repertoire import BOOKS, BookSpec, PieceSpec
from tools import schema as s

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "sample" / "demo"
DEFAULT_SEED = 2026
BOOKS_PER_SHELF = 6

TECHNIQUE_POOL: Dict[v.Style, List[str]] = {
    "etude": ["scales", "broken chords", "arpeggios", "repeated notes", "staccato", "legato",
              "finger independence", "fast passages", "octaves", "trills", "left-hand agility"],
    "character_piece": ["cantabile melody", "pedalling", "voicing", "rubato", "legato",
                        "dynamic control", "phrasing", "chords"],
    "dance": ["waltz accompaniment", "dotted rhythm", "staccato", "rubato", "left-hand leaps", "phrasing"],
    "sonata": ["Alberti bass", "scales", "phrasing", "articulation", "dynamic contrast"],
    "variations": ["ornaments", "scales", "articulation", "character contrast"],
    "duet": ["ensemble timing", "counting", "balance between parts"],
    "pop_arrangement": ["counting", "hand position", "simple chords"],
}

Row = Dict[str, str]


@dataclass(frozen=True)
class Traits:
    """Properties of a piece itself, shared by every copy in every book."""
    level: Optional[int]
    period: Optional[v.Period]
    style: v.Style
    technique: str


def cabinet(book: BookSpec) -> str:
    if book.book_type in ("method", "etudes"):
        return "A"
    if book.book_type in ("single", "exam") or book.style == "duet":
        return "C"
    return "B"


def book_level(book: BookSpec, piece: PieceSpec, index: int) -> Optional[int]:
    """Explicit piece level wins; otherwise spread the book's range in printed order."""
    if piece.level is not None:
        return piece.level
    if book.levels is None:
        return None
    lo, hi = book.levels
    return lo + (index * (hi - lo + 1)) // len(book.pieces)


def generate(seed: int = DEFAULT_SEED) -> Tuple[List[Row], List[Row]]:
    rng = random.Random(seed)
    period_label = v.reverse(v.PERIOD_CODES)
    style_label = v.reverse(v.STYLE_CODES)
    type_label = v.reverse(v.BOOK_TYPE_CODES)

    canonical: Dict[Tuple[str, str], Traits] = {}
    shelf_slots: Dict[str, int] = {}
    books: List[Row] = []
    pieces: List[Row] = []

    for b_index, book in enumerate(BOOKS, start=1):
        book_id = s.book_id(b_index)
        location, link = "", ""
        if book.pdf:
            link = f"https://example.com/drive/{book_id}.pdf"  # placeholder; never a real Drive link
        else:
            cab = cabinet(book)
            slot = shelf_slots.get(cab, 0)
            shelf_slots[cab] = slot + 1
            location = f"{cab}-{slot // BOOKS_PER_SHELF + 1}-{slot % BOOKS_PER_SHELF + 1:02d}"
        books.append({
            s.BOOK_ID: book_id, s.BOOK_TITLE: book.title, s.BOOK_SERIES: book.series,
            s.BOOK_TYPE: type_label[book.book_type], s.BOOK_LOCATION: location,
            s.BOOK_LINK: link, s.BOOK_NOTES: book.notes,
        })

        page = rng.randint(2, 5)
        for p_index, piece in enumerate(book.pieces):
            key = (piece.title, piece.composer)
            level = book_level(book, piece, p_index)
            if key in canonical:
                # Same piece in a second book (graded compilations): keep traits identical.
                traits = canonical[key]
                if level != traits.level:
                    raise ValueError(f"{piece.title!r} is level {traits.level} in its first book but {level} "
                                     f"in {book.title!r}; a piece has one level (set it in repertoire.py)")
            else:
                style = piece.style or book.style
                technique = piece.technique or ", ".join(
                    rng.sample(TECHNIQUE_POOL[style], k=rng.choice([1, 2])))
                traits = Traits(level, book.period, style, technique)
                canonical[key] = traits

            piece_id = s.piece_id(len(pieces) + 1)
            has_demo = rng.random() < 0.15
            pieces.append({
                s.PIECE_ID: piece_id, s.PIECE_BOOK_ID: book_id, s.PIECE_TITLE: piece.title,
                s.PIECE_COMPOSER: piece.composer, s.PIECE_PAGE: str(page),
                s.PIECE_LEVEL: v.int_to_level(level) if level else "", s.PIECE_EXAM: "",
                s.PIECE_PERIOD: period_label[traits.period] if traits.period else "",
                s.PIECE_STYLE: style_label[traits.style], s.PIECE_TECHNIQUE: traits.technique,
                s.PIECE_AUDIO: f"https://example.com/demo/{piece_id}.mp3" if has_demo else "",
                s.PIECE_NOTES: "",
                # Derived columns, as the spreadsheet formulas would show them.
                s.PIECE_BOOK_TITLE: book.title, s.PIECE_BOOK_LOCATION: location,
            })
            page += rng.randint(1, 2 + (level or 2) // 2)
    return books, pieces


def write_csv(path: Path, columns: List[str], rows: List[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_options(path: Path) -> None:
    fields = list(s.VOCAB)
    depth = max(len(values) for values in s.VOCAB.values())
    rows = [{f: (s.VOCAB[f][i] if i < len(s.VOCAB[f]) else "") for f in fields} for i in range(depth)]
    write_csv(path, fields, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic demo catalogue.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    books, pieces = generate(args.seed)
    write_csv(args.out / "books.csv", s.BOOK_COLUMNS, books)
    write_csv(args.out / "pieces.csv", s.PIECE_COLUMNS, pieces)
    write_options(args.out / "options.csv")
    print(f"Wrote {len(books)} books and {len(pieces)} pieces to {args.out}/")


if __name__ == "__main__":
    main()
