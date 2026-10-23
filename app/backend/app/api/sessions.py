import asyncio
import json
import logging
import os
import re
import time
import uuid
import copy
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, update, delete, text, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sse_starlette.sse import EventSourceResponse

from ..core.database import get_db, async_session as db_session_factory
from ..core.auth import get_current_user
from ..core.config import settings
from ..core.queries import similarity_search_sql, format_embedding_for_query, format_embedding_for_storage
from ..models.user import User
from ..models.session import Session, Question, Asset, AssetVersion, Project, UserFile, Feedback, Topic, AppSettings
from ..services.cortex_agent import CortexAgentClient, StreamEvent
from ..services.snowflake_oauth import user_cortex_client
from ..services.skill_loader import skill_loader
from ..services.embeddings import EmbeddingService
from ..services.file_extractor import FileExtractor
from ..services.memory_plugin import get_memory_plugin
from ..api.review import classify_topic

logger = logging.getLogger(__name__)

# --- Background task registry ---
_RUNNING_TASKS: dict[str, asyncio.Task] = {}  # session_id -> asyncio.Task


def _sanitize_response(text: str) -> str:
    """Strip internal artifacts from agent response before showing to user.

    Removes:
    - LOAD_SKILL markers
    - Reflection/review preambles that slipped through
    - LLM thinking-out-loud preambles and postambles
    - Redundant trailing source lists when Documentation References already present
    """
    # Remove LOAD_SKILL markers
    text = re.sub(r"<!--\s*LOAD_SKILL:\s*\S+\s*-->", "", text)

    # --- Leading meta-commentary ---
    # Remove lines at the start that are LLM "thinking out loud" before the actual response.
    leading_patterns = [
        # Reflection leak patterns
        r"^I've reviewed the response[^\n]*\n*",
        r"^I reviewed the response[^\n]*\n*",
        r"^Let me review the response[^\n]*\n*",
        r"^After reviewing[^\n]*\n*",
        r"^Upon review[^\n]*\n*",
        r"^I found (?:several |some )?(?:issues|errors|inaccuracies)[^\n]*\n*",
        r"^Based on my research[^\n]*\n*",
        # Thinking-out-loud preambles
        r"^Now I (?:have|need to|will|can|should)[^\n]*\n*",
        r"^Let me (?:compose|write|draft|put together|synthesize|create|build|compile|format|structure)[^\n]*\n*",
        r"^I(?:'ll| will) (?:now )?(?:compose|write|draft|put together|synthesize|create|build|compile|format|structure)[^\n]*\n*",
        r"^(?:I have |I've )?(?:comprehensive |enough |sufficient )?research[^\n]*(?:synthesize|compile|compose)[^\n]*\n*",
        # Tool availability disclaimers (web search down, etc.)
        r"^Web search (?:is |was )?(?:unavailable|not available|currently unavailable)[^\n]*(?:\n[^\n#]*)*?\n*(?=#|\Z)",
        r"^Output: Web search[^\n]*\n*",
    ]
    for pattern in leading_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # --- Trailing meta-commentary ---
    # Remove LLM sign-off / self-commentary after the actual content ends.
    trailing_patterns = [
        r"\n+The response is complete[^\n]*(?:\n.*)*$",
        r"\n+This response is complete[^\n]*(?:\n.*)*$",
        r"\n+Let me know if you(?:'d| would) like[^\n]*(?:\n.*)*$",
        r"\n+Feel free to (?:ask|let me know|reach out)[^\n]*(?:\n.*)*$",
        r"\n+I(?:'m| am) happy to (?:drill|dive|go|elaborate|expand|provide)[^\n]*(?:\n.*)*$",
        r"\n+(?:Shall|Should|Would you like me to|Do you want me to) [^\n]*$",
        # Tool availability disclaimers at the end
        r"\n+\*{0,2}Note:?\*{0,2}\s*Web search was (?:unavailable|not available)[^\n]*(?:\n.*)*$",
    ]
    for pattern in trailing_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # --- Redundant source sections ---
    # If the response already has a "Documentation References" section,
    # strip a trailing "Sources:" / "Sources" section that duplicates the same links.
    if re.search(r"^#+ *Documentation References", text, re.MULTILINE | re.IGNORECASE):
        text = re.sub(
            r"\n+(?:#+\s*)?Sources:?\s*\n(?:\s*[-*\d.].*\n?)+\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        )

    return text.strip()


def _maybe_wrap_wizard(text: str) -> str:
    """Detect clarification-style responses that lack WIZARD tags and wrap them.

    Skills may emit clarifying questions as plain text (numbered lists, bullet
    points ending in '?'). The frontend needs <!-- WIZARD --> blocks to render
    interactive pill buttons. This function detects such responses and wraps them.

    Heuristics — a response is treated as a clarification prompt when ALL of:
      1. No WIZARD block already present
      2. No WORKSPACE_UPDATE block present (it's a substantive answer)
      3. Contains 2+ lines ending with '?' (questions)
      4. Is relatively short (< 3000 chars — real answers are longer)
      5. Does NOT contain markdown headers ## or ### with substantive content
         after them (which indicates a formatted answer, not questions)
    """
    if "<!-- WIZARD" in text:
        return text  # already has wizard
    if "<!-- WORKSPACE_UPDATE" in text:
        return text  # substantive answer with workspace update

    # Quick length check — long responses are answers, not clarifications
    if len(text) > 3000:
        return text

    # Count lines ending with '?' (question marks)
    lines = text.strip().split("\n")
    question_lines = []
    for line in lines:
        stripped = line.strip().rstrip("*_`")  # strip trailing markdown formatting
        if len(stripped) < 8:
            continue
        if stripped.endswith("?"):
            question_lines.append(stripped)
        elif "?" in stripped and re.search(r"\?\s*\(", stripped):
            # Pattern: "Question? (Option A / Option B / ...)"
            question_lines.append(stripped)

    if len(question_lines) < 1:
        return text  # not enough questions to be a clarification prompt

    # Check it's not a substantive answer with incidental questions
    # (substantive answers have ## headers with paragraphs after them)
    substantive_headers = re.findall(r"^#{2,3}\s+\S", text, re.MULTILINE)
    if len(substantive_headers) >= 2:
        return text  # likely a formatted answer, not a clarification

    # Build WIZARD JSON from detected questions
    questions_json = []
    for i, q in enumerate(question_lines[:4], 1):  # max 4 questions
        # Strip leading bullet/number markers
        q_clean = re.sub(r"^[\s\-\*\d\.\)]+", "", q).strip()
        if not q_clean:
            continue
        # Extract options from parenthetical pattern: "Question? (A / B / C)"
        options = []
        paren_match = re.search(r"\?\s*\(([^)]+)\)", q_clean)
        if paren_match:
            # Split options by " / " or " | " or ", "
            opts_str = paren_match.group(1)
            options = [o.strip() for o in re.split(r"\s*/\s*|\s*\|\s*|\s*,\s*", opts_str) if o.strip()]
            # Clean question: just the part before the parenthetical
            q_clean = q_clean[:paren_match.start()].rstrip() + "?"
        questions_json.append({
            "id": f"q{i}",
            "question": q_clean,
            "options": options
        })

    if not questions_json:
        return text

    # Build the wizard block — append it to the existing text
    import json as _json
    wizard_json = _json.dumps({"questions": questions_json}, indent=2)
    wizard_block = f"\n\n<!-- WIZARD\n{wizard_json}\n-->"

    return text + wizard_block


router = APIRouter(prefix="/api/sessions", tags=["sessions"])

REFLECT_PROMPT = (
    "Review your previous response. Did you fully complete the user's request? Check for:\n"
    "- Errors in tool outputs (SQL errors, failed queries, permission issues)\n"
    "- Incomplete results or missing information the user asked for\n"
    "- Incorrect assumptions about the data, schema, or context\n"
    "- Prohibited language or tone issues (if a security Q&A response)\n"
    "- WORKSPACE_UPDATE block correctness (if you produced one)\n\n"
    "If everything looks correct and complete, respond with just: LGTM\n"
    "If there are issues to fix, produce the COMPLETE corrected response "
    "(not just the fix — the entire response as it should be, including any "
    "WORKSPACE_UPDATE block). Replace the full response."
)


def _get_reflect_prompts() -> list[str]:
    """Load reflection pass prompts. Supports multiple passes (L1, L2, etc.)
    configured via app_settings 'reflect_prompts' (JSON array) or falls back to default."""
    import subprocess
    try:
        psql = settings.get_psql_path()
    except FileNotFoundError:
        return []
    try:
        result = subprocess.run(
            [psql, "-h", "/tmp", "-p", "5433", "-d", "nanocortex",
             "-t", "-A", "-c", "SELECT value FROM app_settings WHERE key = 'reflect_prompts'"],
            capture_output=True, text=True, timeout=3
        )
        val = result.stdout.strip()
        if val:
            import json as _json
            prompts = _json.loads(val)
            if isinstance(prompts, list) and prompts:
                return prompts
    except Exception:
        pass
    # Fallback: use default prompt repeated for max_reflect iterations
    # If max_reflect is 0, no reflection runs
    if settings.agent_max_reflect <= 0:
        return []
    return [REFLECT_PROMPT] * settings.agent_max_reflect


def _get_skip_reflect_skills() -> set:
    """Load the set of skill names that should skip reflection verification."""
    import subprocess
    try:
        psql = settings.get_psql_path()
    except FileNotFoundError:
        return set()
    try:
        result = subprocess.run(
            [psql, "-h", "/tmp", "-p", "5433", "-d", "nanocortex",
             "-t", "-A", "-c", "SELECT value FROM app_settings WHERE key = 'skip_reflect_skills'"],
            capture_output=True, text=True, timeout=3
        )
        val = result.stdout.strip()
        if val:
            return set(v.strip() for v in val.split(",") if v.strip())
    except Exception:
        pass
    return set()


class CreateSessionRequest(BaseModel):
    message: str
    title: Optional[str] = None
    project_id: Optional[str] = None
    model: Optional[str] = None
    skip_suggestion: bool = False
    question_id: Optional[str] = None
    file_ids: Optional[list[str]] = None


class SendMessageRequest(BaseModel):
    message: str
    model: Optional[str] = None
    file_ids: Optional[list[str]] = None


class RenameRequest(BaseModel):
    title: str


class UseAssetRequest(BaseModel):
    question_id: str
    asset_id: str


class RegisterAssetFromSessionRequest(BaseModel):
    filename: Optional[str] = None
    topic: Optional[str] = None
    visibility: Optional[str] = None


class MoveSessionRequest(BaseModel):
    project_id: Optional[str] = None


class CopySessionRequest(BaseModel):
    project_id: Optional[str] = None


@router.get("")
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    include_archived: bool = False,
):
    query = select(Session).where(Session.user_id == user.id, Session.deleted_at == None)
    if not include_archived:
        query = query.where(Session.status != "archived")
    result = await db.execute(query.order_by(Session.updated_at.desc()))
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "title": s.title,
            "status": s.status,
            "project_id": s.project_id,
            "total_time_ms": s.total_time_ms,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        }
        for s in sessions
    ]


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Admins can view any session; regular users only their own
    if user.role == "admin":
        result = await db.execute(select(Session).where(Session.id == session_id))
    else:
        result = await db.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user.id)
        )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # Check if user already gave feedback
    fb_result = await db.execute(
        select(Feedback).where(Feedback.session_id == session_id, Feedback.user_id == user.id)
    )
    existing_fb = fb_result.scalar_one_or_none()

    return {
        "id": session.id,
        "title": session.title,
        "history": session.history,
        "status": session.status,
        "project_id": session.project_id,
        "total_time_ms": session.total_time_ms,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "is_running": session.status == "running" or session.id in _RUNNING_TASKS,
        "feedback": {"rating": existing_fb.rating, "comment": existing_fb.comment} if existing_fb else None,
    }


