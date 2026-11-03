import asyncio
import os
import sys

from beartype import beartype

from reels_ripper_agent.agent import Agent
from reels_ripper_agent.llm.openrouter import OpenRouterLLM
from reels_ripper_agent.tools.download_reels import DownloadReels
from reels_ripper_agent.tools.ingest_reels import IngestReels
from reels_ripper_agent.tools.process_reels import ProcessReels
from reels_ripper_agent.tools.weather import GetWeather


@beartype
async def _main(prompt: str) -> None:
    llm = OpenRouterLLM(model=os.environ.get("OPENROUTER_MODEL", "openrouter/free"))
    try:
        agent = Agent(
            llm, tools=[GetWeather(), IngestReels(llm), DownloadReels(), ProcessReels()]
        )
        print(await agent.run(prompt))
    finally:
        await llm.aclose()


@beartype
def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "What's the weather in Tokyo?"
    asyncio.run(_main(prompt))
