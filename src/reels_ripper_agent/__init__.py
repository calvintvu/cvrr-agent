import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from beartype import beartype
from dotenv import load_dotenv
from pydantic_monty import MontyError

from reels_ripper_agent.agent import Agent
from reels_ripper_agent.llm.openrouter import OpenRouterLLM
from reels_ripper_agent.parser import DEFAULT_PARSER_DIR
from reels_ripper_agent.tools.base import GetWeather
from reels_ripper_agent.tools.reel_tools import repair_parser, try_saved_parser


@beartype
async def _main(prompt: str) -> None:
    llm = OpenRouterLLM(model=os.environ.get("OPENROUTER_MODEL", "openrouter/free"))
    try:
        agent = Agent(llm, tools=[GetWeather()])
        print(await agent.run(prompt))
    finally:
        await llm.aclose()


@beartype
async def _main_reels(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        reels = await try_saved_parser(data, DEFAULT_PARSER_DIR)
    except (FileNotFoundError, MontyError, ValueError, asyncio.TimeoutError) as error:
        print("Generating a parser for this file...", file=sys.stderr)
        llm = OpenRouterLLM(model=os.environ.get("OPENROUTER_MODEL", "openrouter/free"))
        try:
            reels = await repair_parser(
                data, llm, DEFAULT_PARSER_DIR, f"{type(error).__name__}: {error}"
            )
        finally:
            await llm.aclose()
    print(
        json.dumps([reel.model_dump() for reel in reels], indent=2, ensure_ascii=False)
    )


@beartype
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Instagram reels from JSON or run the agent with a prompt."
    )
    parser.add_argument(
        "--reels-file",
        type=Path,
        metavar="PATH",
        help="Import reels from this JSON file.",
    )
    parser.add_argument(
        "prompt", nargs="*", help="Agent prompt; defaults to Tokyo weather."
    )
    args = parser.parse_args()
    if args.reels_file is not None and args.prompt:
        parser.error("Use --reels-file without a positional prompt.")
    load_dotenv()
    try:
        if args.reels_file is not None:
            asyncio.run(_main_reels(args.reels_file))
        else:
            prompt = " ".join(args.prompt) or "What's the weather in Tokyo?"
            asyncio.run(_main(prompt))
    except Exception as error:  # noqa: BLE001 - report command failures without corrupting stdout
        parser.exit(1, f"Error: {str(error) or type(error).__name__}\n")