async def _check_similar_assets(question_text: str, db: AsyncSession):
    # Asset similarity uses the shared service identity (PAT); in passthrough-only setups there is none.
    if settings.sf_oauth_enabled and not settings.snowflake_pat:
        return [], None
    try:
        agent = CortexAgentClient()
        if not agent.session_token:
            await agent.authenticate()
        embedding_svc = EmbeddingService(session_token=agent.session_token)
        embedding = await embedding_svc.generate(question_text)
        if embedding and isinstance(embedding[0], list):
            embedding = embedding[0]

        emb_str = format_embedding_for_query(embedding)
        result = await db.execute(
            text(similarity_search_sql(table="assets", limit=3)),
            {"emb": emb_str, "threshold": settings.similarity_threshold, "lim": 3},
        )
        rows = result.fetchall()
        return [
            {"id": r.id, "filename": r.filename, "topic": r.topic, "similarity": float(r.similarity), "preview": (r.content or "")[:300]}
            for r in rows
        ], embedding
    except Exception as e:
        import traceback
        traceback.print_exc()
        await db.rollback()
        return [], None


async def _record_question(user_id: str, session_id: str, question_text: str, embedding, topic: str, db: AsyncSession) -> str:
    question = Question(
        user_id=user_id,
        session_id=session_id,
        question_text=question_text,
        topic=topic,
        embedding=format_embedding_for_storage(embedding) if embedding else None,
    )
    db.add(question)
    await db.flush()

    if topic:
        await db.execute(
            text(
                "UPDATE security_topics SET question_count = question_count + 1 WHERE name = :topic"
            ),
            {"topic": topic},
        )

    return question.id


