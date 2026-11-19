"""Tests for the agent's data layer and tools. No network, no LLM calls.

Run from the project root with the venv that has agent/requirements.txt:
    .venv/bin/python -m unittest tests.test_agent -v

The vector-search tests need the local index (`python -m agent.build`) and are
skipped when it is missing.
"""

import asyncio
import csv
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HAS_DEPS = all(importlib.util.find_spec(m) for m in ("aiosqlite", "qdrant_client", "fastembed"))

if HAS_DEPS:
    from agent import db, index, vocab  # noqa: E402
    from agent import tools as t  # noqa: E402
    from agent.synth import generate as g  # noqa: E402
    from tools import schema as s  # noqa: E402

DEMO = ROOT / "sample" / "demo"


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@unittest.skipUnless(HAS_DEPS, "agent dependencies not installed")
class SyntheticDataTests(unittest.TestCase):
    def test_vocab_matches_schema(self):
        vocab.check_consistency()

    def test_generation_is_deterministic_and_matches_committed_csv(self):
        # The eval set's expected answers come from sample/demo; it must not drift.
        books, pieces = g.generate(g.DEFAULT_SEED)
        self.assertEqual(g.generate(g.DEFAULT_SEED), (books, pieces))
        self.assertEqual(read_csv(DEMO / "books.csv"), books)
        self.assertEqual(read_csv(DEMO / "pieces.csv"), pieces)

    def test_demo_passes_the_studio_validator(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "validate_catalog.py"),
             str(DEMO / "books.csv"), str(DEMO / "pieces.csv"), str(DEMO / "options.csv")],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("0 error(s)", r.stdout)

    def test_reprinted_pieces_keep_identical_traits(self):
        _, pieces = g.generate(g.DEFAULT_SEED)
        seen = {}
        for p in pieces:
            key = (p[s.PIECE_TITLE], p[s.PIECE_COMPOSER])
            traits = (p[s.PIECE_PERIOD], p[s.PIECE_STYLE], p[s.PIECE_TECHNIQUE])
            self.assertEqual(seen.setdefault(key, traits), traits, key)
        self.assertLess(len(seen), len(pieces))  # there really are reprints


@unittest.skipUnless(HAS_DEPS, "agent dependencies not installed")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "c.db"
        self.counts = db.build_database(DEMO / "books.csv", DEMO / "pieces.csv", self.db_path)

    def test_counts(self):
        self.assertEqual(self.counts, {"books": 31, "pieces": 305})

    def test_fold(self):
        self.assertEqual(db.fold("Burgmüller"), db.fold("BURGMULLER"))
        self.assertEqual(db.fold("Rêverie"), "reverie")

    def test_database_enforces_its_own_rules(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        bad = [
            "INSERT INTO pieces (piece_id, book_id, title, composer, page) VALUES ('P99999','B9999','x','y',1)",
            "INSERT INTO pieces (piece_id, book_id, title, composer, page, level) VALUES ('P99999','B0001','x','y',1,9)",
            "INSERT INTO books (book_id, title, book_type) VALUES (NULL, 'x', 'collection')",
            "INSERT INTO books (book_id, title, book_type) VALUES ('B9999', 'x', 'collection')",  # no location/link
        ]
        for sql in bad:
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                conn.execute(sql)
        conn.close()

    def test_failed_rebuild_keeps_the_old_database(self):
        rows = read_csv(DEMO / "pieces.csv")
        rows[1][s.PIECE_ID] = rows[0][s.PIECE_ID]  # duplicate primary key
        bad = self.tmp / "bad.csv"
        with bad.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        with self.assertRaises(sqlite3.IntegrityError):
            db.build_database(DEMO / "books.csv", bad, self.db_path)
        conn = sqlite3.connect(self.db_path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM pieces").fetchone()[0], 305)
        conn.close()
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])  # temp file cleaned up

    def test_readonly_connection_cannot_write(self):
        async def attempt():
            async with db.connect_readonly(self.db_path) as conn:
                await conn.execute("DELETE FROM pieces")
        with self.assertRaises(sqlite3.OperationalError):
            asyncio.run(attempt())


