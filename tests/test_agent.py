import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import httpx
from pydantic import ValidationError

from reels_ripper_agent.agent import Agent, AgentResponse
from reels_ripper_agent.llm.base import LLM, Message
from reels_ripper_agent.llm.openrouter import OpenRouterLLM
from reels_ripper_agent.tools.base import GetWeather


class ScriptedLLM(LLM):
    def __init__(self, replies: list[Message]) -> None:
        self.replies = iter(replies)

    async def complete(self, messages, tools=None, response_model=None) -> Message:
        return next(self.replies)


def tool_reply(name: str, arguments: str, call_id: str) -> Message:
    return Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call_id,
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        }
    )


def text_reply(decision: str, content: str) -> Message:
    return Message(
        role="assistant", content=json.dumps({"decision": decision, "content": content})
    )


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_commentary_is_normalized_before_final_response(self) -> None:
        for content in [None, "", "I'll check Tokyo for you."]:
            with self.subTest(content=content):
                reply = tool_reply("get_weather", '{"city": "Tokyo"}', "tokyo")
                reply.content = content
                agent = Agent(
                    ScriptedLLM([reply, text_reply("STOP", "Tokyo is sunny.")]),
                    tools=[GetWeather()],
                )
                output = StringIO()
                stdout = StringIO()

                with redirect_stderr(output), redirect_stdout(stdout):
                    result = await agent.run("Check Tokyo.")

                self.assertEqual(result, "Tokyo is sunny.")
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(
                    output.getvalue().splitlines(),
                    [
                        "working...",
                        content or "",
                        "calling tool: get_weather",
                        "working...",
                        "Tokyo is sunny.",
                    ],
                )
                self.assertIs(agent.messages[2], reply)
                self.assertEqual(reply.content, content)
                self.assertEqual(agent.messages[3].tool_call_id, "tokyo")
                self.assertEqual(
                    agent.messages[3].content, "It is 22°C and sunny in Tokyo."
                )

    async def test_continues_through_text_until_structured_stop(self) -> None:
        replies = iter(
            [
                tool_reply("get_weather", '{"city": "Tokyo"}', "tokyo"),
                Message(
                    role="assistant",
                    content='{"decision": "CONTINUE", "content": "I should also check Paris."}',
                ),
                tool_reply("get_weather", '{"city": "Paris"}', "paris"),
                Message(
                    role="assistant",
                    content='{"decision": "STOP", "content": "Both cities are sunny."}',
                ),
            ]
        )
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": next(replies).model_dump(exclude_none=True)}
                    ]
                },
            )

        llm = OpenRouterLLM(api_key="test")
        await llm.aclose()
        llm._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        agent = Agent(llm, tools=[GetWeather()])
        try:
            result = await agent.run("Compare the weather in Tokyo and Paris.")
        finally:
            await llm.aclose()

        self.assertEqual(result, "Both cities are sunny.")
        self.assertEqual(
            [message.content for message in agent.messages if message.role == "tool"],
            [
                "It is 22°C and sunny in Tokyo.",
                "It is 22°C and sunny in Paris.",
            ],
        )
        self.assertEqual(len(requests), 4)
        for request in requests:
            self.assertEqual(
                [tool["function"]["name"] for tool in request["tools"]], ["get_weather"]
            )
            self.assertEqual(request["response_format"]["type"], "json_schema")
            self.assertEqual(
                request["response_format"]["json_schema"]["name"], "AgentResponse"
            )
            self.assertTrue(request["response_format"]["json_schema"]["strict"])
            self.assertTrue(request["provider"]["require_parameters"])
            self.assertEqual(
                [
                    message
                    for message in request["messages"]
                    if message["role"] == "system"
                ],
                [agent.messages[0].model_dump(exclude_none=True)],
            )
            schema = request["response_format"]["json_schema"]["schema"]
            self.assertEqual(
                schema["properties"]["decision"]["enum"], ["STOP", "CONTINUE"]
            )
            self.assertEqual(schema["properties"]["content"]["type"], "string")
            self.assertEqual(set(schema["required"]), {"decision", "content"})
            self.assertFalse(schema["additionalProperties"])

    async def test_schema_is_enforced_without_tools(self) -> None:
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"decision": "STOP", "content": "Done."}',
                            }
                        }
                    ]
                },
            )

        llm = OpenRouterLLM(api_key="test")
        await llm.aclose()
        llm._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        messages = [Message(role="user", content="Finish.")]
        try:
            for tools in [None, []]:
                with self.subTest(tools=tools):
                    response = await llm.complete(
                        messages, tools=tools, response_model=AgentResponse
                    )
                    self.assertEqual(
                        AgentResponse.model_validate_json(response.content).decision,
                        "STOP",
                    )
        finally:
            await llm.aclose()

        for request in requests:
            self.assertEqual(
                request["response_format"],
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "AgentResponse",
                        "strict": True,
                        "schema": AgentResponse.model_json_schema(),
                    },
                },
            )
            self.assertTrue(request["provider"]["require_parameters"])
            self.assertNotIn("tools", request)
            self.assertEqual(
                request["messages"], [{"role": "user", "content": "Finish."}]
            )
        self.assertEqual(messages, [Message(role="user", content="Finish.")])

    async def test_rejects_invalid_structured_response(self) -> None:
        for content in [
            None,
            "not json",
            "{}",
            '{"decision": "DONE", "content": "Done."}',
            '{"decision": "STOP"}',
            '{"decision": "STOP", "content": 123}',
            '{"decision": "STOP", "content": "Done.", "extra": true}',
        ]:
            with self.subTest(content=content):
                llm = ScriptedLLM([Message(role="assistant", content=content)])
                agent = Agent(llm, tools=[])

                with self.assertRaises(ValidationError):
                    await agent.run("Finish.")

    async def test_consecutive_text_responses_reach_limit(self) -> None:
        llm = ScriptedLLM(
            [text_reply("CONTINUE", "Still working.")] * 3
            + [text_reply("STOP", "Done.")]
        )
        agent = Agent(llm, tools=[], max_consecutive_text_responses=3)

        with self.assertRaisesRegex(RuntimeError, "3 consecutive text responses"):
            await agent.run("Keep working.")

    async def test_stop_at_text_limit_allows_empty_answer(self) -> None:
        llm = ScriptedLLM([text_reply("STOP", "")])
        agent = Agent(llm, tools=[], max_consecutive_text_responses=1)

        self.assertEqual(await agent.run("Finish silently."), "")

    async def test_tool_chain_can_exceed_old_step_limit(self) -> None:
        replies = [
            tool_reply("get_weather", '{"city": "Tokyo"}', str(i)) for i in range(12)
        ]
        replies.append(text_reply("STOP", "Done."))
        agent = Agent(ScriptedLLM(replies), tools=[GetWeather()])

        self.assertEqual(await agent.run("Keep checking the weather."), "Done.")
        self.assertEqual(
            len([message for message in agent.messages if message.role == "tool"]), 12
        )

    async def test_tool_response_resets_consecutive_text_count(self) -> None:
        llm = ScriptedLLM(
            [
                text_reply("CONTINUE", "Check Tokyo."),
                tool_reply("get_weather", '{"city": "Tokyo"}', "tokyo"),
                text_reply("CONTINUE", "The result looks useful."),
                text_reply("STOP", "Tokyo is sunny."),
            ]
        )
        agent = Agent(llm, tools=[GetWeather()], max_consecutive_text_responses=2)

        self.assertEqual(await agent.run("Check Tokyo."), "Tokyo is sunny.")

    async def test_text_response_resets_consecutive_tool_count(self) -> None:
        llm = ScriptedLLM(
            [
                tool_reply("get_weather", '{"city": "Tokyo"}', "tokyo"),
                text_reply("CONTINUE", "Check Paris."),
                tool_reply("get_weather", '{"city": "Paris"}', "paris"),
                text_reply("CONTINUE", "Check Berlin."),
                tool_reply("get_weather", '{"city": "Berlin"}', "berlin"),
                text_reply("STOP", "Done."),
            ]
        )
        agent = Agent(llm, tools=[GetWeather()], max_consecutive_tool_responses=2)

        self.assertEqual(await agent.run("Compare cities."), "Done.")
        self.assertEqual(
            [
                message.tool_call_id
                for message in agent.messages
                if message.role == "tool"
            ],
            ["tokyo", "paris", "berlin"],
        )
        self.assertEqual(agent.messages[-1].role, "assistant")
        self.assertIsNone(agent.messages[-1].tool_calls)

    async def test_consecutive_tool_responses_reach_limit(self) -> None:
        llm = ScriptedLLM(
            [
                tool_reply("get_weather", '{"city": "Tokyo"}', "tokyo"),
                tool_reply("get_weather", '{"city": "Paris"}', "paris"),
                tool_reply("get_weather", '{"city": "Berlin"}', "berlin"),
                text_reply("STOP", "Done."),
            ]
        )
        agent = Agent(llm, tools=[GetWeather()], max_consecutive_tool_responses=2)

        with self.assertRaisesRegex(RuntimeError, "2.*tool-call responses"):
            await agent.run("Compare cities.")
        self.assertEqual(
            [
                message.tool_call_id
                for message in agent.messages
                if message.role == "tool"
            ],
            ["tokyo", "paris"],
        )
        self.assertEqual(agent.messages[-1].role, "tool")

    async def test_multiple_tool_calls_count_as_one_response(self) -> None:
        reply = tool_reply("get_weather", '{"city": "Tokyo"}', "tokyo")
        reply.tool_calls.extend(
            tool_reply("get_weather", '{"city": "Paris"}', "paris").tool_calls
        )
        llm = ScriptedLLM([reply, text_reply("STOP", "Both cities are sunny.")])
        agent = Agent(llm, tools=[GetWeather()], max_consecutive_tool_responses=1)

        self.assertEqual(await agent.run("Compare cities."), "Both cities are sunny.")
        self.assertEqual(
            [
                message.tool_call_id
                for message in agent.messages
                if message.role == "tool"
            ],
            ["tokyo", "paris"],
        )

    def test_response_limits_must_be_positive(self) -> None:
        for limits in [
            {"max_consecutive_text_responses": 0},
            {"max_consecutive_text_responses": -1},
            {"max_consecutive_tool_responses": 0},
            {"max_consecutive_tool_responses": -1},
        ]:
            with (
                self.subTest(limits=limits),
                self.assertRaisesRegex(ValueError, "positive"),
            ):
                Agent(ScriptedLLM([]), tools=[], **limits)