async def _resolve_file_content_parts(file_ids: list[str], user_id: str, db: AsyncSession) -> list[dict]:
    if not file_ids:
        return []
    result = await db.execute(
        select(UserFile).where(UserFile.id.in_(file_ids), UserFile.user_id == user_id)
    )
    files = result.scalars().all()
    parts = []
    for f in files:
        upload_dir = FileExtractor.get_upload_dir(user_id, f.id)
        file_path = os.path.join(upload_dir, f.stored_filename)
        file_parts = await FileExtractor.file_to_content_parts(
            file_path, f.content_type, f.file_type, f.extracted_pages
        )
        parts.extend(file_parts)
    return parts


async def _get_skill_knowledge_config(db: AsyncSession) -> dict:
    """Read skill knowledge retrieval config from app_settings."""
    try:
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
    except Exception:
        return {"enabled": True, "limit": 5, "min_score": 0.25, "max_content_len": 800}


async def _build_project_memory_prefix(project_id: Optional[str], query: str, db: AsyncSession) -> str:
    parts = []
    plugin = get_memory_plugin()

    asset_hits = plugin.search_assets(query, limit=3)
    if asset_hits:
        snippets = [f"- {h['content'][:600]}" for h in asset_hits if h.get("score", 0) > 0.20]
        if snippets:
            parts.append("[Approved Assets]\n" + "\n".join(snippets))

    # Skill knowledge retrieval from indexed skill sections
    sk_config = await _get_skill_knowledge_config(db)
    if sk_config["enabled"]:
        from ..services.skill_indexer import search_skill_knowledge
        skill_hits = search_skill_knowledge(
            query, limit=sk_config["limit"], min_score=sk_config["min_score"]
        )
        if skill_hits:
            sk_snippets = [f"- {h['content'][:sk_config['max_content_len']]}" for h in skill_hits]
            if sk_snippets:
                parts.append("[Skill Knowledge]\n" + "\n".join(sk_snippets))

    if not project_id:
        if not parts:
            return ""
        return "\n\n" + "\n\n".join(parts) + "\n"

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        if not parts:
            return ""
        return "\n\n" + "\n\n".join(parts) + "\n"

    if project.memory:
        parts.append(f"[Project Instructions - {project.name}]\n{project.memory}")
    zettel_context = plugin.get_context(project_id, query, max_tokens=2000)
    if zettel_context:
        parts.append(f"[Project Memory - {project.name}]\n{zettel_context}")
    if not parts:
        return ""
    return "\n\n" + "\n\n".join(parts) + "\n"


