"""
Per-user Snowflake access via Entra-issued External OAuth tokens.

- Tokens (access + refresh) are stored server-side in user_oauth_tokens,
  encrypted with Fernet. They never reach the browser.
- Every Snowflake call sets the primary role explicitly (allowlisted) and,
  by default, prefixes `USE SECONDARY ROLES NONE` so only that role's grants apply.
"""
import asyncio
import base64
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.session import UserOAuthToken

logger = logging.getLogger(__name__)

PROVIDER = "entra_snowflake"
_ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,254}$")
_QUERY_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


# ---------------------------------------------------------------- encryption

def _fernet() -> Fernet:
    key = settings.token_encryption_key
    if not key:
        # PoC fallback: derive from the app secret. Use a dedicated KMS-backed key in production.
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: Optional[str]) -> Optional[str]:
    return _fernet().encrypt(value.encode()).decode() if value else value


def decrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        raise RuntimeError("Stored Snowflake token could not be decrypted")


# ---------------------------------------------------------------- Entra endpoints

def entra_authorize_url() -> str:
    return f"https://login.microsoftonline.com/{settings.entra_tenant_id}/oauth2/v2.0/authorize"


def entra_token_url() -> str:
    return f"https://login.microsoftonline.com/{settings.entra_tenant_id}/oauth2/v2.0/token"


def oidc_scopes() -> str:
    return f"openid profile offline_access {settings.entra_snowflake_scope}"


class SnowflakeTokenMissing(Exception):
    """User has no usable Snowflake token; interactive re-auth needed."""


async def store_tokens(db: AsyncSession, user_id: str, token_resp: dict) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token_resp.get("expires_in", 3600)))
    result = await db.execute(
        select(UserOAuthToken).where(UserOAuthToken.user_id == user_id, UserOAuthToken.provider == PROVIDER)
    )
    row = result.scalar_one_or_none()
    access = encrypt(token_resp["access_token"])
    refresh = encrypt(token_resp.get("refresh_token"))
    if row:
        row.access_token = access
        if refresh:
            row.refresh_token = refresh
        row.expires_at = expires_at
        row.scope = token_resp.get("scope", "")
    else:
        db.add(UserOAuthToken(
            user_id=user_id, provider=PROVIDER, access_token=access, refresh_token=refresh,
            token_type="Bearer", expires_at=expires_at, scope=token_resp.get("scope", ""),
        ))
    await db.commit()


