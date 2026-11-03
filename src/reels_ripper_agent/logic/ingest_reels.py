import json
import re
from pathlib import Path
from typing import Annotated

from beartype import beartype
from pydantic import StringConstraints, TypeAdapter, ValidationError
from pydantic_monty import Monty, MontyError, ResourceLimits

from reels_ripper_agent.config import DATA_DIR
from reels_ripper_agent.llm.base import LLM, Message

REEL_URL_RE = r"https://www\.instagram\.com/(?:reel|p)/[\w-]+/?"
ReelUrl = Annotated[str, StringConstraints(pattern=rf"^{REEL_URL_RE}$")]
Handle = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._]{1,30}$")]
Reels = TypeAdapter(list[tuple[ReelUrl, Handle]])

PARSERS_DIR = DATA_DIR / ".parsers"
MAX_ATTEMPTS = 3

PROMPT = """Write a Python snippet that extracts Instagram posts from JSON data.

Rules:
- The parsed JSON is already in a variable named `data`.
- The last line must be an expression that evaluates to a list of (url, author) tuples.
- url: the post link, for example "https://www.instagram.com/reel/<reel_id>/"
  or "https://www.instagram.com/p/<post_id>/".
- author: the Instagram username (handle) of the post owner, for example "<username>".
  Never use the display name, for example "<display_name>".
- Return one tuple for every post in `data`, both /reel/ and /p/ links.
  Do not filter the posts.
- The code runs in a restricted interpreter: no imports, no file or network access.
- Reply with only the code in one ```python block.

Sample of the data (lists show only their first, middle, and last items):
{sample}
"""


def _run_parser(
    code: str, data: object, expected_urls: set[str]
) -> list[tuple[str, str]]:
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
    found = {url for url, _ in reels}
    if found != expected_urls:
        missing = sorted(expected_urls - found)[:5]
        raise ValueError(
            f"expected {len(expected_urls)} unique urls, got {len(found)}. "
            f"Missing, for example: {missing}"
        )
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
    data = json.loads(path.read_text())
    # Scan the decoded data, not the raw text: exports can escape "/" as "\/".
    expected_urls = set(re.findall(REEL_URL_RE, json.dumps(data)))
    if not expected_urls:
        raise ValueError(f"no post urls found in {path}")

    saved = sorted(PARSERS_DIR.glob("*.py"))
    for parser in saved:
        try:
            reels = _run_parser(parser.read_text(), data, expected_urls)
        except ValueError:
            continue
        print(f"  using saved parser {parser.name}")
        return reels

    error = None  # feedback on the last bad code, for the LLM
    failure = None  # reason of the last failed attempt, for the final error
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"  asking LLM for a parser (attempt {attempt}/{MAX_ATTEMPTS})...")
        try:
            code = await _generate_parser(llm, _sample(data), error)
        except RuntimeError as e:  # LLM timeout or HTTP error: try a new request
            failure = str(e)
            print(f"  attempt {attempt} failed: {failure}")
            continue
        try:
            reels = _run_parser(code, data, expected_urls)
        except ValueError as e:
            failure = str(e)
            error = f"Your previous code:\n```python\n{code}```\nfailed: {e}"
            print(f"  attempt {attempt} failed: {failure}")
            continue
        PARSERS_DIR.mkdir(parents=True, exist_ok=True)
        parser = PARSERS_DIR / f"{len(saved) + 1:04d}.py"
        parser.write_text(code)
        print(f"  saved new parser {parser.name}")
        return reels

    raise RuntimeError(f"no parser after {MAX_ATTEMPTS} attempts: {failure}")
