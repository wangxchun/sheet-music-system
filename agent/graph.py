"""The LangGraph agent: tool-calling loop plus a human-approval gate for writes.

    START -> agent --(no tool calls)----------------------------> END
               |  \\--(read tool calls)--> tools ---------------> agent
               |   \\-(propose_new_book)--> review --(reject)---> agent
               |                              |
               |                          interrupt(): a human approves or rejects
               |                              |
               |                          (approve)--> write ----> agent

DESIGN DECISIONS
- The write path is structural, not a prompt rule. The model has no write
  tool. propose_new_book is routed to `review` instead of ToolNode, and
  `write` is reachable only through review's Command(goto="write"), which is
  issued only when the human's resume value is an approval. tests/test_graph.py
  checks both the edge list and the behaviour.
- interrupt() + a checkpointer. The graph state is saved at the interrupt, so
  the approval can arrive in a later process (the CLI could exit and resume
  with --thread). On resume LangGraph re-runs `review` from the top, so
  everything before interrupt() is deterministic (see onboarding.prepare).
- Tools are built per graph from a shared Resources object (DB path, Qdrant
  client, embedder): one Qdrant client per process, because local mode locks
  its directory.
- Model: claude-opus-5-5 with an explicit effort level (its default is medium;
  set explicitly so a default change can't silently move the eval). The
  server-side refusal fallback is on. A refusal is turned into a short visible
  message instead of an empty assistant turn.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional, Sequence

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolCall, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Checkpointer, Command, interrupt
from pydantic import BaseModel, Field, ValidationError

from agent import onboarding, tools as t
from agent.prompts import SYSTEM_PROMPT
from agent.vocab import Period, Style

MODEL = "claude-opus-5-5"
EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
PROPOSE_TOOL = "propose_new_book"


# --- Tool argument schemas: these become the JSON schemas the model sees ------

class SearchPiecesArgs(BaseModel):
    title: Optional[str] = Field(default=None, description="Part of the piece title; accents and case are ignored")
    composer: Optional[str] = Field(default=None, description="Part of the composer name, e.g. 'czerny'")
    book_title: Optional[str] = Field(default=None, description="Part of the book title")
    level_min: Optional[int] = Field(default=None, ge=1, le=8)
    level_max: Optional[int] = Field(default=None, ge=1, le=8)
    period: Optional[Period] = None
    style: Optional[Style] = None
    has_demo: Optional[bool] = Field(default=None, description="True: only pieces with a demo recording")
    limit: int = Field(default=10, ge=1, le=20)


class SqlArgs(BaseModel):
    query: str = Field(description="One SQLite SELECT statement, preferably against the `catalogue` view")


class SemanticArgs(BaseModel):
    query: str = Field(description="English description of what the user wants, e.g. 'gentle piece for staccato'")
    level_min: Optional[int] = Field(default=None, ge=1, le=8)
    level_max: Optional[int] = Field(default=None, ge=1, le=8)
    period: Optional[Period] = None
    style: Optional[Style] = None
    limit: int = Field(default=8, ge=1, le=20)


class DocsArgs(BaseModel):
    query: str = Field(description="The how-to question, in English")


def build_tools(res: t.Resources) -> List[BaseTool]:
    """Read-only tools, bound to shared resources."""

    async def search_pieces(**kw: Any) -> Any:
        return await t.search_pieces(res, **kw)

    async def run_readonly_sql(query: str) -> Any:
        return await t.run_readonly_sql(res, query)

    async def semantic_search_pieces(query: str, **kw: Any) -> Any:
        return await t.semantic_search_pieces(res, query, **kw)

    async def search_docs(query: str) -> Any:
        return await t.search_docs(res, query)

    return [
        StructuredTool.from_function(
            coroutine=search_pieces, name="search_pieces", args_schema=SearchPiecesArgs,
            description="Find pieces by title, composer, book, level range, period, style or demo availability. "
                        "Returns {total, results}; each result has book_title, page, location or file_link."),
        StructuredTool.from_function(
            coroutine=run_readonly_sql, name="run_readonly_sql", args_schema=SqlArgs,
            description="Run one read-only SELECT for counts, rankings or questions search_pieces cannot express. "
                        "Returns columns, up to 50 rows and a truncated flag, or an error to fix and retry."),
        StructuredTool.from_function(
            coroutine=semantic_search_pieces, name="semantic_search_pieces", args_schema=SemanticArgs,
            description="Find pieces by description (mood, technique, use). Query must be English. Reprinted "
                        "pieces appear once, with other books listed in also_in."),
        StructuredTool.from_function(
            coroutine=search_docs, name="search_docs", args_schema=DocsArgs,
            description="Search the studio's manuals for how-to answers. Returns sections with source and heading."),
    ]


def propose_tool_schema() -> Dict[str, Any]:
    """Schema-only tool: the model can call it, but it never executes as a tool."""
    return {
        "name": PROPOSE_TOOL,
        "description": "Propose adding a new book and its pieces to the catalogue. A person reviews the proposal; "
                       "nothing is saved unless they approve. Call it on its own, not alongside other tools.",
        "input_schema": onboarding.BookProposal.model_json_schema(),
    }


# --- Graph -------------------------------------------------------------------

class AgentState(MessagesState, total=False):
    pending: Optional[onboarding.PreparedBook]   # set only by `review` after an approval


def default_model() -> ChatAnthropic:
    # `model` / `max_tokens` are pydantic aliases that mypy can't see without the pydantic plugin.
    return ChatAnthropic(  # type: ignore[call-arg]
        model=MODEL,
        max_tokens=16000,
        effort=EFFORT,
        betas=["server-side-fallback-2026-07-01"],
        model_kwargs={"fallbacks": "default"},  # retry declined requests on a fallback model, same call
    )


def _tool_messages_for(calls: Sequence[ToolCall], text: str) -> List[ToolMessage]:
    return [ToolMessage(content=text, tool_call_id=c["id"], name=c["name"], status="error") for c in calls]


def build_graph(
    res: t.Resources,
    model: Optional[BaseChatModel] = None,
    checkpointer: Checkpointer = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    read_tools = build_tools(res)
    llm = (model or default_model()).bind_tools([*read_tools, propose_tool_schema()])

    async def agent(state: AgentState) -> Dict[str, List[AnyMessage]]:
        response = await llm.ainvoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])
        if response.response_metadata.get("stop_reason") == "refusal":
            response = AIMessage("Sorry, I can't help with that request.")
        return {"messages": [response]}

    def route(state: AgentState) -> Literal["tools", "review", "__end__"]:
        last = state["messages"][-1]
        calls = last.tool_calls if isinstance(last, AIMessage) else []
        if not calls:
            return "__end__"
        if any(c["name"] == PROPOSE_TOOL for c in calls):
            return "review"
        return "tools"

    async def review(state: AgentState) -> Command[Literal["agent", "write"]]:
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        proposals = [c for c in last.tool_calls if c["name"] == PROPOSE_TOOL]
        others = [c for c in last.tool_calls if c["name"] != PROPOSE_TOOL]
        call, extra = proposals[0], proposals[1:]
        # Every tool_call id must get a ToolMessage, or the next model call fails.
        replies = _tool_messages_for(others + extra, f"Not run: call {PROPOSE_TOOL} on its own, one book at a time.")

        try:
            proposal = onboarding.BookProposal.model_validate(call["args"])
        except ValidationError as exc:
            replies += _tool_messages_for([call], f"Invalid proposal: {exc.errors(include_url=False)}")
            return Command(goto="agent", update={"messages": replies})

        prepared = await onboarding.prepare(res.db_path, proposal)
        if prepared["errors"]:
            replies += _tool_messages_for([call], "Proposal not sent for review: " + "; ".join(prepared["errors"]))
            return Command(goto="agent", update={"messages": replies})

        # Pauses the graph. The CLI (or the eval harness) resumes it with
        # Command(resume={"approve": True, "fingerprint": <the one shown>}).
        shown = onboarding.fingerprint(prepared)
        decision = interrupt({"kind": "book_proposal", "proposal": prepared, "fingerprint": shown})

        if isinstance(decision, dict) and decision.get("approve") is True:
            if decision.get("fingerprint") != shown:
                # prepare() re-ran on resume and produced different rows (or the
                # approval didn't say what it approved). Never write unseen rows.
                replies += _tool_messages_for([call], "The catalogue changed while the proposal was waiting for "
                                                      "review, so the approved version is out of date. Nothing was "
                                                      "saved; propose the book again.")
                return Command(goto="agent", update={"messages": replies})
            return Command(goto="write", update={"messages": replies, "pending": prepared})
        feedback = (decision or {}).get("feedback") if isinstance(decision, dict) else None
        text = "The reviewer rejected this proposal; nothing was saved."
        if feedback:
            text += f" Reviewer feedback: {feedback}"
        replies.append(ToolMessage(content=text, tool_call_id=call["id"], name=PROPOSE_TOOL))
        return Command(goto="agent", update={"messages": replies})

    async def write(state: AgentState) -> Dict[str, Any]:
        prepared = state.get("pending")
        # `review` appended its replies after the AI message; find the propose call.
        ai = next(m for m in reversed(state["messages"]) if isinstance(m, AIMessage))
        call = next(c for c in ai.tool_calls if c["name"] == PROPOSE_TOOL)
        if prepared is None:  # unreachable by construction; fail closed if it ever happens
            msg = ToolMessage(content="Internal error: no approved proposal; nothing saved.",
                              tool_call_id=call["id"], name=PROPOSE_TOOL, status="error")
            return {"messages": [msg]}
        result = await onboarding.write(res.db_path, prepared, res.qdrant, res.embedder)
        msg = ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"],
                          name=PROPOSE_TOOL, status="success" if result["saved"] else "error")
        return {"messages": [msg], "pending": None}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(read_tools))
    graph.add_node("review", review, destinations=("agent", "write"))
    graph.add_node("write", write)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", "review": "review", "__end__": END})
    graph.add_edge("tools", "agent")
    graph.add_edge("write", "agent")
    return graph.compile(checkpointer=checkpointer)
