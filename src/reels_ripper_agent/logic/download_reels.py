import logging
from pathlib import Path

from beartype import beartype
from yt_dlp import YoutubeDL

DOWNLOADS_DIR = Path(".downloads")

# yt-dlp prints errors to stderr even with "quiet"; the tool prints its own lines
_SILENT_LOGGER = logging.getLogger("reels_ripper_agent.yt_dlp")
_SILENT_LOGGER.addHandler(logging.NullHandler())
_SILENT_LOGGER.propagate = False


@beartype
def download(url: str) -> Path:
    """Download one reel with yt_dlp to DOWNLOADS_DIR/<id>.<ext>.

    Returns the file path. Raises DownloadError on failure.
    """
    options = {
        "outtmpl": str(DOWNLOADS_DIR / "%(id)s.%(ext)s"),
        # Instagram's single-file formats are H.264, which plays everywhere. The
        # separate video streams are VP9, which QuickTime plays as audio only.
        "format": "b/bv*+ba",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SILENT_LOGGER,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url)
    return Path(info["requested_downloads"][0]["filepath"])
