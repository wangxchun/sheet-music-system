"""Qdrant vector index: one collection for pieces, one for documentation chunks.

DESIGN DECISIONS
- Qdrant in local (embedded) mode: no server or Docker. The same client code
  works against a Qdrant server by changing the constructor to a URL.
- Embedding model and embedded text were chosen by a benchmark, not by
  default (agent/evals/retrieval_bench.py, 12 queries, normalised P@5):
      multilingual MiniLM, title first       0.29   (first version)
      multilingual MiniLM, attributes first  0.59
      bge-base-en-v1.5, title first          0.53
      bge-base-en-v1.5, attributes first     0.88   <- chosen (with STYLE_GLOSS)
  Two findings. Putting style/technique before the title mattered more than
  the model. No model handled a Chinese query, so the tool contract asks the
  LLM to pass English queries (it translates; see graph.py). fastembed runs it
  on CPU locally, with no API cost per query.
- Piece points carry their display fields (book, page, location) in the
  payload. A semantic hit is therefore a complete answer, with no second SQL
  round-trip, and level/period/style can be filtered inside Qdrant.
- Docs are chunked by Markdown heading. A chunk is one answerable section
  ("2.2 Add a dropdown option") and keeps its heading for citation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

from agent.db import DATA_DIR, ROOT

EMBED_MODEL = "BAAI/bge-base-en-v1.5"
EMBED_DIM = 768
MODEL_CACHE = DATA_DIR / "models"
QDRANT_PATH = DATA_DIR / "qdrant"
PIECES = "pieces"
DOCS = "docs"
DOC_FILES = sorted((ROOT / "docs").glob("*.md"))
MAX_CHUNK_CHARS = 1500


def load_embedder() -> TextEmbedding:
    return TextEmbedding(EMBED_MODEL, cache_dir=str(MODEL_CACHE))


STYLE_GLOSS = {"duet": "piano duet, four hands, two players", "character_piece": "character piece"}


def piece_text(p: Dict[str, Any]) -> str:
    """What the embedding 'sees' for a piece, attributes first.

    Location and page are left out on purpose: they carry no meaning. The duet
    gloss was added after the benchmark showed "two pianists" missing every duet.
    It is a fix tuned on the benchmark itself, so the end-to-end eval's held-out
    test set is the real check.
    """
    style = str(p.get("style") or "")
    style_text = STYLE_GLOSS.get(style, style.replace("_", " "))
    return (f"{style_text}; technique: {p.get('technique') or 'none'}; period: {p.get('period') or 'unknown'}; "
            f"{p['title']} by {p['composer']}; book: {p['book_title']}")


def piece_point_id(piece_id: str) -> int:
    return int(piece_id[1:])  # P00042 -> 42; stable, so re-indexing overwrites, never duplicates


@dataclass(frozen=True)
class DocChunk:
    source: str
    heading: str
    text: str


def chunk_markdown(source: str, markdown: str) -> List[DocChunk]:
    """Split on ## / ### headings; split oversized sections on blank lines."""
    chunks: List[DocChunk] = []
    title = ""
    heading = ""
    buffer: List[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if not body:
            return
        label = f"{title} > {heading}" if heading else title
        for piece in _split_long(body):
            chunks.append(DocChunk(source, label, piece))

    for line in markdown.splitlines():
        match = re.match(r"^(#{1,3}) (.+)$", line)
        if match:
            flush()
            buffer = []
            if len(match.group(1)) == 1:
                title, heading = match.group(2), ""
            else:
                heading = match.group(2)
            continue
        buffer.append(line)
    flush()
    return chunks


def _split_long(text: str) -> List[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    out: List[str] = []
    current = ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) > MAX_CHUNK_CHARS:
            out.append(current.strip())
            current = ""
        current += para + "\n\n"
    if current.strip():
        out.append(current.strip())
    return out


def doc_chunks(files: Sequence[Path] = DOC_FILES) -> List[DocChunk]:
    chunks: List[DocChunk] = []
    for path in files:
        chunks.extend(chunk_markdown(f"docs/{path.name}", path.read_text(encoding="utf-8")))
    return chunks


def _recreate(client: QdrantClient, name: str) -> None:
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(
        name, vectors_config=models.VectorParams(size=EMBED_DIM, distance=models.Distance.COSINE)
    )


def piece_points(embedder: TextEmbedding, pieces: Sequence[Dict[str, Any]]) -> List[models.PointStruct]:
    vectors = embedder.embed([piece_text(p) for p in pieces])
    return [
        models.PointStruct(id=piece_point_id(str(p["piece_id"])), vector=vec.tolist(), payload=dict(p))
        for p, vec in zip(pieces, vectors)
    ]


def build_index(
    pieces: Sequence[Dict[str, Any]],
    chunks: Iterable[DocChunk],
    path: Path = QDRANT_PATH,
    embedder: Optional[TextEmbedding] = None,
) -> Dict[str, int]:
    embedder = embedder or load_embedder()
    chunk_list = list(chunks)
    client = QdrantClient(path=str(path))
    try:
        _recreate(client, PIECES)
        client.upsert(PIECES, piece_points(embedder, pieces))
        # No create_payload_index here: local mode ignores payload indexes and
        # filters by scanning, which is fine at 300 points. On a Qdrant server,
        # add indexes on level/period/style so filtered search stays fast at scale.

        _recreate(client, DOCS)
        doc_vectors = embedder.embed([f"{c.heading}\n{c.text}" for c in chunk_list])
        client.upsert(DOCS, [
            models.PointStruct(id=i, vector=vec.tolist(),
                               payload={"source": c.source, "heading": c.heading, "text": c.text})
            for i, (c, vec) in enumerate(zip(chunk_list, doc_vectors))
        ])
    finally:
        client.close()
    return {"pieces": len(pieces), "doc_chunks": len(chunk_list)}
