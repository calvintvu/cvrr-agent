import asyncio
import copy
import io
import json
import os
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import ValidationError
from pydantic_monty import MontyRuntimeError

import reels_ripper_agent as cli
from reels_ripper_agent.llm.base import LLM, Message
from reels_ripper_agent.llm.openrouter import OpenRouterLLM
from reels_ripper_agent.parser import read_parser, save_parser
from reels_ripper_agent.tools.reel_tools import (
    InspectReelsJson,
    InspectReelsJsonArgs,
    repair_parser,
    try_saved_parser,
)

FIRST_URL = "https://www.instagram.com/reel/DS-q1TClQuu/"
SECOND_URL = "https://www.instagram.com/reel/DSeAlkvk1jW/"
FIRST_DATA = {
    "saved_saved_media": [
        {
            "title": "theanomalyvault",
            "string_map_data": {
                "Saved on": {"href": FIRST_URL, "timestamp": 1767520386}
            },
        }
    ]
}
SECOND_DATA = [
    {
        "timestamp": 1779769468,
        "media": [],
        "label_values": [
            {"label": "URL", "value": SECOND_URL, "href": SECOND_URL},
            {"label": "Caption", "value": f"Another reel: {FIRST_URL}"},
            {"label": "Title", "value": ""},
            {"dict": [], "title": "Hashtags"},
            {
                "dict": [
                    {
                        "dict": [
                            {"label": "URL", "value": "http://linktr.ee/revive.wav"},
                            {"label": "Name", "value": "REVIVE RECORDS"},
                            {"label": "Username", "value": "revive.wav"},
                        ],
                        "title": "",
                    }
                ],
                "title": "Owner",
            },
        ],
        "fbid": "17905914705313976",
    }
]
FIRST_CODE = textwrap.dedent("""\
    def parse(data):
        records = data['saved_saved_media']
        if not isinstance(records, list):
            raise ValueError('Expected a saved-post list')
        return [
            {
                'url': record['string_map_data']['Saved on']['href'],
                'author_username': record.get('title') or None,
            }
            for record in records
        ]
""")
SECOND_CODE = textwrap.dedent("""\
    def parse(data):
        if not isinstance(data, list):
            raise ValueError('Expected a saved-post list')
        result = []
        for record in data:
            values = record['label_values']
            urls = [item for item in values if item.get('label') == 'URL']
            if len(urls) != 1:
                raise ValueError('Expected one saved-post URL')
            names = {
                field['value']
                for owner in values if owner.get('title') == 'Owner'
                for group in owner['dict']
                for field in group['dict']
                if field.get('label') == 'Username' and field.get('value')
            }
            result.append({
                'url': urls[0].get('href') or urls[0]['value'],
                'author_username': names.pop() if len(names) == 1 else None,
            })
        return result
""")


class RecordingLLM(LLM):
    def __init__(self, replies: list[Message]) -> None:
        self.replies = iter(replies)
        self.requests: list[list[Message]] = []

    async def complete(self, messages, tools=None, response_model=None) -> Message:
        self.requests.append([message.model_copy(deep=True) for message in messages])
        return next(self.replies)


class ClosingLLM(RecordingLLM):
    def __init__(self, replies: list[Message]) -> None:
        super().__init__(replies)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def tool_reply(
    name: str, args: dict[str, object], call_id: str = "candidate"
) -> Message:
    return Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call_id,
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ],
        }
    )


def stop_reply() -> Message:
    return Message(
        role="assistant", content=json.dumps({"decision": "STOP", "content": "Done."})
    )


class ReelImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_saved_parser_raises(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(FileNotFoundError),
        ):
            await try_saved_parser(FIRST_DATA, Path(directory))

    async def test_repair_then_reuse(self) -> None:
        llm = RecordingLLM(
            [tool_reply("try_reels_parser", {"code": FIRST_CODE}), stop_reply()]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)

            result = await repair_parser(FIRST_DATA, llm, parser_dir, "No parser file")
            cached = await try_saved_parser(FIRST_DATA, parser_dir)

            expected = [{"url": FIRST_URL, "author_username": "theanomalyvault"}]
            self.assertEqual([reel.model_dump() for reel in result], expected)
            self.assertEqual([reel.model_dump() for reel in cached], expected)
            self.assertEqual(read_parser(parser_dir), FIRST_CODE)
            self.assertEqual(len(llm.requests), 2)
            self.assertIn("theanomalyvault", llm.requests[0][-1].content)
            self.assertEqual(
                json.loads(llm.requests[1][-1].content),
                {"status": "accepted", "count": 1},
            )

    async def test_repair_waits_for_model_stop_after_acceptance(self) -> None:
        llm = RecordingLLM(
            [
                tool_reply("try_reels_parser", {"code": FIRST_CODE}),
                Message(
                    role="assistant",
                    content=json.dumps(
                        {"decision": "CONTINUE", "content": "The parser was accepted."}
                    ),
                ),
                stop_reply(),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = await repair_parser(FIRST_DATA, llm, Path(directory), "No parser")

        self.assertEqual(result[0].url, FIRST_URL)
        self.assertEqual(len(llm.requests), 3)

    async def test_model_can_replace_an_empty_accepted_parser(self) -> None:
        empty_code = "def parse(data): return []"
        llm = RecordingLLM(
            [
                tool_reply("try_reels_parser", {"code": empty_code}, "empty"),
                tool_reply("try_reels_parser", {"code": FIRST_CODE}, "corrected"),
                stop_reply(),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            result = await repair_parser(FIRST_DATA, llm, parser_dir, "No parser")

            self.assertEqual(
                [reel.model_dump() for reel in result],
                [{"url": FIRST_URL, "author_username": "theanomalyvault"}],
            )
            self.assertEqual(read_parser(parser_dir), FIRST_CODE)
            self.assertEqual(
                (parser_dir / "previous.py").read_text(encoding="utf-8"), empty_code
            )
            self.assertEqual(
                json.loads(llm.requests[2][-1].content),
                {"status": "accepted", "count": 1},
            )

    async def test_failed_revision_keeps_last_accepted_parser(self) -> None:
        llm = RecordingLLM(
            [
                tool_reply("try_reels_parser", {"code": FIRST_CODE}, "accepted"),
                tool_reply("try_reels_parser", {"code": SECOND_CODE}, "failed"),
                stop_reply(),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            result = await repair_parser(FIRST_DATA, llm, parser_dir, "No parser")

            self.assertEqual(result[0].url, FIRST_URL)
            self.assertEqual(read_parser(parser_dir), FIRST_CODE)
            self.assertFalse((parser_dir / "previous.py").exists())
            self.assertEqual(json.loads(llm.requests[2][-1].content)["status"], "error")

    async def test_candidate_budget_includes_successful_revisions(self) -> None:
        codes = [FIRST_CODE + f"\n# revision {index}\n" for index in range(4)]
        llm = RecordingLLM(
            [
                *(tool_reply("try_reels_parser", {"code": code}) for code in codes),
                stop_reply(),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            result = await repair_parser(FIRST_DATA, llm, parser_dir, "No parser")

            self.assertEqual(result[0].url, FIRST_URL)
            self.assertEqual(read_parser(parser_dir), codes[2])
            self.assertEqual(
                (parser_dir / "previous.py").read_text(encoding="utf-8"), codes[1]
            )
            feedback = json.loads(llm.requests[4][-1].content)
            self.assertEqual(feedback["status"], "error")
            self.assertEqual(feedback["remaining_attempts"], 0)
            self.assertEqual(feedback["error"]["message"], "Candidate limit reached")

    async def test_schema_drift_repairs_parser_and_preserves_previous(self) -> None:
        llm = RecordingLLM(
            [tool_reply("try_reels_parser", {"code": SECOND_CODE}), stop_reply()]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            save_parser(parser_dir, FIRST_CODE)
            with self.assertRaises(MontyRuntimeError) as failure:
                await try_saved_parser(SECOND_DATA, parser_dir)

            result = await repair_parser(
                SECOND_DATA, llm, parser_dir, str(failure.exception)
            )

            self.assertEqual(
                [reel.model_dump() for reel in result],
                [{"url": SECOND_URL, "author_username": "revive.wav"}],
            )
            self.assertEqual(read_parser(parser_dir), SECOND_CODE)
            self.assertEqual(
                (parser_dir / "previous.py").read_text(encoding="utf-8"), FIRST_CODE
            )
            self.assertIn(FIRST_CODE, llm.requests[0][-1].content)

    async def test_reports_execution_failure_before_repair(self) -> None:
        llm = RecordingLLM(
            [
                tool_reply(
                    "try_reels_parser",
                    {"code": "def parse(data): raise ValueError('wrong schema')"},
                    "bad",
                ),
                tool_reply("try_reels_parser", {"code": FIRST_CODE}, "good"),
                stop_reply(),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = await repair_parser(FIRST_DATA, llm, Path(directory), "No parser")

        self.assertEqual(result[0].author_username, "theanomalyvault")
        feedback = json.loads(llm.requests[1][-1].content)
        self.assertEqual(feedback["status"], "error")
        self.assertEqual(feedback["remaining_attempts"], 2)
        self.assertEqual(feedback["error"]["type"], "MontyRuntimeError")
        self.assertIn("wrong schema", feedback["error"]["message"])

    async def test_reports_output_validation_failure_before_repair(self) -> None:
        llm = RecordingLLM(
            [
                tool_reply(
                    "try_reels_parser", {"code": "def parse(data): return {}"}, "bad"
                ),
                tool_reply("try_reels_parser", {"code": FIRST_CODE}, "good"),
                stop_reply(),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = await repair_parser(FIRST_DATA, llm, Path(directory), "No parser")

        self.assertEqual(result[0].url, FIRST_URL)
        feedback = json.loads(llm.requests[1][-1].content)
        self.assertEqual(feedback["error"]["type"], "ValidationError")

    async def test_saved_parser_output_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            save_parser(parser_dir, "def parse(data): return {}")
            with self.assertRaises(ValidationError):
                await try_saved_parser(FIRST_DATA, parser_dir)

    async def test_reordered_labels_ignore_caption_and_owner_links(self) -> None:
        data = copy.deepcopy(SECOND_DATA)
        values = data[0]["label_values"]
        owner = values[-1]
        owner["dict"][0]["dict"].reverse()
        data[0]["label_values"] = [owner, values[3], values[1], values[0], values[2]]
        llm = RecordingLLM(
            [tool_reply("try_reels_parser", {"code": SECOND_CODE}), stop_reply()]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = await repair_parser(data, llm, Path(directory), "New format")

        self.assertEqual(
            [reel.model_dump() for reel in result],
            [{"url": SECOND_URL, "author_username": "revive.wav"}],
        )

    async def test_missing_author_retains_reel(self) -> None:
        data = copy.deepcopy(FIRST_DATA)
        del data["saved_saved_media"][0]["title"]
        llm = RecordingLLM(
            [tool_reply("try_reels_parser", {"code": FIRST_CODE}), stop_reply()]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = await repair_parser(data, llm, Path(directory), "No parser")

        self.assertEqual(
            [reel.model_dump() for reel in result],
            [{"url": FIRST_URL, "author_username": None}],
        )

    async def test_empty_output_is_accepted(self) -> None:
        code = "def parse(data): return []"
        llm = RecordingLLM(
            [tool_reply("try_reels_parser", {"code": code}), stop_reply()]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)

            self.assertEqual(await repair_parser([], llm, parser_dir, "No parser"), [])
            self.assertEqual(read_parser(parser_dir), code)
            self.assertEqual(len(llm.requests), 2)

    async def test_early_stop_cannot_publish_prose_as_results(self) -> None:
        llm = RecordingLLM(
            [
                Message(
                    role="assistant",
                    content=json.dumps(
                        {"decision": "STOP", "content": "Parsed successfully"}
                    ),
                )
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            save_parser(parser_dir, FIRST_CODE)

            with self.assertRaisesRegex(RuntimeError, "without a valid parser"):
                await repair_parser(SECOND_DATA, llm, parser_dir, "Schema drift")

            self.assertEqual(read_parser(parser_dir), FIRST_CODE)
            self.assertFalse((parser_dir / "previous.py").exists())

    async def test_three_failed_candidates_preserve_saved_parser(self) -> None:
        replies = [
            tool_reply(
                "try_reels_parser", {"code": "def parse(data): return {}"}, str(index)
            )
            for index in range(3)
        ]
        replies.append(stop_reply())
        llm = RecordingLLM(replies)
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            save_parser(parser_dir, FIRST_CODE)

            with self.assertRaisesRegex(RuntimeError, "3 attempts"):
                await repair_parser(SECOND_DATA, llm, parser_dir, "Schema drift")

            self.assertEqual(read_parser(parser_dir), FIRST_CODE)
            self.assertFalse((parser_dir / "previous.py").exists())
            self.assertEqual(len(llm.requests), 4)
            feedback = json.loads(llm.requests[-1][-1].content)
            self.assertEqual(feedback["remaining_attempts"], 0)

    async def test_candidate_budget_applies_within_one_tool_batch(self) -> None:
        reply = tool_reply(
            "try_reels_parser", {"code": "def parse(data): return {}"}, "0"
        )
        for index, code in enumerate(
            ["def parse(data): return {}", "def parse(data): return {}", FIRST_CODE], 1
        ):
            reply.tool_calls.extend(
                tool_reply("try_reels_parser", {"code": code}, str(index)).tool_calls
            )
        llm = RecordingLLM([reply, stop_reply()])
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)

            with self.assertRaisesRegex(RuntimeError, "3 attempts"):
                await repair_parser(FIRST_DATA, llm, parser_dir, "No parser")

            self.assertFalse((parser_dir / "latest.py").exists())
            self.assertEqual(len(llm.requests), 2)
            feedback = json.loads(llm.requests[-1][-1].content)
            self.assertEqual(feedback["remaining_attempts"], 0)
            self.assertEqual(feedback["error"]["message"], "Candidate limit reached")

    async def test_existing_agent_response_limit_bounds_tool_activity(self) -> None:
        llm = RecordingLLM(
            [tool_reply("unknown_tool", {}, str(index)) for index in range(13)]
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(RuntimeError, "12 consecutive tool-call responses"),
        ):
            await repair_parser(FIRST_DATA, llm, Path(directory), "No parser")

        self.assertEqual(len(llm.requests), 13)

    async def test_agent_can_inspect_more_data_before_submitting(self) -> None:
        llm = RecordingLLM(
            [
                tool_reply(
                    "inspect_reels_json",
                    {"path": [0, "label_values"], "offset": 3, "limit": 2},
                    "inspect",
                ),
                tool_reply("try_reels_parser", {"code": SECOND_CODE}),
                stop_reply(),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = await repair_parser(
                SECOND_DATA, llm, Path(directory), "New format"
            )

        self.assertEqual(result[0].author_username, "revive.wav")
        inspected = json.loads(llm.requests[1][-1].content)
        self.assertEqual(inspected["length"], 5)
        self.assertEqual(json.loads(inspected["sample"])[1]["title"], "Owner")


class JsonInspectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_nested_path_and_pagination(self) -> None:
        tool = InspectReelsJson({"records": [{"values": [0, 1, 2, 3, 4]}]})

        result = json.loads(
            await tool.execute(
                InspectReelsJsonArgs(path=["records", 0, "values"], offset=2, limit=2)
            )
        )

        self.assertEqual(result["type"], "list")
        self.assertEqual(result["length"], 5)
        self.assertEqual(json.loads(result["sample"]), [2, 3])
        self.assertFalse(result["truncated"])

    async def test_dictionary_pagination(self) -> None:
        tool = InspectReelsJson({"first": 1, "second": 2, "third": 3})

        result = json.loads(await tool.execute(InspectReelsJsonArgs(offset=1, limit=1)))

        self.assertEqual(result["type"], "dict")
        self.assertEqual(result["length"], 3)
        self.assertEqual(json.loads(result["sample"]), {"second": 2})

    async def test_inspection_text_is_bounded(self) -> None:
        tool = InspectReelsJson({"caption": "x" * 100_000})

        result = json.loads(await tool.execute(InspectReelsJsonArgs()))

        self.assertEqual(len(result["sample"]), 12_000)
        self.assertTrue(result["truncated"])

    async def test_invalid_path_is_reported(self) -> None:
        tool = InspectReelsJson({"records": []})
        for path in [["missing"], ["records", -1], ["records", 0], ["records", "0"]]:
            with self.subTest(path=path), self.assertRaises((KeyError, ValueError)):
                await tool.execute(InspectReelsJsonArgs(path=path))

    async def test_inspection_argument_limits(self) -> None:
        for args in [{"offset": -1}, {"limit": 0}, {"limit": 11}, {"path": [True]}]:
            with self.subTest(args=args), self.assertRaises(ValidationError):
                InspectReelsJsonArgs.model_validate(args)


class CliImportTests(unittest.TestCase):
    def _invoke(
        self, args: list[str], parser_dir: Path, llm: LLM | None = None
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        status = 0
        with (
            patch("sys.argv", ["reels-ripper-agent", *args]),
            patch.object(cli, "DEFAULT_PARSER_DIR", parser_dir, create=True),
            patch.object(cli, "load_dotenv"),
            patch.object(cli, "OpenRouterLLM") as factory,
            patch.dict(os.environ, {}, clear=True),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            if llm is None:
                factory.side_effect = AssertionError(
                    "The CLI must not create an LLM client"
                )
            else:
                factory.return_value = llm
            try:
                cli.main()
            except SystemExit as error:
                status = error.code if isinstance(error.code, int) else 1
        return status, stdout.getvalue(), stderr.getvalue()

    def test_cached_cli_import_without_credentials_or_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory) / "parsers"
            source = Path(directory) / "saved posts.json"
            source.write_text(json.dumps(FIRST_DATA), encoding="utf-8")
            save_parser(parser_dir, FIRST_CODE)

            status, stdout, stderr = self._invoke(
                ["--reels-file", str(source)], parser_dir
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(
                json.loads(stdout),
                [{"url": FIRST_URL, "author_username": "theanomalyvault"}],
            )
            self.assertEqual(stderr, "")
            self.assertEqual(read_parser(parser_dir), FIRST_CODE)

    def test_real_adapter_keeps_native_tools_available(self) -> None:
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            requests.append(payload)
            if payload.get("response_format", {}).get("type") == "json_object":
                message = Message(
                    role="assistant",
                    content=json.dumps(
                        {
                            "decision": "STOP",
                            "content": "Parser tool unavailable in JSON-only mode.",
                        }
                    ),
                )
            elif any(message["role"] == "tool" for message in payload["messages"]):
                message = stop_reply()
            else:
                message = tool_reply("try_reels_parser", {"code": FIRST_CODE})
            return httpx.Response(
                200,
                json={"choices": [{"message": message.model_dump(exclude_none=True)}]},
            )

        llm = OpenRouterLLM(api_key="test")
        asyncio.run(llm.aclose())
        llm._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory) / "parsers"
            source = Path(directory) / "input.json"
            source.write_text(json.dumps(FIRST_DATA), encoding="utf-8")

            status, stdout, stderr = self._invoke(
                ["--reels-file", str(source)], parser_dir, llm
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(
                json.loads(stdout),
                [{"url": FIRST_URL, "author_username": "theanomalyvault"}],
            )
            self.assertEqual(read_parser(parser_dir), FIRST_CODE)
            self.assertTrue(llm._client.is_closed)
            self.assertEqual(len(requests), 2)
            for payload in requests:
                self.assertEqual(payload["response_format"]["type"], "json_schema")
                self.assertTrue(payload["response_format"]["json_schema"]["strict"])
                self.assertEqual(
                    [tool["function"]["name"] for tool in payload["tools"]],
                    ["inspect_reels_json", "try_reels_parser"],
                )

    def test_cached_empty_output_does_not_create_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory) / "parsers"
            source = Path(directory) / "empty.json"
            source.write_text("[]", encoding="utf-8")
            save_parser(parser_dir, "def parse(data): return []")

            status, stdout, stderr = self._invoke(
                ["--reels-file", str(source)], parser_dir
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout), [])
            self.assertEqual(stderr, "")

    def test_cli_generates_first_parser_and_closes_client(self) -> None:
        llm = ClosingLLM(
            [tool_reply("try_reels_parser", {"code": FIRST_CODE}), stop_reply()]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory) / "parsers"
            source = Path(directory) / "input.json"
            source.write_text(json.dumps(FIRST_DATA), encoding="utf-8")

            status, stdout, stderr = self._invoke(
                ["--reels-file", str(source)], parser_dir, llm
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(
                json.loads(stdout),
                [{"url": FIRST_URL, "author_username": "theanomalyvault"}],
            )
            self.assertIn("working...", stderr)
            self.assertEqual(read_parser(parser_dir), FIRST_CODE)
            self.assertTrue(llm.closed)
            self.assertEqual(len(llm.requests), 2)

    def test_cli_repairs_schema_drift_and_preserves_previous(self) -> None:
        llm = ClosingLLM(
            [tool_reply("try_reels_parser", {"code": SECOND_CODE}), stop_reply()]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory) / "parsers"
            source = Path(directory) / "input.json"
            source.write_text(json.dumps(SECOND_DATA), encoding="utf-8")
            save_parser(parser_dir, FIRST_CODE)

            status, stdout, stderr = self._invoke(
                ["--reels-file", str(source)], parser_dir, llm
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(
                json.loads(stdout),
                [{"url": SECOND_URL, "author_username": "revive.wav"}],
            )
            self.assertEqual(read_parser(parser_dir), SECOND_CODE)
            self.assertEqual(
                (parser_dir / "previous.py").read_text(encoding="utf-8"), FIRST_CODE
            )
            self.assertTrue(llm.closed)

    def test_cli_failed_candidates_exit_nonzero_and_preserve_parser(self) -> None:
        llm = ClosingLLM(
            [
                *[
                    tool_reply(
                        "try_reels_parser",
                        {"code": "def parse(data): return {}"},
                        str(index),
                    )
                    for index in range(3)
                ],
                stop_reply(),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory) / "parsers"
            source = Path(directory) / "input.json"
            source.write_text(json.dumps(SECOND_DATA), encoding="utf-8")
            save_parser(parser_dir, FIRST_CODE)

            status, stdout, stderr = self._invoke(
                ["--reels-file", str(source)], parser_dir, llm
            )

            self.assertEqual(status, 1)
            self.assertEqual(stdout, "")
            self.assertIn("3 attempts", stderr)
            self.assertEqual(read_parser(parser_dir), FIRST_CODE)
            self.assertFalse((parser_dir / "previous.py").exists())
            self.assertTrue(llm.closed)

    def test_cli_early_model_stop_is_failure(self) -> None:
        llm = ClosingLLM([stop_reply()])
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory) / "parsers"
            source = Path(directory) / "input.json"
            source.write_text(json.dumps(FIRST_DATA), encoding="utf-8")

            status, stdout, stderr = self._invoke(
                ["--reels-file", str(source)], parser_dir, llm
            )

            self.assertEqual(status, 1)
            self.assertEqual(stdout, "")
            self.assertIn("without a valid parser", stderr)
            self.assertFalse((parser_dir / "latest.py").exists())
            self.assertTrue(llm.closed)

    def test_missing_input_does_not_create_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.json"

            status, stdout, stderr = self._invoke(
                ["--reels-file", str(source)], Path(directory)
            )

            self.assertEqual(status, 1)
            self.assertEqual(stdout, "")
            self.assertIn("missing.json", stderr)

    def test_existing_prompt_and_default_modes(self) -> None:
        for args, expected in [
            (["Compare", "weather"], "Compare weather"),
            ([], "What's the weather in Tokyo?"),
        ]:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as directory:
                llm = ClosingLLM([stop_reply()])

                status, stdout, stderr = self._invoke(args, Path(directory), llm)

                self.assertEqual(status, 0, stderr)
                self.assertEqual(stdout, "Done.\n")
                self.assertEqual(llm.requests[0][-1].content, expected)
                self.assertTrue(llm.closed)

    def test_cli_help_is_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status, stdout, stderr = self._invoke(["--help"], Path(directory))

        self.assertEqual(status, 0)
        self.assertIn("--reels-file", stdout)
        self.assertEqual(stderr, "")

    def test_cli_rejects_file_and_prompt_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status, stdout, stderr = self._invoke(
                ["--reels-file", "input.json", "extra prompt"], Path(directory)
            )

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("prompt", stderr)
