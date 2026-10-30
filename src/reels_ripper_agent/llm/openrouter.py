import json
import os
from typing import Any

import httpx
from beartype import beartype
from pydantic import BaseModel

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
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> Message:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }
        if tools:
            payload["tools"] = tools
        if response_model is not None:
            schema = json.dumps(response_model.model_json_schema())
            payload["messages"].insert(
                0,
                {
                    "role": "system",
                    "content": f"Return text responses as JSON matching this schema:\n{schema}",
                },
            )
            # some providers suppress native tool calls in JSON-only mode
            if not tools:
                payload["response_format"] = {"type": "json_object"}
            payload["provider"] = {"require_parameters": True}

        resp = await self._client.post(OPENROUTER_URL, json=payload)
        if resp.is_error:
            raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text}")
        return Message.model_validate(resp.json()["choices"][0]["message"])

    @beartype
    async def aclose(self) -> None:
        await self._client.aclose()
