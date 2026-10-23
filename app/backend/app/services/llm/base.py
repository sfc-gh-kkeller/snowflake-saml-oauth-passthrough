"""Abstract LLM provider interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional
import uuid


@dataclass
class StreamEvent:
    event_type: str  # "response.text.delta", "response.thinking.delta", "response.tool_use", "response.tool_result", "done"
    data: dict


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'cortex', 'openai', 'anthropic', 'ollama')."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        model: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream a response from the LLM. Yields StreamEvent objects."""
        ...
        yield  # Make it a generator

    async def close(self) -> None:
        """Clean up resources. Override if needed."""
        pass
