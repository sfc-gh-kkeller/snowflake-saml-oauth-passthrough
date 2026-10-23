import secrets
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.config import settings
from ..core.auth import create_access_token, validate_email_domain
from ..models.user import User
from ..models.session import MagicLink
from ..services.email import send_magic_link_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthResponse(BaseModel):
    token: str
    user: dict
    passkey_required: bool = False
    mfa_token: str | None = None


class MagicLinkRequest(BaseModel):
    email: str


class MagicLinkVerifyRequest(BaseModel):
    token: str


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Password-based login."""
    from ..core.auth import verify_password, create_access_token

    email = req.email.lower().strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    token = create_access_token(user.id, user.email)
    return {
        "token": token,
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role},
    }


@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user with password."""
    from ..core.auth import hash_password, create_access_token

    if not settings.auth_allow_registration:
        raise HTTPException(status_code=403, detail="Registration is disabled")

    email = req.email.lower().strip()
    if settings.allowed_email_domain:
        if not validate_email_domain(email):
            raise HTTPException(status_code=400, detail=f"Only @{settings.allowed_email_domain} emails allowed")

    # Check if user exists
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already exists")

    display_name = req.display_name or email.split("@")[0].replace(".", " ").title()
    user = User(
        email=email,
        display_name=display_name,
        password_hash=hash_password(req.password),
        role="admin" if not (await db.execute(select(User).limit(1))).scalar_one_or_none() else "user",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.email)
    return {
        "token": token,
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role},
    }


@router.post("/magic-link")
async def request_magic_link(req: MagicLinkRequest, db: AsyncSession = Depends(get_db)):
    email = req.email.lower().strip()
    if settings.allowed_email_domain and not validate_email_domain(email):
        raise HTTPException(status_code=400, detail=f"Only @{settings.allowed_email_domain} email addresses are allowed")

    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.magic_link_expire_minutes)

    magic = MagicLink(
        email=email,
        token=token,
        expires_at=expires_at,
    )
    db.add(magic)
    await db.commit()

    send_magic_link_email(email, token)

    return {"ok": True, "message": "Magic link sent. Check your email."}


@router.post("/magic-link/verify")
async def verify_magic_link(req: MagicLinkVerifyRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MagicLink).where(
            MagicLink.token == req.token,
            MagicLink.used == False,
            MagicLink.expires_at > datetime.now(timezone.utc),
        )
    )
    magic = result.scalar_one_or_none()

    if not magic:
        # Check if token was recently used (double-fire protection)
        retry = await db.execute(
            select(MagicLink).where(
                MagicLink.token == req.token,
                MagicLink.used == True,
                MagicLink.expires_at > datetime.now(timezone.utc) - timedelta(minutes=5),
            )
        )
        recently_used = retry.scalar_one_or_none()
        if not recently_used:
            raise HTTPException(status_code=401, detail="Invalid or expired link")
        # Re-authenticate from the recently used token
        magic = recently_used
    else:
        magic.used = True

    user_result = await db.execute(select(User).where(User.email == magic.email))
    user = user_result.scalar_one_or_none()

    is_new = False
    if not user:
        user = User(
            email=magic.email,
            display_name=magic.email.split("@")[0].replace(".", " ").title(),
            password_hash="",
            role="user",
        )
        db.add(user)
        await db.flush()
        is_new = True

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    from ..models.session import WebAuthnCredential
    cred_result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id).limit(1)
    )
    has_passkey = cred_result.scalar_one_or_none() is not None

    if has_passkey:
        mfa_token = secrets.token_urlsafe(32)
        mfa_expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        from ..models.session import MfaChallenge
        challenge = MfaChallenge(
            user_id=user.id,
            token=mfa_token,
            expires_at=mfa_expires,
        )
        db.add(challenge)
        await db.commit()

        return {
            "token": None,
            "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role},
            "passkey_required": True,
            "mfa_token": mfa_token,
        }

    token = create_access_token(user.id, user.email)
    return {
        "token": token,
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role},
        "passkey_required": False,
        "mfa_token": None,
        "needs_passkey_setup": is_new or not has_passkey,
    }
