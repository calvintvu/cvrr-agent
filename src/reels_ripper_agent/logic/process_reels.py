import subprocess
from pathlib import Path

from beartype import beartype


@beartype
def readable(video: Path) -> bool:
    """True if ffprobe finds a video stream in the file. False if the file is
    missing or ffprobe cannot read it."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0"]
        + ["-show_entries", "stream=codec_type", "-of", "csv=p=0", str(video)],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0 and probe.stdout.strip() == "video"


@beartype
def replace_audio(video: Path, audio: Path, out: Path) -> None:
    """Write video with its audio replaced by audio to out. The output is as long
    as the shorter of the two. Raises CalledProcessError on failure."""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video), "-i", str(audio)]
        + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac"]
        + ["-shortest", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )
