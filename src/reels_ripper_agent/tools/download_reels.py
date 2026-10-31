import asyncio
from pathlib import Path

from beartype import beartype
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from reels_ripper_agent.db import pending_downloads, set_download_path
from reels_ripper_agent.tools.base import Tool

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DELAY_SECONDS = 1


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
        for i, url in enumerate(pending_downloads()):
            if i:
                await asyncio.sleep(DOWNLOADS_DELAY_SECONDS)
            try:
                set_download_path(url, _download(url))
                downloaded += 1
            except DownloadError as e:
                failures.append(f"{url}: {str(e).split('. ')[0]}")
        result = f"Downloaded {downloaded} reels."
        if failures:
            result += f" {len(failures)} failed: " + "; ".join(failures)
        return result
