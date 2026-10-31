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
        When the task is complete, reply with your final answer and no tool calls.
        """,
        max_turns: int = 100,
    ) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be positive")
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.max_turns = max_turns
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]

    @beartype
    async def run(self, prompt: str) -> str:
        self.messages.append(Message(role="user", content=prompt))
        tools = [t.schema() for t in self.tools.values()]

        for _ in range(self.max_turns):
            print("working...")
            reply = await self.llm.complete(messages=self.messages, tools=tools)
            self.messages.append(reply)
            if not reply.tool_calls:
                return reply.content or ""

            for call in reply.tool_calls:
                result = await self._execute(call)
                self.messages.append(
                    Message(role="tool", tool_call_id=call.id, content=result)
                )

        raise RuntimeError(f"Agent reached the limit of {self.max_turns} turns")

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
