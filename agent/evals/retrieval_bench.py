"""Benchmark embedding models for semantic piece search (no LLM, no Qdrant).

Usage:
    python -m agent.evals.retrieval_bench [--models A B ...]

Each query has a relevance rule over the catalogue's structured fields, so
"relevant" is defined by the data, not by eyeballing results. The metric is
normalised precision@5: hits in the top 5 distinct pieces divided by
min(5, number of relevant pieces). Plain P@5 would cap a query with only one
relevant piece ("Christmas song") at 0.2 and make every model look bad on it.

This exists so that the choice of embedding model and of the text being
embedded is backed by a number. See notes/ for the results that informed
index.EMBED_MODEL.
"""

from __future__ import annotations

import argparse
import sqlite3
from typing import Any, Callable, Dict, List, Sequence, Tuple

import numpy as np
from fastembed import TextEmbedding

from agent import db, index

Piece = Dict[str, Any]
Rule = Callable[[Piece], bool]


def tech(word: str) -> Rule:
    return lambda p: word in (p["technique"] or "")


QUERIES: List[Tuple[str, Rule]] = [
    ("pieces to practise staccato", tech("staccato")),
    ("練習斷奏的曲子", tech("staccato")),
    ("a piece for two pianists", lambda p: p["style"] == "duet"),
    ("four-hand duet for a student and teacher", lambda p: p["style"] == "duet"),
    ("something dreamy and impressionistic", lambda p: p["composer"] in ("Debussy", "Satie")),
    ("lyrical melody in the left hand", tech("left-hand melody")),
    ("pieces that work on pedalling", tech("pedalling")),
    ("baroque dance", lambda p: p["period"] == "baroque" and p["style"] == "dance"),
    ("ragtime with syncopation", lambda p: p["composer"] == "Joplin" or "syncopation" in (p["technique"] or "")),
    ("theme and variations", lambda p: p["style"] == "variations"),
    ("Christmas song for a beginner", lambda p: "Jingle" in p["title"]),
    ("waltz", lambda p: "Waltz" in p["title"] or "waltz" in (p["technique"] or "")),
]

# Candidate texts to embed for each piece.
def text_title_first(p: Piece) -> str:
    """The first version of index.piece_text, kept as the baseline."""
    parts = [f"{p['title']} by {p['composer']}"]
    if p.get("style"):
        parts.append(f"style: {str(p['style']).replace('_', ' ')}")
    if p.get("period"):
        parts.append(f"period: {p['period']}")
    if p.get("technique"):
        parts.append(f"technique: {p['technique']}")
    parts.append(f"book: {p['book_title']}")
    return ". ".join(parts)


def text_attributes_first(p: Piece) -> str:
    return index.piece_text(p)  # the production text


TEXTS: Dict[str, Callable[[Piece], str]] = {"title_first": text_title_first, "attributes_first": text_attributes_first}
DEFAULT_MODELS = [
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    "BAAI/bge-small-en-v1.5",
    "BAAI/bge-base-en-v1.5",
]


def load_pieces() -> List[Piece]:
    conn = sqlite3.connect(db.DEFAULT_DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM catalogue ORDER BY piece_id")]
    finally:
        conn.close()


def precision_at_k(model: TextEmbedding, pieces: Sequence[Piece], make_text: Callable[[Piece], str],
                   k: int = 5) -> Tuple[float, List[float]]:
    # Embed each distinct piece once, so reprinted copies don't count twice.
    distinct: Dict[Tuple[str, str], Piece] = {}
    for p in pieces:
        distinct.setdefault((p["title"], p["composer"]), p)
    items = list(distinct.values())
    docs = np.asarray(list(model.embed([make_text(p) for p in items])), dtype=np.float32)
    docs /= np.linalg.norm(docs, axis=1, keepdims=True)
    per_query = []
    for query, rule in QUERIES:
        q = np.asarray(next(iter(model.query_embed(query))), dtype=np.float32)
        q /= np.linalg.norm(q)
        top = np.argsort(-docs @ q)[:k]
        relevant = sum(rule(p) for p in items)
        per_query.append(sum(rule(items[i]) for i in top) / min(k, relevant))
    return float(np.mean(per_query)), per_query


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    args = parser.parse_args()
    pieces = load_pieces()
    print(f"{len(QUERIES)} queries, normalised precision@5\n")
    print(f"{'model':62} {'text':17} {'P@5':>5}   per query")
    for name in args.models:
        model = TextEmbedding(name, cache_dir=str(index.MODEL_CACHE))
        for text_name, make_text in TEXTS.items():
            mean, per = precision_at_k(model, pieces, make_text)
            print(f"{name:62} {text_name:17} {mean:5.2f}   {' '.join(f'{x:.1f}' for x in per)}")


if __name__ == "__main__":
    main()