async def _run_agent_background(
    session_id: str,
    message: str,
    user_id: str,
    model: Optional[str] = None,
    file_content_parts: Optional[list[dict]] = None,
):
    """Run the agent as a background task, independent of client connection.
    
    Saves intermediate progress and final results directly to the database.
    The client polls via the /stream SSE endpoint.
    """
    try:
        async with db_session_factory() as db:
            result = await db.execute(select(Session).where(Session.id == session_id))
            session = result.scalar_one_or_none()
            if not session:
                logger.error(f"Background task: session {session_id} not found")
                return

            agent = await user_cortex_client(db, user_id)
            system_prompt, skills_info = skill_loader.build_system_prompt(question=message)

            project_memory = await _build_project_memory_prefix(session.project_id, message, db)
            if project_memory:
                system_prompt = system_prompt + project_memory

            # --- Workspace: inject existing asset into system prompt ---
            workspace_asset = None
            result = await db.execute(
                select(Asset).where(Asset.session_id == session.id).order_by(Asset.created_at.desc())
            )
            workspace_asset = result.scalar_one_or_none()

            if workspace_asset:
                max_ver = await db.scalar(
                    select(func.max(AssetVersion.version)).where(AssetVersion.asset_id == workspace_asset.id)
                ) or 1
                system_prompt += (
                    f"\n\n## Active Workspace Document\n\n"
                    f"This session has an active workspace document: \"{workspace_asset.filename}\" "
                    f"(v{max_ver}, status: {workspace_asset.status})\n\n"
                    f"<workspace_content>\n{workspace_asset.content or ''}\n</workspace_content>\n\n"
                    f"When the user asks you to update, edit, revise, or improve this document "
                    f"(or any section of it), output the COMPLETE updated document wrapped in:\n"
                    f"<!-- WORKSPACE_UPDATE -->\n"
                    f"(full updated markdown here)\n"
                    f"<!-- /WORKSPACE_UPDATE -->\n\n"
                    f"Always output the full document content, not a partial diff. "
                    f"You may also include explanatory text outside the WORKSPACE_UPDATE block."
                )

            # --- Dynamic skill loading: scan history for LOAD_SKILL requests ---
            loaded_dynamic_skills = set()
            for msg in (session.history or []):
                if msg.get("role") == "assistant":
                    for c in msg.get("content", []):
                        if c.get("type") == "text":
                            txt = c.get("text", "")
                            for skill_match in re.finditer(r"<!--\s*LOAD_SKILL:\s*(\S+)\s*-->", txt):
                                loaded_dynamic_skills.add(skill_match.group(1))

            if loaded_dynamic_skills:
                from ..services.skill_loader import AVAILABLE_SKILLS
                for skill_name in sorted(loaded_dynamic_skills):
                    base_name = skill_name.split("/")[0]
                    if base_name in AVAILABLE_SKILLS:
                        content = skill_loader.load_skill(skill_name)
                        if content and not content.startswith("Unknown skill") and not content.startswith("Skill file not found") and not content.startswith("Sub-skill not found"):
                            system_prompt += (
                                f"\n\n## Dynamically Loaded Skill: {skill_name}\n\n" + content
                            )

            skills_info["dynamic_loaded"] = sorted(loaded_dynamic_skills) if loaded_dynamic_skills else []

            user_content = []
            if file_content_parts:
                user_content.extend(file_content_parts)
                image_keywords = ("image", "picture", "photo", "screenshot", "diagram", "chart", "see", "look", "show")
                if not any(kw in message.lower() for kw in image_keywords):
                    message = f"[An image has been attached inline above. Analyze it visually.] {message}"
            user_content.append({"type": "text", "text": message})

            history = list(session.history or [])
            history.append({
                "role": "user",
                "id": f"msg_{uuid.uuid4().hex[:12]}",
                "content": user_content,
            })

            messages_for_api = history.copy()
            t_start = time.monotonic()

            # Save initial state: user message added, status=running, pending_response shows progress
            session.history = list(history)  # assign new list to trigger ORM dirty
            flag_modified(session, "history")
            session.pending_response = {
                "status": "running",
                "events": [{"event": "skills_loaded", "data": skills_info}],
                "text": "",
            }
            flag_modified(session, "pending_response")
            await db.commit()

            pending_tool_calls = []

            # --- Phase 1: Collect full agent response (buffered) ---
            thinking_parts = []
            text_parts = []
            tool_events = []

            async for event in agent.stream(messages_for_api, system_prompt=system_prompt, model=model):
                if event.event_type == "response.thinking.delta":
                    txt = event.data.get("thinking", "") or event.data.get("text", "")
                    if txt:
                        thinking_parts.append(txt)
                        # Stream thinking delta to client (append, don't replace)
                        pending = dict(session.pending_response or {})
                        pending["events"] = pending.get("events", []) + [{"event": "thinking", "data": {"text": txt}}]
                        session.pending_response = pending
                        flag_modified(session, "pending_response")
                        await db.commit()

                elif event.event_type == "response.text.delta":
                    txt = event.data.get("text", "")
                    if txt:
                        text_parts.append(txt)

                elif event.event_type == "response.tool_use":
                    tool_data = {
                        "tool_use_id": event.data.get("tool_use_id", ""),
                        "name": event.data.get("name", ""),
                        "input": event.data.get("input", {}),
                    }
                    pending_tool_calls.append(tool_data)
                    tool_events.append({"event": "tool_use", "data": tool_data})
                    # Persist tool events so client can see progress
                    pending = dict(session.pending_response or {})
                    pending["events"] = pending.get("events", []) + [{"event": "tool_use", "data": tool_data}]
                    session.pending_response = pending
                    flag_modified(session, "pending_response")
                    await db.commit()

                elif event.event_type == "response.tool_result":
                    tool_events.append({"event": "tool_result", "data": event.data})

                elif event.event_type == "done":
                    break

            full_response_raw = "".join(text_parts)
            full_response = _sanitize_response(full_response_raw)
            full_response = _maybe_wrap_wizard(full_response)
            sanitized_parts = []
            if full_response_raw != full_response:
                sanitized_parts.append(full_response_raw[:500])  # what was stripped (preview)

            # Track any LOAD_SKILL requests in this response (for next turn)
            requested_skills = [
                m.group(1) for m in re.finditer(r"<!--\s*LOAD_SKILL:\s*(\S+)\s*-->", full_response_raw)
            ]
            if requested_skills:
                skills_info["requested_skills"] = requested_skills

            # --- Auto-continue: if response is only LOAD_SKILL with no visible text,
            # load the skill immediately and re-run the agent in the same turn ---
            should_auto_continue = (
                requested_skills
                and len(full_response.strip()) < 200  # short "loading" message, not a real answer
            )
            if should_auto_continue:
                from ..services.skill_loader import AVAILABLE_SKILLS
                for skill_name in requested_skills:
                    base_name = skill_name.split("/")[0]
                    if base_name in AVAILABLE_SKILLS:
                        content = skill_loader.load_skill(skill_name)
                        if content and not content.startswith("Unknown skill") and not content.startswith("Skill file not found") and not content.startswith("Sub-skill not found"):
                            system_prompt += (
                                f"\n\n## Dynamically Loaded Skill: {skill_name}\n\n" + content
                            )

                # Emit a loading event so the UI shows progress
                pending = dict(session.pending_response or {})
                pending["events"] = pending.get("events", []) + [
                    {"event": "skills_loaded", "data": {**skills_info, "dynamic_loaded": requested_skills}}
                ]
                session.pending_response = pending
                flag_modified(session, "pending_response")
                await db.commit()

                # Re-run the agent with the loaded skill
                text_parts = []
                thinking_parts = []
                tool_events = []
                pending_tool_calls = []

                async for event in agent.stream(messages_for_api, system_prompt=system_prompt, model=model):
                    if event.event_type == "response.thinking.delta":
                        txt = event.data.get("thinking", "") or event.data.get("text", "")
                        if txt:
                            thinking_parts.append(txt)
                            pending = dict(session.pending_response or {})
                            pending["events"] = pending.get("events", []) + [{"event": "thinking", "data": {"text": txt}}]
                            session.pending_response = pending
                            flag_modified(session, "pending_response")
                            await db.commit()
                    elif event.event_type == "response.text.delta":
                        txt = event.data.get("text", "")
                        if txt:
                            text_parts.append(txt)
                    elif event.event_type == "response.tool_use":
                        tool_data = {
                            "tool_use_id": event.data.get("tool_use_id", ""),
                            "name": event.data.get("name", ""),
                            "input": event.data.get("input", {}),
                        }
                        pending_tool_calls.append(tool_data)
                        tool_events.append({"event": "tool_use", "data": tool_data})
                        pending = dict(session.pending_response or {})
                        pending["events"] = pending.get("events", []) + [{"event": "tool_use", "data": tool_data}]
                        session.pending_response = pending
                        flag_modified(session, "pending_response")
                        await db.commit()
                    elif event.event_type == "response.tool_result":
                        tool_events.append({"event": "tool_result", "data": event.data})
                    elif event.event_type == "done":
                        break

                full_response_raw = "".join(text_parts)
                full_response = _sanitize_response(full_response_raw)
                full_response = _maybe_wrap_wizard(full_response)
                skills_info["dynamic_loaded"] = requested_skills

            # --- Phase 2: Self-correction (L1+ reflection passes) ---
            # Run reflection on all substantive answers. Skip wizard/clarification
            # and very short responses. Number of passes determined by configured prompts.
            has_wizard = "<!-- WIZARD" in full_response
            reflect_exchanges = []
            original_response = full_response  # preserve pre-reflection version
            # Check if any active skill is in the skip-reflect list
            skip_reflect_skills = _get_skip_reflect_skills()
            active_skills_set = set(skills_info.get("mandatory_skills", []))
            if skills_info.get("detected_skill"):
                active_skills_set.add(skills_info["detected_skill"])
            active_skills_set.update(skills_info.get("dynamic_loaded", []))
            active_skills_set.update(skills_info.get("requested_skills", []))
            skill_skips_reflect = bool(active_skills_set & skip_reflect_skills)

            reflect_prompts = _get_reflect_prompts() if (
                full_response and len(full_response) > 200
                and not has_wizard
                and not skill_skips_reflect
            ) else []
            if reflect_prompts:

                reflect_messages = messages_for_api.copy()
                reflect_messages.append({
                    "role": "assistant",
                    "id": f"msg_{uuid.uuid4().hex[:12]}",
                    "content": [{"type": "text", "text": full_response}],
                })

                # Emit reflecting event to client (shows L1, L2... in UI)
                pending = dict(session.pending_response or {})
                pending["status"] = "reflecting"
                pending["events"] = pending.get("events", []) + [
                    {"event": "reflecting", "data": {"pass": 1, "total": len(reflect_prompts)}}
                ]
                session.pending_response = pending
                flag_modified(session, "pending_response")
                await db.commit()

                for reflect_iter, reflect_prompt in enumerate(reflect_prompts):
                    reflect_messages.append({
                        "role": "user",
                        "id": f"msg_{uuid.uuid4().hex[:12]}",
                        "content": [{"type": "text", "text": reflect_prompt}],
                    })

                    reflect_text_parts = []
                    reflect_thinking_parts = []
                    async for rev in agent.stream(reflect_messages, system_prompt=system_prompt, model=model):
                        if rev.event_type == "response.thinking.delta":
                            txt = rev.data.get("thinking", "") or rev.data.get("text", "")
                            if txt:
                                reflect_thinking_parts.append(txt)
                        elif rev.event_type == "response.text.delta":
                            txt = rev.data.get("text", "")
                            if txt:
                                reflect_text_parts.append(txt)
                        elif rev.event_type == "done":
                            break

                    reflect_text = "".join(reflect_text_parts).strip()

                    # Stream reflection thinking + response as a thinking event
                    reflect_display = ""
                    if reflect_thinking_parts:
                        reflect_display = "".join(reflect_thinking_parts)
                    if reflect_text and not reflect_text.upper().startswith("LGTM"):
                        reflect_display += f"\n\n**L1 Reflection (pass {reflect_iter + 1}):**\n{reflect_text[:2000]}"
                    elif reflect_text.upper().startswith("LGTM"):
                        reflect_display += f"\n\n**L1 Verification: LGTM** (no changes needed)"
                    if reflect_display:
                        pending = dict(session.pending_response or {})
                        pending["events"] = pending.get("events", []) + [{"event": "thinking", "data": {"text": reflect_display}}]
                        session.pending_response = pending
                        flag_modified(session, "pending_response")
                        await db.commit()

                    if reflect_text.upper() == "LGTM" or reflect_text.upper().startswith("LGTM"):
                        reflect_exchanges.append({
                            "prompt": reflect_prompt[:200],
                            "response": "LGTM",
                            "accepted": False,
                            "pass": reflect_iter + 1,
                        })
                        break

                    # Only accept revision if it also contains a WORKSPACE_UPDATE block
                    # (meaning the model actually rewrote the deliverable, not just commented)
                    accepted = "<!-- WORKSPACE_UPDATE" in reflect_text
                    reflect_exchanges.append({
                        "prompt": reflect_prompt[:200],
                        "response": reflect_text[:1000],
                        "accepted": accepted,
                        "pass": reflect_iter + 1,
                    })
                    if accepted:
                        # Extract only the content inside the workspace block;
                        # discard reflection commentary outside the tags.
                        ws_block = re.search(
                            r"<!--\s*WORKSPACE_UPDATE\s*-->\s*\n?([\s\S]*?)\n?\s*<!--\s*/WORKSPACE_UPDATE\s*-->",
                            reflect_text,
                        )
                        if ws_block:
                            if workspace_asset:
                                # Keep tags so _process_workspace can do an update
                                full_response = ws_block.group(0)
                            else:
                                # Strip tags; _process_workspace will auto-create
                                full_response = ws_block.group(1).strip()
                        else:
                            full_response = _sanitize_response(reflect_text)
                    
                    # Emit event for next pass if there are more
                    if reflect_iter + 1 < len(reflect_prompts):
                        pending = dict(session.pending_response or {})
                        pending["events"] = pending.get("events", []) + [
                            {"event": "reflecting", "data": {"pass": reflect_iter + 2, "total": len(reflect_prompts)}}
                        ]
                        session.pending_response = pending
                        flag_modified(session, "pending_response")
                        await db.commit()

            # --- Store internal dialogue for debugging ---
            if settings.agent_log_internal:
                session.internal_dialogue = {
                    "skills": skills_info,
                    "original_response": original_response[:5000],
                    "sanitized_parts": sanitized_parts,
                    "reflect_exchanges": reflect_exchanges,
                    "final_response_differs": full_response != original_response,
                }
                flag_modified(session, "internal_dialogue")

            # --- Phase 3: Save final response ---
            elapsed_total = int((time.monotonic() - t_start) * 1000)

            if full_response:
                history.append({
                    "role": "assistant",
                    "id": f"msg_{uuid.uuid4().hex[:12]}",
                    "content": [{"type": "text", "text": full_response}],
                })

            session.history = list(history)
            flag_modified(session, "history")
            session.total_time_ms = elapsed_total
            web_count = sum(
                1 for tc in pending_tool_calls
                if "search" in (tc.get("name") or "").lower()
            )
            if web_count:
                session.web_search_count = (session.web_search_count or 0) + web_count

            # Build final events for the stream endpoint to replay
            final_events = []
            for te in tool_events:
                final_events.append(te)
            if full_response:
                final_events.append({"event": "text", "data": {"text": full_response}})

            # Workspace events
            workspace_events = await _process_workspace(
                session, full_response, workspace_asset, db
            )
            final_events.extend(workspace_events)

            final_events.append({"event": "done", "data": {"total_ms": elapsed_total}})

            session.pending_response = {
                "status": "done",
                "events": (session.pending_response or {}).get("events", []) + final_events,
                "text": full_response,
                "total_ms": elapsed_total,
            }
            flag_modified(session, "pending_response")
            session.status = "active"
            await db.commit()

            # --- Project memory ---
            if session.project_id and full_response and len(full_response) > 20:
                try:
                    summary = f"Q: {message[:200]}\nA: {full_response[:500]}"
                    get_memory_plugin().add(session.project_id, summary, importance=0.6)
                except Exception:
                    pass

    except asyncio.CancelledError:
        # Task was cancelled (e.g., user hit stop)
        async with db_session_factory() as db:
            result = await db.execute(select(Session).where(Session.id == session_id))
            session = result.scalar_one_or_none()
            if session:
                session.status = "active"
                session.pending_response = {
                    **(session.pending_response or {}),
                    "status": "cancelled",
                    "events": (session.pending_response or {}).get("events", []) + [
                        {"event": "error", "data": {"error": "Agent task was cancelled"}}
                    ],
                }
                await db.commit()
    except Exception as e:
        logger.exception(f"Background agent task failed for session {session_id}")
        async with db_session_factory() as db:
            result = await db.execute(select(Session).where(Session.id == session_id))
            session = result.scalar_one_or_none()
            if session:
                session.status = "active"
                session.pending_response = {
                    **(session.pending_response or {}),
                    "status": "error",
                    "events": (session.pending_response or {}).get("events", []) + [
                        {"event": "error", "data": {"error": str(e)}}
                    ],
                }
                await db.commit()
    finally:
        _RUNNING_TASKS.pop(session_id, None)


