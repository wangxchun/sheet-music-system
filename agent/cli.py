"""Chat with the catalogue agent in the terminal.

Usage:
    python -m agent.cli                 # new conversation
    python -m agent.cli --thread ID     # resume a saved conversation (including a pending approval)

Commands inside the chat: /new (start a new thread), /thread (show its ID), /quit.

When the agent proposes a new book, the CLI shows the exact rows that would be
written and waits for you: [y] approve, [n] reject, or type feedback to reject
with a reason the agent can act on.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

import anthropic
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from agent import index, runtime
from agent.graph import build_graph
from agent.onboarding import PreparedBook

RECURSION_LIMIT = 25  # agent<->tools round trips per user turn before LangGraph stops the loop


def run_config(thread_id: str) -> RunnableConfig:
    # metadata.thread_id makes LangSmith group the turns of one conversation into a thread.
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT,
            "metadata": {"thread_id": thread_id}, "tags": ["cli"], "run_name": "catalogue-agent"}


def short(value: Any, limit: int = 100) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 1] + "…"


def show_proposal(prepared: PreparedBook) -> None:
    book = prepared["book"]
    where = book["location"] or book["file_link"]
    print(f"\n  ┌─ Proposed book {book['book_id']}: {book['title']}  [{book['book_type']}]  {where}")
    if book["series"]:
        print(f"  │  series: {book['series']}")
    for p in prepared["pieces"]:
        # Show every field that will be written, including ones the model filled in
        # itself (it may infer period/style): the reviewer approves all of it.
        level = f"level {p['level']}" if p["level"] else "no level"
        tags = ", ".join(str(x) for x in (p["period"], p["style"], p["technique"]) if x)
        print(f"  │  {p['piece_id']}  p.{p['page']:<4} {p['title']} — {p['composer']} ({level})"
              + (f"  [{tags}]" if tags else ""))
    for w in prepared["warnings"]:
        print(f"  │  warning: {w}")
    print("  └─ Nothing is saved unless you approve.")


async def ask(prompt: str) -> str:
    return (await asyncio.to_thread(input, prompt)).strip()


async def stream_turn(graph: CompiledStateGraph[Any, Any, Any, Any], payload: Any, config: RunnableConfig) -> None:
    async for update in graph.astream(payload, config, stream_mode="updates"):
        for node, delta in update.items():
            if node == "__interrupt__" or not isinstance(delta, dict):
                continue
            for msg in delta.get("messages", []):
                if isinstance(msg, AIMessage):
                    for call in msg.tool_calls:
                        print(f"  → {call['name']}({short(call['args'])})")
                    if msg.text.strip() and not msg.tool_calls:
                        print(f"\nagent> {msg.text.strip()}\n")
                elif isinstance(msg, ToolMessage) and msg.status == "error":
                    print(f"  ✗ {msg.name}: {short(msg.content, 160)}")


async def handle_interrupts(graph: CompiledStateGraph[Any, Any, Any, Any], config: RunnableConfig) -> None:
    while True:
        state = await graph.aget_state(config)
        pending = [i for i in state.interrupts if isinstance(i.value, dict) and i.value.get("kind") == "book_proposal"]
        if not pending:
            return
        show_proposal(pending[0].value["proposal"])
        answer = await ask("  Approve? [y] yes / [n] no / or type feedback: ")
        decision: Dict[str, Any]
        if answer.lower() in ("y", "yes"):
            # Echo the fingerprint of what was displayed: approve exactly these rows.
            decision = {"approve": True, "fingerprint": pending[0].value["fingerprint"]}
        elif answer.lower() in ("n", "no", ""):
            decision = {"approve": False}
        else:
            decision = {"approve": False, "feedback": answer}
        await stream_turn(graph, Command(resume=decision), config)


def describe_api_error(exc: anthropic.APIError) -> str:
    """Most specific first: what happened and whether retrying can help."""
    if isinstance(exc, anthropic.RateLimitError):
        return "rate limited by the Claude API; wait a moment and try again"
    if isinstance(exc, anthropic.APIConnectionError):
        return "could not reach the Claude API (network); check the connection and try again"
    if isinstance(exc, anthropic.APIStatusError):
        body = exc.body if isinstance(exc.body, dict) else {}
        detail = (body.get("error") or {}).get("message") or str(exc)
        return f"Claude API error {exc.status_code}: {detail}"
    return f"Claude API error: {exc}"


async def run_turn(graph: CompiledStateGraph[Any, Any, Any, Any], payload: Any, config: RunnableConfig) -> None:
    """One user turn, including any approval prompts. API failures end the turn, not the session.

    If the model call fails, the user's message is already in the checkpoint. The
    next message is appended after it, and the API accepts consecutive user turns.
    """
    try:
        await stream_turn(graph, payload, config)
        await handle_interrupts(graph, config)
    except anthropic.APIError as exc:
        print(f"\n  ✗ {describe_api_error(exc)}\n")


async def chat(thread_id: Optional[str]) -> None:
    runtime.load_settings()
    embedder = index.load_embedder()  # before the loop does real work; see runtime.py
    thread = thread_id or uuid.uuid4().hex[:12]
    async with runtime.open_resources(embedder) as res, runtime.open_checkpointer() as saver:
        graph = build_graph(res, checkpointer=saver)
        print(f"Piano catalogue agent. Thread {thread}. {runtime.tracing_status()}. /quit to exit.\n")
        try:  # a resumed thread may be waiting for approval
            await handle_interrupts(graph, run_config(thread))
        except anthropic.APIError as exc:
            print(f"\n  ✗ {describe_api_error(exc)}\n")
        while True:
            try:
                text = await ask("you> ")
            except (EOFError, KeyboardInterrupt):
                break
            if text in ("/quit", "/exit"):
                break
            if text == "/new":
                thread = uuid.uuid4().hex[:12]
                print(f"New thread {thread}\n")
                continue
            if text == "/thread":
                print(f"Thread {thread} (resume with: python -m agent.cli --thread {thread})\n")
                continue
            if not text:
                continue
            messages: List[HumanMessage] = [HumanMessage(text)]
            await run_turn(graph, {"messages": messages}, run_config(thread))
    print(f"Bye. Resume with: python -m agent.cli --thread {thread}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the piano catalogue agent.")
    parser.add_argument("--thread", help="resume a saved conversation")
    args = parser.parse_args()
    asyncio.run(chat(args.thread))


if __name__ == "__main__":
    main()
