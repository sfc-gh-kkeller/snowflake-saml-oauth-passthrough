"""Anthropic Messages API provider."""
import json
import logging
from typing import AsyncGenerator, Optional

import httpx

from .base import LLMProvider, StreamEvent
from ...core.config import settings

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.anthropic_api_key
        self.base_url = "https://api.anthropic.com/v1"
        self.default_model = model or settings.anthropic_model or "claude-sonnet-4-20250514"

    @property
    def name(self) -> str:
        return "anthropic"

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        """Convert internal format to Anthropic format."""
        ant_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", [])

            if isinstance(content, str):
                ant_messages.append({"role": role, "content": content})
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif "text" in block:
                            text_parts.append(block["text"])
                if text_parts:
                    ant_messages.append({"role": role, "content": "\n".join(text_parts)})

        return ant_messages

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        model: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        url = f"{self.base_url}/messages"
        ant_messages = self._convert_messages(messages)

        body = {
            "model": model or self.default_model,
            "messages": ant_messages,
            "max_tokens": 8192,
            "stream": True,
        }
        if system_prompt:
            body["system"] = system_prompt

        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as client:
            async with client.stream("POST", url, json=body, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise RuntimeError(f"Anthropic API error {resp.status_code}: {error_body.decode()}")

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        event_type = data.get("type", "")

                        if event_type == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield StreamEvent(
                                    event_type="response.text.delta",
                                    data={"text": delta.get("text", "")},
                                )
                        elif event_type == "message_stop":
                            yield StreamEvent(event_type="done", data={})
                            return
                    except json.JSONDecodeError:
                        continue

        yield StreamEvent(event_type="done", data={})
