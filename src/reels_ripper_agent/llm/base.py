from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel


class FunctionCall(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@runtime_checkable
class LLM(Protocol):
    async def complete(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> Message: ...