async def _process_workspace(
    session: Session,
    full_response: str,
    workspace_asset: Optional[Asset],
    db: AsyncSession,
) -> list[dict]:
    """Process workspace updates from the agent response. Returns events to emit."""
    events = []
    if not full_response:
        return events

    ws_match = re.search(
        r"<!--\s*WORKSPACE_UPDATE\s*-->\s*\n?([\s\S]*?)\n?\s*<!--\s*/WORKSPACE_UPDATE\s*-->",
        full_response,
    )

    if ws_match and workspace_asset:
        new_content = ws_match.group(1).strip()
        workspace_asset.content = new_content
        max_ver = await db.scalar(
            select(func.max(AssetVersion.version)).where(
                AssetVersion.asset_id == workspace_asset.id
            )
        ) or 0
        new_version = AssetVersion(
            asset_id=workspace_asset.id,
            version=max_ver + 1,
            content=new_content,
            edited_by=session.user_id,
            comment="Updated by agent",
        )
        db.add(new_version)
        await db.commit()
        events.append({
            "event": "workspace_updated",
            "data": {
                "asset_id": workspace_asset.id,
                "filename": workspace_asset.filename,
                "version": max_ver + 1,
            },
        })
    elif ws_match and not workspace_asset:
        new_content = ws_match.group(1).strip()
        topic = classify_topic(new_content)
        filename = f"{(session.title or 'response')[:60].replace(' ', '_')}.md"
        new_asset = Asset(
            session_id=session.id,
            owner_id=session.user_id,
            filename=filename,
            content=new_content,
            topic=topic,
            status="draft",
            visibility="generated",
        )
        db.add(new_asset)
        await db.flush()
        version = AssetVersion(
            asset_id=new_asset.id,
            version=1,
            content=new_content,
            edited_by=session.user_id,
            comment="Auto-created from session",
        )
        db.add(version)
        await db.commit()
        events.append({
            "event": "workspace_created",
            "data": {
                "asset_id": new_asset.id,
                "filename": filename,
            },
        })
    elif not workspace_asset and not ws_match:
        # Auto-create workspace from first substantive answer
        # Skip wizard/clarification responses and very short replies
        is_wizard = "<!-- WIZARD" in full_response
        if not is_wizard and len(full_response) > 200:
            topic = classify_topic(full_response)
            filename = f"{(session.title or 'response')[:60].replace(' ', '_')}.md"
            new_asset = Asset(
                session_id=session.id,
                owner_id=session.user_id,
                filename=filename,
                content=full_response,
                topic=topic,
                status="draft",
                visibility="generated",
            )
            db.add(new_asset)
            await db.flush()
            version = AssetVersion(
                asset_id=new_asset.id,
                version=1,
                content=full_response,
                edited_by=session.user_id,
                comment="Auto-created from session",
            )
            db.add(version)
            await db.commit()
            events.append({
                "event": "workspace_created",
                "data": {
                    "asset_id": new_asset.id,
                    "filename": filename,
                },
            })

    return events


