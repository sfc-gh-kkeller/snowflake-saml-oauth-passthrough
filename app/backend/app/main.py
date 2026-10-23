from contextlib import asynccontextmanager
import asyncio
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .core.config import settings
from .core.database import engine, async_session, Base, _sync_engine
from .models.user import User
from .models.session import Session, Project, Asset, AssetVersion, Question, Feedback, SearchCache, Topic, ReviewFlag, UserFile, UserOAuthToken, OAuthState, OAuthClient, McpServer, MagicLink, WebAuthnCredential, MfaChallenge, AppSettings
from .api.auth import router as auth_router
from .api.auth_passkey import router as passkey_router
from .api.sessions import router as sessions_router
from .api.assets import router as assets_router
from .api.admin import router as admin_router
from .api.review import router as review_router
from .api.files import router as files_router
from .api.projects import router as projects_router
from .api.oauth import router as oauth_router
from .api.mcp import router as mcp_router
from .api.auth_saml import router as saml_router
from .api.role_test import router as role_test_router
from .services.memory_plugin import init_memory_plugin, get_memory_plugin
from .services.asset_refresh import refresh_worker_loop

SEED_TOPICS = [
    ("auto", "Liability, collision, comprehensive, uninsured-motorist, deductibles, premiums"),
    ("home", "Dwelling, personal-property, liability, water-damage, flood, earthquake"),
    ("life", "Term, whole, universal, beneficiaries, riders, cash-value"),
    ("health", "HMO, PPO, deductible, copay, coinsurance, out-of-pocket-max"),
    ("claims", "FNOL, adjuster, estimate, subrogation, settlement"),
    ("underwriting", "Risk-assessment, actuarial, loss-history, credit-score"),
    ("billing", "Premium-payment, grace-period, lapse, reinstatement"),
    ("policy", "Declarations, endorsements, exclusions, limits, coverage"),
    ("commercial", "General-liability, workers-comp, BOP, property, cyber"),
    ("regulatory", "State-DOI, compliance, NAIC, market-conduct"),
]


