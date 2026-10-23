import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.auth import get_current_user
from ..models.user import User
from ..models.session import Project, Session
from ..services.memory_plugin import get_memory_plugin

router = APIRouter(prefix="/api/projects", tags=["projects"])
logger = logging.getLogger(__name__)


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class UpdateMemoryRequest(BaseModel):
    memory: str


class AddZettelRequest(BaseModel):
    content: str
    tags: Optional[list[str]] = None
    importance: float = 0.5


class MoveSessionRequest(BaseModel):
    project_id: Optional[str] = None


async def _verify_project(project_id: str, user: User, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@router.get("")
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.user_id == user.id).order_by(Project.updated_at.desc())
    )
    projects = result.scalars().all()

    project_ids = [p.id for p in projects]
    counts = {}
    if project_ids:
        count_result = await db.execute(
            select(Session.project_id, func.count())
            .where(Session.project_id.in_(project_ids))
            .group_by(Session.project_id)
        )
        counts = {r[0]: r[1] for r in count_result.fetchall()}

    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "has_memory": bool(p.memory),
            "is_system": p.is_system,
            "session_count": counts.get(p.id, 0),
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in projects
    ]


@router.post("")
async def create_project(
    req: CreateProjectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = Project(user_id=user.id, name=req.name, description=req.description)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "has_memory": False,
        "session_count": 0,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await _verify_project(project_id, user, db)
    session_count = await db.scalar(
        select(func.count()).select_from(Session).where(Session.project_id == project_id)
    )
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "memory": p.memory,
        "session_count": session_count or 0,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


@router.put("/{project_id}")
async def update_project(
    project_id: str,
    req: UpdateProjectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await _verify_project(project_id, user, db)
    if req.name is not None:
        p.name = req.name
    if req.description is not None:
        p.description = req.description
    await db.commit()
    return {"ok": True}


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _verify_project(project_id, user, db)
    if project.is_system:
        raise HTTPException(status_code=403, detail="Cannot delete system project")
    await db.execute(
        update(Session).where(Session.project_id == project_id).values(project_id=None)
    )
    await db.execute(
        delete(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    await db.commit()
    get_memory_plugin().delete_all(project_id)
    return {"ok": True}


@router.get("/{project_id}/memory")
async def get_project_memory(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await _verify_project(project_id, user, db)
    return {"memory": p.memory or ""}


@router.put("/{project_id}/memory")
async def update_project_memory(
    project_id: str,
    req: UpdateMemoryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await _verify_project(project_id, user, db)
    p.memory = req.memory
    await db.commit()
    return {"ok": True}


@router.get("/{project_id}/zettel")
async def list_zettel(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_project(project_id, user, db)
    return {
        "entries": get_memory_plugin().list_entries(project_id, limit=limit),
        "stats": get_memory_plugin().stats(project_id),
        "plugin": get_memory_plugin().name,
    }


@router.post("/{project_id}/zettel")
async def add_zettel(
    project_id: str,
    req: AddZettelRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_project(project_id, user, db)
    tags = set(req.tags) if req.tags else None
    entry = get_memory_plugin().add(project_id, req.content, tags=tags, importance=req.importance)
    return entry


@router.get("/{project_id}/zettel/search")
async def search_zettel(
    project_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_project(project_id, user, db)
    return {"results": get_memory_plugin().search(project_id, q, limit=limit)}


@router.get("/{project_id}/zettel/stats")
async def zettel_stats(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_project(project_id, user, db)
    return get_memory_plugin().stats(project_id)


@router.delete("/{project_id}/zettel/{zettel_id}")
async def delete_zettel_entry(
    project_id: str,
    zettel_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_project(project_id, user, db)
    ok = get_memory_plugin().delete_entry(project_id, zettel_id)
    if not ok:
        raise HTTPException(404, "Memory entry not found")
    return {"ok": True}


@router.get("/{project_id}/sessions")
async def list_project_sessions(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session)
        .where(Session.project_id == project_id, Session.user_id == user.id)
        .order_by(Session.updated_at.desc())
    )
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "title": s.title,
            "status": s.status,
            "project_id": s.project_id,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        }
        for s in sessions
    ]
