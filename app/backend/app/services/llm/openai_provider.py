"""OpenAI API provider (also works with Azure OpenAI and compatible APIs)."""
import json
import logging
from typing import AsyncGenerator, Optional

import httpx

from .base import LLMProvider, StreamEvent
from ...core.config import settings

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.openai_api_key
        self.base_url = (base_url or settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        self.default_model = model or settings.openai_model or "gpt-4o"

    @property
    def name(self) -> str:
        return "openai"

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _convert_messages(self, messages: list[dict], system_prompt: str) -> list[dict]:
        """Convert internal message format to OpenAI format."""
        oai_messages = []
        if system_prompt:
            oai_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", [])

            if isinstance(content, str):
                oai_messages.append({"role": role, "content": content})
            elif isinstance(content, list):
                # Extract text from content blocks
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif "text" in block:
                            text_parts.append(block["text"])
                if text_parts:
                    oai_messages.append({"role": role, "content": "\n".join(text_parts)})

        return oai_messages

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        model: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        url = f"{self.base_url}/chat/completions"
        oai_messages = self._convert_messages(messages, system_prompt)

        body = {
            "model": model or self.default_model,
            "messages": oai_messages,
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as client:
            async with client.stream("POST", url, json=body, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise RuntimeError(f"OpenAI API error {resp.status_code}: {error_body.decode()}")

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        yield StreamEvent(event_type="done", data={})
                        return
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                yield StreamEvent(
                                    event_type="response.text.delta",
                                    data={"text": content},
                                )
                    except json.JSONDecodeError:
                        continue

        yield StreamEvent(event_type="done", data={})
