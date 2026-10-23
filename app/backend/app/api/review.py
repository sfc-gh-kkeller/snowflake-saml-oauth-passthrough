import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import get_db
from ..core.auth import get_current_user
from ..models.user import User
from ..models.session import Asset, AssetVersion, ReviewFlag, Session
from ..services.embeddings import EmbeddingService
from ..services.cortex_agent import CortexAgentClient
from ..services.memory_plugin import get_memory_plugin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review", tags=["review"])


def require_reviewer(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("reviewer", "admin"):
        raise HTTPException(status_code=403, detail="Reviewer access required")
    return user


class ReviewAssetRequest(BaseModel):
    status: str
    reject_reason: Optional[str] = None
    notes: Optional[str] = None


class UpdateAssetContentRequest(BaseModel):
    content: str
    comment: Optional[str] = None
    filename: Optional[str] = None
    topic: Optional[str] = None


class FlagRequest(BaseModel):
    session_id: str
    reason: str


class ResolveFlagRequest(BaseModel):
    status: str


@router.get("/assets")
async def list_review_assets(
    status: Optional[str] = None,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    q = select(Asset).where(Asset.status.in_(["draft", "in_review", "pending"])).order_by(Asset.updated_at.desc())
    if status:
        q = select(Asset).where(Asset.status == status).order_by(Asset.updated_at.desc())
    result = await db.execute(q)
    assets = result.scalars().all()
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "content": (a.content or "")[:500],
            "status": a.status,
            "topic": a.topic,
            "owner_id": a.owner_id,
            "reviewer_id": a.reviewer_id,
            "reviewer_locked_at": a.reviewer_locked_at.isoformat() if a.reviewer_locked_at else None,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat(),
            "updated_at": a.updated_at.isoformat(),
        }
        for a in assets
    ]


