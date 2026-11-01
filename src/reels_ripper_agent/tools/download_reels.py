import asyncio
import logging
from pathlib import Path

from beartype import beartype
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from reels_ripper_agent.db import pending_downloads, set_download_path
from reels_ripper_agent.tools.base import Tool

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DELAY_SECONDS = 1

# yt-dlp prints errors to stderr even with "quiet"; the tool prints its own lines
_SILENT_LOGGER = logging.getLogger("reels_ripper_agent.yt_dlp")
_SILENT_LOGGER.addHandler(logging.NullHandler())
_SILENT_LOGGER.propagate = False


class DownloadReelsArgs(BaseModel):
    pass  # no args: the tool works through every pending reel


def _download(url: str) -> Path:
    """Download one reel with yt_dlp to DOWNLOADS_DIR/<id>.<ext>.

    Returns the file path. Raises DownloadError on failure.
    """
    options = {
        "outtmpl": str(DOWNLOADS_DIR / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SILENT_LOGGER,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url)
    return Path(info["requested_downloads"][0]["filepath"])


class DownloadReels(Tool):
    name = "download_reels"
    description = (
        "Download every saved reel that is not downloaded yet. "
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
                await asyncio.sleep(DOWNLOADS_DELAY_SECONDS)
            try:
                set_download_path(url, _download(url))
            except DownloadError as e:
                error = str(e).split(". ")[0]
                failures.append(f"{url}: {error}")
                print(f"  [{i}/{len(urls)}] failed {url}: {error}")
                continue
            downloaded += 1
            print(f"  [{i}/{len(urls)}] downloaded {url}")
        result = f"Downloaded {downloaded} reels."
        if failures:
            result += f" {len(failures)} failed: " + "; ".join(failures)
        return result
