import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import async_session
from ..models.session import Asset, AssetVersion, Session
from .cortex_agent import CortexAgentClient
from .embeddings import EmbeddingService
from .skill_loader import skill_loader

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 3600


async def _refresh_asset(db: AsyncSession, asset: Asset) -> bool:
    session_result = await db.execute(
        select(Session).where(Session.id == asset.session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        logger.warning("Asset %s has no session, skipping refresh", asset.id)
        return False

    question = None
    for h in (session.history or []):
        if h.get("role") == "user":
            texts = [c.get("text", "") for c in h.get("content", []) if c.get("type") == "text"]
            if texts:
                question = " ".join(texts)
                break

    if not question:
        logger.warning("Asset %s: no question found in session history", asset.id)
        return False

    try:
        system_prompt, _ = skill_loader.build_system_prompt(question=question)
        agent = CortexAgentClient()
        if not agent.session_token:
            logger.error("No Snowflake PAT configured, cannot refresh assets")
            return False

        full_text = ""
        async for ev in agent.stream(question, system_prompt=system_prompt):
            if ev.event_type == "text":
                full_text += ev.data.get("text", "")

        if not full_text or len(full_text) < 50:
            logger.warning("Asset %s: refresh produced insufficient content (%d chars)", asset.id, len(full_text))
            return False

        max_ver = await db.execute(
            select(AssetVersion.version)
            .where(AssetVersion.asset_id == asset.id)
            .order_by(AssetVersion.version.desc())
            .limit(1)
        )
        current_max = max_ver.scalar_one_or_none() or 0

        new_version = AssetVersion(
            id=str(uuid.uuid4()),
            asset_id=asset.id,
            version=current_max + 1,
            content=full_text,
            edited_by=None,
            comment="Auto-refresh: content regenerated after TTL expiry",
        )
        db.add(new_version)

        asset.content = full_text
        asset.expires_at = datetime.now(timezone.utc) + timedelta(days=settings.asset_ttl_days)
        asset.updated_at = datetime.now(timezone.utc)

        try:
            embedding_svc = EmbeddingService(session_token=agent.session_token)
            embedding = await embedding_svc.generate(full_text[:8000])
            if embedding and isinstance(embedding[0], list):
                embedding = embedding[0]
            asset.embedding = embedding
        except Exception as e:
            logger.warning("Asset %s: embedding regeneration failed: %s", asset.id, e)

        await db.commit()
        logger.info("Asset %s refreshed: v%d, new expiry %s", asset.id, current_max + 1, asset.expires_at)
        return True

    except Exception as e:
        logger.error("Asset %s refresh failed: %s", asset.id, e)
        await db.rollback()
        return False


async def refresh_expired_assets() -> dict:
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        result = await db.execute(
            select(Asset).where(
                Asset.status == "approved",
                Asset.is_active == True,
                Asset.expires_at != None,
                Asset.expires_at <= now,
            ).limit(10)
        )
        expired = result.scalars().all()

        if not expired:
            return {"checked": 0, "refreshed": 0}

        logger.info("Found %d expired assets to refresh", len(expired))
        refreshed = 0
        for asset in expired:
            ok = await _refresh_asset(db, asset)
            if ok:
                refreshed += 1
            await asyncio.sleep(2)

        return {"checked": len(expired), "refreshed": refreshed}


async def refresh_worker_loop():
    logger.info("Asset refresh worker started (interval: %ds)", REFRESH_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
            result = await refresh_expired_assets()
            if result["checked"] > 0:
                logger.info("Asset refresh cycle: %s", result)
        except asyncio.CancelledError:
            logger.info("Asset refresh worker cancelled")
            break
        except Exception as e:
            logger.error("Asset refresh worker error: %s", e)
            await asyncio.sleep(60)
