"""Tests for the eval itself: the case set, the checks, and the harness. No LLM calls.

The oracle tests matter most. A scripted model gives the *right* answer and
the case must pass, which proves its checks are satisfiable. It then gives a
*wrong* answer and the case must fail, which proves the checks catch it. A check
that can never pass, or never fail, would make the headline number meaningless.
"""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

HAS_DEPS = all(importlib.util.find_spec(m) for m in ("langgraph", "langchain_anthropic", "qdrant_client", "fastembed"))

if HAS_DEPS:
    from langchain_core.messages import AIMessage

    from agent import db, index
    from agent.evals import checks as ck
    from agent.evals.cases import build_cases
    from agent.evals.harness import Harness
    from agent.graph import PROPOSE_TOOL
    from scripted import ScriptedModel

BUILT = HAS_DEPS and db.DEFAULT_DB.exists() and index.QDRANT_PATH.exists()


def obs(answer, tools=(), **kw):
    o = ck.Observation(turns=[ck.Turn(user="q", answer=answer, tools=list(tools))], **kw)
    return o


def search_event(*records):
    return ck.ToolEvent("search_pieces", {}, json.dumps({"total": len(records), "results": list(records)}))


@unittest.skipUnless(BUILT, "agent data not built")
class CaseSetTests(unittest.TestCase):
    def test_shape(self):
        cases = build_cases()
        self.assertEqual(len(cases), 50)
        self.assertEqual(len({c.id for c in cases}), 50)
        self.assertEqual((sum(c.split == "dev" for c in cases), sum(c.split == "test" for c in cases)), (28, 22))
        for cat in {c.category for c in cases}:
            splits = {c.split for c in cases if c.category == cat}
            self.assertEqual(splits, {"dev", "test"}, cat)  # every category is represented in the held-out set
        self.assertTrue(all(c.checks for c in cases))

    def test_only_approving_cases_may_write(self):
        for c in build_cases():
            self.assertEqual(c.expects_write, "approve" in c.approvals, c.id)


@unittest.skipUnless(HAS_DEPS, "agent dependencies not installed")
class CheckTests(unittest.TestCase):
    def test_mentions_folds_accents_and_case(self):
        self.assertTrue(ck.Mentions("Für Elise")(obs("fur elise is in C-1-03")).passed)
        self.assertTrue(ck.Mentions(("cabinet B", "B櫃"))(obs("在 B櫃")).passed)
        self.assertFalse(ck.Mentions("A-1-03", "C-2-02")(obs("only A-1-03")).passed)

    def test_page_reference_forms(self):
        for text in ("page 7", "p. 7", "p7", "第 7 頁", "在 7 頁"):
            self.assertTrue(ck.MentionsPage(7)(obs(text)).passed, text)
        for text in ("page 17", "A-1-07", "level 7"):
            self.assertFalse(ck.MentionsPage(7)(obs(text)).passed, text)

    def test_number_must_be_whole(self):
        self.assertTrue(ck.MentionsNumber(50)(obs("There are 50 pieces.")).passed)
        self.assertFalse(ck.MentionsNumber(50)(obs("150 pieces, 5.0 average")).passed)

    def test_chinese_detection_ignores_titles(self):
        self.assertFalse(ck.AnswerInChinese()(obs("It's in **布爾格繆勒 25 首練習曲 Op. 100** on A-1-03.")).passed)
        self.assertTrue(ck.AnswerInChinese()(obs("這首曲子在布爾格繆勒那本書的第七頁，書櫃位置是 A-1-03。")).passed)

    def test_mentioned_pieces_resolve_against_tool_results(self):
        a = {"title": "Arabesque (Op. 100 No. 2)", "composer": "Burgmüller", "level": 3}
        b = {"title": "Arabesque No. 1", "composer": "Debussy", "level": 6}
        o = obs("Try Arabesque No. 1 by Debussy.", [search_event(a, b)])
        hits = ck.mentioned(o.answer, ck.retrieved_records(o))
        self.assertEqual(list(hits), [("Arabesque No. 1", "Debussy")])  # the core "Arabesque" is ambiguous
        rule = ck.PiecesMentioned(lambda r: r["level"] <= 4, "easy")
        self.assertFalse(rule(o).passed)
        self.assertTrue(rule(obs("Try the Burgmüller Arabesque (Op. 100 No. 2).", [search_event(a, b)])).passed)

    def test_quotes_and_emphasis_are_ignored(self):
        w = {"title": "Waltz in D-flat major 'Minute', Op. 64 No. 1", "composer": "Chopin"}
        o = obs('- **Waltz in D-flat major "Minute", Op. 64 No. 1**', [search_event(w)])
        self.assertEqual(len(ck.mentioned(o.answer, ck.retrieved_records(o))), 1)

    def test_flagged_non_matches_are_tolerated_unflagged_ones_fail(self):
        good = {"title": "Ballade (Op. 100 No. 15)", "composer": "Burgmüller", "technique": "staccato chords"}
        other = {"title": "The Happy Farmer (Op. 68 No. 10)", "composer": "Schumann", "technique": "phrasing"}
        rule = ck.PiecesMentioned(lambda r: "staccato" in r["technique"], "staccato")
        flagged = obs("- Ballade (Op. 100 No. 15)\n\nThe search also found The Happy Farmer, but it doesn't "
                      "work on staccato, so I didn't list it.", [search_event(good, other)])
        self.assertTrue(rule(flagged).passed)
        recommended = obs("- Ballade (Op. 100 No. 15)\n- The Happy Farmer (Op. 68 No. 10)",
                          [search_event(good, other)])
        self.assertFalse(rule(recommended).passed)
        only_flagged = obs("The Happy Farmer doesn't work on staccato.", [search_event(good, other)])
        self.assertFalse(rule(only_flagged).passed)  # a flagged miss doesn't count toward min_count

    def test_reprints_count_if_any_copy_satisfies(self):
        copy_a = {"title": "Für Elise, WoO 59", "composer": "Beethoven", "demo_url": None}
        copy_b = dict(copy_a, demo_url="https://example.com/x.mp3")
        o = obs("Für Elise", [search_event(copy_a, copy_b)])
        self.assertTrue(ck.PiecesMentioned(lambda r: bool(r["demo_url"]), "demo")(o).passed)

    def test_no_writes(self):
        self.assertTrue(ck.NoWrites()(obs("")).passed)
        self.assertFalse(ck.NoWrites()(obs("", changed_rows=1)).passed)
        self.assertFalse(ck.NoWrites()(obs("", new_books=[{"book_id": "B0032"}])).passed)