def _launch_agent_task(session_id: str, message: str, user_id: str, model: Optional[str] = None, file_content_parts: Optional[list[dict]] = None):
    """Launch the agent as a background asyncio task. Returns the task."""
    # Cancel any existing task for this session
    existing = _RUNNING_TASKS.get(session_id)
    if existing and not existing.done():
        existing.cancel()

    task = asyncio.create_task(
        _run_agent_background(session_id, message, user_id, model=model, file_content_parts=file_content_parts)
    )
    _RUNNING_TASKS[session_id] = task
    return task


@router.post("")
async def create_session(
    req: CreateSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    topic = classify_topic(req.message)
    user_id = user.id

    if not req.skip_suggestion:
        suggestions, embedding = await _check_similar_assets(req.message, db)
        if suggestions:
            question_id = await _record_question(user_id, None, req.message, embedding, topic, db)
            await db.commit()
            return {
                "type": "suggestion",
                "question_id": question_id,
                "suggestions": suggestions,
            }

    session = Session(
        user_id=user_id,
        title=req.title or req.message[:80],
        project_id=req.project_id,
        history=[],
        status="running",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    if not req.skip_suggestion:
        try:
            agent = CortexAgentClient()
            if not agent.session_token:
                await agent.authenticate()
            embedding_svc = EmbeddingService(session_token=agent.session_token)
            embedding = await embedding_svc.generate(req.message)
            if embedding and isinstance(embedding[0], list):
                embedding = embedding[0]
        except Exception:
            embedding = None
    else:
        embedding = None

    await _record_question(user_id, session.id, req.message, embedding, topic, db)
    await db.commit()

    file_parts = await _resolve_file_content_parts(req.file_ids or [], user_id, db)

    # Launch agent as background task — returns immediately
    _launch_agent_task(session.id, req.message, user_id, model=req.model, file_content_parts=file_parts)

    return {
        "type": "session",
        "id": session.id,
        "title": session.title,
        "status": "running",
    }


@router.post("/use-asset")
async def use_asset(
    req: UseAssetRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Asset).where(Asset.id == req.asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    result = await db.execute(select(Question).where(Question.id == req.question_id))
    question = result.scalar_one_or_none()
    if question:
        question.matched_asset_id = req.asset_id
        question.reuse_accepted = True

    session = Session(
        user_id=user.id,
        title=f"Reused: {asset.filename}",
        history=[
            {
                "role": "user",
                "id": f"msg_{uuid.uuid4().hex[:12]}",
                "content": [{"type": "text", "text": question.question_text if question else "Reused asset"}],
            },
            {
                "role": "assistant",
                "id": f"msg_{uuid.uuid4().hex[:12]}",
                "content": [{"type": "text", "text": asset.content or ""}],
            },
        ],
        status="done",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "content": asset.content,
    }


@router.post("/{session_id}/messages")
async def send_message(
    session_id: str,
    req: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.status = "running"
    session.pending_response = {"status": "running", "events": [], "text": ""}
    await db.commit()

    file_parts = await _resolve_file_content_parts(req.file_ids or [], user.id, db)

    # Launch agent as background task — returns immediately
    _launch_agent_task(session.id, req.message, user.id, model=req.model, file_content_parts=file_parts)

    return {"ok": True, "status": "running"}


@router.get("/{session_id}/stream")
async def stream_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for streaming agent progress. Polls the pending_response field.
    
    The client connects here after launching a message. Events are streamed as they
    become available from the background task. When the task finishes, all remaining
    events are flushed and the connection closes.
    """
    # Verify access
    if user.role == "admin":
        result = await db.execute(select(Session).where(Session.id == session_id))
    else:
        result = await db.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user.id)
        )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        """Stream events from the background task via polling pending_response."""
        events_sent = 0

        while True:
            # Re-fetch session to get latest pending_response
            async with db_session_factory() as poll_db:
                result = await poll_db.execute(select(Session).where(Session.id == session_id))
                s = result.scalar_one_or_none()
                if not s:
                    yield {"event": "error", "data": json.dumps({"error": "Session not found"})}
                    return

                pending = s.pending_response or {}
                events = pending.get("events", [])
                status = pending.get("status", "")

                # Stream any new events
                if len(events) > events_sent:
                    for ev in events[events_sent:]:
                        yield {"event": ev["event"], "data": json.dumps(ev.get("data", {}))}
                    events_sent = len(events)

                # If task is done/error/cancelled, we're finished
                if status in ("done", "error", "cancelled"):
                    return

                # If session is no longer running and no task is active, it's done
                if s.status != "running" and session_id not in _RUNNING_TASKS:
                    # Flush any remaining events
                    if len(events) > events_sent:
                        for ev in events[events_sent:]:
                            yield {"event": ev["event"], "data": json.dumps(ev.get("data", {}))}
                    return

            # Poll interval
            await asyncio.sleep(0.3)

    headers = {"X-Session-Id": session_id}
    return EventSourceResponse(event_generator(), headers=headers)


@router.post("/{session_id}/stop")
async def stop_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop a running agent task for this session."""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    task = _RUNNING_TASKS.get(session_id)
    if task and not task.done():
        task.cancel()
        return {"ok": True, "stopped": True}

    # Task already done or not found — just reset status
    if session.status == "running":
        session.status = "active"
        await db.commit()
    return {"ok": True, "stopped": False}


@router.post("/{session_id}/save-to-collection")
async def save_to_collection(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move session to user's 'My Collection' project (auto-created if needed)."""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get or create the "My Collection" system project for this user
    result = await db.execute(
        select(Project).where(Project.user_id == user.id, Project.is_system == True, Project.name == "My Collection")
    )
    collection = result.scalar_one_or_none()
    if not collection:
        collection = Project(
            user_id=user.id,
            name="My Collection",
            description="Your saved responses and documents",
            is_system=True,
        )
        db.add(collection)
        await db.flush()

    # Move the session to the collection project
    already = session.project_id == collection.id
    if not already:
        session.project_id = collection.id
        await db.commit()

    return {
        "ok": True,
        "already": already,
        "project_id": collection.id,
        "project_name": collection.name,
    }


@router.post("/{session_id}/register-asset")
async def register_asset_from_session(
    session_id: str,
    req: RegisterAssetFromSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # If session already has a workspace asset, return it instead of creating a duplicate
    existing = await db.execute(
        select(Asset).where(Asset.session_id == session_id, Asset.owner_id == user.id)
    )
    existing_asset = existing.scalar_one_or_none()
    if existing_asset:
        # Update visibility if requested (e.g. saveToCollection sets visibility=private)
        if req.visibility and existing_asset.visibility != req.visibility:
            existing_asset.visibility = req.visibility
            await db.commit()
        return {"id": existing_asset.id, "filename": existing_asset.filename, "status": existing_asset.status, "topic": existing_asset.topic}

    content = ""
    for msg in (session.history or []):
        if msg.get("role") == "assistant":
            for c in msg.get("content", []):
                if c.get("type") == "text":
                    content += c.get("text", "")

    if not content.strip():
        raise HTTPException(status_code=400, detail="No assistant response to register")

    topic = req.topic or classify_topic(content)
    filename = req.filename or f"{session.title[:60].replace(' ', '_')}.md"

    asset = Asset(
        session_id=session.id,
        owner_id=user.id,
        filename=filename,
        content=content,
        topic=topic,
        status="draft",
        visibility=req.visibility or "generated",
    )
    db.add(asset)
    await db.flush()

    version = AssetVersion(
        asset_id=asset.id,
        version=1,
        content=content,
        edited_by=user.id,
        comment="Registered from session",
    )
    db.add(version)
    await db.commit()
    await db.refresh(asset)

    return {"id": asset.id, "filename": asset.filename, "status": asset.status, "topic": asset.topic}


@router.put("/{session_id}/rename")
async def rename_session(
    session_id: str,
    req: RenameRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.user_id == user.id)
        .values(title=req.title)
    )
    await db.commit()
    return {"ok": True}


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.user_id == user.id)
        .values(deleted_at=func.now())
    )
    await db.commit()
    return {"ok": True}


@router.post("/{session_id}/cancel")
async def cancel_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Cancel any running background task
    task = _RUNNING_TASKS.get(session_id)
    if task and not task.done():
        task.cancel()

    await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.user_id == user.id)
        .values(status="cancelled")
    )
    await db.commit()
    return {"ok": True}


@router.put("/{session_id}/project")
async def move_session_to_project(
    session_id: str,
    req: MoveSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    if req.project_id:
        proj = await db.execute(
            select(Project).where(Project.id == req.project_id, Project.user_id == user.id)
        )
        if not proj.scalar_one_or_none():
            raise HTTPException(404, "Project not found")

    session.project_id = req.project_id
    await db.commit()
    return {"ok": True, "project_id": req.project_id}


@router.post("/{session_id}/copy")
async def copy_session(
    session_id: str,
    req: CopySessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(404, "Session not found")

    if req.project_id:
        proj = await db.execute(
            select(Project).where(Project.id == req.project_id, Project.user_id == user.id)
        )
        if not proj.scalar_one_or_none():
            raise HTTPException(404, "Project not found")

    new_session = Session(
        user_id=user.id,
        title=f"Copy: {original.title}",
        project_id=req.project_id,
        history=copy.deepcopy(original.history or []),
        status=original.status,
        total_time_ms=original.total_time_ms,
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return {
        "id": new_session.id,
        "title": new_session.title,
        "project_id": new_session.project_id,
    }


class SetStatusRequest(BaseModel):
    status: str


@router.put("/{session_id}/status")
async def set_session_status(
    session_id: str,
    req: SetStatusRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = {"active", "done", "archived"}
    if req.status not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {', '.join(sorted(allowed))}")
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = req.status
    await db.commit()
    return {"ok": True}


@router.post("/{session_id}/archive")
async def archive_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = "archived"
    await db.commit()
    return {"ok": True}


@router.post("/{session_id}/unarchive")
async def unarchive_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = "active"
    await db.commit()
    return {"ok": True}


class FeedbackRequest(BaseModel):
    rating: int
    comment: Optional[str] = None


@router.post("/{session_id}/feedback")
async def submit_feedback(
    session_id: str,
    req: FeedbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Session not found")

    existing = await db.execute(
        select(Feedback).where(Feedback.session_id == session_id, Feedback.user_id == user.id)
    )
    fb = existing.scalar_one_or_none()
    if fb:
        fb.rating = req.rating
        fb.comment = req.comment
    else:
        fb = Feedback(
            session_id=session_id,
            user_id=user.id,
            rating=req.rating,
            comment=req.comment,
        )
        db.add(fb)

    await db.commit()
    return {"ok": True}


@router.get("/{session_id}/download")
async def download_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    lines = [f"# {session.title}\n", f"Session ID: {session.id}\n", f"Created: {session.created_at.isoformat()}\n", "---\n"]
    for msg in (session.history or []):
        role = msg.get("role", "unknown").upper()
        lines.append(f"\n## {role}\n\n")
        for part in msg.get("content", []):
            if part.get("type") == "text":
                lines.append(part.get("text", ""))
                lines.append("\n")

    content = "\n".join(lines)
    filename = f"session_{session_id[:8]}.md"
    return StreamingResponse(
        iter([content]),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
