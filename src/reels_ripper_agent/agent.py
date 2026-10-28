from beartype import beartype
from pydantic import ValidationError

from reels_ripper_agent.llm.base import LLM, Message, ToolCall
from reels_ripper_agent.tools import Tool


class Agent:
    @beartype
    def __init__(
        self,
        llm: LLM,
        tools: list[Tool],
        system_prompt: str = """
        You are a helpful assistant with access to tools.
        Use tools whenever they help you accomplish your tasks or give more accurate answers.
        When you have enough information, respond directly and concisely.
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
            reply = await self.llm.complete(self.messages, schemas)
            self.messages.append(reply)
            if not reply.tool_calls:
                return reply.content or ""
            for call in reply.tool_calls:
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
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