def parse_seed_topics(raw: str) -> list[tuple[str, str]]:
    """Parse seed_topics from 'name:desc;name:desc' format."""
    topics = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            name, desc = entry.split(":", 1)
            topics.append((name.strip(), desc.strip()))
        else:
            topics.append((entry, ""))
    return topics


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_backend == "postgres":
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
            # Add columns that create_all won't add to existing tables
            await conn.execute(text("""
                ALTER TABLE sessions ADD COLUMN IF NOT EXISTS pending_response JSONB
            """))
            await conn.execute(text("""
                ALTER TABLE sessions ADD COLUMN IF NOT EXISTS internal_dialogue JSONB
            """))
            await conn.execute(text("""
                ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE
            """))
    else:
        # Snowflake: create tables via sync engine
        await asyncio.to_thread(Base.metadata.create_all, _sync_engine)

    async with async_session() as db:
        from sqlalchemy import select, update
        # Reset any sessions stuck in 'running' from a previous server crash/restart
        await db.execute(
            update(Session).where(Session.status == "running").values(status="active")
        )
        await db.commit()

        # Load disabled tools from DB
        dt_result = await db.execute(select(AppSettings).where(AppSettings.key == "disabled_tools"))
        dt_row = dt_result.scalar_one_or_none()
        if dt_row and dt_row.value:
            from .services.llm.cortex import set_disabled_tools
            set_disabled_tools({t.strip() for t in dt_row.value.split(",") if t.strip()})

        existing_topics = await db.execute(select(Topic))
        if not existing_topics.scalars().first():
            topics = parse_seed_topics(settings.seed_topics) if settings.seed_topics else SEED_TOPICS
            for name, desc in topics:
                db.add(Topic(name=name, description=desc))
            await db.commit()

        # Seed default admin user in dev mode
        if settings.dev_mode:
            from .core.auth import hash_password
            existing_admin = await db.execute(select(User).where(User.role == "admin"))
            if not existing_admin.scalars().first():
                admin_user = User(
                    email="admin@acme-insurance.demo",
                    display_name="Admin",
                    password_hash=hash_password("admin123"),
                    role="admin",
                )
                db.add(admin_user)
                await db.commit()
                import logging
                logging.getLogger(__name__).info("Seeded dev admin user: admin@acme-insurance.demo / admin123")

        # Seed default app_settings for a working out-of-the-box experience
        existing_settings = await db.execute(select(AppSettings))
        if not existing_settings.scalars().first():
            import json as _json
            default_settings = {
                "mandatory_skills": "knowledge-agent",
                "skill_knowledge_enabled": "true",
                "skill_knowledge_limit": "5",
                "skill_knowledge_min_score": "0.25",
                "skill_knowledge_max_content_len": "800",
                "reflect_prompts": _json.dumps([
                    "Review the response for accuracy, completeness, and tone. "
                    "Check that all claims are factually correct and policy references are accurate. "
                    "If everything looks correct and complete, respond with just: LGTM\n"
                    "If there are issues to fix, produce the COMPLETE corrected response."
                ]),
                "system_prefix": (
                    "## Clarification Wizard\n\n"
                    "When you need to ask the user clarifying questions before you can proceed, "
                    "embed a wizard block in your response using this exact format:\n\n"
                    "```\n"
                    "<!-- WIZARD\n"
                    '{"questions": [\n'
                    '  {"id": "q1", "question": "Your question here?", "options": ["Option A", "Option B", "Option C"]},\n'
                    '  {"id": "q2", "question": "Another question?", "options": ["Yes", "No"]}\n'
                    "]}\n"
                    "-->\n"
                    "```\n\n"
                    "Rules:\n"
                    "- Use 1-4 questions max per wizard block\n"
                    "- Provide 2-5 concrete options per question\n"
                    "- Put the wizard block at the END of your message (after any explanatory text)\n"
                    "- The user will see clickable buttons for each option and can also type a custom answer\n"
                    "- Only use a wizard when you genuinely need clarification to proceed\n\n"
                    "## Workspace Document\n\n"
                    "Every conversation automatically creates a workspace document (markdown asset) "
                    "from your first response. This document is the deliverable that the user will "
                    "review, iterate on, and eventually approve.\n\n"
                    "When the user asks you to update, edit, revise, add to, or improve the document "
                    "(or any section of it), output the COMPLETE updated document wrapped in:\n\n"
                    "```\n"
                    "<!-- WORKSPACE_UPDATE -->\n"
                    "(full updated markdown content here)\n"
                    "<!-- /WORKSPACE_UPDATE -->\n"
                    "```\n\n"
                    "Rules:\n"
                    "- Always output the FULL document, not just the changed section\n"
                    "- You may include explanatory text before or after the WORKSPACE_UPDATE block\n"
                    "- The document in the workspace is the canonical version — always base edits on it\n"
                    "- When the workspace document is shown in `<workspace_content>` tags in your context, "
                    "that is the current version to work from\n"
                    "- If the user gives instructions about content changes without explicitly saying "
                    "'update the document', still apply the changes via WORKSPACE_UPDATE if the intent "
                    "is clearly to modify the deliverable\n\n"
                    "## Dynamic Skill Loading\n\n"
                    "You have access to companion skills that provide domain-specific knowledge. "
                    "To load a skill, include this marker in your response:\n\n"
                    "```\n"
                    "<!-- LOAD_SKILL: skill-name -->\n"
                    "```\n\n"
                    "The skill content will be available in your next response. Use this when:\n"
                    "- The user's question requires specialized knowledge you don't have in context\n"
                    "- The conversation pivots to a topic covered by a companion skill\n"
                    "- You can load multiple skills by including multiple LOAD_SKILL markers\n\n"
                    "Sub-skills can be loaded with a path: `<!-- LOAD_SKILL: skill-name/sub-skill-name -->`\n\n"
                    "If a skill instructs you to ask clarifying questions, use the WIZARD block format.\n"
                ),
            }
            for key, value in default_settings.items():
                db.add(AppSettings(key=key, value=value))
            await db.commit()
            import logging
            logging.getLogger(__name__).info("Seeded default app_settings (system_prefix, reflect_prompts, mandatory_skills)")

    init_memory_plugin()

    plugin = get_memory_plugin()
    if plugin.name != "none":
        from .services.memory_plugin import ASSETS_NAMESPACE
        plugin.delete_all(ASSETS_NAMESPACE)
        async with async_session() as db:
            from sqlalchemy import select
            from datetime import datetime, timezone
            result = await db.execute(
                select(Asset).where(
                    Asset.status == "approved",
                    Asset.is_active == True,
                )
            )
            assets = result.scalars().all()
            indexed = 0
            for a in assets:
                if a.expires_at and a.expires_at < datetime.now(timezone.utc):
                    continue
                if not a.content:
                    continue
                try:
                    plugin.index_asset(a.id, a.content, filename=a.filename, topic=a.topic or "")
                    indexed += 1
                except Exception:
                    pass
            if indexed:
                import logging
                logging.getLogger(__name__).info("Synced %d approved assets into zettel", indexed)

        # Auto-index skill knowledge into the zettelkasten
        from .services.skill_indexer import index_skill_to_zettel, KNOWLEDGE_DIR
        from .services.skill_loader import SKILLS_DIR
        skill_names = set()
        if SKILLS_DIR.is_dir():
            for skill_file in SKILLS_DIR.glob("*.md"):
                skill_names.add(skill_file.stem)
        if KNOWLEDGE_DIR.is_dir():
            for kd in KNOWLEDGE_DIR.iterdir():
                if kd.is_dir():
                    skill_names.add(kd.name)
        sk_indexed = 0
        kg_indexed = 0
        for sn in sorted(skill_names):
            r = index_skill_to_zettel(sn)
            sk_indexed += r.get("entries_indexed", 0)
            kg_indexed += r.get("knowledge_entries", 0)
        if sk_indexed:
            import logging
            logging.getLogger(__name__).info(
                "Indexed %d knowledge entries into zettel (%d from knowledge files)", sk_indexed, kg_indexed
            )

    refresh_task = asyncio.create_task(refresh_worker_loop())

    yield

    refresh_task.cancel()
    try:
        await refresh_task
    except asyncio.CancelledError:
        pass

    if settings.database_backend == "postgres":
        await engine.dispose()
    else:
        await asyncio.to_thread(_sync_engine.dispose)


