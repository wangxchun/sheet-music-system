"""A chat model that replays pre-written AI messages. Shared by the graph and eval tests."""

from typing import Any, List

from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedModel(BaseChatModel):
    """Returns the next scripted AIMessage on each call; records what it was sent."""
    script: List[Any] = []
    seen: List[Any] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])

    def bind_tools(self, tools, **kwargs):
        return self
