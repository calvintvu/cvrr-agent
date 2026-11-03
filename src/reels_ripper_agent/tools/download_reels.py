import asyncio
import random

from beartype import beartype
from pydantic import BaseModel
from yt_dlp.utils import DownloadError

from reels_ripper_agent.db.operations import (
    delete_reel,
    pending_downloads,
    set_download_path,
)
from reels_ripper_agent.logic.download_reels import download
from reels_ripper_agent.tools.base import Tool

# random gap between downloads so Instagram does not rate-limit a residential IP
DOWNLOADS_DELAY_SECONDS = (10, 30)


class DownloadReelsArgs(BaseModel):
    pass  # no args: the tool works through every pending reel


class DownloadReels(Tool):
    name = "download_reels"
    description = (
        "Download every saved reel that is not downloaded yet. "
        "Failed reels are deleted from the database. "
        "Returns how many downloaded and which urls failed."
    )
    args_model = DownloadReelsArgs

    @beartype
    async def execute(self, args: DownloadReelsArgs) -> str:
        downloaded = 0
        failures = []
        urls = pending_downloads()
        for i, url in enumerate(urls, 1):
            if i > 1:
                await asyncio.sleep(random.uniform(*DOWNLOADS_DELAY_SECONDS))
            try:
                set_download_path(url, download(url))
            except DownloadError as e:
                error = str(e).split(". ")[0]
                delete_reel(url)
                failures.append(f"{url}: {error}")
                print(f"  [{i}/{len(urls)}] failed and deleted {url}: {error}")
                continue
            downloaded += 1
            print(f"  [{i}/{len(urls)}] downloaded {url}")
        result = f"Downloaded {downloaded} reels."
        if failures:
            result += f" {len(failures)} failed and were deleted: " + "; ".join(
                failures
            )
        return result
