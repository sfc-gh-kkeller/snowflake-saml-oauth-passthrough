import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, Integer, ForeignKey, Float, Boolean, func, JSON, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from ..core.config import settings

# Snowflake doesn't support regular indexes — only use them on Postgres
_USE_INDEX = settings.database_backend == "postgres"

# JSON column type — Snowflake needs VARIANT with JSON serialization
if settings.database_backend == "snowflake":
    import json as _json
    from sqlalchemy.types import TypeDecorator, Text as _Text

    class _JSON(TypeDecorator):
        """VARIANT column that auto-serializes Python dicts/lists to JSON strings."""
        impl = _Text
        cache_ok = True

        def process_bind_param(self, value, dialect):
            if value is None:
                return None
            return _json.dumps(value)

        def process_result_value(self, value, dialect):
            if value is None:
                return None
            if isinstance(value, str):
                try:
                    return _json.loads(value)
                except (ValueError, TypeError):
                    return value
            return value
else:
    _JSON = JSON

# Vector column type — pgvector for Postgres, Text (JSON array string) for Snowflake
if settings.database_backend == "postgres":
    from pgvector.sqlalchemy import Vector

    def _embedding_col():
        return mapped_column(Vector(settings.embedding_dimensions), nullable=True)
else:
    def _embedding_col():
        return mapped_column(Text, nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=_USE_INDEX)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="New Session")
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    history: Mapped[dict] = mapped_column(_JSON, nullable=False, default=list)
    pending_response: Mapped[dict] = mapped_column(_JSON, nullable=True)  # In-progress agent output
    internal_dialogue: Mapped[dict] = mapped_column(_JSON, nullable=True)  # Debug: reflection exchanges
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    total_time_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    time_to_first_token_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    web_search_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=_USE_INDEX)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    memory: Mapped[str] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserFile(Base):
    __tablename__ = "user_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=_USE_INDEX)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    extracted_pages: Mapped[dict] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="shared")
    topic: Mapped[str] = mapped_column(String(100), nullable=True)
    embedding = _embedding_col()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_by: Mapped[str] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_version: Mapped[int] = mapped_column(Integer, nullable=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AssetVersion(Base):
    __tablename__ = "asset_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=_USE_INDEX)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    edited_by: Mapped[str] = mapped_column(String(36), nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(String(100), nullable=True)
    embedding = _embedding_col()
    matched_asset_id: Mapped[str] = mapped_column(String(36), nullable=True)
    reuse_accepted: Mapped[bool] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchCache(Base):
    __tablename__ = "search_cache"

    query_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    results: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Topic(Base):
    __tablename__ = "security_topics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    leading_asset_id: Mapped[str] = mapped_column(String(36), nullable=True)


# Backward-compatible alias
SecurityTopic = Topic


class ReviewFlag(Base):
    __tablename__ = "review_flags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=_USE_INDEX)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSettings(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


from sqlalchemy import UniqueConstraint


class UserOAuthToken(Base):
    __tablename__ = "user_oauth_tokens"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=_USE_INDEX)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=_USE_INDEX)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=True)
    token_type: Mapped[str] = mapped_column(String(20), default="Bearer")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    scope: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret: Mapped[str] = mapped_column(Text, nullable=True)
    registration_access_token: Mapped[str] = mapped_column(Text, nullable=True)
    registration_client_uri: Mapped[str] = mapped_column(Text, nullable=True)
    redirect_uris: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=True)
    command: Mapped[str] = mapped_column(Text, nullable=True)
    args: Mapped[dict] = mapped_column(_JSON, nullable=True, default=list)
    auth_type: Mapped[str] = mapped_column(String(20), default="none")
    oauth_provider: Mapped[str] = mapped_column(String(50), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MagicLink(Base):
    __tablename__ = "magic_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=_USE_INDEX)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=_USE_INDEX)
    credential_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[str] = mapped_column(Text, nullable=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class MfaChallenge(Base):
    __tablename__ = "mfa_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    challenge: Mapped[str] = mapped_column(Text, nullable=True)
    rp_id: Mapped[str] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
