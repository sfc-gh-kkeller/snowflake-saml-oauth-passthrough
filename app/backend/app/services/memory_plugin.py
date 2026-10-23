"""
Project memory plugin system.

Defines a MemoryPlugin protocol and provides:
  - NullMemoryPlugin: no-op fallback (app works without any memory backend)
  - ZettelMemoryPlugin: uses zettelkasten-memory when installed

The active plugin is selected at import time based on whether
zettelkasten-memory is importable and the zettel_provider config.

Asset indexing:
  Approved assets are indexed into a global "__assets__" namespace so
  they can be discovered via semantic search during any chat.
"""
from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

ASSETS_NAMESPACE = "__assets__"
SKILL_KNOWLEDGE_NAMESPACE = "__skill_knowledge__"


@runtime_checkable
class MemoryPlugin(Protocol):
    """Interface every project-memory backend must satisfy."""

    @property
    def name(self) -> str: ...

    def add(self, project_id: str, content: str, *, tags: Optional[set[str]] = None, importance: float = 0.5) -> dict: ...

    def search(self, project_id: str, query: str, *, limit: int = 5) -> list[dict]: ...

    def get_context(self, project_id: str, query: str, *, max_tokens: int = 3000) -> str: ...

    def stats(self, project_id: str) -> dict: ...

    def delete_entry(self, project_id: str, zettel_id: str) -> bool: ...

    def delete_all(self, project_id: str) -> None: ...

    def list_entries(self, project_id: str, *, limit: int = 50) -> list[dict]: ...

    def index_asset(self, asset_id: str, content: str, *, filename: str = "", topic: str = "") -> dict: ...

    def remove_asset(self, asset_id: str) -> bool: ...

    def search_assets(self, query: str, *, limit: int = 3) -> list[dict]: ...


class NullMemoryPlugin:
    """No-op fallback — the app runs fine without semantic memory."""

    @property
    def name(self) -> str:
        return "none"

    def add(self, project_id: str, content: str, *, tags: Optional[set[str]] = None, importance: float = 0.5) -> dict:
        return {}

    def search(self, project_id: str, query: str, *, limit: int = 5) -> list[dict]:
        return []

    def get_context(self, project_id: str, query: str, *, max_tokens: int = 3000) -> str:
        return ""

    def stats(self, project_id: str) -> dict:
        return {"total_zettels": 0, "total_connections": 0, "avg_connections": 0, "plugin": "none"}

    def delete_entry(self, project_id: str, zettel_id: str) -> bool:
        return False

    def delete_all(self, project_id: str) -> None:
        pass

    def list_entries(self, project_id: str, *, limit: int = 50) -> list[dict]:
        return []

    def index_asset(self, asset_id: str, content: str, *, filename: str = "", topic: str = "") -> dict:
        return {}

    def remove_asset(self, asset_id: str) -> bool:
        return False

    def search_assets(self, query: str, *, limit: int = 3) -> list[dict]:
        return []


