from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.auth import get_current_user
from ..models.user import User
from ..models.session import McpServer

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class AddMcpRequest(BaseModel):
    name: str
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list] = None
    auth_type: str = "none"
    oauth_provider: Optional[str] = None


@router.get("")
async def list_mcp_servers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(McpServer).order_by(McpServer.name))
    servers = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "url": s.url,
            "command": s.command,
            "args": s.args or [],
            "auth_type": s.auth_type,
            "oauth_provider": s.oauth_provider,
            "enabled": s.enabled,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in servers
    ]


@router.post("")
async def add_mcp_server(
    req: AddMcpRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")

    existing = await db.execute(
        select(McpServer).where(McpServer.name == req.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"MCP server '{req.name}' already exists")

    server = McpServer(
        name=req.name,
        url=req.url,
        command=req.command,
        args=req.args or [],
        auth_type=req.auth_type,
        oauth_provider=req.oauth_provider,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return {
        "id": server.id,
        "name": server.name,
        "url": server.url,
        "command": server.command,
        "args": server.args or [],
        "auth_type": server.auth_type,
        "oauth_provider": server.oauth_provider,
        "enabled": server.enabled,
    }


@router.delete("/{name}")
async def remove_mcp_server(
    name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")

    result = await db.execute(
        select(McpServer).where(McpServer.name == name)
    )
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(404, f"MCP server '{name}' not found")

    await db.delete(server)
    await db.commit()
    return {"ok": True, "name": name}


@router.patch("/{name}/toggle")
async def toggle_mcp_server(
    name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")

    result = await db.execute(
        select(McpServer).where(McpServer.name == name)
    )
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(404, f"MCP server '{name}' not found")

    server.enabled = not server.enabled
    await db.commit()
    return {"name": name, "enabled": server.enabled}
