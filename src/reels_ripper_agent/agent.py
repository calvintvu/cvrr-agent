import sys
import time

from beartype import beartype
from pydantic import ValidationError

from reels_ripper_agent.db import operations as db
from reels_ripper_agent.llm.base import LLM, Message, ToolCall
from reels_ripper_agent.tools.base import Tool


def _show_commentary(text: str) -> None:
    print(f"\033[2m{text}\033[0m" if sys.stdout.isatty() else text)


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
        self.system_prompt = system_prompt
        self.messages: list[Message] = []
        self.run_id: int | None = None

    @beartype
    async def run(self, prompt: str) -> str:
        """Start a new run. Each message is saved before the loop uses it."""
        self.messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=prompt),
        ]
        self.run_id = db.create_run(self.messages)
        return await self._loop()

    @beartype
    async def resume(self, run_id: int) -> str:
        """Continue a run from its saved messages. If the last message is a
        final answer, the crash came before the run was marked done: mark it
        now. Otherwise first run the tool calls of the last assistant message
        that have no saved result."""
        self.run_id = run_id
        self.messages = db.load_messages(run_id)
        final = self.messages[-1]
        if final.role == "assistant" and not final.tool_calls:
            result = final.content or ""
            db.finish_run(run_id, "done", result)
            return result
        last = next(
            (
                i
                for i in reversed(range(len(self.messages)))
                if self.messages[i].role == "assistant"
            ),
            None,
        )
        if last is not None:
            answered = {m.tool_call_id for m in self.messages[last + 1 :]}
            for call in self.messages[last].tool_calls or []:
                if call.id not in answered:
                    await self._run_tool_call(call)
        return await self._loop()

    @beartype
    def _append(self, message: Message) -> None:
        assert self.run_id is not None
        db.append_message(self.run_id, len(self.messages), message)
        self.messages.append(message)

    @beartype
    async def _run_tool_call(self, call: ToolCall) -> None:
        result = await self._execute(call)
        self._append(Message(role="tool", tool_call_id=call.id, content=result))

    @beartype
    async def _loop(self) -> str:
        assert self.run_id is not None
        started_at = time.perf_counter()
        tools = [t.schema() for t in self.tools.values()]
        turns_used = sum(m.role == "assistant" for m in self.messages)

        for _ in range(self.max_turns - turns_used):
            print("working...")
            reply = await self.llm.complete(messages=self.messages, tools=tools)
            self._append(reply)
            if reply.reasoning:
                _show_commentary(reply.reasoning)
            if not reply.tool_calls:
                _show_commentary(
                    f"Agent loop completed in {time.perf_counter() - started_at:.2f}s"
                )
                result = reply.content or ""
                db.finish_run(self.run_id, "done", result)
                return result
            if reply.content:
                _show_commentary(reply.content)

            for call in reply.tool_calls:
                await self._run_tool_call(call)

        db.finish_run(self.run_id, "failed", None)
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
        print(f"→ {call.function.name}({call.function.arguments or '{}'})")
        try:
            return await tool.execute(args)
        except Exception as e:  # noqa: BLE001 - report tool failures to the model
            return f"Error: {type(e).__name__}: {e}"
