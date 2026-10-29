import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class Reel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    url: str
    author_username: Annotated[str, Field(min_length=1, pattern=r"\S")] | None


_REEL_LIST = TypeAdapter(list[Reel])


def check_output(raw: object) -> list[Reel]:
    """Validate parser output and return unique reels with canonical URLs."""
    authors_by_url: dict[str, set[str]] = {}
    for reel in _REEL_LIST.validate_python(raw, strict=True):
        parts = urlsplit(reel.url)
        match = re.fullmatch(r"/(reel|p)/([A-Za-z0-9_-]+)/?", parts.path)
        if (
            re.search(r"[\s\x00-\x1f\x7f]", reel.url)
            or parts.scheme not in {"http", "https"}
            or parts.netloc.lower() not in {"instagram.com", "www.instagram.com"}
            or match is None
        ):
            raise ValueError(
                f"Expected an Instagram reel or post URL, got {reel.url!r}"
            )
        if match[1] == "p":
            continue

        url = f"https://www.instagram.com/reel/{match[2]}/"
        authors = authors_by_url.setdefault(url, set())
        if reel.author_username is not None:
            authors.add(reel.author_username)

    return [
        Reel(
            url=url,
            author_username=next(iter(authors)) if len(authors) == 1 else None,
        )
        for url, authors in authors_by_url.items()
    ]