async def delete_tokens(db: AsyncSession, user_id: str) -> None:
    result = await db.execute(
        select(UserOAuthToken).where(UserOAuthToken.user_id == user_id, UserOAuthToken.provider == PROVIDER)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()


async def get_valid_snowflake_token(db: AsyncSession, user_id: str) -> str:
    """Return a non-expired access token, refreshing via the stored refresh token if needed."""
    result = await db.execute(
        select(UserOAuthToken).where(UserOAuthToken.user_id == user_id, UserOAuthToken.provider == PROVIDER)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise SnowflakeTokenMissing("No Snowflake token for user")

    if row.expires_at and row.expires_at > datetime.now(timezone.utc) + timedelta(minutes=2):
        return decrypt(row.access_token)

    refresh = decrypt(row.refresh_token)
    if not refresh:
        raise SnowflakeTokenMissing("Token expired and no refresh token")

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(entra_token_url(), data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": settings.entra_client_id,
            "client_secret": settings.entra_client_secret,
            "scope": oidc_scopes(),
        })
    if resp.status_code != 200:
        # e.g. Conditional Access sign-in frequency -> interaction_required
        logger.warning("Entra refresh failed: %s", resp.text[:300])
        raise SnowflakeTokenMissing(resp.json().get("error", "refresh_failed"))
    await store_tokens(db, user_id, resp.json())
    logger.info("[SF-OAUTH] refreshed token for user %s", user_id)
    return resp.json()["access_token"]


# ---------------------------------------------------------------- role control

def allowed_roles() -> list[str]:
    return [r.strip().upper() for r in (settings.sf_oauth_allowed_roles or "").split(",") if r.strip()]


def _check_role_name(role: str) -> str:
    role = role.upper()
    if not _ROLE_RE.match(role):
        raise ValueError(f"Invalid role name: {role!r}")
    return role


def resolve_role(requested: Optional[str]) -> str:
    """App-side allowlist. Snowflake's EXTERNAL_OAUTH_ALLOWED_ROLES_LIST is the hard cap behind it."""
    role = _check_role_name(requested or settings.sf_oauth_default_role or "")
    allow = allowed_roles()
    if allow and role not in allow:
        raise PermissionError(f"Role {role} is not allowed for this app")
    return role


def base_url() -> str:
    return f"https://{settings.snowflake_account.lower().replace('_', '-')}.snowflakecomputing.com"


def oauth_headers(token: str, role: Optional[str] = None) -> dict:
    h = {
        "Authorization": f"Bearer {token}",
        "X-Snowflake-Authorization-Token-Type": "OAUTH",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if role:
        h["X-Snowflake-Role"] = role
    return h


async def run_sql(
    token: str,
    sql: str,
    *,
    role: Optional[str],
    secondary_roles: str = "none",
    user_label: str = "",
    warehouse: Optional[str] = None,
    database: Optional[str] = None,
    schema: Optional[str] = None,
    timeout: int = 120,
    enforce_allowlist: bool = True,
) -> dict:
    """Run SQL through /api/v2/statements as the token's user.

    secondary_roles: "none" -> disable secondary roles for this request,
                     "default" -> leave whatever the user's session default is.

    For "none", queries (SELECT/WITH) are wrapped in a single Snowflake Scripting block
    (USE SECONDARY ROLES NONE + RETURN TABLE). Other statements fall back to a
    multi-statement request. The multi-statement child-result GET opens a session with the
    user's DEFAULT_ROLE, so that path also needs DEFAULT_ROLE in the integration allowlist.
    Either way `sql` must be fully rendered server-side: neither path supports binds here.
    Returns the SQL API JSON of the last statement.
    """
    if role is not None:
        role = resolve_role(role) if enforce_allowlist else _check_role_name(role)
    statement = sql
    params: dict = {"QUERY_TAG": f"app=sso-passthrough;user={user_label};role={role or '-'};sec={secondary_roles}"}
    if secondary_roles == "none":
        body = sql.strip().rstrip(";").strip()
        if _QUERY_RE.match(body) and "$$" not in body:
            statement = (
                "EXECUTE IMMEDIATE $$\nDECLARE res RESULTSET;\nBEGIN\n"
                "  USE SECONDARY ROLES NONE;\n"
                f"  res := ({body});\n"
                "  RETURN TABLE(res);\nEND;\n$$"
            )
        else:
            statement = f"USE SECONDARY ROLES NONE;\n{sql}"
            params["MULTI_STATEMENT_COUNT"] = "2"

    payload: dict = {"statement": statement, "timeout": timeout, "parameters": params,
                     "resultSetMetaData": {"format": "jsonv2"}}
    if role:
        payload["role"] = role
    wh = warehouse or settings.sf_oauth_warehouse
    if wh:
        payload["warehouse"] = wh.upper()
    if database:
        payload["database"] = database.upper()
    if schema:
        payload["schema"] = schema.upper()

    logger.info("[SF-OAUTH] user=%s role=%s secondary=%s", user_label, role, secondary_roles)
    url = f"{base_url()}/api/v2/statements"
    hdrs = oauth_headers(token)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 60, connect=30)) as http:
        resp = await http.post(url, json=payload, headers=hdrs)
        data = await _await_result(http, url, hdrs, resp)
        handles = data.get("statementHandles")
        if handles:
            last = await http.get(f"{url}/{handles[-1]}", headers=hdrs)
            data = await _await_result(http, url, hdrs, last)
    return data


async def _await_result(http: httpx.AsyncClient, url: str, hdrs: dict, resp: httpx.Response) -> dict:
    for _ in range(60):
        if resp.status_code != 202:
            break
        await asyncio.sleep(1)
        resp = await http.get(f"{url}/{resp.json()['statementHandle']}", headers=hdrs)
    try:
        data = resp.json()
    except json.JSONDecodeError:
        data = {"message": resp.text[:500]}
    if resp.status_code != 200:
        raise SnowflakeSqlError(resp.status_code, data.get("message", str(data))[:500], data.get("code"))
    return data


class SnowflakeSqlError(Exception):
    def __init__(self, status: int, message: str, code: Optional[str] = None):
        super().__init__(f"Snowflake SQL error {status} ({code}): {message}")
        self.status, self.message, self.code = status, message, code


def rows_as_dicts(data: dict) -> list[dict]:
    cols = [c["name"] for c in data.get("resultSetMetaData", {}).get("rowType", [])]
    return [dict(zip(cols, r)) for r in data.get("data", [])]


async def user_cortex_client(db: AsyncSession, user_id: str):
    """CortexAgentClient acting as the user (External OAuth) when enabled, else the shared PAT."""
    from .llm.cortex import CortexAgentClient
    if not settings.sf_oauth_enabled:
        return CortexAgentClient()
    from ..models.user import User
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    try:
        token = await get_valid_snowflake_token(db, user_id)
    except SnowflakeTokenMissing:
        # Password/magic-link users have no Entra token; fall back to the service identity.
        logger.info("[SF-OAUTH] no token for %s, using service PAT", user.email)
        return CortexAgentClient()
    return CortexAgentClient(oauth_token=token, user_label=user.email)
