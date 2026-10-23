"""
PoC role-control checks: what role context does each Snowflake path actually give us?

GET /api/poc/role-check?role=APP_ANALYST
  1. rest_header      - Snowflake REST API (list schemas) with X-Snowflake-Role
  2. sql_default      - SQL API, role in body, secondary roles left at user default
  3. sql_no_secondary - SQL API, role in body, prefixed USE SECONDARY ROLES NONE
Each SQL path reports CURRENT_ROLE / CURRENT_SECONDARY_ROLES and whether the
PII table (granted only to APP_RESTRICTED) is readable.

`bypass_app_allowlist=true` (dev_mode only) skips the backend allowlist so the
Snowflake-side EXTERNAL_OAUTH_ALLOWED_ROLES_LIST can be shown rejecting a role.
"""
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import get_current_user
from ..core.config import settings
from ..core.database import get_db
from ..models.user import User
from ..services import snowflake_oauth as sfo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/poc", tags=["poc"])

CONTEXT_SQL = (
    "SELECT CURRENT_USER() AS USER_NAME, CURRENT_ROLE() AS PRIMARY_ROLE, "
    "CURRENT_SECONDARY_ROLES() AS SECONDARY_ROLES, "
    "IS_ROLE_IN_SESSION('APP_RESTRICTED') AS OTHER_ROLE_ACTIVE"
)
PII_SQL = "SELECT COUNT(*) AS N FROM SSO_DEMO_DB.SECRET.CLAIMS_PII"
APP_SQL = "SELECT COUNT(*) AS N FROM SSO_DEMO_DB.APP.POLICIES"


async def _sql_path(token: str, role: str, secondary: str, user: str, enforce: bool) -> dict:
    out: dict = {"role_requested": role, "secondary_roles_mode": secondary}
    try:
        ctx = sfo.rows_as_dicts(await sfo.run_sql(token, CONTEXT_SQL, role=role, secondary_roles=secondary,
                                                  user_label=user, enforce_allowlist=enforce))[0]
        if isinstance(ctx.get("SECONDARY_ROLES"), str):
            try:
                ctx["SECONDARY_ROLES"] = json.loads(ctx["SECONDARY_ROLES"])
            except json.JSONDecodeError:
                pass
        out["context"] = ctx
    except (sfo.SnowflakeSqlError, PermissionError, ValueError) as exc:
        out["error"] = str(exc)
        return out
    for key, sql in (("app_table_readable", APP_SQL), ("pii_table_readable", PII_SQL)):
        try:
            await sfo.run_sql(token, sql, role=role, secondary_roles=secondary, user_label=user, enforce_allowlist=enforce)
            out[key] = True
        except sfo.SnowflakeSqlError as exc:
            out[key] = False
            out[f"{key}_error"] = exc.message[:160]
    return out


async def _rest_path(token: str, role: str) -> dict:
    """REST resource API: only primary role via header, no secondary-role control."""
    url = f"{sfo.base_url()}/api/v2/databases/SSO_DEMO_DB/schemas"
    async with httpx.AsyncClient(timeout=60) as http:
        resp = await http.get(url, headers=sfo.oauth_headers(token, role))
    out: dict = {"role_requested": role, "http_status": resp.status_code}
    if resp.status_code == 200:
        names = sorted(s["name"] for s in resp.json())
        out["visible_schemas"] = names
        out["secret_schema_visible"] = "SECRET" in names
    else:
        out["error"] = resp.text[:300]
    return out


@router.get("/role-check")
async def role_check(
    role: str = Query(None),
    bypass_app_allowlist: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.sf_oauth_enabled:
        raise HTTPException(400, "snowflake_oauth not enabled")
    if bypass_app_allowlist and not settings.dev_mode:
        raise HTTPException(403, "bypass only available in dev_mode")
    try:
        token = await sfo.get_valid_snowflake_token(db, user.id)
    except sfo.SnowflakeTokenMissing as exc:
        raise HTTPException(401, f"Snowflake session missing: {exc}. Sign in again via SSO.")

    role = (role or settings.sf_oauth_default_role).upper()
    enforce = not bypass_app_allowlist
    if enforce:
        try:
            sfo.resolve_role(role)
        except (PermissionError, ValueError) as exc:
            return {"role": role, "blocked_by": "app_allowlist", "error": str(exc)}

    return {
        "role": role,
        "user": user.email,
        "app_allowlist": sfo.allowed_roles(),
        "paths": {
            "rest_header": await _rest_path(token, role),
            "sql_default": await _sql_path(token, role, "default", user.email, enforce),
            "sql_no_secondary": await _sql_path(token, role, "none", user.email, enforce),
        },
    }
