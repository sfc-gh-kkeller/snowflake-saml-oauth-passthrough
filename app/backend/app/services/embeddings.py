"""Embedding service with multiple provider support."""
import logging
from typing import Optional

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Unified embedding service that delegates to the configured provider."""

    def __init__(self, provider: Optional[str] = None, session_token: Optional[str] = None):
        self.provider = provider or settings.embedding_provider
        self._session_token: Optional[str] = session_token

    async def _authenticate_snowflake(self) -> str:
        """Get a Snowflake session token for embedding API calls."""
        account = settings.snowflake_account.lower().replace("_", "-")
        base_url = f"https://{account}.snowflakecomputing.com"
        async with httpx.AsyncClient(verify=True) as client:
            resp = await client.post(
                f"{base_url}/session/v1/login-request",
                json={
                    "data": {
                        "ACCOUNT_NAME": account.split(".")[0],
                        "LOGIN_NAME": settings.snowflake_user,
                        "AUTHENTICATOR": "PROGRAMMATIC_ACCESS_TOKEN",
                        "TOKEN": settings.snowflake_pat,
                    }
                },
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("success"):
                raise RuntimeError(f"Snowflake auth failed: {body.get('message', 'unknown')}")
            self._session_token = body["data"]["token"]
            return self._session_token

    async def _generate_snowflake(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via Snowflake Cortex."""
        if not self._session_token:
            await self._authenticate_snowflake()

        account = settings.snowflake_account.lower().replace("_", "-")
        url = f"https://{account}.snowflakecomputing.com/api/v2/cortex/inference:embed"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f'Snowflake Token="{self._session_token}"',
        }
        body = {
            "text": texts,
            "model": settings.embedding_model,
        }
        async with httpx.AsyncClient(verify=True, timeout=60) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def _generate_openai(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via OpenAI API."""
        base_url = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.openai_api_key}",
        }
        body = {
            "input": texts,
            "model": settings.embedding_model_openai or "text-embedding-3-small",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def _generate_ollama(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via Ollama API."""
        base_url = (settings.ollama_base_url or "http://localhost:11434").rstrip("/")
        url = f"{base_url}/api/embed"
        body = {
            "model": settings.embedding_model_ollama or "nomic-embed-text",
            "input": texts,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            return data["embeddings"]

    async def generate(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        results = await self.generate_batch([text])
        return results[0]

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if self.provider == "snowflake":
            return await self._generate_snowflake(texts)
        elif self.provider == "openai":
            return await self._generate_openai(texts)
        elif self.provider == "ollama":
            return await self._generate_ollama(texts)
        elif self.provider == "none":
            # Return zero vectors when embeddings are disabled
            dim = settings.embedding_dimensions
            return [[0.0] * dim for _ in texts]
        else:
            raise ValueError(f"Unknown embedding provider: {self.provider}. Supported: snowflake, openai, ollama, none")
