from typing import Literal

from beartype import beartype
from pydantic import BaseModel, ConfigDict, ValidationError

from reels_ripper_agent.llm.base import LLM, Message, ToolCall
from reels_ripper_agent.tools import Tool


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["STOP", "CONTINUE"]
    content: str


class Agent:
    @beartype
    def __init__(
        self,
        llm: LLM,
        tools: list[Tool],
        system_prompt: str = """
        You are a helpful assistant with access to tools.
        Use tools whenever they help you accomplish your tasks or give more accurate answers.
        When the task is complete, respond with decision STOP and your final answer in content.
        Otherwise, use tools or respond with decision CONTINUE and a brief progress update in content.
        """,
        max_steps: int = 10,
    ) -> None:
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.max_steps = max_steps
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]

    @beartype
    async def run(self, prompt: str) -> str:
        self.messages.append(Message(role="user", content=prompt))
        schemas = [t.schema() for t in self.tools.values()]

        for _ in range(self.max_steps):
            reply = await self.llm.complete(
                self.messages, schemas, response_model=AgentResponse
            )
            self.messages.append(reply)
            if not reply.tool_calls:
                response = AgentResponse.model_validate_json(reply.content)
                if response.decision == "STOP":
                    return response.content
            for call in reply.tool_calls or []:
                result = await self._execute(call)
                self.messages.append(
                    Message(role="tool", tool_call_id=call.id, content=result)
                )

        raise RuntimeError(f"Agent did not finish within {self.max_steps} steps")

    @beartype
    async def _execute(self, call: ToolCall) -> str:
        tool = self.tools.get(call.function.name)
        if tool is None:
            return f"Error: unknown tool '{call.function.name}'"
        try:
            args = tool.args_model.model_validate_json(call.function.arguments or "{}")
        except ValidationError as e:
            return f"Error: invalid arguments: {e}"
        try:
            return await tool.execute(args)
        except Exception as e:  # noqa: BLE001 - report tool failures to the model
            return f"Error: {type(e).__name__}: {e}"
