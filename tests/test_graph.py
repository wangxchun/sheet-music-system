"""Tests for the LangGraph agent and its human-approval gate. No LLM calls.

A scripted chat model returns pre-written AI messages (including tool calls),
so the graph's control flow is tested deterministically: which node runs,
what is written, and what is not.
"""

import asyncio
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HAS_DEPS = all(importlib.util.find_spec(m) for m in ("langgraph", "langchain_anthropic", "aiosqlite", "qdrant_client"))

if HAS_DEPS:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agent import db
    from agent import tools as t
    from agent.graph import PROPOSE_TOOL, build_graph

    sys.path.insert(0, str(ROOT / "tests"))
    from scripted import ScriptedModel

DEMO = ROOT / "sample" / "demo"


def call(name, args, cid="c1"):
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


NEW_BOOK = {
    "title": "Heller: 25 Melodious Studies, Op. 45",
    "book_type": "etudes",
    "location": "A-1-06",
    "pieces": [
        {"title": "Study No. 1 (Op. 45)", "composer": "Heller", "page": 2, "level": 4},
        {"title": "Study No. 2 (Op. 45)", "composer": "Heller", "page": 4},
    ],
}


@unittest.skipUnless(HAS_DEPS, "agent dependencies not installed")
class GraphTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "c.db"
        db.build_database(DEMO / "books.csv", DEMO / "pieces.csv", self.db_path)
        # No Qdrant/embedder: these tests cover SQL tools and the write gate.
        self.res = t.Resources(self.db_path, None, None)  # type: ignore[arg-type]
        self.config = {"configurable": {"thread_id": "t1"}}

    def graph(self, script, checkpointer=None):
        self.model = ScriptedModel(script=list(script), seen=[])
        return build_graph(self.res, model=self.model, checkpointer=checkpointer or InMemorySaver())

    def count(self, table):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    async def run_turn(self, graph, text):
        return await graph.ainvoke({"messages": [HumanMessage(text)]}, self.config)

    async def approve(self, graph):
        """Approve what the human was shown, as the CLI does."""
        shown = (await graph.aget_state(self.config)).interrupts[0].value["fingerprint"]
        return await graph.ainvoke(Command(resume={"approve": True, "fingerprint": shown}), self.config)

    def test_write_is_reachable_only_from_review(self):
        g = self.graph([]).get_graph()
        self.assertEqual({e.source for e in g.edges if e.target == "write"}, {"review"})
        self.assertNotIn("write", {e.target for e in g.edges if e.source in ("agent", "tools")})

    async def test_read_tool_round_trip(self):
        graph = self.graph([
            AIMessage("", tool_calls=[call("search_pieces", {"composer": "joplin"})]),
            AIMessage("Maple Leaf Rag is in C-1-05."),
        ])
        out = await self.run_turn(graph, "Where is Maple Leaf Rag?")
        tool_msg = next(m for m in out["messages"] if isinstance(m, ToolMessage))
        self.assertIn("Maple Leaf Rag", tool_msg.content)
        self.assertEqual(out["messages"][-1].content, "Maple Leaf Rag is in C-1-05.")
        # The model saw the tool result on its second call.
        self.assertIsInstance(self.model.seen[1][-1], ToolMessage)

    async def test_proposal_pauses_and_writes_nothing_until_approved(self):
        graph = self.graph([
            AIMessage("", tool_calls=[call(PROPOSE_TOOL, NEW_BOOK)]),
            AIMessage("Saved as B0032."),
        ])
        await self.run_turn(graph, "Add the Heller book")
        state = await graph.aget_state(self.config)
        self.assertEqual(len(state.interrupts), 1)
        proposal = state.interrupts[0].value["proposal"]
        self.assertEqual(proposal["book"]["book_id"], "B0032")  # assigned by code, not the model
        self.assertEqual([p["piece_id"] for p in proposal["pieces"]], ["P00306", "P00307"])
        self.assertIn("1 piece(s) have no level yet", proposal["warnings"])
        self.assertEqual(self.count("books"), 31)  # paused: nothing written

        out = await self.approve(graph)
        self.assertEqual(self.count("books"), 32)
        self.assertEqual(self.count("pieces"), 307)
        result = next(m for m in out["messages"] if isinstance(m, ToolMessage) and m.name == PROPOSE_TOOL)
        self.assertIn('"saved": true', result.content)
        self.assertIn("not in semantic search yet", result.content)  # no Qdrant in this test

    async def test_rejection_writes_nothing_and_passes_feedback(self):
        graph = self.graph([
            AIMessage("", tool_calls=[call(PROPOSE_TOOL, NEW_BOOK)]),
            AIMessage("OK, I'll fix the shelf."),
        ])
        await self.run_turn(graph, "Add the Heller book")
        out = await graph.ainvoke(Command(resume={"approve": False, "feedback": "it goes on A-2"}), self.config)
        self.assertEqual(self.count("books"), 31)
        result = next(m for m in out["messages"] if isinstance(m, ToolMessage) and m.name == PROPOSE_TOOL)
        self.assertIn("rejected", result.content)
        self.assertIn("it goes on A-2", result.content)

    async def test_resume_value_must_be_an_explicit_approval(self):
        # Not tested: None. Command(resume=None) crashes inside LangGraph 1.2.23
        # (UnboundLocalError); the CLI never sends it.
        for value in (True, "yes", {"approve": "true"}, {"approve": True}, {"approve": True, "fingerprint": "x"}):
            with self.subTest(value=value):
                self.setUp()
                graph = self.graph([AIMessage("", tool_calls=[call(PROPOSE_TOOL, NEW_BOOK)]), AIMessage("ok")])
                await self.run_turn(graph, "Add it")
                await graph.ainvoke(Command(resume=value), self.config)
                self.assertEqual(self.count("books"), 31)

    async def test_invalid_proposal_never_reaches_the_human(self):
        taken = NEW_BOOK | {"location": "A-1-01"}  # already the method book's slot
        graph = self.graph([
            AIMessage("", tool_calls=[call(PROPOSE_TOOL, taken)]),
            AIMessage("That shelf slot is taken; where should it go?"),
        ])
        out = await self.run_turn(graph, "Add it")
        state = await graph.aget_state(self.config)
        self.assertEqual(state.interrupts, ())
        result = next(m for m in out["messages"] if isinstance(m, ToolMessage))
        self.assertIn("already used by B0001", result.content)
        self.assertEqual(self.count("books"), 31)

    async def test_schema_violation_is_reported_to_the_model(self):
        bad = NEW_BOOK | {"book_type": "novel"}
        graph = self.graph([AIMessage("", tool_calls=[call(PROPOSE_TOOL, bad)]), AIMessage("Which type?")])
        out = await self.run_turn(graph, "Add it")
        result = next(m for m in out["messages"] if isinstance(m, ToolMessage))
        self.assertIn("Invalid proposal", result.content)

    async def test_other_calls_alongside_a_proposal_are_not_run(self):
        graph = self.graph([
            AIMessage("", tool_calls=[call(PROPOSE_TOOL, NEW_BOOK, "c1"), call("search_pieces", {"composer": "x"}, "c2")]),
            AIMessage("done"),
        ])
        await self.run_turn(graph, "Add it")
        self.assertEqual(len((await graph.aget_state(self.config)).interrupts), 1)
        out = await self.approve(graph)  # review's replies land in state when the node returns
        replies = {m.tool_call_id: m.content for m in out["messages"] if isinstance(m, ToolMessage)}
        self.assertIn("Not run", replies["c2"])
        self.assertIn('"saved": true', replies["c1"])

    async def test_catalogue_change_during_review_blocks_the_write(self):
        graph = self.graph([AIMessage("", tool_calls=[call(PROPOSE_TOOL, NEW_BOOK)]), AIMessage("ok")])
        await self.run_turn(graph, "Add it")
        conn = sqlite3.connect(self.db_path)  # someone else adds a book while the proposal waits
        conn.execute("INSERT INTO books (book_id, title, book_type, location) VALUES ('B0032','Other','single','C-9-01')")
        conn.commit()
        conn.close()
        out = await self.approve(graph)
        result = next(m for m in out["messages"] if isinstance(m, ToolMessage) and m.name == PROPOSE_TOOL)
        self.assertIn("catalogue changed", result.content)
        self.assertEqual(self.count("pieces"), 305)
        self.assertEqual(self.count("books"), 32)  # only the other writer's book

    async def test_approval_survives_a_restart(self):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        path = str(self.tmp / "ckpt.db")
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            graph = self.graph([AIMessage("", tool_calls=[call(PROPOSE_TOOL, NEW_BOOK)])], checkpointer=saver)
            await self.run_turn(graph, "Add it")
        # New saver and new graph object: as if the CLI exited and was started with --thread.
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            graph = self.graph([AIMessage("Saved.")], checkpointer=saver)
            self.assertEqual(len((await graph.aget_state(self.config)).interrupts), 1)
            await self.approve(graph)
        self.assertEqual(self.count("books"), 32)

    async def test_refusal_becomes_a_visible_message(self):
        refused = AIMessage("", response_metadata={"stop_reason": "refusal"})
        out = await self.run_turn(self.graph([refused]), "something")
        self.assertIn("can't help", out["messages"][-1].content)


if __name__ == "__main__":
    unittest.main()
