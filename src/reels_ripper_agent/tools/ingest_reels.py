import json
import re
from pathlib import Path
from typing import Annotated

from beartype import beartype
from pydantic import BaseModel, Field, StringConstraints, TypeAdapter, ValidationError
from pydantic_monty import Monty, MontyError, ResourceLimits

from reels_ripper_agent.db import save_reels
from reels_ripper_agent.llm.base import LLM, Message
from reels_ripper_agent.tools.base import Tool

REEL_URL_RE = r"https://www\.instagram\.com/(?:reel|p)/[\w-]+/?"
ReelUrl = Annotated[str, StringConstraints(pattern=rf"^{REEL_URL_RE}$")]
Handle = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._]{1,30}$")]
Reels = TypeAdapter(list[tuple[ReelUrl, Handle]])

PARSERS_DIR = Path(".parsers")
MAX_ATTEMPTS = 3

PROMPT = """Write a Python snippet that extracts Instagram reels from JSON data.

Rules:
- The parsed JSON is already in a variable named `data`.
- The last line must be an expression that evaluates to a list of (url, author) tuples.
- url: the reel link, for example "https://www.instagram.com/reel/<reel_id>/".
- author: the Instagram username (handle) of the reel owner, for example "<username>".
  Never use the display name, for example "<display_name>".
- Return one tuple for every reel in `data`.
- The code runs in a restricted interpreter: no imports, no file or network access.
- Reply with only the code in one ```python block.

Sample of the data (lists show only their first, middle, and last items):
{sample}
"""


class IngestReelsArgs(BaseModel):
    path: str = Field(description="Path to an Instagram saved-posts JSON export")


def _run_parser(code: str, data: object, expected_urls: int) -> list[tuple[str, str]]:
    """Run code in Monty with `data` as input and validate the result.

    Raises ValueError with a message the LLM can act on.
    """
    try:
        with (
            Monty() as pool,
            pool.checkout(limits=ResourceLimits(max_feed_duration_secs=10)) as session,
        ):
            result = session.feed_run(code, inputs={"data": data})
    except MontyError as e:
        raise ValueError(f"the code raised {type(e).__name__}: {e}") from e
    try:
        reels = Reels.validate_python(result)
    except ValidationError as e:
        raise ValueError(f"invalid output: {str(e)[:1500]}") from e
    found = len({url for url, _ in reels})
    if found != expected_urls:
        raise ValueError(f"expected {expected_urls} unique urls, got {found}")
    return reels


def _sample(data: object) -> str:
    """Copy of `data` with each outermost list cut to its first, middle, and last
    items, as JSON. Lists inside the kept items stay whole.
    """

    def trim(value: object) -> object:
        if isinstance(value, list):
            return (
                value
                if len(value) <= 3
                else [value[0], value[len(value) // 2], value[-1]]
            )
        if isinstance(value, dict):
            return {k: trim(v) for k, v in value.items()}
        return value

    return json.dumps(trim(data), indent=2, ensure_ascii=False)


async def _generate_parser(llm: LLM, sample: str, error: str | None) -> str:
    """Ask the LLM for parser code. Returns the code from the reply."""
    prompt = PROMPT.format(sample=sample)
    if error:
        prompt += f"\n{error}\nCorrect the code.\n"
    reply = await llm.complete([Message(role="user", content=prompt)])
    content = reply.content or ""
    match = re.search(r"```(?:python)?\n(.*?)```", content, re.DOTALL)
    return match.group(1) if match else content


@beartype
async def extract_reels(llm: LLM, path: Path) -> list[tuple[str, str]]:
    raw_text = path.read_text()
    data = json.loads(raw_text)
    expected_urls = len(set(re.findall(REEL_URL_RE, raw_text)))

    saved = sorted(PARSERS_DIR.glob("*.py"))
    for parser in saved:
        try:
            return _run_parser(parser.read_text(), data, expected_urls)
        except ValueError:
            continue

    error = None  # feedback on the last bad code, for the LLM
    failure = None  # reason of the last failed attempt, for the final error
    for _ in range(MAX_ATTEMPTS):
        try:
            code = await _generate_parser(llm, _sample(data), error)
        except RuntimeError as e:  # LLM timeout or HTTP error: try a new request
            failure = str(e)
            continue
        try:
            reels = _run_parser(code, data, expected_urls)
        except ValueError as e:
            failure = str(e)
            error = f"Your previous code:\n```python\n{code}```\nfailed: {e}"
            continue
        PARSERS_DIR.mkdir(parents=True, exist_ok=True)
        (PARSERS_DIR / f"{len(saved) + 1:04d}.py").write_text(code)
        return reels

    raise RuntimeError(f"no parser after {MAX_ATTEMPTS} attempts: {failure}")


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
