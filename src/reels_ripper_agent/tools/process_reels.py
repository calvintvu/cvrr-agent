import subprocess
from pathlib import Path

from beartype import beartype
from pydantic import BaseModel

from reels_ripper_agent.db import delete_reel, pending_processing, set_processed
from reels_ripper_agent.logic.process_reels import readable, replace_audio
from reels_ripper_agent.tools.base import Tool

ASSETS_DIR = Path("assets")
PROCESSED_DIR = Path(".processed")


class ProcessReelsArgs(BaseModel):
    pass  # no args: the tool works through every downloaded, unprocessed reel


class ProcessReels(Tool):
    name = "process_reels"
    description = (
        "For every downloaded reel that is not processed, make one video per audio "
        "cut in assets/, with the original audio replaced by the cut. "
        "Unreadable reels are deleted from the database. "
        "Returns how many reels were processed, deleted, and failed."
    )
    args_model = ProcessReelsArgs

    @beartype
    async def execute(self, args: ProcessReelsArgs) -> str:
        cuts = sorted(ASSETS_DIR.rglob("*.mp3"))
        if not cuts:
            return f"Error: no .mp3 cuts found in {ASSETS_DIR}/"
        processed = 0
        deleted = []
        failures = []
        reels = pending_processing()
        for i, (url, author, video) in enumerate(reels, 1):
            if not readable(video):
                delete_reel(url)
                video.unlink(missing_ok=True)
                deleted.append(url)
                print(f"  [{i}/{len(reels)}] unreadable, deleted {url}")
                continue
            out_dir = PROCESSED_DIR / author / video.stem
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                for cut in cuts:
                    replace_audio(video, cut, out_dir / f"{cut.stem}.mp4")
            except subprocess.CalledProcessError as e:
                error = (e.stderr.strip().splitlines() or ["unknown error"])[-1]
                failures.append(f"{url}: {error}")
                print(f"  [{i}/{len(reels)}] failed {url}: {error}")
                continue
            set_processed(url)
            processed += 1
            print(f"  [{i}/{len(reels)}] processed {url} ({len(cuts)} videos)")
        result = f"Processed {processed} reels into {len(cuts)} videos each."
        if deleted:
            result += f" {len(deleted)} unreadable and were deleted: " + "; ".join(
                deleted
            )
        if failures:
            result += f" {len(failures)} failed and stay unprocessed: " + "; ".join(
                failures
            )
        return result
