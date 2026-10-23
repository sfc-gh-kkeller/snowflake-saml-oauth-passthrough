import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.auth import get_current_user
from ..core.config import settings
from ..core.queries import similarity_search_sql, format_embedding_for_query, format_embedding_for_storage
from ..models.user import User
from ..models.session import Asset, AssetVersion, Session
from ..services.embeddings import EmbeddingService
from ..services.cortex_agent import CortexAgentClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assets", tags=["assets"])


class RegisterAssetRequest(BaseModel):
    session_id: Optional[str] = None
    filename: str
    content: str
    topic: Optional[str] = None


class UpdateStatusRequest(BaseModel):
    status: str
    review_notes: Optional[str] = None


class SaveEditRequest(BaseModel):
    content: str
    comment: Optional[str] = None


@router.get("")
async def list_assets(
    status: Optional[str] = None,
    topic: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Asset).where(Asset.visibility == "shared").order_by(Asset.updated_at.desc())
    if status:
        q = q.where(Asset.status == status)
    if topic:
        q = q.where(Asset.topic == topic)
    result = await db.execute(q)
    assets = result.scalars().all()
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "status": a.status,
            "visibility": a.visibility,
            "topic": a.topic,
            "owner_id": a.owner_id,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat(),
            "updated_at": a.updated_at.isoformat(),
        }
        for a in assets
    ]


@router.get("/mine")
async def list_my_assets(
    visibility: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Asset).where(Asset.owner_id == user.id).order_by(Asset.updated_at.desc())
    if visibility:
        q = q.where(Asset.visibility == visibility)
    else:
        q = q.where(Asset.visibility.in_(["generated", "private"]))
    result = await db.execute(q)
    assets = result.scalars().all()
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "status": a.status,
            "visibility": a.visibility,
            "topic": a.topic,
            "session_id": a.session_id,
            "created_at": a.created_at.isoformat(),
            "updated_at": a.updated_at.isoformat(),
        }
        for a in assets
    ]


@router.put("/{asset_id}/promote")
async def promote_asset(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can promote this asset")
    if asset.visibility == "shared":
        raise HTTPException(status_code=400, detail="Asset is already shared")
    asset.visibility = "shared"
    asset.status = "draft"
    await db.commit()
    return {"ok": True, "visibility": "shared", "status": "draft"}


@router.post("")
async def register_asset(
    req: RegisterAssetRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    asset = Asset(
        session_id=req.session_id,
        owner_id=user.id,
        filename=req.filename,
        content=req.content,
        topic=req.topic,
        status="draft",
    )
    db.add(asset)
    await db.flush()

    version = AssetVersion(
        asset_id=asset.id,
        version=1,
        content=req.content,
        edited_by=user.id,
        comment="Initial version",
    )
    db.add(version)
    await db.commit()
    await db.refresh(asset)

    return {"id": asset.id, "status": asset.status}


@router.get("/search")
async def search_similar_assets(
    query: str,
    limit: int = 5,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = CortexAgentClient()
    if not agent.session_token:
        await agent.authenticate()
    embedding_svc = EmbeddingService(session_token=agent.session_token)
    embedding = await embedding_svc.generate(query)

    if embedding and isinstance(embedding[0], list):
        embedding = embedding[0]
    emb_str = format_embedding_for_query(embedding)

    result = await db.execute(
        text(similarity_search_sql(table="assets", limit=limit)),
        {"emb": emb_str, "threshold": settings.similarity_threshold, "lim": limit},
    )
    rows = result.fetchall()
    return [{"id": r.id, "filename": r.filename, "topic": r.topic, "similarity": float(r.similarity)} for r in rows]


@router.get("/by-session/{session_id}")
async def get_assets_by_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Asset).where(Asset.session_id == session_id).order_by(Asset.created_at.desc())
    )
    assets = result.scalars().all()
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "content": a.content,
            "status": a.status,
            "topic": a.topic,
            "owner_id": a.owner_id,
            "created_at": a.created_at.isoformat(),
            "updated_at": a.updated_at.isoformat(),
        }
        for a in assets
    ]


@router.get("/{asset_id}")
async def get_asset(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
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
        "has_embedding": asset.embedding is not None,
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
    }


