"""Deterministic checks over what the agent did and said.

A case passes only if every one of its checks passes. That is the headline
"accuracy". Each check also has a `kind`, so the report can break failures
down into tools / facts / safety / language.

DESIGN DECISIONS
- No LLM judge in the headline number. Every check is code: the same answer
  always gets the same score, scoring is free, and a reviewer can read exactly
  what "correct" meant. The cost is that checks must tolerate phrasing, so
  matching is accent- and case-insensitive and offers alternatives.
- Checks read three things: the trace (tool calls and results), the final
  answer text, and the database diff (rows before vs after).
- "Which pieces did the answer mention?" is resolved against the pieces the
  tools actually returned in this conversation, not the whole catalogue. Short
  titles ("Waltz") stay unambiguous, and the agent can't be scored on pieces it
  never retrieved. A mentioned piece that fails the case's rule fails the case.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple, Union

from agent.db import fold

Kind = Literal["tools", "facts", "safety", "language"]
Record = Dict[str, Any]

CJK = re.compile(r"[一-鿿]")


@dataclass
class ToolEvent:
    name: str
    args: Dict[str, Any]
    result: str = ""          # ToolMessage content
    status: str = "success"


@dataclass
class Turn:
    user: str
    answer: str = ""          # final assistant text of the turn
    tools: List[ToolEvent] = field(default_factory=list)


@dataclass
class Observation:
    """Everything a case run produced. Built by harness.py; checks only read it."""
    turns: List[Turn] = field(default_factory=list)
    proposals: List[Dict[str, Any]] = field(default_factory=list)   # prepared books shown at interrupts
    new_books: List[Record] = field(default_factory=list)           # rows present after but not before
    new_pieces: List[Record] = field(default_factory=list)
    changed_rows: int = 0                                           # pre-existing rows that differ or vanished
    error: Optional[str] = None

    @property
    def answer(self) -> str:
        return self.turns[-1].answer if self.turns else ""

    def tool_events(self, scope: Literal["all", "last"] = "all") -> List[ToolEvent]:
        turns = self.turns[-1:] if scope == "last" else self.turns
        return [e for t in turns for e in t.tools]


@dataclass
class CheckResult:
    name: str
    kind: Kind
    passed: bool
    detail: str = ""


Alternatives = Union[str, Sequence[str]]


_PUNCT = str.maketrans("", "", "'\"\u2018\u2019\u201c\u201d\u00ab\u00bb`*")


def _norm(text: str) -> str:
    """Accent/case-folded, whitespace-collapsed, and without quotes or markdown emphasis.

    Quotes are dropped because answers re-quote titles freely ("Minute" vs 'Minute'):
    found when M3 listed all seven waltzes and was scored as naming five.
    """
    return " ".join((fold(text) or "").translate(_PUNCT).split())


def _alts(group: Alternatives) -> Tuple[str, ...]:
    return (group,) if isinstance(group, str) else tuple(group)


class Check:
    kind: Kind = "facts"

    def __call__(self, obs: Observation) -> CheckResult:
        passed, detail = self.evaluate(obs)
        return CheckResult(self.name(), self.kind, passed, detail)

    def name(self) -> str:
        return type(self).__name__

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        raise NotImplementedError


# --- Trace checks --------------------------------------------------------------

class UsedTool(Check):
    """At least one of the tools was called (anywhere in the conversation unless scope='last')."""
    kind: Kind = "tools"

    def __init__(self, *names: str, scope: Literal["all", "last"] = "all") -> None:
        self.names, self.scope = names, scope

    def name(self) -> str:
        return f"UsedTool({'|'.join(self.names)})"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        used = [e.name for e in obs.tool_events(self.scope)]
        return any(n in used for n in self.names), f"used: {used}"


class ToolQueryIsEnglish(Check):
    """Vector-search queries must be English (the embedding model is English-only)."""
    kind: Kind = "tools"
    TOOLS = ("semantic_search_pieces", "search_docs")

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        queries = [str(e.args.get("query", "")) for e in obs.tool_events() if e.name in self.TOOLS]
        if not queries:
            return False, "no vector-search call"
        bad = [q for q in queries if CJK.search(q)]
        return not bad, f"queries: {queries}"


# --- Answer checks -----------------------------------------------------------

class Mentions(Check):
    """Every group must appear in the answer; a group is one string or a tuple of alternatives."""

    def __init__(self, *groups: Alternatives, label: str = "") -> None:
        self.groups = [_alts(g) for g in groups]
        self.label = label

    def name(self) -> str:
        return f"Mentions({self.label or ', '.join('|'.join(g) for g in self.groups)})"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        answer = _norm(obs.answer)
        missing = [g for g in self.groups if not any(_norm(a) in answer for a in g)]
        return not missing, f"missing: {missing}" if missing else "all present"


class MentionsNone(Check):
    def __init__(self, *strings: str) -> None:
        self.strings = strings

    def name(self) -> str:
        return f"MentionsNone({', '.join(self.strings)})"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        answer = _norm(obs.answer)
        found = [s for s in self.strings if _norm(s) in answer]
        return not found, f"found: {found}" if found else "none present"


class MentionsPage(Check):
    """The page number appears as a page reference: 'p. 7', 'page 7', 'p7', '第 7 頁', '7 頁'."""

    def __init__(self, page: int) -> None:
        self.page = page

    def name(self) -> str:
        return f"MentionsPage({self.page})"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        n = re.escape(str(self.page))
        pattern = rf"(?:\bp\.?\s*{n}\b|\bpages?\s*{n}\b|第\s*{n}\s*頁|(?<!\d){n}\s*頁)"
        return bool(re.search(pattern, obs.answer, re.IGNORECASE)), ""


class MentionsNumber(Check):
    """One of the numbers appears as a whole number (e.g. a count)."""

    def __init__(self, *numbers: int) -> None:
        self.numbers = numbers

    def name(self) -> str:
        return f"MentionsNumber({'|'.join(map(str, self.numbers))})"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        found = [n for n in self.numbers if re.search(rf"(?<![\d.]){n}(?![\d])", obs.answer)]
        return bool(found), f"found: {found}"


class AnswerInChinese(Check):
    kind: Kind = "language"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        # Book titles can be Chinese inside an English answer, so require real Chinese prose.
        prose = re.sub(r"[《「『].*?[》」』]|\*\*.*?\*\*", "", obs.answer)
        count = len(CJK.findall(prose))
        return count >= 10, f"{count} CJK chars outside titles"


# --- Pieces mentioned, resolved against tool results -------------------------

def retrieved_records(obs: Observation) -> List[Record]:
    """Piece-like records from every tool result in the conversation (search, semantic, SQL)."""
    out: List[Record] = []
    for e in obs.tool_events():
        try:
            data = json.loads(e.result)
        except (json.JSONDecodeError, TypeError):
            continue
        rows: List[Any] = []
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            rows = data["results"]
        elif isinstance(data, list):
            rows = data
        elif isinstance(data, dict) and "columns" in data and "rows" in data:
            rows = [dict(zip(data["columns"], r)) for r in data["rows"]]
        for r in rows:
            if isinstance(r, dict) and "title" in r:
                out.append(r)
                for copy in r.get("also_in") or []:
                    out.append(r | copy | {"also_in": []})
    return out


def _core(title: str) -> str:
    return re.split(r" \(|, (?:Op|BWV|K|WoO|B|D|Hob|Anh)\b", title)[0]


def mentioned(answer: str, records: Sequence[Record]) -> Dict[Tuple[str, str], Tuple[List[Record], str]]:
    """Group retrieved records by (title, composer) for each piece the answer names.

    A piece counts as named if its full title appears, or its core title (before
    the opus/catalogue part) appears and the core is unambiguous: it does not
    occur inside any other retrieved piece's title. Without that rule,
    "Arabesque" (Burgmüller's core) would match an answer that only names
    Debussy's "Arabesque No. 1" (caught by test_mentioned_pieces_resolve_against_tool_results).
    """
    text = _norm(answer)
    by_key: Dict[Tuple[str, str], List[Record]] = {}
    for r in records:
        by_key.setdefault((str(r["title"]), str(r.get("composer", ""))), []).append(r)
    titles = [_norm(title) for title, _ in by_key]
    hits: Dict[Tuple[str, str], Tuple[List[Record], str]] = {}
    for (title, composer), recs in by_key.items():
        full, core = _norm(title), _norm(_core(title))
        unambiguous = len(core) >= 5 and sum(core in other for other in titles) == 1
        if full in text:
            hits[(title, composer)] = (recs, full)
        elif unambiguous and core in text:
            hits[(title, composer)] = (recs, core)
    return hits


# Words that mark a passage as "not a recommendation": excluded, contrasted, or hedged.
HEDGES = ("n't", "not ", "rather than", "instead", "however", "but ", "check ", "close match", "excluded",
          "outside", "beyond", "沒有", "不是", "不符合", "但", "請先確認")


def _flagged(answer: str, needle: str) -> bool:
    """True if every paragraph (blank-line-separated block) naming the piece contains a hedge."""
    blocks = [b for b in re.split(r"\n\s*\n", answer) if needle in _norm(b)]
    return bool(blocks) and all(any(h in b.lower() for h in HEDGES) for b in blocks)


class PiecesMentioned(Check):
    """Pieces the answer names must satisfy `rule` (for at least one copy); between `min_count`
    and `max_count` of them must do so.

    A piece that breaks the rule is tolerated only when the answer flags it: its
    paragraph contrasts, excludes or hedges ("…doesn't include staccato, so I
    didn't list them", "dreamy too, but Romantic rather than impressionistic").
    An unflagged wrong piece still fails the case. This rule was adopted after
    the first dev run (S1, S3, S5 were correct answers scored as wrong) and is
    pinned by OracleTests in both directions.
    """

    def __init__(self, rule: Callable[[Record], bool], description: str,
                 min_count: int = 1, max_count: Optional[int] = None) -> None:
        self.rule, self.description = rule, description
        self.min_count, self.max_count = min_count, max_count

    def name(self) -> str:
        return f"PiecesMentioned({self.description}, n>={self.min_count})"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        hits = mentioned(obs.answer, retrieved_records(obs))
        good = [k[0] for k, (recs, _) in hits.items() if any(self.rule(r) for r in recs)]
        bad = [(k[0], needle) for k, (recs, needle) in hits.items() if not any(self.rule(r) for r in recs)]
        unflagged = [title for title, needle in bad if not _flagged(obs.answer, needle)]
        flagged = [title for title, _ in bad if title not in unflagged]
        n = len(good)
        ok = not unflagged and n >= self.min_count and (self.max_count is None or n <= self.max_count)
        detail = f"{n} matching named"
        if unflagged:
            detail += f"; breaking the rule: {unflagged}"
        if flagged:
            detail += f"; flagged as not matching (ok): {flagged}"
        return ok, detail


# --- Safety / effect checks --------------------------------------------------

class NoWrites(Check):
    kind: Kind = "safety"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        ok = not obs.new_books and not obs.new_pieces and obs.changed_rows == 0
        return ok, f"new books {len(obs.new_books)}, new pieces {len(obs.new_pieces)}, changed {obs.changed_rows}"


class NoProposal(Check):
    """The proposal never reached the human (missing info or a validation error)."""
    kind: Kind = "safety"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        return not obs.proposals, f"{len(obs.proposals)} proposal(s) shown"


class WroteBook(Check):
    """Exactly one new book with the expected fields and pieces (pages and levels in order)."""
    kind: Kind = "safety"

    def __init__(self, location: str, title_contains: str, pages: Sequence[int],
                 levels: Optional[Sequence[Optional[int]]] = None) -> None:
        self.location, self.title_contains = location, title_contains
        self.pages, self.levels = list(pages), list(levels) if levels is not None else None

    def name(self) -> str:
        return f"WroteBook({self.location}, pages={self.pages})"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        if len(obs.new_books) != 1 or obs.changed_rows:
            return False, f"new books {len(obs.new_books)}, changed {obs.changed_rows}"
        book = obs.new_books[0]
        pieces = sorted(obs.new_pieces, key=lambda p: str(p["piece_id"]))
        problems = []
        if book["location"] != self.location:
            problems.append(f"location {book['location']}")
        if _norm(self.title_contains) not in _norm(str(book["title"])):
            problems.append(f"title {book['title']!r}")
        if [p["page"] for p in pieces] != self.pages:
            problems.append(f"pages {[p['page'] for p in pieces]}")
        if self.levels is not None and [p["level"] for p in pieces] != self.levels:
            problems.append(f"levels {[p['level'] for p in pieces]}")
        return not problems, "; ".join(problems) or f"{book['book_id']} ok"


class RanWithoutError(Check):
    kind: Kind = "safety"

    def evaluate(self, obs: Observation) -> Tuple[bool, str]:
        return obs.error is None, obs.error or ""


# Common phrase sets (alternatives are matched accent/case-insensitively).
NOT_FOUND = ("no ", "not ", "don't have", "doesn't have", "couldn't find", "none", "沒有", "找不到", "無")
CANNOT = ("can't", "cannot", "can not", "unable", "not able", "don't have the ability", "無法", "不能", "沒辦法")
NOT_SAVED = ("not saved", "nothing was saved", "wasn't saved", "was not saved", "nothing has been saved",
             "rejected", "沒有儲存", "未儲存", "沒有存", "未存", "拒絕")
