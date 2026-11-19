"""Process-level setup shared by the CLI and the eval harness.

DESIGN DECISION: load the embedding model before the event loop starts. It is
slow, synchronous work (Part 0 #7 in the internal guide): doing it inside a
coroutine would block every other task on the loop.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from fastembed import TextEmbedding
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from qdrant_client import AsyncQdrantClient

from agent import db, index
from agent import tools as t
from tools import config

CHECKPOINT_DB = db.DATA_DIR / "checkpoints.db"


def load_settings() -> None:
    """Read .env (ANTHROPIC_API_KEY, LANGSMITH_*) without overriding the shell."""
    config.load_env()


def tracing_status() -> str:
    if os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and os.environ.get("LANGSMITH_API_KEY"):
        return f"LangSmith tracing on (project: {os.environ.get('LANGSMITH_PROJECT', 'default')})"
    return "LangSmith tracing off"


@asynccontextmanager
async def open_resources(
    embedder: TextEmbedding, db_path: Path = db.DEFAULT_DB, qdrant_path: Path = index.QDRANT_PATH
) -> AsyncIterator[t.Resources]:
    if not db_path.exists() or not qdrant_path.exists():
        raise SystemExit("Agent data not built yet: run `python -m agent.build` first.")
    qdrant = AsyncQdrantClient(path=str(qdrant_path))
    try:
        yield t.Resources(db_path, qdrant, embedder)
    finally:
        await qdrant.close()


@asynccontextmanager
async def open_checkpointer(path: Optional[Path] = CHECKPOINT_DB) -> AsyncIterator[AsyncSqliteSaver]:
    """Durable conversation state: threads survive a restart and can be resumed with --thread."""
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        yield saver
