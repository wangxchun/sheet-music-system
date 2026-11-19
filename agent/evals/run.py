"""Run the end-to-end eval.

Usage:
    python -m agent.evals.run --split dev                 # plan + cost estimate only (no API calls)
    python -m agent.evals.run --split dev --yes           # run the dev split against Claude
    python -m agent.evals.run --split dev --case L1 M2 --yes
    python -m agent.evals.run --split test --final --yes  # the held-out number; logged in TEST_LOG.md
    ... --langsmith                                       # also record it as a LangSmith experiment
    python -m agent.evals.run --rescore REPORT.json       # re-score saved answers with the current checks

--rescore separates evaluator changes from agent changes: the same saved
answers are scored again, with no API calls and no cost.

DESIGN DECISIONS
- Dry run by default. Every real run costs money (CLAUDE.md: check before
  paid calls), so it prints the plan and an estimate unless --yes is passed.
- The test split needs --final, and every test run is appended to
  agent/evals/TEST_LOG.md (committed). How many times the held-out set was
  looked at is part of the result; one run per frozen configuration is the rule.
- Reports go to agent/.data/evals/ as JSON (every check, trace and answer), so
  a failure can be read without re-running.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from agent import db, index, runtime
from agent.evals.cases import Case, build_cases, by_split
from agent.evals.checks import NoWrites, Observation, RanWithoutError, ToolEvent, Turn
from agent.evals.harness import CaseResult, Harness
from agent.graph import EFFORT, MODEL, default_model
from agent.prompts import PROMPT_VERSION

REPORT_DIR = db.DATA_DIR / "evals"
TEST_LOG = Path(__file__).with_name("TEST_LOG.md")
# From the Day 2 smoke test: ~4k input tokens per model call, ~2 calls per turn, $4/$20 per MTok.
EST_COST_PER_TURN = 0.05


def git_commit() -> str:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=db.ROOT)
    dirty = subprocess.run(["git", "status", "--porcelain", "agent"], capture_output=True, text=True, cwd=db.ROOT)
    return r.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")


def summarise(results: Sequence[CaseResult]) -> Dict[str, Any]:
    by_cat: Dict[str, List[bool]] = defaultdict(list)
    kind_fail: Dict[str, int] = defaultdict(int)
    for r in results:
        by_cat[r.category].append(r.passed)
        for c in r.checks:
            if not c.passed:
                kind_fail[c.kind] += 1
    tokens_in = sum(r.input_tokens for r in results)
    tokens_out = sum(r.output_tokens for r in results)
    passed = sum(r.passed for r in results)
    return {
        "cases": len(results), "passed": passed, "accuracy": round(passed / len(results), 4) if results else 0.0,
        "by_category": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_cat.items())},
        "failed_checks_by_kind": dict(kind_fail),
        "model_calls": sum(r.model_calls for r in results),
        "input_tokens": tokens_in, "output_tokens": tokens_out,
        "cost_usd": round(tokens_in * 4 / 1e6 + tokens_out * 20 / 1e6, 2),
        "seconds_total": round(sum(r.seconds for r in results), 1),
    }


def print_report(summary: Dict[str, Any], results: Sequence[CaseResult]) -> None:
    print(f"\n{summary['passed']}/{summary['cases']} passed  (accuracy {summary['accuracy']:.0%})")
    for cat, score in summary["by_category"].items():
        print(f"  {cat:11} {score}")
    print(f"failed checks by kind: {summary['failed_checks_by_kind'] or 'none'}")
    print(f"{summary['model_calls']} model calls, {summary['input_tokens']} in / {summary['output_tokens']} out "
          f"tokens, ~${summary['cost_usd']}")
    for r in results:
        if not r.passed:
            print(f"\n✗ {r.case_id} [{r.category}] {r.observation.turns[-1].user if r.observation.turns else ''}")
            for c in r.checks:
                if not c.passed:
                    print(f"    {c.name}: {c.detail}")
            print(f"    answer: {r.observation.answer[:300]!r}")


def save(results: Sequence[CaseResult], summary: Dict[str, Any], meta: Dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{meta['split']}.json"
    payload = {"meta": meta, "summary": summary, "results": [dataclasses.asdict(r) for r in results]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def log_test_run(summary: Dict[str, Any], meta: Dict[str, Any], report: Path) -> None:
    if not TEST_LOG.exists():
        TEST_LOG.write_text("# Test-split runs\n\nEvery run of the held-out test split is logged here. "
                            "Report the latest run for a frozen configuration; never tune against it.\n\n"
                            "| When | Commit | Model | Effort | Prompt | Score | Report |\n|---|---|---|---|---|---|---|\n",
                            encoding="utf-8")
    with TEST_LOG.open("a", encoding="utf-8") as f:
        f.write(f"| {meta['started']} | {meta['commit']} | {meta['model']} | {meta['effort']} | "
                f"{meta['prompt_version']} | {summary['passed']}/{summary['cases']} ({summary['accuracy']:.0%}) | "
                f"{report.name} |\n")


async def run_local(cases: Sequence[Case], harness: Harness, concurrency: int, tags: List[str]) -> List[CaseResult]:
    sem = asyncio.Semaphore(concurrency)

    async def one(case: Case) -> CaseResult:
        async with sem:
            result = await harness.run(case, tags=tags)
            print(f"  {'✓' if result.passed else '✗'} {case.id:3} {case.category:11} {result.seconds:5.1f}s")
            return result

    results = await asyncio.gather(*(one(c) for c in cases))
    return sorted(results, key=lambda r: [c.id for c in cases].index(r.case_id))


async def run_langsmith(cases: Sequence[Case], harness: Harness, split: str, concurrency: int,
                        meta: Dict[str, Any]) -> List[CaseResult]:
    from langsmith import Client, aevaluate

    client = Client()
    name = f"piano-catalog-eval-{split}"
    wanted = {c.id: {"case_id": c.id, "turns": c.turns} for c in cases}
    if client.has_dataset(dataset_name=name):
        existing = {(e.inputs or {}).get("case_id"): e.inputs for e in client.list_examples(dataset_name=name)}
        if existing != wanted:  # the dataset is derived from cases.py; rebuild it on any change
            client.delete_dataset(dataset_name=name)
    if not client.has_dataset(dataset_name=name):
        client.create_dataset(name, description="Piano catalogue agent eval (generated from agent/evals/cases.py)")
        client.create_examples(dataset_name=name, examples=[
            {"inputs": wanted[c.id], "metadata": {"category": c.category, "split": c.split}} for c in cases])

    by_id = {c.id: c for c in cases}
    results: Dict[str, CaseResult] = {}

    async def target(inputs: Dict[str, Any]) -> Dict[str, Any]:
        r = await harness.run(by_id[inputs["case_id"]], tags=["langsmith"])
        results[r.case_id] = r
        return {"answer": r.observation.answer, "passed": r.passed,
                "checks": [dataclasses.asdict(c) for c in r.checks]}

    def passed(outputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"key": "pass", "score": int(outputs["passed"])}

    def kind_evaluator(kind: str) -> Any:
        def ev(outputs: Dict[str, Any]) -> Dict[str, Any]:
            relevant = [c for c in outputs["checks"] if c["kind"] == kind]
            return {"key": kind, "score": int(all(c["passed"] for c in relevant))}
        ev.__name__ = kind
        return ev

    await aevaluate(target, data=name, evaluators=[passed, *(kind_evaluator(k) for k in
                                                             ("tools", "facts", "safety", "language"))],
                    experiment_prefix=f"{PROMPT_VERSION}-{split}", max_concurrency=concurrency, metadata=meta)
    return [results[c.id] for c in cases if c.id in results]


def rescore(report_path: Path) -> int:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    cases = {c.id: c for c in build_cases()}
    results: List[CaseResult] = []
    for old in data["results"]:
        o = old["observation"]
        obs = Observation(
            turns=[Turn(t["user"], t["answer"], [ToolEvent(**e) for e in t["tools"]]) for t in o["turns"]],
            proposals=o["proposals"], new_books=o["new_books"], new_pieces=o["new_pieces"],
            changed_rows=o["changed_rows"], error=o["error"])
        case = cases[old["case_id"]]
        checks = [RanWithoutError(), *case.checks] + ([] if case.expects_write else [NoWrites()])
        scored = [c(obs) for c in checks]
        results.append(CaseResult(case.id, case.category, case.split, all(r.passed for r in scored), scored, obs,
                                  old["seconds"], old["model_calls"], old["input_tokens"], old["output_tokens"],
                                  old["approvals_used"]))
        if old["passed"] != results[-1].passed:
            print(f"  {case.id}: {'fail -> pass' if results[-1].passed else 'pass -> fail'}")
    print(f"re-scored {report_path.name} (originally {data['summary']['passed']}/{data['summary']['cases']})")
    print_report(summarise(results), results)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the catalogue agent eval.")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--case", nargs="*", help="only these case IDs")
    parser.add_argument("--yes", action="store_true", help="actually call the API (costs money)")
    parser.add_argument("--final", action="store_true", help="required to run the held-out test split")
    parser.add_argument("--langsmith", action="store_true", help="record the run as a LangSmith experiment")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--rescore", type=Path, help="re-score a saved report with the current checks (free)")
    args = parser.parse_args(argv)
    if args.rescore:
        return rescore(args.rescore)

    cases = by_split(build_cases(), args.split)
    if args.case:
        cases = [c for c in cases if c.id in set(args.case)]
    if args.split in ("test", "all") and not args.final:
        print("The test split is held out. Tune on --split dev; run test once per frozen setup with --final.")
        return 2
    turns = sum(len(c.turns) for c in cases)
    print(f"{len(cases)} cases ({turns} user turns), model {MODEL}, effort {EFFORT}, prompt {PROMPT_VERSION}")
    print(f"estimated cost ~${turns * EST_COST_PER_TURN:.2f}")
    if not args.yes:
        print("Dry run: add --yes to call the API.")
        return 0

    runtime.load_settings()
    embedder = index.load_embedder()
    meta = {"split": args.split, "model": MODEL, "effort": EFFORT, "prompt_version": PROMPT_VERSION,
            "commit": git_commit(), "started": f"{datetime.now():%Y-%m-%d %H:%M}",
            "cases": [c.id for c in cases]}

    async def go() -> List[CaseResult]:
        async with Harness(embedder, default_model) as harness:
            if args.langsmith:
                return await run_langsmith(cases, harness, args.split, args.concurrency, meta)
            return await run_local(cases, harness, args.concurrency, tags=[PROMPT_VERSION])

    try:
        results = asyncio.run(go())
    except Exception as exc:
        if "credit balance is too low" in str(exc):
            print("\nStopped: the Anthropic API credit balance is too low. Top up, then re-run.")
            return 1
        raise
    summary = summarise(results)
    print_report(summary, results)
    report = save(results, summary, meta)
    print(f"\nreport: {report}")
    if args.split == "test":
        log_test_run(summary, meta, report)
        print(f"logged in {TEST_LOG}")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
