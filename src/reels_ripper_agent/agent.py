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
        max_consecutive_text_responses: int = 5,
        max_consecutive_tool_responses: int = 100,
    ) -> None:
        if max_consecutive_text_responses < 1 or max_consecutive_tool_responses < 1:
            raise ValueError("Response limits must be positive")
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.max_consecutive_text_responses = max_consecutive_text_responses
        self.max_consecutive_tool_responses = max_consecutive_tool_responses
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]

    @beartype
    async def run(self, prompt: str) -> str:
        self.messages.append(Message(role="user", content=prompt))
        schemas = [t.schema() for t in self.tools.values()]
        consecutive_text_responses = 0
        consecutive_tool_responses = 0

        while True:
            print("working...")
            reply = await self.llm.complete(
                self.messages, schemas, response_model=AgentResponse
            )
            response = (
                AgentResponse(decision="CONTINUE", content=reply.content or "")
                if reply.tool_calls
                else AgentResponse.model_validate_json(reply.content)
            )
            print(response.content)
            if reply.tool_calls:
                if consecutive_tool_responses >= self.max_consecutive_tool_responses:
                    raise RuntimeError(
                        f"Agent reached the limit of {self.max_consecutive_tool_responses} consecutive tool-call responses"
                    )
                consecutive_tool_responses += 1
                consecutive_text_responses = 0
            self.messages.append(reply)
            if not reply.tool_calls:
                consecutive_tool_responses = 0
                if response.decision == "STOP":
                    return response.content
                consecutive_text_responses += 1
                if consecutive_text_responses >= self.max_consecutive_text_responses:
                    raise RuntimeError(
                        f"Agent reached the limit of {self.max_consecutive_text_responses} consecutive text responses"
                    )
            for call in reply.tool_calls or []:
                result = await self._execute(call)
                print(f"calling tool: {call.function.name}")
                self.messages.append(
                    Message(role="tool", tool_call_id=call.id, content=result)
                )

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
