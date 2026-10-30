import asyncio
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pydantic_monty import MontyRuntimeError, MontySyntaxError

from reels_ripper_agent.parser import read_parser, run_parser, save_parser


class ParserExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_parser(self) -> None:
        data = [
            {"url": "https://www.instagram.com/reel/example/", "author_username": None}
        ]

        result = await run_parser("def parse(data): return data", data)

        self.assertEqual(
            result,
            [
                {
                    "url": "https://www.instagram.com/reel/example/",
                    "author_username": None,
                }
            ],
        )

    async def test_sandbox_cannot_mutate_host_input(self) -> None:
        data = {"records": [1, 2, 3]}

        self.assertEqual(
            await run_parser("def parse(data): data.clear(); return []", data), []
        )
        self.assertEqual(data, {"records": [1, 2, 3]})

    async def test_reports_parser_exception(self) -> None:
        with self.assertRaisesRegex(MontyRuntimeError, "unsupported format"):
            await run_parser(
                "def parse(data): raise ValueError('unsupported format')", {}
            )

    async def test_reports_syntax_error(self) -> None:
        with self.assertRaises(MontySyntaxError):
            await run_parser("def parse(:", {})

    async def test_requires_parse_entry_point(self) -> None:
        with self.assertRaisesRegex(MontyRuntimeError, "parse"):
            await run_parser("value = 1", {})

    async def test_stops_infinite_loop(self) -> None:
        with self.assertRaisesRegex(MontyRuntimeError, "TimeoutError"):
            await asyncio.wait_for(
                run_parser("def parse(data):\n    while True:\n        pass", {}),
                timeout=8,
            )

    async def test_limits_memory(self) -> None:
        with self.assertRaisesRegex(MontyRuntimeError, "MemoryError"):
            await run_parser("def parse(data): return [0] * 20_000_000", {})

    async def test_host_deadline_includes_sleep(self) -> None:
        with self.assertRaises(asyncio.TimeoutError):
            await run_parser("import time\ndef parse(data): time.sleep(60)", {})

    async def test_blocks_host_file_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.txt"
            path.write_text("host-only value", encoding="utf-8")

            for body in [
                "return open(data).read()",
                "open(data, 'w').write('overwritten')",
            ]:
                with self.subTest(body=body), self.assertRaises(MontyRuntimeError):
                    await run_parser(f"def parse(data): {body}", str(path))

            self.assertEqual(path.read_text(encoding="utf-8"), "host-only value")

    async def test_blocks_host_environment_access(self) -> None:
        with (
            patch.dict(os.environ, {"REELS_MONTY_TEST_SECRET": "host-only value"}),
            self.assertRaises(MontyRuntimeError),
        ):
            await run_parser(
                "import os\ndef parse(data): return os.environ['REELS_MONTY_TEST_SECRET']",
                {},
            )

    async def test_parser_prints_do_not_pollute_host_output(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = await run_parser("def parse(data): print('debug'); return []", {})

        self.assertEqual(result, [])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")


class ParserStorageTests(unittest.TestCase):
    def test_missing_parser_raises(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(FileNotFoundError),
        ):
            read_parser(Path(directory))

    def test_first_save_creates_directory_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory) / "parsers"
            source = "# café\ndef parse(data): return data\n"

            save_parser(parser_dir, source)

            self.assertEqual(read_parser(parser_dir), source)
            self.assertFalse((parser_dir / "previous.py").exists())
            self.assertEqual(
                {path.name for path in parser_dir.iterdir()}, {"latest.py"}
            )

    def test_replacement_preserves_immediately_previous_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            for source in ["first", "second", "third"]:
                save_parser(parser_dir, source)

            self.assertEqual(read_parser(parser_dir), "third")
            self.assertEqual(
                (parser_dir / "previous.py").read_text(encoding="utf-8"), "second"
            )
            self.assertEqual(
                {path.name for path in parser_dir.iterdir()},
                {"latest.py", "previous.py"},
            )

    def test_failed_replacement_keeps_latest_and_cleans_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            save_parser(parser_dir, "working parser")
            replace = os.replace

            def fail_latest(source, destination):
                if Path(destination).name == "latest.py":
                    raise OSError("simulated replacement failure")
                return replace(source, destination)

            with (
                patch("reels_ripper_agent.parser.os.replace", side_effect=fail_latest),
                self.assertRaisesRegex(OSError, "simulated replacement failure"),
            ):
                save_parser(parser_dir, "candidate parser")

            self.assertEqual(read_parser(parser_dir), "working parser")
            self.assertEqual(
                (parser_dir / "previous.py").read_text(encoding="utf-8"),
                "working parser",
            )
            self.assertEqual(
                {path.name for path in parser_dir.iterdir()},
                {"latest.py", "previous.py"},
            )

    def test_failed_backup_preserves_both_saved_parsers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parser_dir = Path(directory)
            save_parser(parser_dir, "first")
            save_parser(parser_dir, "second")

            with (
                patch(
                    "reels_ripper_agent.parser.os.replace",
                    side_effect=OSError("backup failed"),
                ),
                self.assertRaisesRegex(OSError, "backup failed"),
            ):
                save_parser(parser_dir, "third")

            self.assertEqual(read_parser(parser_dir), "second")
            self.assertEqual(
                (parser_dir / "previous.py").read_text(encoding="utf-8"), "first"
            )
            self.assertEqual(
                {path.name for path in parser_dir.iterdir()},
                {"latest.py", "previous.py"},
            )