@unittest.skipUnless(HAS_DEPS, "agent dependencies not installed")
class SqlToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        db.build_database(DEMO / "books.csv", DEMO / "pieces.csv", tmp / "c.db")
        # SQL tools never touch Qdrant or the embedder.
        self.res = t.Resources(tmp / "c.db", cast(Any, None), cast(Any, None))

    async def test_search_is_accent_and_case_insensitive(self):
        r = await t.search_pieces(self.res, composer="burgmuller", title="ARABESQUE")
        self.assertEqual(r["total"], 2)  # original book + graded compilation
        self.assertEqual({x["location"] for x in r["results"]}, {"A-1-03", "C-2-02"})

    async def test_total_reports_matches_beyond_the_limit(self):
        r = await t.search_pieces(self.res, composer="czerny", limit=5)
        self.assertEqual(len(r["results"]), 5)
        self.assertEqual(r["total"], 50)

    async def test_filters_combine(self):
        r = await t.search_pieces(self.res, level_min=6, period="modern", style="dance")
        self.assertEqual({x["title"] for x in r["results"]}, {"Maple Leaf Rag"})

    async def test_bad_level_is_returned_as_error(self):
        self.assertIn("error", await t.search_pieces(self.res, level_max=0))

    async def test_sql_answers_aggregate_questions(self):
        r = await t.run_readonly_sql(self.res, "SELECT COUNT(*) FROM catalogue WHERE level IS NULL")
        self.assertEqual(r["rows"], [[8]])  # the ungraded Grieg book

    async def test_sql_refuses_writes_at_every_layer(self):
        for q in ("DELETE FROM books", "SELECT 1; DELETE FROM books", "DROP TABLE pieces"):
            self.assertIn("only", (await t.run_readonly_sql(self.res, q))["error"])
        # Passes the statement check, stopped by the read-only connection.
        r = await t.run_readonly_sql(self.res, "WITH x AS (SELECT 1) DELETE FROM books")
        self.assertIn("readonly", r["error"])
        conn = sqlite3.connect(self.res.db_path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM books").fetchone()[0], 31)
        conn.close()

    async def test_sql_step_budget_stops_runaway_queries(self):
        q = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"
        self.assertIn("interrupted", (await t.run_readonly_sql(self.res, q))["error"])

    async def test_sql_row_cap(self):
        r = await t.run_readonly_sql(self.res, "SELECT piece_id FROM pieces")
        self.assertEqual(len(r["rows"]), t.SQL_MAX_ROWS)
        self.assertTrue(r["truncated"])


@unittest.skipUnless(HAS_DEPS, "agent dependencies not installed")
class ChunkingTests(unittest.TestCase):
    def test_chunks_carry_title_and_heading(self):
        md = "# Manual\n\nintro\n\n## 1. Setup\n\nstep one\n\n### 1.1 Import\n\nupload it\n"
        chunks = index.chunk_markdown("docs/x.md", md)
        self.assertEqual([c.heading for c in chunks], ["Manual", "Manual > 1. Setup", "Manual > 1.1 Import"])
        self.assertEqual(chunks[2].text, "upload it")

    def test_long_sections_are_split(self):
        md = "# T\n\n## S\n\n" + "\n\n".join("x" * 600 for _ in range(5))
        chunks = index.chunk_markdown("d", md)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.text) <= index.MAX_CHUNK_CHARS for c in chunks))


@unittest.skipUnless(HAS_DEPS and (index.QDRANT_PATH if HAS_DEPS else Path("/nonexistent")).exists()
                     and db.DEFAULT_DB.exists(), "local index not built")
class VectorToolTests(unittest.IsolatedAsyncioTestCase):
    """Integration tests against the built index. Assertions are loose on purpose: they
    check that retrieval works, while retrieval_bench.py measures how well."""

    @classmethod
    def setUpClass(cls):
        # Loading the model is slow, synchronous work: do it once, outside the event loop.
        cls.embedder = index.load_embedder()

    async def asyncSetUp(self):
        from qdrant_client import AsyncQdrantClient
        self.qdrant = AsyncQdrantClient(path=str(index.QDRANT_PATH))
        self.res = t.Resources(db.DEFAULT_DB, self.qdrant, self.embedder)

    async def asyncTearDown(self):
        await self.qdrant.close()

    async def test_duets_found_by_description(self):
        r = await t.semantic_search_pieces(self.res, "a piece for two pianists", limit=3)
        self.assertEqual(r[0]["style"], "duet")

    async def test_reprints_collapse_into_also_in(self):
        r = await t.semantic_search_pieces(self.res, "Für Elise Beethoven broken chords pedalling", limit=5)
        titles = [x["title"] for x in r]
        self.assertEqual(titles.count("Für Elise, WoO 59"), 1)
        hit = r[titles.index("Für Elise, WoO 59")]
        self.assertEqual(len(hit["also_in"]), 2)

    async def test_filters_apply_inside_qdrant(self):
        r = await t.semantic_search_pieces(self.res, "gentle melody", level_min=2, level_max=3, period="romantic")
        self.assertTrue(r)
        self.assertTrue(all(2 <= x["level"] <= 3 and x["period"] == "romantic" for x in r))

    async def test_docs_retrieval_finds_the_right_section(self):
        r = await t.search_docs(self.res, "how do I add a new dropdown option?", limit=1)
        self.assertEqual(r[0]["source"], "docs/04_admin_manual.md")
        self.assertIn("2.2", r[0]["heading"])


if __name__ == "__main__":
    unittest.main()
