"""
Entra SAML login (SP) chained to a silent OIDC hop for the Snowflake token.

  /api/auth/saml/login     -> HTTP-Redirect AuthnRequest to Entra
  /api/auth/saml/acs       -> validate assertion, then 302 to Entra /authorize
                              with prompt=none + login_hint=<upn>
  /api/auth/oidc/callback  -> code -> tokens (confidential client), store
                              server-side, issue app JWT, back to deep link
  /api/auth/sso/logout     -> clear Snowflake tokens, return Entra logout URL
"""
import base64
import html
import json
import logging
import secrets
import time
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import jwt as jose_jwt
from lxml import etree
from signxml import XMLVerifier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import create_access_token, get_current_user
from ..core.config import settings
from ..core.database import get_db
from ..models.session import OAuthState
from ..models.user import User
from ..services import snowflake_oauth as sfo
from .oauth import _generate_pkce, _generate_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["sso"])

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}
CLOCK_SKEW = timedelta(minutes=3)
OIDC_PROVIDER = "entra_oidc"

# In-memory PoC stores (use Redis/DB in production)
_pending_requests: dict[str, tuple[str, float]] = {}   # AuthnRequest ID -> (relay, expiry)
_seen_assertions: dict[str, float] = {}                # assertion ID -> expiry (replay guard)
_idp_cache: dict = {}


def _acs_url() -> str:
    return f"{settings.oauth_base_url}/api/auth/saml/acs"


def _oidc_redirect() -> str:
    return f"{settings.oauth_base_url}/api/auth/oidc/callback"


def _safe_relay(relay: str | None) -> str:
    """Only allow same-origin relative paths (blocks open redirects)."""
    if not relay or not relay.startswith("/") or relay.startswith("//") or "\\" in relay:
        return "/"
    return relay


def _purge(store: dict) -> None:
    now = time.time()
    for k in [k for k, v in store.items() if (v[1] if isinstance(v, tuple) else v) < now]:
        store.pop(k, None)


async def _idp() -> dict:
    """Fetch and cache Entra federation metadata: entityID, SSO URL, signing certs."""
    if _idp_cache.get("exp", 0) > time.time():
        return _idp_cache
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.get(settings.saml_idp_metadata_url)
        resp.raise_for_status()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(resp.content, parser)
    idp = root.find("md:IDPSSODescriptor", NS)
    certs = [c.text.strip() for c in idp.findall("md:KeyDescriptor/ds:KeyInfo/ds:X509Data/ds:X509Certificate", NS)]
    sso = next(s.get("Location") for s in idp.findall("md:SingleSignOnService", NS)
               if s.get("Binding").endswith("HTTP-Redirect"))
    _idp_cache.update(entity_id=root.get("entityID"), sso_url=sso, certs=certs, exp=time.time() + 3600)
    return _idp_cache


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_assertion(saml_response_b64: str, idp: dict) -> dict:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(base64.b64decode(saml_response_b64), parser)

    status = root.find("samlp:Status/samlp:StatusCode", NS)
    if status is None or not status.get("Value", "").endswith(":Success"):
        raise HTTPException(401, f"SAML status not success: {status.get('Value') if status is not None else 'none'}")

    assertions = root.findall("saml:Assertion", NS)
    if len(assertions) != 1:
        raise HTTPException(401, "Expected exactly one assertion")

    # Verify signature over the assertion and continue ONLY with the signed subtree (anti XSW).
    assertion_bytes = etree.tostring(assertions[0])
    signed = None
    for cert in idp["certs"]:
        try:
            signed = XMLVerifier().verify(assertion_bytes, x509_cert=cert, parser=parser).signed_xml
            break
        except Exception as exc:  # try next cert (rollover)
            logger.debug("SAML cert did not verify: %s", exc)
    if signed is None:
        raise HTTPException(401, "SAML assertion signature invalid")

    if signed.findtext("saml:Issuer", namespaces=NS) != idp["entity_id"]:
        raise HTTPException(401, "Unexpected SAML issuer")

    now = datetime.now(timezone.utc)
    cond = signed.find("saml:Conditions", NS)
    if cond is None:
        raise HTTPException(401, "Missing Conditions")
    if now + CLOCK_SKEW < _parse_time(cond.get("NotBefore")) or now - CLOCK_SKEW >= _parse_time(cond.get("NotOnOrAfter")):
        raise HTTPException(401, "SAML assertion outside validity window")
    audiences = [a.text for a in cond.findall("saml:AudienceRestriction/saml:Audience", NS)]
    if settings.saml_sp_entity_id not in audiences:
        raise HTTPException(401, "SAML audience mismatch")

    scd = signed.find("saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData", NS)
    if scd is None or scd.get("Recipient") != _acs_url():
        raise HTTPException(401, "SAML recipient mismatch")
    if now - CLOCK_SKEW >= _parse_time(scd.get("NotOnOrAfter")):
        raise HTTPException(401, "SAML subject confirmation expired")

    _purge(_seen_assertions)
    aid = signed.get("ID")
    if aid in _seen_assertions:
        raise HTTPException(401, "SAML assertion replay")
    _seen_assertions[aid] = time.time() + 600

    attrs = {a.get("Name"): a.findtext("saml:AttributeValue", namespaces=NS)
             for a in signed.findall("saml:AttributeStatement/saml:Attribute", NS)}
    # Entra's default NameID for non-gallery apps is an opaque persistent ID; the UPN is in the
    # .../claims/name attribute (user.userprincipalname). Fall back to NameID if it's configured as UPN.
    upn = (attrs.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name")
           or signed.findtext("saml:Subject/saml:NameID", namespaces=NS))
    return {
        "upn": upn,
        "in_response_to": scd.get("InResponseTo"),
        "display_name": attrs.get("http://schemas.microsoft.com/identity/claims/displayname")
                        or attrs.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname") or "",
    }