@router.get("/assets/{asset_id}")
async def get_review_asset(
    asset_id: str,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    versions_result = await db.execute(
        select(AssetVersion).where(AssetVersion.asset_id == asset_id).order_by(AssetVersion.version.desc())
    )
    versions = versions_result.scalars().all()

    return {
        "id": asset.id,
        "filename": asset.filename,
        "content": asset.content,
        "status": asset.status,
        "topic": asset.topic,
        "owner_id": asset.owner_id,
        "is_active": asset.is_active,
        "approved_by": asset.approved_by,
        "approved_at": asset.approved_at.isoformat() if asset.approved_at else None,
        "approved_version": asset.approved_version,
        "reviewer_id": asset.reviewer_id,
        "reviewer_locked_at": asset.reviewer_locked_at.isoformat() if asset.reviewer_locked_at else None,
        "expires_at": asset.expires_at.isoformat() if asset.expires_at else None,
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "content": v.content,
                "edited_by": v.edited_by,
                "comment": v.comment,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
    }


@router.post("/assets/{asset_id}/claim")
async def claim_review_asset(
    asset_id: str,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.status != "in_review":
        raise HTTPException(status_code=400, detail="Asset is not in review")

    if asset.reviewer_id and asset.reviewer_id != user.id:
        # Any reviewer can claim over another reviewer
        pass

    asset.reviewer_id = user.id
    asset.reviewer_locked_at = datetime.now(timezone.utc)
    await db.commit()

    from .assets import _notify_claim_action
    await _notify_claim_action(asset, user, "claimed", db)

    return {"ok": True, "reviewer_id": user.id}


@router.delete("/assets/{asset_id}/claim")
async def release_review_asset(
    asset_id: str,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.reviewer_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the assigned reviewer can release")

    asset.reviewer_id = None
    asset.reviewer_locked_at = None
    await db.commit()

    from .assets import _notify_claim_action
    await _notify_claim_action(asset, user, "released", db)

    return {"ok": True}


class TransferClaimRequest(BaseModel):
    target_user_id: str


@router.put("/assets/{asset_id}/claim")
async def transfer_review_asset(
    asset_id: str,
    req: TransferClaimRequest,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.reviewer_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the assigned reviewer or admin can transfer")

    target_result = await db.execute(select(User).where(User.id == req.target_user_id))
    target_user = target_result.scalar_one_or_none()
    if not target_user or target_user.role not in ("reviewer", "admin"):
        raise HTTPException(status_code=400, detail="Target user is not a reviewer")

    asset.reviewer_id = target_user.id
    asset.reviewer_locked_at = datetime.now(timezone.utc)
    await db.commit()

    from .assets import _notify_claim_action
    await _notify_claim_action(asset, user, f"transferred to {target_user.display_name}", db)

    return {"ok": True, "reviewer_id": target_user.id}


@router.patch("/assets/{asset_id}/content")
async def update_asset_content(
    asset_id: str,
    req: UpdateAssetContentRequest,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    versions_result = await db.execute(
        select(AssetVersion)
        .where(AssetVersion.asset_id == asset_id)
        .order_by(AssetVersion.version.desc())
        .limit(1)
    )
    last_version = versions_result.scalar_one_or_none()
    next_version = (last_version.version + 1) if last_version else 1

    asset.content = req.content
    if req.filename:
        asset.filename = req.filename
    if req.topic:
        asset.topic = req.topic
    elif not asset.topic:
        topic = classify_topic(req.content)
        if topic:
            asset.topic = topic

    version = AssetVersion(
        asset_id=asset.id,
        version=next_version,
        content=req.content,
        edited_by=user.id,
        comment=req.comment or f"Edited by reviewer (v{next_version})",
    )
    db.add(version)
    await db.commit()
    await db.refresh(asset)

    return {
        "ok": True,
        "version": next_version,
        "asset_id": asset.id,
        "filename": asset.filename,
    }


@router.post("/assets/{asset_id}/restore/{version_id}")
async def restore_asset_version(
    asset_id: str,
    version_id: str,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    ver_result = await db.execute(
        select(AssetVersion).where(AssetVersion.id == version_id, AssetVersion.asset_id == asset_id)
    )
    source_version = ver_result.scalar_one_or_none()
    if not source_version:
        raise HTTPException(status_code=404, detail="Version not found")

    versions_result = await db.execute(
        select(AssetVersion)
        .where(AssetVersion.asset_id == asset_id)
        .order_by(AssetVersion.version.desc())
        .limit(1)
    )
    last_version = versions_result.scalar_one_or_none()
    next_version = (last_version.version + 1) if last_version else 1

    asset.content = source_version.content

    version = AssetVersion(
        asset_id=asset.id,
        version=next_version,
        content=source_version.content,
        edited_by=user.id,
        comment=f"Restored from v{source_version.version}",
    )
    db.add(version)
    await db.commit()

    return {"ok": True, "version": next_version, "content": source_version.content}


@router.put("/assets/{asset_id}")
async def review_asset(
    asset_id: str,
    req: ReviewAssetRequest,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    if req.status not in ("approved", "rejected", "draft", "in_review", "archived"):
        raise HTTPException(status_code=400, detail="Invalid status")

    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    asset.status = req.status

    if req.status == "approved":
        asset.approved_by = user.id
        asset.approved_at = datetime.now(timezone.utc)
        asset.expires_at = datetime.now(timezone.utc) + timedelta(days=settings.asset_ttl_days)

        latest_ver = await db.execute(
            select(AssetVersion.version)
            .where(AssetVersion.asset_id == asset_id)
            .order_by(AssetVersion.version.desc())
            .limit(1)
        )
        ver_num = latest_ver.scalar()
        asset.approved_version = ver_num

        if asset.content:
            try:
                agent = CortexAgentClient()
                if not agent.session_token:
                    await agent.authenticate()
                embedding_svc = EmbeddingService(session_token=agent.session_token)
                emb = await embedding_svc.generate(asset.content[:8000])
                if emb and isinstance(emb[0], list):
                    emb = emb[0]
                asset.embedding = emb
                logger.info("Embedding generated for asset %s (%d dims)", asset.id, len(emb) if emb else 0)
            except Exception as e:
                logger.error("Failed to generate embedding for asset %s: %s", asset.id, e)

        topic = classify_topic(asset.content or asset.filename)
        if topic:
            asset.topic = topic

        try:
            get_memory_plugin().index_asset(
                asset.id, asset.content or "",
                filename=asset.filename, topic=topic or asset.topic or "",
            )
        except Exception as e:
            logger.warning("Failed to index asset %s into zettel: %s", asset.id, e)

    if req.status in ("rejected", "draft", "in_review"):
        try:
            get_memory_plugin().remove_asset(asset.id)
        except Exception as e:
            logger.warning("Failed to remove asset %s from zettel: %s", asset.id, e)

    if req.status == "rejected" and req.reject_reason:
        version = AssetVersion(
            asset_id=asset.id,
            version=0,
            content=f"REJECTED: {req.reject_reason}",
            edited_by=user.id,
            comment=f"Rejected by reviewer: {req.reject_reason}",
        )
        db.add(version)

    # Clear reviewer assignment on any final action
    if req.status in ("approved", "rejected", "draft"):
        asset.reviewer_id = None
        asset.reviewer_locked_at = None

    await db.commit()

    # Send notification emails
    from .assets import _notify_review_decision
    await _notify_review_decision(asset, user, req.status, req.reject_reason, db)

    return {"ok": True, "status": asset.status}


@router.get("/flags")
async def list_flags(
    status: Optional[str] = None,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    q = select(ReviewFlag).order_by(ReviewFlag.created_at.desc())
    if status:
        q = q.where(ReviewFlag.status == status)
    else:
        q = q.where(ReviewFlag.status.in_(["pending", "in_review"]))
    result = await db.execute(q)
    flags = result.scalars().all()
    return [
        {
            "id": f.id,
            "session_id": f.session_id,
            "user_id": f.user_id,
            "reason": f.reason,
            "status": f.status,
            "reviewer_id": f.reviewer_id,
            "created_at": f.created_at.isoformat(),
        }
        for f in flags
    ]


@router.post("/flags")
async def create_flag(
    req: FlagRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Session).where(Session.id == req.session_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Session not found")

    flag = ReviewFlag(
        session_id=req.session_id,
        user_id=user.id,
        reason=req.reason,
        status="pending",
    )
    db.add(flag)
    await db.commit()
    await db.refresh(flag)
    return {"id": flag.id, "status": flag.status}


@router.put("/flags/{flag_id}")
async def resolve_flag(
    flag_id: str,
    req: ResolveFlagRequest,
    user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    if req.status not in ("reviewed", "dismissed"):
        raise HTTPException(status_code=400, detail="Invalid status")

    result = await db.execute(select(ReviewFlag).where(ReviewFlag.id == flag_id))
    flag = result.scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")

    flag.status = req.status
    flag.reviewer_id = user.id
    flag.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


TOPIC_KEYWORDS = {
    "authentication": ["authentication", "login", "password", "credential", "oauth", "saml", "federation", "idp"],
    "encryption": ["encrypt", "tls", "ssl", "aes", "tri-secret", "byok", "key rotation", "cipher"],
    "network": ["privatelink", "network policy", "firewall", "vpn", "sase", "proxy", "ip allow"],
    "rbac": ["role", "grant", "privilege", "rbac", "scim", "access control", "database role"],
    "compliance": ["soc2", "soc 2", "hipaa", "fedramp", "hitrust", "pci", "iso 27001", "gdpr", "ccpa"],
    "data_protection": ["masking", "row access", "classification", "dlp", "data protection", "tag-based"],
    "audit": ["audit", "access history", "query history", "login history", "siem", "log"],
    "key_management": ["hsm", "key hierarchy", "re-key", "key management", "escrow", "kms"],
    "mfa": ["mfa", "multi-factor", "totp", "duo", "webauthn", "authenticator"],
    "sso": ["sso", "single sign", "saml 2.0", "okta", "entra", "azure ad"],
    "ai_security": ["cortex", "ai security", "guardrail", "llm", "tenant isolation", "zdr", "trust"],
    "incident_response": ["incident", "breach", "forensic", "containment", "response plan"],
}


def classify_topic(text: str) -> Optional[str]:
    text_lower = (text or "").lower()
    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[topic] = score
    if not scores:
        return None
    return max(scores, key=scores.get)
