"""The agent's four read-only tools, as plain async functions.

They have no LangChain dependency: graph.py wraps them as LLM tools. Keeping
them plain means unit tests can call them directly, with no model involved.

DESIGN DECISIONS
- Two SQL tools on purpose:
  * search_pieces: structured filters with typed arguments. Reliable, and it
    covers about 90% of teacher questions. The tool schema rules out invalid
    values (period must be one of six codes).
  * run_readonly_sql: free-form SELECT for questions the filters can't express
    ("which composer has the most pieces at level 5?"). More powerful and
    riskier, so it sits behind three layers: a statement check, a `mode=ro`
    connection, and PRAGMA query_only. A step budget stops runaway queries.
- Tools return errors as data ({"error": ...}) instead of raising. The model
  sees the message and can correct its next call, and the graph doesn't crash.
- Every result says how many rows matched in total. The model can then tell
  the user "showing 20 of 57" rather than presenting a truncated list as complete.
- Semantic hits are de-duplicated by (title, composer). Graded compilations
  reprint pieces, and without this one piece could fill several top-k slots.
  Other copies are kept in `also_in`, so no location is lost.
- Embedding is CPU-bound and synchronous (fastembed), so it runs in
  asyncio.to_thread and never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict, cast

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient, models

from agent import db
from agent.index import DOCS, PIECES
from agent.vocab import LEVEL_MAX, LEVEL_MIN, Period, Style

MAX_RESULTS = 20
SQL_MAX_ROWS = 50
SQL_STEP_BUDGET = 2_000_000   # SQLite VM instructions; the catalogue's real queries need far fewer


class PieceRecord(TypedDict):
    piece_id: str
    title: str
    composer: str
    book_id: str
    book_title: str
    page: int
    location: Optional[str]
    file_link: Optional[str]
    level: Optional[int]
    period: Optional[str]
    style: Optional[str]
    technique: Optional[str]
    demo_url: Optional[str]


class PieceSearchResult(TypedDict):
    total: int
    results: List[PieceRecord]


class Copy(TypedDict):
    book_id: str
    book_title: str
    page: int
    location: Optional[str]
    file_link: Optional[str]


class ScoredPiece(PieceRecord):
    score: float
    also_in: List[Copy]   # the same piece printed in other books


class DocHit(TypedDict):
    source: str
    heading: str
    text: str
    score: float


@dataclass
class Resources:
    """Everything the tools need, created once per process and shared."""
    db_path: Path
    qdrant: AsyncQdrantClient
    embedder: TextEmbedding

    async def embed(self, text: str) -> List[float]:
        vectors = await asyncio.to_thread(lambda: list(self.embedder.query_embed(text)))
        return [float(x) for x in vectors[0]]


RECORD_COLUMNS = list(PieceRecord.__annotations__)


def _record(row: Any) -> PieceRecord:
    return cast(PieceRecord, {k: row[k] for k in RECORD_COLUMNS})


def _check_level(value: Optional[int], name: str) -> Optional[str]:
    if value is not None and not LEVEL_MIN <= value <= LEVEL_MAX:
        return f"{name} must be between {LEVEL_MIN} and {LEVEL_MAX}"
    return None


async def search_pieces(
    res: Resources,
    *,
    title: Optional[str] = None,
    composer: Optional[str] = None,
    book_title: Optional[str] = None,
    level_min: Optional[int] = None,
    level_max: Optional[int] = None,
    period: Optional[Period] = None,
    style: Optional[Style] = None,
    has_demo: Optional[bool] = None,
    limit: int = MAX_RESULTS,
) -> PieceSearchResult | Dict[str, str]:
    """Structured search. Text filters are case-, accent- and substring-insensitive."""
    for value, name in ((level_min, "level_min"), (level_max, "level_max")):
        if (problem := _check_level(value, name)):
            return {"error": problem}
    where: List[str] = []
    params: List[Any] = []
    for column, text in (("title", title), ("composer", composer), ("book_title", book_title)):
        if text:
            where.append(f"fold({column}) LIKE '%' || fold(?) || '%'")
            params.append(text)
    if level_min is not None:
        where.append("level >= ?")
        params.append(level_min)
    if level_max is not None:
        where.append("level <= ?")
        params.append(level_max)
    if period:
        where.append("period = ?")
        params.append(period)
    if style:
        where.append("style = ?")
        params.append(style)
    if has_demo is not None:
        where.append("demo_url IS NOT NULL" if has_demo else "demo_url IS NULL")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    limit = max(1, min(limit, MAX_RESULTS))

    async with db.connect_readonly(res.db_path) as conn:
        async with conn.execute(f"SELECT COUNT(*) FROM catalogue {clause}", params) as cur:
            count_row = await cur.fetchone()
        total = int(count_row[0]) if count_row else 0
        async with conn.execute(
            f"SELECT * FROM catalogue {clause} ORDER BY level IS NULL, level, piece_id LIMIT ?",
            [*params, limit],
        ) as cur:
            rows = await cur.fetchall()
    return PieceSearchResult(total=total, results=[_record(r) for r in rows])


_SQL_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def check_sql(query: str) -> Optional[str]:
    """Return a reason to refuse, or None. The connection is read-only regardless; this is the first layer."""
    stripped = query.strip().rstrip(";").strip()
    if not stripped:
        return "empty query"
    if ";" in stripped:
        return "only one statement is allowed"
    if not _SQL_START.match(stripped):
        return "only SELECT queries are allowed; the catalogue is read-only for this tool"
    return None


async def run_readonly_sql(res: Resources, query: str) -> Dict[str, Any]:
    """Run one SELECT against the catalogue. Returns columns, rows (max 50) and a truncated flag."""
    if (problem := check_sql(query)):
        return {"error": problem}
    steps = 0

    def budget() -> int:
        nonlocal steps
        steps += 1
        return 1 if steps > SQL_STEP_BUDGET // 1000 else 0  # non-zero aborts the query

    try:
        async with db.connect_readonly(res.db_path) as conn:
            await conn.set_progress_handler(budget, 1000)
            async with conn.execute(query.strip().rstrip(";")) as cur:
                rows = list(await cur.fetchmany(SQL_MAX_ROWS + 1))
                columns = [d[0] for d in cur.description or []]
    except Exception as exc:  # sqlite3.Error and friends: report, let the model retry
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "columns": columns,
        "rows": [list(r) for r in rows[:SQL_MAX_ROWS]],
        "truncated": len(rows) > SQL_MAX_ROWS,
    }


def _piece_filter(
    level_min: Optional[int], level_max: Optional[int], period: Optional[Period], style: Optional[Style]
) -> Optional[models.Filter]:
    must: List[models.Condition] = []
    if level_min is not None or level_max is not None:
        must.append(models.FieldCondition(key="level", range=models.Range(gte=level_min, lte=level_max)))
    if period:
        must.append(models.FieldCondition(key="period", match=models.MatchValue(value=period)))
    if style:
        must.append(models.FieldCondition(key="style", match=models.MatchValue(value=style)))
    return models.Filter(must=must) if must else None


async def semantic_search_pieces(
    res: Resources,
    query: str,
    *,
    level_min: Optional[int] = None,
    level_max: Optional[int] = None,
    period: Optional[Period] = None,
    style: Optional[Style] = None,
    limit: int = 8,
) -> List[ScoredPiece] | Dict[str, str]:
    """Meaning-based search over style, technique, period, title and composer.

    `query` should be in English: the embedding model is English-only (see index.py).
    """
    for value, name in ((level_min, "level_min"), (level_max, "level_max")):
        if (problem := _check_level(value, name)):
            return {"error": problem}
    limit = max(1, min(limit, MAX_RESULTS))
    vector = await res.embed(query)
    response = await res.qdrant.query_points(
        PIECES, query=vector, query_filter=_piece_filter(level_min, level_max, period, style),
        limit=limit * 3, with_payload=True,   # over-fetch: duplicates collapse below
    )
    out: Dict[Tuple[str, str], ScoredPiece] = {}
    for point in response.points:
        payload = point.payload or {}
        key = (str(payload.get("title")), str(payload.get("composer")))
        if key in out:
            out[key]["also_in"].append(cast(Copy, {k: payload.get(k) for k in Copy.__annotations__}))
        elif len(out) < limit:
            hit = {k: payload.get(k) for k in RECORD_COLUMNS} | {"score": round(point.score, 4), "also_in": []}
            out[key] = cast(ScoredPiece, hit)
    return list(out.values())


async def search_docs(res: Resources, query: str, *, limit: int = 4) -> List[DocHit]:
    """RAG retrieval over the studio's manuals (docs/*.md)."""
    vector = await res.embed(query)
    response = await res.qdrant.query_points(DOCS, query=vector, limit=max(1, min(limit, 8)), with_payload=True)
    return [
        DocHit(source=str(p.payload["source"]), heading=str(p.payload["heading"]),
               text=str(p.payload["text"]), score=round(p.score, 4))
        for p in response.points if p.payload
    ]
