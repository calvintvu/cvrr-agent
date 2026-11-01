from pathlib import Path

from beartype import beartype
from pydantic import BaseModel, Field

from reels_ripper_agent.db.operations import save_reels
from reels_ripper_agent.llm.base import LLM
from reels_ripper_agent.logic.ingest_reels import extract_reels
from reels_ripper_agent.tools.base import Tool


class IngestReelsArgs(BaseModel):
    path: str = Field(description="Path to an Instagram saved-posts JSON export")


class IngestReels(Tool):
    name = "ingest_reels"
    description = (
        "Extract (reel_url, author_username) pairs from an Instagram saved-posts "
        "JSON file and save new ones to the database. Returns the number of reels "
        "extracted and the number of new reels saved."
    )
    args_model = IngestReelsArgs

    @beartype
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    @beartype
    async def execute(self, args: IngestReelsArgs) -> str:
        posts = await extract_reels(self.llm, Path(args.path))
        reels = [(url, author) for url, author in posts if "/reel/" in url]
        inserted = save_reels(reels)
        return (
            f"Extracted {len(posts)} posts, skipped {len(posts) - len(reels)} "
            f"non-reel posts, saved {inserted} new reels."
        )
