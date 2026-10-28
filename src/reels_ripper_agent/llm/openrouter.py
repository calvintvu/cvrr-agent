import os
from typing import Any

import httpx
from beartype import beartype

from reels_ripper_agent.llm.base import LLM, Message

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterLLM(LLM):
    @beartype
    def __init__(
        self,
        model: str = "openrouter/free",
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        api_key = api_key or os.environ["OPENROUTER_API_KEY"]
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout
        )

    @beartype
    async def complete(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> Message:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }
        if tools:
            payload["tools"] = tools

        resp = await self._client.post(OPENROUTER_URL, json=payload)
        if resp.is_error:
            raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text}")
        return Message.model_validate(resp.json()["choices"][0]["message"])

    @beartype
    async def aclose(self) -> None:
        await self._client.aclose()
