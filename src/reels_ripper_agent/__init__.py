import asyncio
import os
import sys

from beartype import beartype

from reels_ripper_agent.agent import Agent
from reels_ripper_agent.db import operations as db
from reels_ripper_agent.llm.openrouter import OpenRouterLLM
from reels_ripper_agent.tools.download_reels import DownloadReels
from reels_ripper_agent.tools.ingest_reels import IngestReels
from reels_ripper_agent.tools.process_reels import ProcessReels
from reels_ripper_agent.tools.weather import GetWeather


@beartype
async def _main(prompt: str | None) -> None:
    """Start a new run with prompt, or resume the unfinished run if prompt
    is None."""
    llm = OpenRouterLLM(model=os.environ.get("OPENROUTER_MODEL", "openrouter/free"))
    try:
        agent = Agent(
            llm, tools=[GetWeather(), IngestReels(llm), DownloadReels(), ProcessReels()]
        )
        if prompt is not None:
            print(await agent.run(prompt))
            return
        run_id = db.unfinished_run()
        if run_id is None:
            sys.exit("No unfinished run to resume.")
        print(f"Resuming run {run_id}")
        print(await agent.resume(run_id))
    finally:
        await llm.aclose()


@beartype
def main() -> None:
    args = sys.argv[1:]
    if args == ["--resume"]:
        asyncio.run(_main(None))
        return
    asyncio.run(_main(" ".join(args) or "What's the weather in Tokyo?"))