def call(name, args, cid="c1"):
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


@unittest.skipUnless(BUILT, "agent data not built")
class OracleTests(unittest.IsolatedAsyncioTestCase):
    """Right answers pass, wrong answers fail, through the real harness and graph."""

    @classmethod
    def setUpClass(cls):
        cls.embedder = index.load_embedder()
        cls.cases = {c.id: c for c in build_cases()}

    async def run_case(self, case_id, script):
        model = ScriptedModel(script=list(script), seen=[])
        async with Harness(self.embedder, lambda: model) as h:
            return await h.run(self.cases[case_id])

    def failed(self, result):
        return [c.name for c in result.checks if not c.passed]

    async def test_lookup_right_and_wrong(self):
        search = AIMessage("", tool_calls=[call("search_pieces", {"title": "Arabesque", "composer": "burgmuller"})])
        right = await self.run_case("L1", [search, AIMessage(
            "Arabesque is in two books: 布爾格繆勒 25 首練習曲 Op. 100, page 7, shelf A-1-03; "
            "and 檢定曲集 3–4 級, page 14, shelf C-2-02.")])
        self.assertTrue(right.passed, self.failed(right))
        wrong = await self.run_case("L1", [search, AIMessage("It's on page 7, shelf A-1-03.")])  # misses a copy
        self.assertEqual(self.failed(wrong), ["Mentions(C-2-02)", "MentionsPage(14)"])

    async def test_filter_rejects_a_piece_that_breaks_the_rule(self):
        search = AIMessage("", tool_calls=[call("search_pieces", {"composer": "chopin", "level_max": 4})])
        ok = ("Chopin at level 4 or below: Waltz in A minor, B. 150; Prelude in A major, Op. 28 No. 7; "
              "Prelude in E minor, Op. 28 No. 4; Prelude in B minor, Op. 28 No. 6; Prelude in C minor, Op. 28 No. 20.")
        right = await self.run_case("F4", [search, AIMessage(ok)])
        self.assertTrue(right.passed, self.failed(right))
        # Naming a level-5 waltz that the search also returned (via a second, wider call) must fail.
        wide = AIMessage("", tool_calls=[call("search_pieces", {"composer": "chopin"}, "c2")])
        wrong = await self.run_case("F4", [search, wide, AIMessage(ok + " Also Waltz in B minor, Op. 69 No. 2.")])
        self.assertFalse(wrong.passed)

    async def test_onboarding_approved_book_is_written(self):
        case = self.cases["O1"]
        propose = AIMessage("", tool_calls=[call(PROPOSE_TOOL, {
            "title": "Heller: 25 Melodious Studies, Op. 45", "book_type": "etudes", "location": "A-1-06",
            "pieces": [{"title": "Study No. 1 (Op. 45)", "composer": "Heller", "page": 2, "level": 4},
                       {"title": "Study No. 2 (Op. 45)", "composer": "Heller", "page": 4, "level": 4}]})])
        right = await self.run_case(case.id, [propose, AIMessage("Saved as B0032 on shelf A-1-06.")])
        self.assertTrue(right.passed, self.failed(right))
        self.assertEqual(right.approvals_used, ["approve"])
        self.assertEqual([p["page"] for p in right.observation.new_pieces], [2, 4])

    async def test_rejected_proposal_writes_nothing(self):
        propose = AIMessage("", tool_calls=[call(PROPOSE_TOOL, {
            "title": "Gurlitt: Album for the Young, Op. 140", "book_type": "collection", "location": "C-2-04",
            "pieces": [{"title": "The Hunt (Op. 140 No. 1)", "composer": "Gurlitt", "page": 3}]})])
        right = await self.run_case("O2", [propose, AIMessage("The reviewer rejected it, so nothing was saved.")])
        self.assertTrue(right.passed, self.failed(right))
        lying = await self.run_case("O2", [propose, AIMessage("Done, the book has been saved.")])
        self.assertIn("Mentions(" + "|".join(ck.NOT_SAVED) + ")", self.failed(lying))

    async def test_unexpected_proposal_is_rejected_and_fails_the_case(self):
        propose = AIMessage("", tool_calls=[call(PROPOSE_TOOL, {
            "title": "x", "book_type": "single", "location": "C-9-09"})])
        result = await self.run_case("G1", [propose, AIMessage("I can't do that.")])
        self.assertEqual(result.approvals_used, ["reject"])     # the scripted human rejects unlisted proposals
        self.assertIn("NoProposal", self.failed(result))
        self.assertNotIn("NoWrites", self.failed(result))       # and nothing was written

    async def test_crash_is_a_failure_not_a_skip(self):
        result = await self.run_case("G5", [])  # script exhausted: the model call raises
        self.assertIn("RanWithoutError", self.failed(result))


if __name__ == "__main__":
    unittest.main()
