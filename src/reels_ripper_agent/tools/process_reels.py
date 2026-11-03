import subprocess
from pathlib import Path

from beartype import beartype
from pydantic import BaseModel

from reels_ripper_agent.config import DATA_DIR
from reels_ripper_agent.db.operations import (
    add_render,
    delete_reel,
    pending_renders,
)
from reels_ripper_agent.logic.process_reels import readable, replace_audio
from reels_ripper_agent.tools.base import Tool

ASSETS_DIR = Path("assets")
PROCESSED_DIR = DATA_DIR / ".processed"


class ProcessReelsArgs(BaseModel):
    pass  # no args: the tool renders every missing (reel, cut) pair


class ProcessReels(Tool):
    name = "process_reels"
    description = (
        "For every downloaded reel, make one video per audio cut in assets/ that "
        "the reel has no video for yet, with the original audio replaced by the "
        "cut. Unreadable reels are deleted from the database. "
        "Returns how many videos were made and how many reels were deleted or failed."
    )
    args_model = ProcessReelsArgs

    @beartype
    async def execute(self, args: ProcessReelsArgs) -> str:
        cuts = [str(c.relative_to(ASSETS_DIR)) for c in ASSETS_DIR.rglob("*.mp3")]
        if not cuts:
            return f"Error: no .mp3 cuts found in {ASSETS_DIR}/"
        made = 0
        deleted = []
        failures = []
        reels = pending_renders(sorted(cuts))
        for i, (reel_id, url, author, video, missing) in enumerate(reels, 1):
            if not readable(video):
                delete_reel(url)
                video.unlink(missing_ok=True)
                deleted.append(url)
                print(f"  [{i}/{len(reels)}] unreadable, deleted {url}")
                continue
            try:
                for cut in missing:
                    out = (
                        PROCESSED_DIR
                        / author
                        / video.stem
                        / Path(cut).with_suffix(".mp4")
                    )
                    out.parent.mkdir(parents=True, exist_ok=True)
                    replace_audio(video, ASSETS_DIR / cut, out)
                    add_render(reel_id, cut, out)
                    made += 1
            except subprocess.CalledProcessError as e:
                error = (e.stderr.strip().splitlines() or ["unknown error"])[-1]
                failures.append(f"{url}: {error}")
                print(f"  [{i}/{len(reels)}] failed {url}: {error}")
                continue
            print(f"  [{i}/{len(reels)}] rendered {url} ({len(missing)} videos)")
        result = f"Made {made} videos."
        if deleted:
            result += f" {len(deleted)} unreadable and were deleted: " + "; ".join(
                deleted
            )
        if failures:
            result += f" {len(failures)} failed and will retry next run: " + "; ".join(
                failures
            )
        return result