@router.put("/{asset_id}/status")
async def update_asset_status(
    asset_id: str,
    req: UpdateStatusRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Only the owner can withdraw from review (back to draft)
    if asset.status == "in_review":
        if req.status != "draft" or asset.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Only the asset owner can withdraw from review")
        asset.reviewer_id = None
        asset.reviewer_locked_at = None

    asset.status = req.status
    if req.status == "approved":
        asset.approved_by = user.id
        asset.approved_at = datetime.now(timezone.utc)
        asset.expires_at = datetime.now(timezone.utc) + timedelta(days=settings.asset_ttl_days)

        latest_ver = await db.execute(
            select(func.max(AssetVersion.version)).where(AssetVersion.asset_id == asset_id)
        )
        asset.approved_version = latest_ver.scalar()

        if asset.content:
            try:
                agent = CortexAgentClient()
                if not agent.session_token:
                    await agent.authenticate()
                embedding_svc = EmbeddingService(session_token=agent.session_token)
                emb = await embedding_svc.generate(asset.content[:8000])
                if emb and isinstance(emb[0], list):
                    emb = emb[0]
                asset.embedding = format_embedding_for_storage(emb)
                logger.info("Embedding generated for asset %s (%d dims)", asset.id, len(emb) if emb else 0)
            except Exception as e:
                logger.error("Failed to generate embedding for asset %s: %s", asset.id, e)

    await db.commit()

    # Notify reviewers when submitted for review
    if req.status == "in_review":
        await _notify_review_submitted(asset, user, db)

    return {"ok": True, "status": asset.status}


@router.get("/{asset_id}/versions")
async def list_asset_versions(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AssetVersion)
        .where(AssetVersion.asset_id == asset_id)
        .order_by(AssetVersion.version.desc())
    )
    versions = result.scalars().all()
    return [
        {
            "id": v.id,
            "version": v.version,
            "edited_by": v.edited_by,
            "comment": v.comment,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


@router.get("/{asset_id}/versions/{version_num}")
async def get_asset_version(
    asset_id: str,
    version_num: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AssetVersion).where(
            AssetVersion.asset_id == asset_id,
            AssetVersion.version == version_num,
        )
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return {
        "id": v.id,
        "version": v.version,
        "content": v.content,
        "edited_by": v.edited_by,
        "comment": v.comment,
        "created_at": v.created_at.isoformat(),
    }


@router.put("/{asset_id}")
async def save_asset_edit(
    asset_id: str,
    req: SaveEditRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.status == "in_review" and user.role not in ("reviewer", "admin"):
        raise HTTPException(status_code=403, detail="Asset is under review and cannot be edited")

    max_ver = await db.execute(
        select(func.max(AssetVersion.version)).where(AssetVersion.asset_id == asset_id)
    )
    current_max = max_ver.scalar() or 0

    version = AssetVersion(
        asset_id=asset_id,
        version=current_max + 1,
        content=req.content,
        edited_by=user.id,
        comment=req.comment or "Manual edit",
    )
    db.add(version)

    asset.content = req.content
    await db.commit()

    return {"ok": True, "version": version.version}


@router.get("/{asset_id}/download")
async def download_asset(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import Response
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    return Response(
        content=asset.content or "",
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{asset.filename}"'},
    )


# --- Notification helpers (called from review.py too) ---

async def _notify_review_submitted(asset: Asset, submitter: User, db: AsyncSession):
    """Notify all reviewers + submitter that an asset was submitted for review."""
    from ..services.email import send_review_submitted_email

    try:
        result = await db.execute(
            select(User.email).where(User.role.in_(["reviewer", "admin"]), User.is_active == True)
        )
        reviewer_emails = [r[0] for r in result.all()]
        # Include submitter
        all_emails = list(set(reviewer_emails + [submitter.email]))
        send_review_submitted_email(all_emails, asset.filename, submitter.display_name)
    except Exception as e:
        logger.error("Failed to send review submitted notifications: %s", e)


async def _notify_review_claimed(asset: Asset, reviewer: User, db: AsyncSession):
    """Notify the asset owner that a reviewer claimed their asset."""
    from ..services.email import send_review_claimed_email

    try:
        owner_result = await db.execute(select(User).where(User.id == asset.owner_id))
        owner = owner_result.scalar_one_or_none()
        if owner:
            send_review_claimed_email(owner.email, asset.filename, reviewer.display_name)
    except Exception as e:
        logger.error("Failed to send review claimed notification: %s", e)


async def _notify_claim_action(asset: Asset, actor: User, action: str, db: AsyncSession):
    """Notify all admins and reviewers about a claim/unclaim/transfer action."""
    from ..services.email import send_claim_action_email

    try:
        result = await db.execute(
            select(User.email).where(User.role.in_(["reviewer", "admin"]), User.is_active == True)
        )
        reviewer_emails = [r[0] for r in result.all()]
        # Also include asset owner
        owner_result = await db.execute(select(User.email).where(User.id == asset.owner_id))
        owner_email = owner_result.scalar_one_or_none()
        all_emails = list(set(reviewer_emails + ([owner_email] if owner_email else [])))
        send_claim_action_email(all_emails, asset.filename, actor.display_name, action)
    except Exception as e:
        logger.error("Failed to send claim action notification: %s", e)


async def _notify_review_decision(asset: Asset, reviewer: User, status: str, reason: str | None, db: AsyncSession):
    """Notify asset owner + reviewer about approve/reject."""
    from ..services.email import send_review_approved_email, send_review_rejected_email

    try:
        owner_result = await db.execute(select(User).where(User.id == asset.owner_id))
        owner = owner_result.scalar_one_or_none()
        if not owner:
            return

        notify_emails = list(set([owner.email, reviewer.email]))

        if status == "approved":
            send_review_approved_email(notify_emails, asset.filename, reviewer.display_name)
        elif status == "rejected":
            send_review_rejected_email(notify_emails, asset.filename, reviewer.display_name, reason or "")
    except Exception as e:
        logger.error("Failed to send review decision notification: %s", e)