# ------------------------------------------------------------------ routes

@router.get("/saml/login")
async def saml_login(next: str = Query("/")):
    if not settings.saml_enabled:
        raise HTTPException(404, "SAML not enabled")
    idp = await _idp()
    rid = f"_{uuid.uuid4().hex}"
    _purge(_pending_requests)
    relay = _safe_relay(next)
    _pending_requests[rid] = (relay, time.time() + 600)
    issue = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="{NS["samlp"]}" xmlns:saml="{NS["saml"]}" '
        f'ID="{rid}" Version="2.0" IssueInstant="{issue}" Destination="{idp["sso_url"]}" '
        f'AssertionConsumerServiceURL="{_acs_url()}" '
        f'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f'<saml:Issuer>{settings.saml_sp_entity_id}</saml:Issuer></samlp:AuthnRequest>'
    )
    deflater = zlib.compressobj(9, zlib.DEFLATED, -15)
    encoded = base64.b64encode(deflater.compress(xml.encode()) + deflater.flush()).decode()
    return RedirectResponse(f'{idp["sso_url"]}?{urlencode({"SAMLRequest": encoded, "RelayState": relay})}', 302)


@router.post("/saml/acs")
async def saml_acs(
    SAMLResponse: str = Form(...),
    RelayState: str = Form("/"),
    db: AsyncSession = Depends(get_db),
):
    idp = await _idp()
    claims = _validate_assertion(SAMLResponse, idp)

    # SP-initiated only: InResponseTo must match a request we issued.
    pending = _pending_requests.pop(claims["in_response_to"] or "", None)
    if not pending:
        raise HTTPException(401, "Unsolicited or expired SAML response")
    relay = pending[0]

    upn = claims["upn"].lower()
    user = (await db.execute(select(User).where(User.email == upn))).scalar_one_or_none()
    if not user:
        user = User(email=upn, display_name=claims["display_name"] or upn.split("@")[0], password_hash="", role="user")
        db.add(user)
        await db.flush()
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    if not settings.sf_oauth_enabled:
        return _finish_login(user, relay)
    redirect = await _oidc_redirect_response(db, user, relay, silent=True)
    return _interstitial(redirect.headers["location"])


