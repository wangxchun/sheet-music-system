"""Build the agent's local data: validate the CSVs, load SQLite, index Qdrant.

Usage:
    python -m agent.build [--books sample/demo/books.csv] [--pieces sample/demo/pieces.csv]
                          [--options sample/demo/options.csv]
    python -m agent.build --reindex     # rebuild Qdrant from SQLite only

A full build reloads SQLite from the CSVs, so books added through the agent's
onboarding flow are dropped (the CSVs remain the demo's source data). --reindex
keeps SQLite as it is and only rebuilds the derived vector index.

DESIGN DECISION: the existing validator (tools/validate_catalog.py) is a hard
gate. The agent never loads data that the studio's own checks would reject.
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from agent import db, index

VALIDATOR = db.ROOT / "tools" / "validate_catalog.py"


def validate(books: Path, pieces: Path, options: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(books), str(pieces), str(options)],
        capture_output=True, text=True,
    )
    summary = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    print(f"validate: {summary}")
    if result.returncode != 0:
        sys.exit(f"Validation failed; fix the CSVs first.\n{result.stdout}")


def load_catalogue_rows(db_path: Path) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM catalogue ORDER BY piece_id")]
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the agent's SQLite database and Qdrant index.")
    parser.add_argument("--books", type=Path, default=db.DEMO_DIR / "books.csv")
    parser.add_argument("--pieces", type=Path, default=db.DEMO_DIR / "pieces.csv")
    parser.add_argument("--options", type=Path, default=db.DEMO_DIR / "options.csv")
    parser.add_argument("--db", type=Path, default=db.DEFAULT_DB)
    parser.add_argument("--reindex", action="store_true", help="rebuild only the Qdrant index from SQLite")
    args = parser.parse_args()

    if not args.reindex:
        validate(args.books, args.pieces, args.options)
        counts = db.build_database(args.books, args.pieces, args.db)
        print(f"sqlite:   {counts['books']} books, {counts['pieces']} pieces -> {args.db}")
    stats = index.build_index(load_catalogue_rows(args.db), index.doc_chunks())
    print(f"qdrant:   {stats['pieces']} pieces, {stats['doc_chunks']} doc chunks -> {index.QDRANT_PATH}")


if __name__ == "__main__":
    main()
