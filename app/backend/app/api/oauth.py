import hashlib
import base64
import os
import logging
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import get_db
from ..core.auth import get_current_user
from ..models.user import User
from ..models.session import UserOAuthToken, OAuthState, OAuthClient, AppSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


def _get_oauth_setting(key: str, default: str) -> str:
    """Read an OAuth setting from DB (app_settings) first, fall back to config."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT value FROM app_settings WHERE key = :k"), {"k": key})
            row = result.fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return default


PROVIDERS = {
    "glean": {
        "auth_url": lambda: settings.glean_auth_url,
        "token_url": lambda: settings.glean_token_url,
        "client_id": lambda: _get_oauth_setting("glean_client_id", settings.glean_client_id),
        "client_secret": lambda: _get_oauth_setting("glean_client_secret", settings.glean_client_secret),
        "scopes": lambda: _get_oauth_setting("glean_scopes", settings.glean_scopes),
        "dcr_url": lambda: settings.glean_dcr_url,
    },
    "atlassian": {
        "auth_url": lambda: settings.atlassian_auth_url,
        "token_url": lambda: settings.atlassian_token_url,
        "client_id": lambda: _get_oauth_setting("atlassian_client_id", settings.atlassian_client_id),
        "client_secret": lambda: _get_oauth_setting("atlassian_client_secret", settings.atlassian_client_secret),
        "scopes": lambda: _get_oauth_setting("atlassian_scopes", settings.atlassian_scopes),
        "dcr_url": lambda: "",
    },
}


def _generate_pkce():
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _generate_state():
    return base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()


async def _get_or_register_client(db: AsyncSession, provider: str) -> tuple[str, str]:
    result = await db.execute(
        select(OAuthClient).where(OAuthClient.provider == provider)
    )
    client = result.scalar_one_or_none()
    if client:
        return client.client_id, client.client_secret or ""

    prov = PROVIDERS[provider]
    client_id = prov["client_id"]()
    client_secret = prov["client_secret"]()
    if client_id:
        return client_id, client_secret

    dcr_url = prov["dcr_url"]()
    if not dcr_url:
        raise HTTPException(400, f"No client_id configured for {provider} and DCR not available")

    redirect_uri = f"{settings.oauth_base_url}/api/oauth/{provider}/callback"
    async with httpx.AsyncClient() as http:
        resp = await http.post(dcr_url, json={
            "client_name": f"NanoCortex - {provider}",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
        })
    if resp.status_code not in (200, 201):
        logger.error("DCR failed for %s: %s", provider, resp.text)
        raise HTTPException(502, f"Dynamic Client Registration failed for {provider}")

    data = resp.json()
    new_client = OAuthClient(
        provider=provider,
        client_id=data["client_id"],
        client_secret=data.get("client_secret"),
        registration_access_token=data.get("registration_access_token"),
        registration_client_uri=data.get("registration_client_uri"),
        redirect_uris=redirect_uri,
    )
    db.add(new_client)
    await db.commit()
    return new_client.client_id, new_client.client_secret or ""


@router.get("/status")
async def get_oauth_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserOAuthToken).where(UserOAuthToken.user_id == user.id)
    )
    tokens = result.scalars().all()

    connected = {}
    for t in tokens:
        connected[t.provider] = {
            "connected": True,
            "scope": t.scope,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }

    providers = {}
    for name in PROVIDERS:
        if name in connected:
            providers[name] = connected[name]
        else:
            providers[name] = {"connected": False}

    return {"providers": providers}


@router.get("/{provider}/start")
async def start_oauth(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider}")

    prov = PROVIDERS[provider]
    client_id, _ = await _get_or_register_client(db, provider)
    verifier, challenge = _generate_pkce()
    state = _generate_state()
    redirect_uri = f"{settings.oauth_base_url}/api/oauth/{provider}/callback"

    oauth_state = OAuthState(
        state=state,
        user_id=user.id,
        provider=provider,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(oauth_state)
    await db.commit()

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": prov["scopes"](),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if provider == "atlassian":
        params["audience"] = "api.atlassian.com"
        params["prompt"] = "consent"

    auth_url = prov["auth_url"]()
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return {"auth_url": f"{auth_url}?{qs}"}


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider}")

    result = await db.execute(
        select(OAuthState).where(OAuthState.state == state)
    )
    oauth_state = result.scalar_one_or_none()
    if not oauth_state:
        raise HTTPException(400, "Invalid or expired OAuth state")

    if oauth_state.expires_at < datetime.now(timezone.utc):
        await db.delete(oauth_state)
        await db.commit()
        raise HTTPException(400, "OAuth state expired")

    if oauth_state.provider != provider:
        raise HTTPException(400, "Provider mismatch")

    user_id = oauth_state.user_id
    code_verifier = oauth_state.code_verifier
    redirect_uri = oauth_state.redirect_uri

    await db.delete(oauth_state)
    await db.commit()

    client_id, client_secret = await _get_or_register_client(db, provider)
    prov = PROVIDERS[provider]

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if client_secret:
        token_data["client_secret"] = client_secret

    async with httpx.AsyncClient() as http:
        resp = await http.post(
            prov["token_url"](),
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        logger.error("Token exchange failed for %s: %s", provider, resp.text)
        return RedirectResponse(f"/settings?oauth_error=token_exchange_failed")

    token_resp = resp.json()
    access_token = token_resp.get("access_token", "")
    refresh_token = token_resp.get("refresh_token")
    token_type = token_resp.get("token_type", "Bearer")
    scope = token_resp.get("scope", "")
    expires_in = token_resp.get("expires_in")
    expires_at = None
    if expires_in:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    existing = await db.execute(
        select(UserOAuthToken).where(
            UserOAuthToken.user_id == user_id,
            UserOAuthToken.provider == provider,
        )
    )
    existing_token = existing.scalar_one_or_none()

    if existing_token:
        existing_token.access_token = access_token
        if refresh_token:
            existing_token.refresh_token = refresh_token
        existing_token.token_type = token_type
        existing_token.expires_at = expires_at
        existing_token.scope = scope
    else:
        db.add(UserOAuthToken(
            user_id=user_id,
            provider=provider,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type,
            expires_at=expires_at,
            scope=scope,
        ))

    await db.commit()
    return RedirectResponse(f"/settings?oauth_success={provider}")


@router.delete("/{provider}/disconnect")
async def disconnect_oauth(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider}")

    await db.execute(
        delete(UserOAuthToken).where(
            UserOAuthToken.user_id == user.id,
            UserOAuthToken.provider == provider,
        )
    )
    await db.commit()
    return {"ok": True, "provider": provider}


from pydantic import BaseModel as _BaseModel

class PasteTokenRequest(_BaseModel):
    access_token: str
    refresh_token: str | None = None


@router.put("/{provider}/token")
async def paste_oauth_token(
    provider: str,
    req: PasteTokenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider}")

    result = await db.execute(
        select(UserOAuthToken).where(
            UserOAuthToken.user_id == user.id,
            UserOAuthToken.provider == provider,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.access_token = req.access_token
        existing.refresh_token = req.refresh_token
        existing.scope = PROVIDERS[provider]["scopes"]()
        existing.expires_at = datetime.now(timezone.utc) + timedelta(days=90)
    else:
        token = UserOAuthToken(
            user_id=user.id,
            provider=provider,
            access_token=req.access_token,
            refresh_token=req.refresh_token,
            token_type="Bearer",
            scope=PROVIDERS[provider]["scopes"](),
            expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        )
        db.add(token)

    await db.commit()
    return {"ok": True, "provider": provider}