app = FastAPI(
    title="NanoCortex Web Agent",
    description="AI agent platform with knowledge management workflow",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://nanocortex.afe.digital", "http://localhost:9011", "http://localhost:9001", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(passkey_router)
app.include_router(sessions_router)
app.include_router(assets_router)
app.include_router(admin_router)
app.include_router(review_router)
app.include_router(files_router)
app.include_router(projects_router)
app.include_router(oauth_router)
app.include_router(mcp_router)
app.include_router(saml_router)
app.include_router(role_test_router)

upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), settings.upload_dir)
os.makedirs(upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/config")
async def get_config():
    # Normalize legacy mode values
    mode = settings.app_mode
    if mode == "se_internal":
        mode = "chat"
    elif mode == "customer_audit":
        mode = "tiled"

    # Parse quick_questions from comma-separated string
    quick_questions = []
    if settings.quick_questions:
        quick_questions = [q.strip() for q in settings.quick_questions.split(",") if q.strip()]

    return {
        "app_mode": mode,
        "auth_mode": settings.auth_mode,
        "saml_enabled": bool(settings.saml_enabled),
        "snowflake_oauth": bool(settings.sf_oauth_enabled),
        "branding": {
            "title": settings.app_title,
            "subtitle": settings.app_subtitle,
            "logo_icon": settings.app_logo_icon,
        },
        "features": {
            "tasks": mode == "tiled",
            "review": True,
            "qa": True,
            "thinking": settings.agent_provider == "cortex" or settings.agent_model.startswith("claude-"),
        },
        "agent_model": settings.agent_model,
        "quick_questions": quick_questions,
    }


static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        file_path = os.path.join(static_dir, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(static_dir, "index.html"))
