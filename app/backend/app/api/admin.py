import json
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, func, text, case, delete, update, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.auth import get_current_user, hash_password
from ..core.config import settings
from ..models.user import User
from ..models.session import Session, Asset, Feedback, Topic, AssetVersion, Question, ReviewFlag, AppSettings
from ..services.embeddings import EmbeddingService
from ..api.review import classify_topic

from ..services.asset_refresh import refresh_expired_assets, _refresh_asset

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/stats")
async def get_stats(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    users_count = await db.scalar(select(func.count()).select_from(User))
    sessions_count = await db.scalar(select(func.count()).select_from(Session))
    assets_count = await db.scalar(select(func.count()).select_from(Asset))
    approved_count = await db.scalar(select(func.count()).select_from(Asset).where(Asset.status == "approved"))
    in_review_count = await db.scalar(select(func.count()).select_from(Asset).where(Asset.status == "in_review"))
    rejected_count = await db.scalar(select(func.count()).select_from(Asset).where(Asset.status == "rejected"))
    draft_count = await db.scalar(select(func.count()).select_from(Asset).where(Asset.status == "draft"))
    with_embedding = await db.scalar(select(func.count()).select_from(Asset).where(Asset.embedding.isnot(None)))
    expired_count = await db.scalar(
        select(func.count()).select_from(Asset).where(
            Asset.status == "approved",
            Asset.expires_at.isnot(None),
            Asset.expires_at < func.now(),
        )
    )
    versions_count = await db.scalar(select(func.count()).select_from(AssetVersion))
    feedback_count = await db.scalar(select(func.count()).select_from(Feedback))
    pending_flags = await db.scalar(
        select(func.count()).select_from(ReviewFlag).where(ReviewFlag.status == "pending")
    )
    sessions_today = await db.scalar(
        select(func.count()).select_from(Session).where(
            func.date(Session.created_at) == date.today()
        )
    )
    total_questions = await db.scalar(select(func.count()).select_from(Question))

    topic_result = await db.execute(
        select(Asset.topic, func.count()).where(Asset.topic.isnot(None)).group_by(Asset.topic).order_by(func.count().desc())
    )
    topics_breakdown = [{"topic": r[0], "count": r[1]} for r in topic_result.fetchall()]

    return {
        "users": users_count,
        "sessions": sessions_count,
        "assets_total": assets_count,
        "assets_approved": approved_count,
        "assets_in_review": in_review_count,
        "assets_rejected": rejected_count,
        "assets_draft": draft_count,
        "assets_with_embedding": with_embedding,
        "assets_expired": expired_count,
        "versions_total": versions_count,
        "feedback_total": feedback_count,
        "pending_flags": pending_flags,
        "sessions_today": sessions_today,
        "total_questions": total_questions,
        "topics_breakdown": topics_breakdown,
    }


@router.get("/users")
async def list_users(
    search: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    base = select(User)
    count_base = select(func.count()).select_from(User)

    if search:
        base = base.where(or_(User.email.ilike(f"%{search}%"), User.display_name.ilike(f"%{search}%")))
        count_base = count_base.where(or_(User.email.ilike(f"%{search}%"), User.display_name.ilike(f"%{search}%")))
    if role:
        base = base.where(User.role == role)
        count_base = count_base.where(User.role == role)

    total = await db.scalar(count_base) or 0
    result = await db.execute(base.order_by(User.created_at.desc()).limit(limit).offset(offset))
    users = result.scalars().all()
    return {
        "total": total,
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "role": u.role,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat(),
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in users
        ],
    }


class UpdateRoleRequest(BaseModel):
    role: str


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    req: UpdateRoleRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if req.role not in ("user", "reviewer", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.role = req.role
    await db.commit()
    return {"ok": True}


@router.put("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    target.is_active = not target.is_active
    await db.commit()
    return {"ok": True, "is_active": target.is_active}


class UpdateEmailRequest(BaseModel):
    email: str


@router.put("/users/{user_id}/email")
async def update_user_email(
    user_id: str,
    req: UpdateEmailRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    email = req.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    existing = await db.execute(select(User).where(User.email == email, User.id != user_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already in use")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.email = email
    await db.commit()
    return {"ok": True, "email": email}


@router.delete("/users/{user_id}/passkeys")
async def reset_user_passkeys(
    user_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ..models.session import WebAuthnCredential
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id)
    )
    from sqlalchemy import delete as sql_delete
    await db.execute(sql_delete(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id))
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(target)
    await db.commit()
    return {"ok": True}


@router.get("/topics")
async def list_topics(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Topic).order_by(Topic.name))
    topics = result.scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "question_count": t.question_count,
        }
        for t in topics
    ]


@router.get("/analytics/reuse")
async def get_reuse_analytics(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total_questions = await db.scalar(select(func.count()).select_from(Question)) or 0
    reused_count = await db.scalar(
        select(func.count()).select_from(Question).where(Question.reuse_accepted == True)
    ) or 0
    suggested_count = await db.scalar(
        select(func.count()).select_from(Question).where(Question.matched_asset_id.isnot(None))
    ) or 0

    reuse_rate = round(reused_count / total_questions * 100, 1) if total_questions else 0
    acceptance_rate = round(reused_count / suggested_count * 100, 1) if suggested_count else 0

    top_result = await db.execute(
        select(
            Asset.id, Asset.filename,
            func.count(Question.id).label("reuse_count"),
        )
        .join(Question, Question.matched_asset_id == Asset.id)
        .where(Question.reuse_accepted == True)
        .group_by(Asset.id, Asset.filename)
        .order_by(func.count(Question.id).desc())
        .limit(10)
    )
    top_reused = [
        {"id": r.id, "filename": r.filename, "reuse_count": r.reuse_count}
        for r in top_result.fetchall()
    ]

    return {
        "total_questions": total_questions,
        "reused_count": reused_count,
        "suggested_count": suggested_count,
        "reuse_rate": reuse_rate,
        "acceptance_rate": acceptance_rate,
        "top_reused_assets": top_reused,
    }


@router.get("/analytics/questions")
async def get_question_analytics(
    topic: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    base = select(
        Question.id,
        Question.question_text,
        Question.topic,
        Question.session_id,
        Question.matched_asset_id,
        Question.reuse_accepted,
        Question.created_at,
        User.email,
        User.display_name,
    ).join(User, User.id == Question.user_id)

    count_base = select(func.count()).select_from(Question).join(User, User.id == Question.user_id)

    if topic:
        base = base.where(Question.topic == topic)
        count_base = count_base.where(Question.topic == topic)
    if search:
        base = base.where(Question.question_text.ilike(f"%{search}%"))
        count_base = count_base.where(Question.question_text.ilike(f"%{search}%"))

    total = await db.scalar(count_base) or 0
    result = await db.execute(
        base.order_by(Question.created_at.desc()).limit(limit).offset(offset)
    )
    questions = [
        {
            "id": r.id,
            "question_text": r.question_text[:200],
            "topic": r.topic,
            "session_id": r.session_id,
            "matched_asset_id": r.matched_asset_id,
            "reuse_accepted": r.reuse_accepted,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "user_email": r.email,
            "user_name": r.display_name,
        }
        for r in result.fetchall()
    ]

    return {"total": total, "questions": questions}


@router.get("/analytics/users")
async def get_user_question_stats(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            User.id,
            User.email,
            User.display_name,
            func.count(Question.id).label("question_count"),
            func.sum(case((Question.reuse_accepted == True, 1), else_=0)).label("reuse_count"),
        )
        .outerjoin(Question, User.id == Question.user_id)
        .group_by(User.id, User.email, User.display_name)
        .order_by(func.count(Question.id).desc())
        .limit(50)
    )
    return [
        {
            "id": r.id,
            "email": r.email,
            "display_name": r.display_name,
            "question_count": r.question_count,
            "reuse_count": r.reuse_count or 0,
            "reuse_rate": round((r.reuse_count or 0) / r.question_count * 100, 1) if r.question_count else 0,
        }
        for r in result.fetchall()
    ]


@router.get("/analytics/feedback")
async def get_feedback_analytics(
    filter: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    positive = await db.scalar(
        select(func.count()).select_from(Feedback).where(Feedback.rating == 1)
    ) or 0
    negative = await db.scalar(
        select(func.count()).select_from(Feedback).where(Feedback.rating == 0)
    ) or 0
    total = positive + negative

    base = (
        select(
            Feedback.id,
            Feedback.session_id,
            Feedback.rating,
            Feedback.comment,
            Feedback.created_at,
            User.email,
            User.display_name,
        )
        .join(User, User.id == Feedback.user_id)
    )
    if filter == "positive":
        base = base.where(Feedback.rating == 1)
    elif filter == "negative":
        base = base.where(Feedback.rating == 0)

    result = await db.execute(
        base.order_by(Feedback.created_at.desc()).limit(limit).offset(offset)
    )
    items = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "rating": r.rating,
            "comment": r.comment,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "user_email": r.email,
            "user_name": r.display_name,
        }
        for r in result.fetchall()
    ]

    return {
        "positive": positive,
        "negative": negative,
        "total": total,
        "satisfaction_rate": round(positive / total * 100, 1) if total else 0,
        "feedback": items,
    }


@router.get("/sessions")
async def list_admin_sessions(
    search: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    base = (
        select(
            Session.id,
            Session.title,
            Session.status,
            Session.total_time_ms,
            Session.time_to_first_token_ms,
            Session.web_search_count,
            Session.created_at,
            Session.updated_at,
            Session.deleted_at,
            User.email,
            User.display_name,
        )
        .join(User, User.id == Session.user_id)
    )
    count_base = select(func.count()).select_from(Session).join(User, User.id == Session.user_id)

    if search:
        base = base.where(or_(Session.title.ilike(f"%{search}%"), User.email.ilike(f"%{search}%")))
        count_base = count_base.where(or_(Session.title.ilike(f"%{search}%"), User.email.ilike(f"%{search}%")))
    if status:
        base = base.where(Session.status == status)
        count_base = count_base.where(Session.status == status)

    total = await db.scalar(count_base) or 0
    result = await db.execute(base.order_by(Session.created_at.desc()).limit(limit).offset(offset))
    sessions = [
        {
            "id": r.id,
            "title": r.title,
            "status": r.status,
            "total_time_ms": r.total_time_ms,
            "ttft_ms": r.time_to_first_token_ms,
            "web_search_count": r.web_search_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
            "user_email": r.email,
            "user_name": r.display_name,
        }
        for r in result.fetchall()
    ]
    return {"total": total, "sessions": sessions}


@router.delete("/sessions/{session_id}")
async def hard_delete_session(
    session_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()
    return {"ok": True}


@router.get("/sessions/{session_id}/internal")
async def get_session_internal_dialogue(
    session_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get the internal dialogue (reflection exchanges) for a session."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    return {
        "session_id": session_id,
        "internal_dialogue": session.internal_dialogue,
    }


@router.get("/flags")
async def list_admin_flags(
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    base = (
        select(
            ReviewFlag.id,
            ReviewFlag.session_id,
            ReviewFlag.reason,
            ReviewFlag.status,
            ReviewFlag.created_at,
            ReviewFlag.resolved_at,
            User.email.label("user_email"),
            User.display_name.label("user_name"),
        )
        .join(User, User.id == ReviewFlag.user_id)
    )
    count_base = select(func.count()).select_from(ReviewFlag)

    if status:
        base = base.where(ReviewFlag.status == status)
        count_base = count_base.where(ReviewFlag.status == status)

    total = await db.scalar(count_base) or 0
    result = await db.execute(base.order_by(ReviewFlag.created_at.desc()).limit(limit).offset(offset))
    flags = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "reason": r.reason,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "user_email": r.user_email,
            "user_name": r.user_name,
        }
        for r in result.fetchall()
    ]
    return {"total": total, "flags": flags}


@router.get("/assets")
async def list_admin_assets(
    status: Optional[str] = None,
    topic: Optional[str] = None,
    search: Optional[str] = None,
    visibility: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    base = select(Asset)
    count_base = select(func.count()).select_from(Asset)

    # Default: exclude generated assets unless explicitly requested
    if visibility:
        base = base.where(Asset.visibility == visibility)
        count_base = count_base.where(Asset.visibility == visibility)
    else:
        base = base.where(Asset.visibility != "generated")
        count_base = count_base.where(Asset.visibility != "generated")

    if status:
        base = base.where(Asset.status == status)
        count_base = count_base.where(Asset.status == status)
    if topic:
        base = base.where(Asset.topic == topic)
        count_base = count_base.where(Asset.topic == topic)
    if search:
        base = base.where(Asset.filename.ilike(f"%{search}%"))
        count_base = count_base.where(Asset.filename.ilike(f"%{search}%"))

    total = await db.scalar(count_base) or 0
    result = await db.execute(base.order_by(Asset.updated_at.desc()).limit(limit).offset(offset))
    assets = result.scalars().all()
    return {
        "total": total,
        "assets": [
            {
                "id": a.id,
                "filename": a.filename,
                "status": a.status,
                "visibility": a.visibility,
                "topic": a.topic,
                "is_active": a.is_active,
                "owner_id": a.owner_id,
                "approved_at": a.approved_at.isoformat() if a.approved_at else None,
                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                "created_at": a.created_at.isoformat(),
                "updated_at": a.updated_at.isoformat(),
            }
            for a in assets
        ],
    }


@router.delete("/assets/{asset_id}")
async def delete_admin_asset(
    asset_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    await db.execute(delete(AssetVersion).where(AssetVersion.asset_id == asset_id))
    await db.delete(asset)
    await db.commit()
    return {"ok": True}


class ClassifyRequest(BaseModel):
    topic: Optional[str] = None


@router.patch("/assets/{asset_id}/classify")
async def classify_admin_asset(
    asset_id: str,
    req: ClassifyRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if req.topic:
        asset.topic = req.topic
    else:
        topic = classify_topic(asset.content or asset.filename)
        asset.topic = topic

    await db.commit()
    return {"ok": True, "topic": asset.topic}


@router.post("/assets/{asset_id}/deactivate")
async def deactivate_admin_asset(
    asset_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    asset.is_active = not asset.is_active
    await db.commit()
    return {"ok": True, "is_active": asset.is_active}


@router.post("/assets/fix-expiration")
async def fix_asset_expiration(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Asset).where(
            Asset.status == "approved",
            Asset.expires_at.is_(None),
        )
    )
    assets = result.scalars().all()
    count = 0
    for a in assets:
        base_time = a.approved_at or a.updated_at or a.created_at
        a.expires_at = base_time + timedelta(days=settings.asset_ttl_days)
        count += 1

    await db.commit()
    return {"ok": True, "fixed": count}


@router.post("/assets/classify-all")
async def classify_all_assets(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Asset).where(Asset.topic.is_(None))
    )
    assets = result.scalars().all()
    classified = 0
    for a in assets:
        topic = classify_topic(a.content or a.filename)
        if topic:
            a.topic = topic
            classified += 1

    await db.commit()
    return {"ok": True, "classified": classified, "total_unclassified": len(assets)}


@router.get("/topics/with-assets")
async def list_topics_with_assets(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            Topic.id,
            Topic.name,
            Topic.description,
            Topic.question_count,
            func.count(Asset.id).label("asset_count"),
        )
        .outerjoin(Asset, Asset.topic == Topic.name)
        .group_by(Topic.id, Topic.name, Topic.description, Topic.question_count)
        .order_by(Topic.name)
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "question_count": r.question_count,
            "asset_count": r.asset_count,
        }
        for r in result.fetchall()
    ]


@router.get("/settings")
async def get_settings(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ..core.config import SECRET_FIELDS, _FIELD_MAP
    schema = settings.get_schema()
    # Mask secrets in response
    for field in schema:
        if field["secret"]:
            val = field["value"]
            if val:
                field["value"] = str(val)[:4] + "••••" + str(val)[-4:] if len(str(val)) > 8 else "••••••••"
    sections = settings.get_all()
    # Mask secrets in sections view
    secret_keys_by_section: dict[str, set] = {}
    for attr_name, (section, key) in _FIELD_MAP.items():
        if attr_name in SECRET_FIELDS:
            secret_keys_by_section.setdefault(section, set()).add(key)
    for section_name, section_data in sections.items():
        for key in secret_keys_by_section.get(section_name, set()):
            val = section_data.get(key)
            if val:
                section_data[key] = str(val)[:4] + "••••" + str(val)[-4:] if len(str(val)) > 8 else "••••••••"
    return {"settings": sections, "schema": schema}


class UpdateSettingsRequest(BaseModel):
    settings: dict[str, str]


@router.put("/settings")
async def update_settings(
    req: UpdateSettingsRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ..core.config import SECRET_FIELDS, _FIELD_MAP
    # Filter out masked secrets (don't save "••••" back)
    changes = {}
    for key, value in req.settings.items():
        if key in SECRET_FIELDS and "••••" in str(value):
            continue  # Skip masked values
        changes[key] = value

    # Persist to config.toml
    if changes:
        settings.update(changes)

    # Also store in app_settings DB for backward compat with skill_loader psql reads
    for key, value in changes.items():
        result = await db.execute(select(AppSettings).where(AppSettings.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = str(value)
        else:
            db.add(AppSettings(key=key, value=str(value)))
    await db.commit()
    return {"ok": True}


@router.get("/settings/{key}")
async def get_setting(
    key: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    return {"key": key, "value": row.value if row else None}


@router.put("/settings/{key}")
async def put_setting(
    key: str,
    req: UpdateSettingsRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    value = req.settings.get(key, req.settings.get("value", ""))
    result = await db.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=key, value=value))
    await db.commit()
    return {"ok": True}


class AssetLifecycleRequest(BaseModel):
    is_active: Optional[bool] = None
    expires_at: Optional[str] = None


@router.patch("/assets/{asset_id}/lifecycle")
async def update_asset_lifecycle(
    asset_id: str,
    req: AssetLifecycleRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if req.is_active is not None:
        asset.is_active = req.is_active
    if req.expires_at is not None:
        asset.expires_at = datetime.fromisoformat(req.expires_at)

    await db.commit()
    return {
        "ok": True,
        "is_active": asset.is_active,
        "expires_at": asset.expires_at.isoformat() if asset.expires_at else None,
    }


@router.post("/assets/{asset_id}/refresh")
async def trigger_asset_refresh(
    asset_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.status != "approved":
        raise HTTPException(status_code=400, detail="Only approved assets can be refreshed")

    ok = await _refresh_asset(db, asset)
    if not ok:
        raise HTTPException(status_code=500, detail="Refresh failed")

    return {
        "ok": True,
        "expires_at": asset.expires_at.isoformat() if asset.expires_at else None,
    }


@router.post("/assets/refresh-expired")
async def trigger_refresh_expired(
    user: User = Depends(require_admin),
):
    result = await refresh_expired_assets()
    return result


@router.patch("/topics/{topic_id}/leading-asset")
async def set_leading_asset(
    topic_id: str,
    asset_id: str = Query(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Topic).where(Topic.id == topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if asset_id:
        asset_result = await db.execute(select(Asset).where(Asset.id == asset_id))
        if not asset_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Asset not found")

    topic.leading_asset_id = asset_id or None
    await db.commit()
    return {"ok": True, "leading_asset_id": topic.leading_asset_id}


class CreateUserRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None
    role: str = "user"


@router.post("/users")
async def create_user(
    req: CreateUserRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if req.role not in ("user", "reviewer", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already exists")

    new_user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        display_name=req.display_name or req.email.split("@")[0],
        role=req.role,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return {
        "id": new_user.id,
        "email": new_user.email,
        "display_name": new_user.display_name,
        "role": new_user.role,
    }


# --- System Prompt & Skills Management ---

@router.get("/system-prompt")
async def get_system_prompt(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AppSettings).where(AppSettings.key == "system_prefix"))
    row = result.scalar_one_or_none()
    return {"system_prefix": row.value if row else settings.system_prefix}


class UpdateSystemPromptRequest(BaseModel):
    system_prefix: str


@router.put("/system-prompt")
async def update_system_prompt(
    req: UpdateSystemPromptRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AppSettings).where(AppSettings.key == "system_prefix"))
    existing = result.scalar_one_or_none()
    if existing:
        existing.value = req.system_prefix
    else:
        db.add(AppSettings(key="system_prefix", value=req.system_prefix))
    await db.commit()

    # Invalidate cached skill content so next request picks up new prefix
    from ..services.skill_loader import skill_loader
    skill_loader._skill_content = None

    return {"ok": True}


@router.post("/skills/refresh")
async def refresh_skills_endpoint(
    user: User = Depends(require_admin),
):
    """Re-scan companion skills directory and clear all caches.
    Use after uploading/removing skill files at runtime."""
    from ..services.skill_loader import refresh_skills
    refresh_skills()
    from ..services.skill_loader import AVAILABLE_SKILLS
    return {"ok": True, "skills_found": len(AVAILABLE_SKILLS), "skills": sorted(AVAILABLE_SKILLS)}


@router.get("/zettel/status")
async def zettel_status(user: User = Depends(require_admin)):
    """Get zettelkasten plugin status and global stats."""
    from ..services.memory_plugin import get_memory_plugin, ASSETS_NAMESPACE
    plugin = get_memory_plugin()
    active = plugin.name != "none"
    status = {
        "active": active,
        "plugin_name": plugin.name,
    }
    if active:
        try:
            # Discover projects from persist dir (each .json file = a project namespace)
            persist_dir = getattr(plugin, "_persist_dir", None)
            projects = []
            total_entries = 0
            if persist_dir and persist_dir.exists():
                for f in persist_dir.glob("*.json"):
                    ns = f.stem
                    projects.append(ns)
                    try:
                        s = plugin.stats(ns)
                        total_entries += s.get("total_zettels", 0)
                    except Exception:
                        pass
            status["total_entries"] = total_entries
            status["projects"] = [p for p in projects if p != ASSETS_NAMESPACE]
            status["project_count"] = len(status["projects"])
            # Asset index stats separately
            try:
                asset_stats = plugin.stats(ASSETS_NAMESPACE)
                status["assets_indexed"] = asset_stats.get("total_zettels", 0)
            except Exception:
                status["assets_indexed"] = 0
        except Exception:
            status["total_entries"] = 0
            status["projects"] = []
            status["project_count"] = 0
            status["assets_indexed"] = 0
    else:
        status["total_entries"] = 0
        status["projects"] = []
        status["project_count"] = 0
        status["assets_indexed"] = 0
    return status


# --- Agent Tools Management ---

@router.get("/tools")
async def list_agent_tools(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all available agent tools and their enabled/disabled status."""
    from ..services.llm.cortex import CortexAgentClient, get_disabled_tools
    available = CortexAgentClient.AVAILABLE_TOOLS
    disabled = get_disabled_tools()
    tools = [{"name": t, "enabled": t not in disabled} for t in available]
    return {"tools": tools}


@router.put("/tools/{tool_name}")
async def toggle_agent_tool(
    tool_name: str,
    body: dict,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable an agent tool."""
    from ..services.llm.cortex import CortexAgentClient, get_disabled_tools, set_disabled_tools
    if tool_name not in CortexAgentClient.AVAILABLE_TOOLS:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

    enabled = body.get("enabled", True)
    disabled = set(get_disabled_tools())
    if enabled:
        disabled.discard(tool_name)
    else:
        disabled.add(tool_name)
    set_disabled_tools(disabled)

    # Persist to DB
    disabled_str = ",".join(sorted(disabled)) if disabled else ""
    existing = await db.execute(select(AppSettings).where(AppSettings.key == "disabled_tools"))
    row = existing.scalar_one_or_none()
    if row:
        row.value = disabled_str
    else:
        db.add(AppSettings(key="disabled_tools", value=disabled_str))
    await db.commit()

    return {"ok": True, "tool": tool_name, "enabled": enabled}


# --- Skill Knowledge Graph Admin Endpoints ---

@router.post("/skills/{skill_name}/index")
async def index_skill_knowledge(
    skill_name: str,
    user: User = Depends(require_admin),
):
    """Index a skill's content into the zettelkasten knowledge graph."""
    from ..services.skill_indexer import index_skill_to_zettel
    result = index_skill_to_zettel(skill_name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True, **result}


@router.post("/knowledge/reindex-all")
async def reindex_all_skills(user: User = Depends(require_admin)):
    """Re-index content from all skill files and knowledge files into the knowledge graph."""
    from ..services.skill_indexer import index_skill_to_zettel, KNOWLEDGE_DIR
    from ..services.skill_loader import SKILLS_DIR

    # Collect all skill names from both skills/ and knowledge/ directories
    skill_names = set()
    if SKILLS_DIR.is_dir():
        for skill_file in SKILLS_DIR.glob("*.md"):
            skill_names.add(skill_file.stem)
    if KNOWLEDGE_DIR.is_dir():
        for knowledge_dir in KNOWLEDGE_DIR.iterdir():
            if knowledge_dir.is_dir():
                skill_names.add(knowledge_dir.name)

    results = []
    for skill_name in sorted(skill_names):
        r = index_skill_to_zettel(skill_name)
        if "error" not in r:
            results.append(r)

    total_indexed = sum(r.get("entries_indexed", 0) for r in results)
    total_knowledge = sum(r.get("knowledge_entries", 0) for r in results)
    return {
        "ok": True,
        "skills_indexed": len(results),
        "total_entries": total_indexed,
        "knowledge_entries": total_knowledge,
        "details": results,
    }


@router.get("/knowledge/stats")
async def get_knowledge_stats_endpoint(user: User = Depends(require_admin)):
    """Get statistics about the skill knowledge graph."""
    from ..services.skill_indexer import get_knowledge_stats
    return get_knowledge_stats()


@router.get("/knowledge/graph")
async def get_knowledge_graph_data(user: User = Depends(require_admin)):
    """Get graph data (nodes + edges) for visualization."""
    from ..services.skill_indexer import get_knowledge_graph
    return get_knowledge_graph()


@router.get("/knowledge/entries")
async def list_knowledge_entries_endpoint(
    domain: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    user: User = Depends(require_admin),
):
    """List indexed knowledge entries."""
    from ..services.skill_indexer import list_knowledge_entries
    entries = list_knowledge_entries(domain=domain, limit=limit)
    return {"entries": entries, "count": len(entries)}


@router.post("/knowledge/search")
async def search_knowledge(
    body: dict,
    user: User = Depends(require_admin),
):
    """Test search against the skill knowledge graph."""
    from ..services.skill_indexer import search_skill_knowledge

    query = body.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    domain = body.get("domain") or None
    limit = min(int(body.get("limit", 10)), 50)
    min_score = float(body.get("min_score", 0.1))

    results = search_skill_knowledge(query, domain=domain, limit=limit, min_score=min_score)
    return {"results": results, "count": len(results), "query": query, "domain": domain}


@router.delete("/knowledge/clear")
async def clear_all_knowledge_endpoint(user: User = Depends(require_admin)):
    """Clear all entries from the skill knowledge graph."""
    from ..services.skill_indexer import clear_all_knowledge
    clear_all_knowledge()
    return {"ok": True, "message": "All skill knowledge entries cleared"}


@router.delete("/knowledge/clear/{skill_name}")
async def clear_skill_knowledge(
    skill_name: str,
    user: User = Depends(require_admin),
):
    """Clear knowledge entries for a specific skill."""
    from ..services.skill_indexer import _remove_skill_entries
    removed = _remove_skill_entries(skill_name)
    return {"ok": True, "removed": removed, "skill": skill_name}


@router.get("/knowledge/config")
async def get_knowledge_config(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get skill knowledge retrieval configuration."""
    result = await db.execute(
        select(AppSettings).where(AppSettings.key.in_([
            "skill_knowledge_enabled",
            "skill_knowledge_limit",
            "skill_knowledge_min_score",
            "skill_knowledge_max_content_len",
        ]))
    )
    rows = {r.key: r.value for r in result.scalars()}
    return {
        "enabled": rows.get("skill_knowledge_enabled", "true") == "true",
        "limit": int(rows.get("skill_knowledge_limit", "5")),
        "min_score": float(rows.get("skill_knowledge_min_score", "0.25")),
        "max_content_len": int(rows.get("skill_knowledge_max_content_len", "800")),
    }


@router.put("/knowledge/config")
async def update_knowledge_config(
    body: dict,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update skill knowledge retrieval configuration."""
    config_map = {
        "enabled": ("skill_knowledge_enabled", lambda v: "true" if v else "false"),
        "limit": ("skill_knowledge_limit", str),
        "min_score": ("skill_knowledge_min_score", str),
        "max_content_len": ("skill_knowledge_max_content_len", str),
    }

    for field, (key, converter) in config_map.items():
        if field in body:
            value = converter(body[field])
            existing = await db.execute(select(AppSettings).where(AppSettings.key == key))
            row = existing.scalar_one_or_none()
            if row:
                row.value = value
            else:
                db.add(AppSettings(key=key, value=value))

    await db.commit()
    return {"ok": True}


@router.get("/skills")
async def list_skills(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ..services.skill_loader import AVAILABLE_SKILLS, SKILL_KEYWORDS, COMPANIONS_DIR, refresh_skills

    # Always re-scan disk so new/removed files are picked up
    refresh_skills()
    from ..services.skill_loader import AVAILABLE_SKILLS as REFRESHED_SKILLS

    # Load disabled skills from DB
    result = await db.execute(select(AppSettings).where(AppSettings.key == "disabled_skills"))
    row = result.scalar_one_or_none()
    disabled = set(row.value.split(",")) if row and row.value else set()

    # Load custom keywords from DB
    kw_result = await db.execute(select(AppSettings).where(AppSettings.key == "skill_keywords"))
    kw_row = kw_result.scalar_one_or_none()
    custom_keywords = {}
    if kw_row and kw_row.value:
        import json
        try:
            custom_keywords = json.loads(kw_row.value)
        except:
            pass

    # Load mandatory skills from DB
    mand_result = await db.execute(select(AppSettings).where(AppSettings.key == "mandatory_skills"))
    mand_row = mand_result.scalar_one_or_none()
    mandatory = set(mand_row.value.split(",")) if mand_row and mand_row.value else set()
    mandatory.discard("")

    # Load skip-reflect skills from DB
    sr_result = await db.execute(select(AppSettings).where(AppSettings.key == "skip_reflect_skills"))
    sr_row = sr_result.scalar_one_or_none()
    skip_reflect = set(sr_row.value.split(",")) if sr_row and sr_row.value else set()
    skip_reflect.discard("")

    # Load display names from DB
    dn_result = await db.execute(select(AppSettings).where(AppSettings.key == "skill_display_names"))
    dn_row = dn_result.scalar_one_or_none()
    display_names = {}
    if dn_row and dn_row.value:
        import json as _json
        try:
            display_names = _json.loads(dn_row.value)
        except:
            pass

    skills = []

    # All skills from companions directory
    for name in sorted(REFRESHED_SKILLS):
        # Resolve entry point: prefer name.md, fall back to name/SKILL.md
        filepath = COMPANIONS_DIR / f"{name}.md"
        if not filepath.exists():
            filepath = COMPANIONS_DIR / name / "SKILL.md"
        size = filepath.stat().st_size if filepath.exists() else 0
        keywords = custom_keywords.get(name, SKILL_KEYWORDS.get(name, []))

        # Discover sub-skills (directories with SKILL.md inside)
        sub_skills = []
        skill_dir = COMPANIONS_DIR / name
        if skill_dir.is_dir():
            for item in sorted(skill_dir.iterdir()):
                if item.is_dir() and (item / "SKILL.md").exists():
                    sub_path = f"{name}/{item.name}"
                    sub_skills.append({
                        "name": sub_path,
                        "short_name": item.name,
                        "skip_reflect": sub_path in skip_reflect,
                    })

        skill_entry = {
            "name": name,
            "filename": filepath.name,
            "path": str(filepath),
            "display_name": display_names.get(name, ""),
            "enabled": name not in disabled,
            "mandatory": name in mandatory,
            "skip_reflect": name in skip_reflect,
            "keywords": keywords,
            "size": size,
        }
        if sub_skills:
            skill_entry["sub_skills"] = sub_skills
        skills.append(skill_entry)

    return {"skills": skills}


class UpdateSkillConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    keywords: Optional[list[str]] = None
    mandatory: Optional[bool] = None
    display_name: Optional[str] = None
    skip_reflect: Optional[bool] = None


@router.put("/skills/{skill_name}")
async def update_skill_config(
    skill_name: str,
    req: UpdateSkillConfigRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ..services.skill_loader import AVAILABLE_SKILLS, skill_loader, refresh_skills, COMPANIONS_DIR
    # Refresh first so newly uploaded skills are recognized
    refresh_skills()
    from ..services.skill_loader import AVAILABLE_SKILLS as CURRENT_SKILLS
    if skill_name not in CURRENT_SKILLS:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Handle enabled/disabled
    if req.enabled is not None:
        result = await db.execute(select(AppSettings).where(AppSettings.key == "disabled_skills"))
        row = result.scalar_one_or_none()
        disabled = set(row.value.split(",")) if row and row.value else set()
        disabled.discard("")

        if req.enabled:
            disabled.discard(skill_name)
        else:
            disabled.add(skill_name)

        new_val = ",".join(sorted(disabled))
        if row:
            row.value = new_val
        else:
            db.add(AppSettings(key="disabled_skills", value=new_val))

    # Handle mandatory toggle
    if req.mandatory is not None:
        mand_result = await db.execute(select(AppSettings).where(AppSettings.key == "mandatory_skills"))
        mand_row = mand_result.scalar_one_or_none()
        mandatory = set(mand_row.value.split(",")) if mand_row and mand_row.value else set()
        mandatory.discard("")

        if req.mandatory:
            mandatory.add(skill_name)
        else:
            mandatory.discard(skill_name)

        new_val = ",".join(sorted(mandatory))
        if mand_row:
            mand_row.value = new_val
        else:
            db.add(AppSettings(key="mandatory_skills", value=new_val))

        # Invalidate skill cache so changes take effect
        skill_loader._skill_cache.clear()

    # Handle keywords
    if req.keywords is not None:
        import json
        kw_result = await db.execute(select(AppSettings).where(AppSettings.key == "skill_keywords"))
        kw_row = kw_result.scalar_one_or_none()
        custom_keywords = {}
        if kw_row and kw_row.value:
            try:
                custom_keywords = json.loads(kw_row.value)
            except:
                pass

        custom_keywords[skill_name] = req.keywords
        new_val = json.dumps(custom_keywords)
        if kw_row:
            kw_row.value = new_val
        else:
            db.add(AppSettings(key="skill_keywords", value=new_val))

    # Handle display_name
    if req.display_name is not None:
        import json
        dn_result = await db.execute(select(AppSettings).where(AppSettings.key == "skill_display_names"))
        dn_row = dn_result.scalar_one_or_none()
        display_names = {}
        if dn_row and dn_row.value:
            try:
                display_names = json.loads(dn_row.value)
            except:
                pass
        if req.display_name.strip():
            display_names[skill_name] = req.display_name.strip()
        else:
            display_names.pop(skill_name, None)
        new_val = json.dumps(display_names)
        if dn_row:
            dn_row.value = new_val
        else:
            db.add(AppSettings(key="skill_display_names", value=new_val))

    # Handle skip_reflect toggle
    if req.skip_reflect is not None:
        sr_result = await db.execute(select(AppSettings).where(AppSettings.key == "skip_reflect_skills"))
        sr_row = sr_result.scalar_one_or_none()
        skip_reflect = set(sr_row.value.split(",")) if sr_row and sr_row.value else set()
        skip_reflect.discard("")

        if req.skip_reflect:
            skip_reflect.add(skill_name)
        else:
            skip_reflect.discard(skill_name)

        new_val = ",".join(sorted(skip_reflect))
        if sr_row:
            sr_row.value = new_val
        else:
            db.add(AppSettings(key="skip_reflect_skills", value=new_val))
        await db.commit()

    await db.commit()
    return {"ok": True}


@router.put("/skills/{skill_name}/{sub_skill}")
async def update_sub_skill_config(
    skill_name: str,
    sub_skill: str,
    req: UpdateSkillConfigRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle skip_reflect for a sub-skill."""
    from ..services.skill_loader import AVAILABLE_SKILLS, COMPANIONS_DIR, refresh_skills
    refresh_skills()
    from ..services.skill_loader import AVAILABLE_SKILLS as CURRENT_SKILLS

    if skill_name not in CURRENT_SKILLS:
        raise HTTPException(status_code=404, detail="Skill not found")
    sub_file = COMPANIONS_DIR / skill_name / sub_skill / "SKILL.md"
    if not sub_file.exists():
        raise HTTPException(status_code=404, detail="Sub-skill not found")

    full_path = f"{skill_name}/{sub_skill}"

    if req.skip_reflect is not None:
        sr_result = await db.execute(select(AppSettings).where(AppSettings.key == "skip_reflect_skills"))
        sr_row = sr_result.scalar_one_or_none()
        skip_reflect = set(sr_row.value.split(",")) if sr_row and sr_row.value else set()
        skip_reflect.discard("")

        if req.skip_reflect:
            skip_reflect.add(full_path)
        else:
            skip_reflect.discard(full_path)

        new_val = ",".join(sorted(skip_reflect))
        if sr_row:
            sr_row.value = new_val
        else:
            db.add(AppSettings(key="skip_reflect_skills", value=new_val))

    await db.commit()
    return {"ok": True}


@router.get("/skills/{skill_name}/content")
async def get_skill_content(
    skill_name: str,
    user: User = Depends(require_admin),
):
    from ..services.skill_loader import AVAILABLE_SKILLS, COMPANIONS_DIR

    if skill_name not in AVAILABLE_SKILLS:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Resolve: prefer name.md, fall back to name/SKILL.md
    filepath = COMPANIONS_DIR / f"{skill_name}.md"
    if not filepath.exists():
        filepath = COMPANIONS_DIR / skill_name / "SKILL.md"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Skill file not found")

    content = filepath.read_text(encoding="utf-8")
    return {"name": skill_name, "content": content, "size": len(content)}


class UpdateSkillContentRequest(BaseModel):
    content: str


@router.put("/skills/{skill_name}/content")
async def update_skill_content(
    skill_name: str,
    req: UpdateSkillContentRequest,
    user: User = Depends(require_admin),
):
    from ..services.skill_loader import AVAILABLE_SKILLS, COMPANIONS_DIR, skill_loader

    if skill_name not in AVAILABLE_SKILLS:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Resolve: prefer name.md, fall back to name/SKILL.md
    filepath = COMPANIONS_DIR / f"{skill_name}.md"
    if not filepath.exists():
        filepath = COMPANIONS_DIR / skill_name / "SKILL.md"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Skill file not found")

    filepath.write_text(req.content, encoding="utf-8")

    # Invalidate cache
    skill_loader._skill_cache.pop(skill_name, None)

    return {"ok": True, "size": len(req.content)}


@router.post("/skills/upload")
async def upload_skill_zip(
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
):
    """Upload a skill as a zip file. Supports two layouts:
    1. Flat: root-level .md files become skills directly in companions/.
    2. Directory-based: a folder containing SKILL.md becomes a skill (discovered
       automatically). Common for GitHub downloads like repo-main.zip where all
       files are nested under one directory.

    If all files in the zip share a single root directory AND that directory
    contains a SKILL.md, it's extracted as-is into companions/ and discovered
    as a directory-based skill.

    If the zip has a flat layout (files at root), .md files become skills and
    subfolders become sub-skill directories.
    """
    import zipfile
    import io
    from ..services.skill_loader import COMPANIONS_DIR, SKILLS_DIR, skill_loader, refresh_skills

    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50MB max
        raise HTTPException(status_code=400, detail="Zip file too large (max 50MB)")

    COMPANIONS_DIR.mkdir(parents=True, exist_ok=True)

    extracted_files = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            # Collect all valid file entries (skip dirs, macOS junk, hidden files)
            entries = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if '/__MACOSX/' in info.filename or info.filename.startswith('.') or '/.' in info.filename:
                    continue
                entries.append(info)

            if not entries:
                raise HTTPException(status_code=400, detail="Zip file contains no valid files")

            # Detect single-root-folder pattern (GitHub download style):
            # All files under one directory, e.g. "security-afe-main/SKILL.md"
            top_dirs = set()
            top_files = False
            for info in entries:
                parts = info.filename.split('/')
                if len(parts) == 1:
                    top_files = True
                else:
                    top_dirs.add(parts[0])

            # If single root folder: use the zip filename (minus .zip) as the
            # skill directory name instead of the internal folder name. This
            # normalizes "security-afe-main" from a GitHub download to match
            # whatever the user named their zip file.
            skill_dir_name = None
            if not top_files and len(top_dirs) == 1:
                internal_prefix = top_dirs.pop() + "/"
                # Derive skill name from zip filename: "security-afe-main.zip" -> "security-afe-main"
                skill_dir_name = file.filename.rsplit('.', 1)[0] if file.filename else None
                # If zip filename matches internal folder, just extract normally
                if skill_dir_name and skill_dir_name != internal_prefix.rstrip('/'):
                    # Rename: strip internal prefix, re-add with zip-derived name
                    rename_prefix = skill_dir_name + "/"
                else:
                    # Same name or can't determine — extract as-is
                    skill_dir_name = None

            for info in entries:
                filename = info.filename

                if skill_dir_name:
                    # Replace internal folder prefix with zip-derived name
                    if filename.startswith(internal_prefix):
                        filename = rename_prefix + filename[len(internal_prefix):]

                parts = filename.split('/')
                if len(parts) == 1:
                    # Root-level file -> place directly in companions dir
                    dest = COMPANIONS_DIR / filename
                else:
                    # Nested file -> place relative to companions dir
                    dest = COMPANIONS_DIR / filename
                    dest.parent.mkdir(parents=True, exist_ok=True)

                dest.write_bytes(zf.read(info.filename))
                extracted_files.append(str(dest.relative_to(SKILLS_DIR)))

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")

    # Invalidate all skill caches and re-discover
    skill_loader._skill_cache.clear()
    refresh_skills()

    return {"ok": True, "extracted": extracted_files, "count": len(extracted_files)}
