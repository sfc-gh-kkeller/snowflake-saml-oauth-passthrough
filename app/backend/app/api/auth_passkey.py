import json
import secrets
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from ..core.database import get_db
from ..core.config import settings
from ..core.auth import get_current_user_optional, create_access_token
from ..models.user import User
from ..models.session import WebAuthnCredential, MfaChallenge
from ..services.webauthn_service import (
    create_registration_options,
    verify_registration,
    create_authentication_options,
    verify_authentication,
    get_rp_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/passkey", tags=["passkey"])


class RegisterOptionsRequest(BaseModel):
    mfa_token: str | None = None


class RegisterVerifyRequest(BaseModel):
    credential: dict
    mfa_token: str | None = None
    device_name: str | None = None


class AuthOptionsRequest(BaseModel):
    mfa_token: str


class AuthVerifyRequest(BaseModel):
    mfa_token: str
    credential: dict


def _get_origin(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:9001")
    return f"{forwarded_proto}://{host}"


async def _resolve_mfa_user(mfa_token: str, db: AsyncSession) -> User:
    result = await db.execute(
        select(MfaChallenge).where(
            MfaChallenge.token == mfa_token,
            MfaChallenge.expires_at > datetime.now(timezone.utc),
        )
    )
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=401, detail="Invalid or expired MFA token")

    user_result = await db.execute(select(User).where(User.id == challenge.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/register-options")
async def passkey_register_options(
    req: RegisterOptionsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    if req.mfa_token:
        user = await _resolve_mfa_user(req.mfa_token, db)
    elif current_user:
        user = current_user
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    origin = _get_origin(request)
    rp_id = get_rp_id(origin)

    existing = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
    )
    existing_creds = existing.scalars().all()
    existing_ids = [base64url_to_bytes(c.credential_id) for c in existing_creds]

    options_json, challenge = create_registration_options(
        user_id=user.id,
        user_email=user.email,
        user_name=user.display_name,
        existing_credential_ids=existing_ids,
        rp_id=rp_id,
    )

    challenge_token = secrets.token_urlsafe(32)
    mfa_challenge = MfaChallenge(
        user_id=user.id,
        token=challenge_token,
        challenge=bytes_to_base64url(challenge),
        rp_id=rp_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db.add(mfa_challenge)
    await db.commit()

    return {
        "options": json.loads(options_json),
        "challenge_token": challenge_token,
    }


@router.post("/register-verify")
async def passkey_register_verify(
    req: RegisterVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    if req.mfa_token:
        user = await _resolve_mfa_user(req.mfa_token, db)
    elif current_user:
        user = current_user
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    challenge_token = req.credential.pop("challenge_token", None)
    if not challenge_token:
        raise HTTPException(status_code=400, detail="Missing challenge_token")

    result = await db.execute(
        select(MfaChallenge).where(
            MfaChallenge.token == challenge_token,
            MfaChallenge.user_id == user.id,
            MfaChallenge.expires_at > datetime.now(timezone.utc),
        )
    )
    stored = result.scalar_one_or_none()
    if not stored or not stored.challenge:
        raise HTTPException(status_code=401, detail="Invalid or expired challenge")

    origin = _get_origin(request)
    expected_challenge = base64url_to_bytes(stored.challenge)

    try:
        verified = verify_registration(
            credential_json=req.credential,
            expected_challenge=expected_challenge,
            expected_origin=origin,
            expected_rp_id=stored.rp_id,
        )
    except Exception as e:
        logger.error("Passkey registration verification failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Verification failed: {e}")

    cred = WebAuthnCredential(
        user_id=user.id,
        credential_id=verified["credential_id"],
        public_key=verified["public_key"],
        sign_count=verified["sign_count"],
        device_name=req.device_name,
    )
    db.add(cred)

    await db.delete(stored)
    await db.commit()

    token = create_access_token(user.id, user.email)
    return {
        "ok": True,
        "token": token,
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role},
    }


@router.post("/auth-options")
async def passkey_auth_options(
    req: AuthOptionsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _resolve_mfa_user(req.mfa_token, db)
    origin = _get_origin(request)
    rp_id = get_rp_id(origin)

    cred_result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
    )
    creds = cred_result.scalars().all()
    if not creds:
        raise HTTPException(status_code=400, detail="No passkeys registered")

    cred_ids = [base64url_to_bytes(c.credential_id) for c in creds]

    options_json, challenge = create_authentication_options(
        credential_ids=cred_ids,
        rp_id=rp_id,
    )

    result = await db.execute(
        select(MfaChallenge).where(MfaChallenge.token == req.mfa_token)
    )
    mfa_record = result.scalar_one_or_none()
    if mfa_record:
        mfa_record.challenge = bytes_to_base64url(challenge)
        mfa_record.rp_id = rp_id
        await db.commit()

    return {"options": json.loads(options_json)}


@router.post("/auth-verify")
async def passkey_auth_verify(
    req: AuthVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _resolve_mfa_user(req.mfa_token, db)

    result = await db.execute(
        select(MfaChallenge).where(
            MfaChallenge.token == req.mfa_token,
            MfaChallenge.user_id == user.id,
        )
    )
    stored = result.scalar_one_or_none()
    if not stored or not stored.challenge:
        raise HTTPException(status_code=401, detail="Invalid challenge state")

    raw_id = req.credential.get("id") or req.credential.get("rawId")
    if not raw_id:
        raise HTTPException(status_code=400, detail="Missing credential id")

    cred_result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == raw_id,
            WebAuthnCredential.user_id == user.id,
        )
    )
    stored_cred = cred_result.scalar_one_or_none()
    if not stored_cred:
        raise HTTPException(status_code=401, detail="Credential not found")

    origin = _get_origin(request)
    expected_challenge = base64url_to_bytes(stored.challenge)

    try:
        verified = verify_authentication(
            credential_json=req.credential,
            expected_challenge=expected_challenge,
            expected_origin=origin,
            expected_rp_id=stored.rp_id,
            credential_public_key=base64url_to_bytes(stored_cred.public_key),
            credential_current_sign_count=stored_cred.sign_count,
        )
    except Exception as e:
        logger.error("Passkey auth verification failed: %s", e)
        raise HTTPException(status_code=401, detail=f"Verification failed: {e}")

    stored_cred.sign_count = verified["new_sign_count"]
    stored_cred.last_used_at = datetime.now(timezone.utc)
    await db.delete(stored)
    await db.commit()

    token = create_access_token(user.id, user.email)
    return {
        "token": token,
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role},
    }
