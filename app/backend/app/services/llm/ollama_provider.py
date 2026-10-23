"""Ollama provider using OpenAI-compatible API."""
import json
import logging
from typing import AsyncGenerator, Optional

import httpx

from .base import LLMProvider, StreamEvent
from ...core.config import settings

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        self.base_url = (base_url or settings.ollama_base_url or "http://localhost:11434").rstrip("/")
        self.default_model = model or settings.ollama_model or "llama3.1"

    @property
    def name(self) -> str:
        return "ollama"

    def _convert_messages(self, messages: list[dict], system_prompt: str) -> list[dict]:
        """Convert internal format to OpenAI-compatible format."""
        result = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", [])

            if isinstance(content, str):
                result.append({"role": role, "content": content})
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif "text" in block:
                            text_parts.append(block["text"])
                if text_parts:
                    result.append({"role": role, "content": "\n".join(text_parts)})

        return result

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        model: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        url = f"{self.base_url}/v1/chat/completions"
        body = {
            "model": model or self.default_model,
            "messages": self._convert_messages(messages, system_prompt),
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as client:
            async with client.stream("POST", url, json=body) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise RuntimeError(f"Ollama API error {resp.status_code}: {error_body.decode()}")

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
