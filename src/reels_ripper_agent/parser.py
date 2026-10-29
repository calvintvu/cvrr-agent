import asyncio
import os
import tempfile
from pathlib import Path

from beartype import beartype
from pydantic_monty import AsyncMonty

DEFAULT_PARSER_DIR = Path(".reels-parser")


@beartype
async def run_parser(code: str, data: object) -> object:
    """Run parse(data) in a fresh sandbox with execution and memory limits."""

    @beartype
    async def execute() -> object:
        async with (
            AsyncMonty(max_processes=1, request_timeout=5) as pool,
            pool.checkout(
                script_name="parser.py",
                limits={"max_feed_duration_secs": 2.0, "max_memory": 32 * 1024 * 1024},
            ) as session,
        ):
            return await session.feed_run(
                f"{code}\n\nparse(data)",
                inputs={"data": data},
                print_callback=lambda _stream, _text: None,
            )

    return await asyncio.wait_for(execute(), timeout=5)


@beartype
def read_parser(parser_dir: Path) -> str:
    return (parser_dir / "latest.py").read_text(encoding="utf-8")


@beartype
def _atomic_write(path: Path, code: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(code)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@beartype
def save_parser(parser_dir: Path, code: str) -> None:
    """Store source after the caller has checked its execution and output."""
    parser_dir.mkdir(parents=True, exist_ok=True)
    try:
        previous = read_parser(parser_dir)
    except FileNotFoundError:
        pass
    else:
        _atomic_write(parser_dir / "previous.py", previous)
    _atomic_write(parser_dir / "latest.py", code)