class ZettelMemoryPlugin:
    """Zettelkasten-memory backed project memory."""

    def __init__(self, *, persist_dir: str, provider: str, max_zettels: int, connection_threshold: float, embed_kwargs: dict[str, Any]) -> None:
        from zettelkasten_memory import ZettelMemory, EmbeddingBackend

        self._ZettelMemory = ZettelMemory
        self._EmbeddingBackend = EmbeddingBackend
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._provider = provider
        self._max_zettels = max_zettels
        self._connection_threshold = connection_threshold
        self._embed_kwargs = embed_kwargs
        self._cache: dict[str, ZettelMemory] = {}
        self._lock = Lock()

    @property
    def name(self) -> str:
        return f"zettel:{self._provider}"

    def _persist_path(self, project_id: str) -> Path:
        return self._persist_dir / f"{project_id}.json"

    def _build_backend(self):
        if self._provider == "tfidf":
            return None
        try:
            return self._EmbeddingBackend.from_provider(self._provider, **self._embed_kwargs)
        except Exception as e:
            logger.warning(f"Zettel backend {self._provider} failed: {e}, falling back to TF-IDF")
            return None

    def _get(self, project_id: str):
        with self._lock:
            if project_id in self._cache:
                return self._cache[project_id]

            pp = self._persist_path(project_id)
            if pp.exists():
                try:
                    backend = self._build_backend()
                    embed_fn = backend._embed_fn if backend else None
                    mem = self._ZettelMemory.load(str(pp), embed_fn=embed_fn)
                    self._cache[project_id] = mem
                    return mem
                except Exception as e:
                    logger.warning(f"Failed to load zettel {project_id}: {e}")

            backend = self._build_backend()
            kwargs: dict[str, Any] = {"max_zettels": self._max_zettels, "connection_threshold": self._connection_threshold}
            if backend:
                kwargs["backend"] = backend
            mem = self._ZettelMemory(**kwargs)
            self._cache[project_id] = mem
            return mem

    def _save(self, project_id: str) -> None:
        with self._lock:
            mem = self._cache.get(project_id)
            if mem:
                mem.save(str(self._persist_path(project_id)))

    def add(self, project_id: str, content: str, *, tags: Optional[set[str]] = None, importance: float = 0.5) -> dict:
        mem = self._get(project_id)
        z = mem.add(content, tags=tags, importance=importance)
        self._save(project_id)
        return {"id": z.id, "content": z.content, "tags": sorted(z.tags), "importance": z.importance, "connections": len(z.connections)}

    def search(self, project_id: str, query: str, *, limit: int = 5) -> list[dict]:
        mem = self._get(project_id)
        results = mem.search(query, limit=limit)
        return [
            {"id": r.zettel.id, "content": r.zettel.content, "score": round(r.score, 4), "tags": sorted(r.zettel.tags), "connections": len(r.zettel.connections)}
            for r in results
        ]

    def get_context(self, project_id: str, query: str, *, max_tokens: int = 3000) -> str:
        mem = self._get(project_id)
        return mem.get_context(query, max_tokens=max_tokens)

    def stats(self, project_id: str) -> dict:
        mem = self._get(project_id)
        s = mem.stats
        s["plugin"] = self.name
        return s

    def delete_entry(self, project_id: str, zettel_id: str) -> bool:
        mem = self._get(project_id)
        ok = mem.delete(zettel_id)
        if ok:
            self._save(project_id)
        return ok

    def delete_all(self, project_id: str) -> None:
        with self._lock:
            self._cache.pop(project_id, None)
        pp = self._persist_path(project_id)
        if pp.exists():
            pp.unlink()

    def list_entries(self, project_id: str, *, limit: int = 50) -> list[dict]:
        mem = self._get(project_id)
        zettels = sorted(mem._zettels.values(), key=lambda z: z.accessed_at, reverse=True)[:limit]
        return [
            {"id": z.id, "content": z.content, "tags": sorted(z.tags), "importance": z.importance, "connections": len(z.connections), "access_count": z.access_count}
            for z in zettels
        ]

    def index_asset(self, asset_id: str, content: str, *, filename: str = "", topic: str = "") -> dict:
        self.remove_asset(asset_id)
        tags = {"asset", "approved", f"aid:{asset_id}"}
        if topic:
            tags.add(topic)
        if filename:
            tags.add(filename.replace(" ", "_").lower())
        header = f"[Asset: {filename or asset_id}]"
        if topic:
            header += f" (topic: {topic})"
        full_content = f"{header}\n{content[:4000]}"
        result = self.add(ASSETS_NAMESPACE, full_content, tags=tags, importance=0.9)
        result["asset_id"] = asset_id
        logger.info("Indexed asset %s into zettel (%s)", asset_id[:8], filename)
        return result

    def remove_asset(self, asset_id: str) -> bool:
        mem = self._get(ASSETS_NAMESPACE)
        removed = False
        aid_tag = f"aid:{asset_id}"
        to_delete = [
            z.id for z in mem._zettels.values()
            if aid_tag in z.tags
        ]
        if not to_delete:
            to_delete = [
                z.id for z in mem._zettels.values()
                if f"[Asset: " in z.content and asset_id in z.content
            ]
        for zid in to_delete:
            if mem.delete(zid):
                removed = True
        if removed:
            self._save(ASSETS_NAMESPACE)
            logger.info("Removed asset %s from zettel", asset_id[:8])
        return removed

    def search_assets(self, query: str, *, limit: int = 3) -> list[dict]:
        return self.search(ASSETS_NAMESPACE, query, limit=limit)


def _create_plugin() -> MemoryPlugin:
    from ..core.config import settings

    if settings.zettel_provider == "none":
        logger.info("Memory plugin: none (disabled)")
        return NullMemoryPlugin()

    try:
        import zettelkasten_memory  # noqa: F401
    except ImportError:
        logger.info("Memory plugin: none (zettelkasten-memory not installed)")
        return NullMemoryPlugin()

    embed_kwargs: dict[str, Any] = {}
    if settings.zettel_provider == "snowflake":
        embed_kwargs["account"] = settings.snowflake_account.lower().replace("_", "-")
        embed_kwargs["token"] = settings.snowflake_pat
        embed_kwargs["model"] = settings.embedding_model

    try:
        plugin = ZettelMemoryPlugin(
            persist_dir=settings.zettel_persist_dir,
            provider=settings.zettel_provider,
            max_zettels=settings.zettel_max_zettels,
            connection_threshold=settings.zettel_connection_threshold,
            embed_kwargs=embed_kwargs,
        )
        logger.info(f"Memory plugin: {plugin.name}")
        return plugin
    except Exception as e:
        logger.warning(f"Failed to create zettel plugin: {e}")
        return NullMemoryPlugin()


_memory_plugin: MemoryPlugin = NullMemoryPlugin()


def get_memory_plugin() -> MemoryPlugin:
    return _memory_plugin


def init_memory_plugin() -> None:
    global _memory_plugin
    _memory_plugin = _create_plugin()