def _interstitial(url: str) -> HTMLResponse:
    """Brief 'Connecting to your data' page; meta refresh replaces it, so it never lands in history."""
    safe = html.escape(url, quote=True)
    return HTMLResponse(
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={safe}"><title>Signing in</title>'
        f'<style>body{{font-family:system-ui;display:flex;height:100vh;align-items:center;justify-content:center;'
        f'color:#444}}</style></head><body><p>Connecting to your data&hellip;</p></body></html>',
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


async def _oidc_redirect_response(db: AsyncSession, user: User, relay: str, silent: bool) -> RedirectResponse:
    verifier, challenge = _generate_pkce()
    state = _generate_state()
    db.add(OAuthState(
        state=state, user_id=user.id, provider=OIDC_PROVIDER, code_verifier=verifier,
        # redirect_uri column doubles as relay + attempt marker for the PoC
        redirect_uri=f"{'silent' if silent else 'interactive'}|{relay}",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    ))
    await db.commit()
    params = {
        "client_id": settings.entra_client_id,
        "response_type": "code",
        "redirect_uri": _oidc_redirect(),
        "response_mode": "query",
        "scope": sfo.oidc_scopes(),
        "state": state,
        "nonce": secrets.token_urlsafe(16),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "login_hint": user.email,
    }
    if settings.entra_domain_hint:
        params["domain_hint"] = settings.entra_domain_hint
    if silent:
        params["prompt"] = "none"
    logger.info("[SSO] OIDC %s hop for %s", "silent" if silent else "interactive", user.email)
    return RedirectResponse(f"{sfo.entra_authorize_url()}?{urlencode(params)}", 302)


def _finish_login(user: User, relay: str) -> RedirectResponse:
    """Hand the app JWT to the SPA via URL fragment (never sent to servers or logged)."""
    token = create_access_token(user.id, user.email)
    u = base64.urlsafe_b64encode(json.dumps(
        {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}
    ).encode()).decode()
    return RedirectResponse(f"/sso-complete#token={token}&user={u}&next={quote(relay, safe='')}", 302)


@router.get("/oidc/callback")
async def oidc_callback(
    state: str = Query(...),
    code: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(OAuthState).where(OAuthState.state == state))).scalar_one_or_none()
    if not row or row.provider != OIDC_PROVIDER or row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invalid or expired state")
    attempt, relay = row.redirect_uri.split("|", 1)
    user_id, verifier = row.user_id, row.code_verifier
    await db.delete(row)
    await db.commit()
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()

    if error:
        logger.warning("[SSO] OIDC %s failed: %s %s", attempt, error, (error_description or "")[:200])
        if attempt == "silent" and error in ("login_required", "interaction_required", "consent_required", "account_selection_required"):
            # Fallback: real Entra UI (MFA / picker), still a top-level redirect.
            return await _oidc_redirect_response(db, user, relay, silent=False)
        raise HTTPException(401, f"Entra sign-in failed: {error}")

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(sfo.entra_token_url(), data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _oidc_redirect(),
            "client_id": settings.entra_client_id,
            "client_secret": settings.entra_client_secret,
            "code_verifier": verifier,
            "scope": sfo.oidc_scopes(),
        })
    if resp.status_code != 200:
        logger.error("[SSO] token exchange failed: %s", resp.text[:300])
        raise HTTPException(502, "Token exchange failed")
    tokens = resp.json()

    # Bind the OIDC identity to the SAML identity. The id_token came straight from Entra's
    # token endpoint over TLS to a confidential client, so its claims can be read directly.
    id_claims = jose_jwt.get_unverified_claims(tokens["id_token"])
    oidc_upn = (id_claims.get("preferred_username") or id_claims.get("upn") or "").lower()
    if oidc_upn != user.email:
        logger.error("[SSO] identity mismatch SAML=%s OIDC=%s", user.email, oidc_upn)
        raise HTTPException(401, "OIDC identity does not match SAML identity")

    await sfo.store_tokens(db, user.id, tokens)
    logger.info("[SSO] stored Snowflake token for %s (%s hop)", user.email, attempt)
    return _finish_login(user, relay)


@router.post("/sso/logout")
async def sso_logout(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await sfo.delete_tokens(db, user.id)
    logout = (f"https://login.microsoftonline.com/{settings.entra_tenant_id}/oauth2/v2.0/logout?"
              + urlencode({"post_logout_redirect_uri": f"{settings.oauth_base_url}/"}))
    return {"ok": True, "entra_logout_url": logout}


@router.get("/sso/status")
async def sso_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope = settings.entra_snowflake_scope or ""
    mode = "role-any" if "session:role-any" in scope else "scoped"
    try:
        await sfo.get_valid_snowflake_token(db, user.id)
        return {"snowflake_connected": True, "allowed_roles": sfo.allowed_roles(), "token_mode": mode,
                "default_role": settings.sf_oauth_default_role}
    except sfo.SnowflakeTokenMissing as exc:
        return {"snowflake_connected": False, "reason": str(exc), "token_mode": mode}
