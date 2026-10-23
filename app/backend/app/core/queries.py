"""Dialect-aware SQL helpers for vector similarity queries."""

from .config import settings

_DIMS = settings.embedding_dimensions


def similarity_search_sql(table: str = "assets", extra_where: str = "", limit: int = 3) -> str:
    """Return the appropriate vector similarity SQL for the configured backend."""
    if settings.database_backend == "snowflake":
        return f"""
            SELECT id, filename, topic, content,
                   VECTOR_COSINE_SIMILARITY(
                       embedding::VECTOR(FLOAT, {_DIMS}),
                       :emb::VECTOR(FLOAT, {_DIMS})
                   ) as similarity
            FROM {table}
            WHERE status = 'approved'
              AND embedding IS NOT NULL
              AND is_active = true
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP())
              AND VECTOR_COSINE_SIMILARITY(
                      embedding::VECTOR(FLOAT, {_DIMS}),
                      :emb::VECTOR(FLOAT, {_DIMS})
                  ) > :threshold
              {extra_where}
            ORDER BY similarity DESC
            LIMIT :lim
        """
    else:
        return f"""
            SELECT id, filename, topic, content,
                   1 - (embedding <=> cast(:emb as vector)) as similarity
            FROM {table}
            WHERE status = 'approved'
              AND embedding IS NOT NULL
              AND is_active = true
              AND (expires_at IS NULL OR expires_at > now())
              AND 1 - (embedding <=> cast(:emb as vector)) > :threshold
              {extra_where}
            ORDER BY similarity DESC
            LIMIT :lim
        """


def format_embedding_for_query(embedding: list[float]) -> str:
    """Format an embedding list as a string suitable for the SQL backend.

    - Postgres: '[0.1,0.2,...]' (pgvector text format)
    - Snowflake: '[0.1,0.2,...]' (cast to VECTOR via ::VECTOR)
    """
    return "[" + ",".join(str(float(v)) for v in embedding) + "]"


def format_embedding_for_storage(embedding: list[float]):
    """Format an embedding for ORM column storage.

    - Postgres: returns the list directly (pgvector Vector column handles it)
    - Snowflake: returns JSON string (stored in Text column)
    """
    if settings.database_backend == "snowflake":
        return "[" + ",".join(str(float(v)) for v in embedding) + "]"
    else:
        return embedding
