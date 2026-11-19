"""Run one eval case against the real graph and record an Observation.

DESIGN DECISIONS
- Isolation: every case gets its own copy of the SQLite database, so a write
  in one case can never leak into another, and the before/after diff is exact.
  Read-only cases share one copy of the Qdrant index. Cases that may write get
  their own copy, because an approved book is also upserted into Qdrant.
- The human is scripted. A case lists what the reviewer does at each interrupt
  (approve / reject with feedback). Any interrupt beyond the list is rejected,
  so an unexpected proposal can never write.
- Every non-onboarding case also gets NoWrites and RanWithoutError, and every
  case gets RanWithoutError. "Did nothing unsafe" is part of being correct.
- The model is injected (`model_factory`), so tests drive the harness with a
  scripted model and the real run uses Claude.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastembed import TextEmbedding
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from qdrant_client import AsyncQdrantClient

from agent import db, index
from agent import tools as t
from agent.evals.cases import Case
from agent.evals.checks import CheckResult, NoWrites, Observation, RanWithoutError, ToolEvent, Turn
from agent.graph import build_graph

MAX_INTERRUPTS = 3
RECURSION_LIMIT = 25


@dataclass
class CaseResult:
    case_id: str
    category: str
    split: str
    passed: bool
    checks: List[CheckResult]
    observation: Observation
    seconds: float
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    approvals_used: List[str] = field(default_factory=list)


def _snapshot(path: Path) -> Tuple[Dict[str, Tuple[Any, ...]], Dict[str, Tuple[Any, ...]]]:
    conn = sqlite3.connect(path)
    try:
        books = {r[0]: tuple(r) for r in conn.execute("SELECT * FROM books")}
        pieces = {r[0]: tuple(r) for r in conn.execute("SELECT * FROM pieces")}
    finally:
        conn.close()
    return books, pieces


def _rows_as_dicts(path: Path, table: str, ids: List[str]) -> List[Dict[str, Any]]:
    if not ids:
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    key = "book_id" if table == "books" else "piece_id"
    try:
        q = f"SELECT * FROM {table} WHERE {key} IN ({','.join('?' * len(ids))})"
        return [dict(r) for r in conn.execute(q, ids)]
    finally:
        conn.close()


def _decision(step: str, fingerprint: str) -> Dict[str, Any]:
    if step == "approve":
        return {"approve": True, "fingerprint": fingerprint}
    _, _, feedback = step.partition(":")
    return {"approve": False, "feedback": feedback} if feedback else {"approve": False}


class Harness:
    """Holds the shared, read-only resources for a whole eval run."""

    def __init__(self, embedder: TextEmbedding, model_factory: Callable[[], Optional[BaseChatModel]],
                 base_db: Path = db.DEFAULT_DB, base_qdrant: Path = index.QDRANT_PATH) -> None:
        self.embedder = embedder
        self.model_factory = model_factory
        self.base_db, self.base_qdrant = base_db, base_qdrant
        self.workdir = Path(tempfile.mkdtemp(prefix="piano-eval-"))
        self.shared_qdrant: Optional[AsyncQdrantClient] = None

    async def __aenter__(self) -> "Harness":
        shared = self.workdir / "qdrant-shared"
        shutil.copytree(self.base_qdrant, shared)
        self.shared_qdrant = AsyncQdrantClient(path=str(shared))
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.shared_qdrant is not None:
            await self.shared_qdrant.close()
        shutil.rmtree(self.workdir, ignore_errors=True)

    async def run(self, case: Case, tags: Optional[List[str]] = None) -> CaseResult:
        started = time.perf_counter()
        case_dir = self.workdir / f"{case.id}-{uuid.uuid4().hex[:6]}"
        case_dir.mkdir()
        db_path = case_dir / "catalog.db"
        shutil.copy(self.base_db, db_path)
        before_books, before_pieces = _snapshot(db_path)

        obs = Observation()
        usage = {"calls": 0, "in": 0, "out": 0}
        approvals_used: List[str] = []
        async with AsyncExitStack() as stack:
            qdrant = self.shared_qdrant
            if case.expects_write:  # private index copy: the approved book gets upserted
                private = case_dir / "qdrant"
                shutil.copytree(self.base_qdrant, private)
                qdrant = AsyncQdrantClient(path=str(private))
                stack.push_async_callback(qdrant.close)
            assert qdrant is not None
            res = t.Resources(db_path, qdrant, self.embedder)
            graph = build_graph(res, model=self.model_factory(), checkpointer=InMemorySaver())
            thread = f"eval-{case.id}-{uuid.uuid4().hex[:6]}"
            config: RunnableConfig = {
                "configurable": {"thread_id": thread}, "recursion_limit": RECURSION_LIMIT,
                "metadata": {"thread_id": thread, "case_id": case.id, "category": case.category},
                "tags": ["eval", case.split, *(tags or [])], "run_name": f"eval-{case.id}",
            }
            steps = list(case.approvals)
            try:
                for text in case.turns:
                    turn = Turn(user=text)
                    obs.turns.append(turn)
                    payload: Any = {"messages": [HumanMessage(text)]}
                    for _ in range(MAX_INTERRUPTS + 1):
                        await self._stream(graph, payload, config, turn, usage)
                        state = await graph.aget_state(config)
                        pending = [i for i in state.interrupts if isinstance(i.value, dict)]
                        if not pending:
                            break
                        value = pending[0].value
                        obs.proposals.append(value["proposal"])
                        step = steps.pop(0) if steps else "reject"
                        approvals_used.append(step)
                        payload = Command(resume=_decision(step, value["fingerprint"]))
                    else:
                        obs.error = f"more than {MAX_INTERRUPTS} proposals in one turn"
            except Exception as exc:  # recorded, scored as a failure; the run carries on
                obs.error = f"{type(exc).__name__}: {exc}"
                if "credit balance is too low" in str(exc):
                    raise  # every later case would fail the same way: stop the run

        after_books, after_pieces = _snapshot(db_path)
        new_book_ids = sorted(set(after_books) - set(before_books))
        new_piece_ids = sorted(set(after_pieces) - set(before_pieces))
        obs.new_books = _rows_as_dicts(db_path, "books", new_book_ids)
        obs.new_pieces = _rows_as_dicts(db_path, "pieces", new_piece_ids)
        obs.changed_rows = sum(before_books[k] != after_books.get(k) for k in before_books) + \
            sum(before_pieces[k] != after_pieces.get(k) for k in before_pieces)

        checks = [RanWithoutError(), *case.checks]
        if not case.expects_write:
            checks.append(NoWrites())
        results = [c(obs) for c in checks]
        return CaseResult(case.id, case.category, case.split, all(r.passed for r in results), results, obs,
                          round(time.perf_counter() - started, 2), usage["calls"], usage["in"], usage["out"],
                          approvals_used)

    @staticmethod
    async def _stream(graph: Any, payload: Any, config: RunnableConfig, turn: Turn, usage: Dict[str, int]) -> None:
        pending: Dict[str, ToolEvent] = {}
        async for update in graph.astream(payload, config, stream_mode="updates"):
            for delta in update.values():
                if not isinstance(delta, dict):
                    continue
                for msg in delta.get("messages", []):
                    if isinstance(msg, AIMessage):
                        u: Dict[str, Any] = dict(msg.usage_metadata or {})
                        usage["calls"] += 1 if u else 0
                        usage["in"] += u.get("input_tokens", 0)
                        usage["out"] += u.get("output_tokens", 0)
                        for c in msg.tool_calls:
                            event = ToolEvent(c["name"], dict(c["args"]))
                            pending[str(c["id"])] = event
                            turn.tools.append(event)
                        if not msg.tool_calls and msg.text.strip():
                            turn.answer = msg.text.strip()
                    elif isinstance(msg, ToolMessage):
                        found = pending.get(str(msg.tool_call_id))
                        if found is not None:
                            found.result = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                            found.status = msg.status
