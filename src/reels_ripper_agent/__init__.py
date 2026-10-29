import asyncio
import os
import sys

from beartype import beartype
from dotenv import load_dotenv

from reels_ripper_agent.agent import Agent
from reels_ripper_agent.llm.openrouter import OpenRouterLLM
from reels_ripper_agent.tools.tools import GetWeather


@beartype
async def _main(prompt: str) -> None:
    llm = OpenRouterLLM(model=os.environ.get("OPENROUTER_MODEL", "openrouter/free"))
    try:
        agent = Agent(llm, tools=[GetWeather()])
        print(await agent.run(prompt))
    finally:
        await llm.aclose()


@beartype
def main() -> None:
    load_dotenv()
    prompt = " ".join(sys.argv[1:]) or "What's the weather in Tokyo?"
    asyncio.run(_main(prompt))
