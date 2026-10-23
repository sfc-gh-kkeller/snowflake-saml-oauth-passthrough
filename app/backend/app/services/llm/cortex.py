"""Cortex Agent LLM provider — wraps the Snowflake Cortex Agent API."""
import json
import uuid
import hashlib
import platform
import time
import logging
from typing import AsyncGenerator, Optional
from dataclasses import dataclass, field

import httpx

from .base import LLMProvider, StreamEvent
from ...core.config import settings

logger = logging.getLogger(__name__)

# Module-level disabled tools cache (updated by admin endpoints)
_disabled_tools: set[str] = set()


def get_disabled_tools() -> set[str]:
    """Return the current set of disabled tool names."""
    return _disabled_tools


def set_disabled_tools(tools: set[str]) -> None:
    """Update the disabled tools set (called by admin API)."""
    global _disabled_tools
    _disabled_tools = tools
if not logger.handlers:
    _fh = logging.FileHandler("/tmp/nanocortex_agent.log")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(_fh)
    logger.setLevel(logging.INFO)


@dataclass
class AgentMessage:
    role: str
    content: list[dict]
    id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")


@dataclass
class ToolCall:
    tool_use_id: str
    name: str
    input: dict
    client_side: bool = True


MAX_TOOL_LOOPS = 10


class CortexAgentClient(LLMProvider):
    def __init__(
        self,
        account: Optional[str] = None,
        user: Optional[str] = None,
        pat: Optional[str] = None,
        warehouse: Optional[str] = None,
        role: Optional[str] = None,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        oauth_token: Optional[str] = None,
        user_label: str = "",
    ):
        # Per-user mode: an Entra-issued External OAuth token replaces the shared PAT.
        self.oauth_token = oauth_token
        self.user_label = user_label
        self.account = (account or settings.snowflake_account).lower().replace("_", "-")
        self.user = user or settings.snowflake_user
        self.pat = pat or settings.snowflake_pat
        self.warehouse = warehouse or (settings.sf_oauth_warehouse if oauth_token else "") or settings.snowflake_warehouse
        self.role = role or (settings.sf_oauth_default_role if oauth_token else "") or settings.snowflake_role
        self.database = database or settings.snowflake_database
        self.schema = schema or settings.snowflake_schema
        self.base_url = f"https://{self.account}.snowflakecomputing.com"
        self.session_token: Optional[str] = None
        self.session_id = str(uuid.uuid4())

    @property
    def name(self) -> str:
        return "cortex"

    async def authenticate(self) -> str:
        if self.oauth_token:
            # Bearer token is used directly on every request; no login-request round trip.
            self.session_token = self.oauth_token
            return self.session_token
        async with httpx.AsyncClient(verify=True) as client:
            resp = await client.post(
                f"{self.base_url}/session/v1/login-request",
                json={
                    "data": {
                        "ACCOUNT_NAME": self.account.split(".")[0],
                        "LOGIN_NAME": self.user,
                        "AUTHENTICATOR": "PROGRAMMATIC_ACCESS_TOKEN",
                        "TOKEN": self.pat,
                    }
                },
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("success"):
                raise RuntimeError(f"Auth failed: {body.get('message', 'unknown error')}")
            self.session_token = body["data"]["token"]
            return self.session_token

    def _headers(self) -> dict:
        if self.oauth_token:
            return {
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {self.oauth_token}",
                "X-Snowflake-Authorization-Token-Type": "OAUTH",
                "X-Snowflake-Role": self.role.upper(),
            }
        return {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f'Snowflake Token="{self.session_token}"',
        }

    def _format_session_context(self) -> str:
        parts = [f"account={self.account.split('.')[0].upper().replace('-', '_')}"]
        if self.role:
            parts.append(f"role={self.role.upper()}")
        if self.warehouse:
            parts.append(f"warehouse={self.warehouse.upper()}")
        if self.database:
            parts.append(f"database={self.database.upper()}")
        else:
            parts.append("database=<unset>")
        if self.schema:
            parts.append(f"schema={self.schema.upper()}")
        else:
            parts.append("schema=<unset>")
        return f"Snowflake session: {', '.join(parts)}"

    def _build_coding_agent_config(
        self,
        working_directory: str = "/tmp",
        system_prompt: str = "",
        use_web_search_passthrough: bool = False,
    ) -> dict:
        return {
            "UserID": self.user,
            "SessionID": self.session_id,
            "Temperature": 1,
            "SystemPromptInternal": {
                "Prompt": system_prompt,
                "Attributes": {
                    "WorkingDirectory": working_directory,
                    "IsGitRepo": False,
                    "Platform": platform.system().lower(),
                    "AgentIdentity": "nanocortex",
                    "OSVersion": platform.platform(),
                },
                "Version": "v2",
                "FullOverride": False,
            },
            "UserMessageSystemReminder": [self._format_session_context()],
            "UseWebSearchPassthrough": use_web_search_passthrough,
            "PrivateMode": False,
            "OriginApplication": "snova",
            "SessionAccountLocators": [self.account.split(".")[0].upper().replace("-", "_")],
            "CurrentSqlAccountLocator": self.account.split(".")[0].upper().replace("-", "_"),
        }

    # All tools the Cortex Agent can use
    AVAILABLE_TOOLS = ["web_search"]

    def _build_tools(self) -> list[dict]:
        tools = []
        disabled = get_disabled_tools()
        names = list(self.AVAILABLE_TOOLS)
        if self.oauth_token:
            # Per-user mode: let the agent query Snowflake as the signed-in user.
            names.append("snowflake_sql_execute")
        for name in names:
            if name not in disabled:
                tools.append({"tool_spec": {"type": name, "name": name}})
        return tools

    def _build_request(
        self,
        messages: list[dict],
        system_prompt: str = "",
        model: Optional[str] = None,
        max_steps: Optional[int] = None,
        thinking_effort: Optional[str] = None,
    ) -> dict:
        tools = self._build_tools()
        return {
            "messages": messages,
            "model": model or settings.agent_model,
            "stream": True,
            "origin_application": "coding_agent",
            "tools": tools,
            "tool_choice": {"type": "auto"},
            "tool_resources": {
                "web_search": {"api_mode": "search", "max_results": 10},
            },
            "experimental": {
                "UseLegacyAnswersToolNames": False,
                "ResponseSchemaVersion": "v2",
                "EnableSingleAgentOrchestration": True,
                "EnableFunctionCallAPIForPlanning": True,
                "ReasoningAgentFlowType": "simple",
                "StopCondition": {"NumSteps": max_steps or settings.agent_max_steps},
                "ThinkingEffort": thinking_effort or settings.agent_thinking_effort,
                "UseAdaptiveThinking": True,
                "EnableStepTrace": True,
                "CodingAgent": self._build_coding_agent_config(
                    system_prompt=system_prompt,
                    use_web_search_passthrough=False,
                ),
            },
        }

    async def _stream_single(
        self,
        body: dict,
    ) -> AsyncGenerator[StreamEvent, None]:
        url = f"{self.base_url}/api/v2/cortex/agent:run"
        async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(300, connect=30)) as client:
            async with client.stream("POST", url, json=body, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise RuntimeError(f"Agent API error {resp.status_code}: {error_body.decode()}")

                event_type = ""
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                        continue
                    if line.startswith("data:"):
                        data_str = line.split(":", 1)[1].strip()
                        if data_str == "[DONE]":
                            logger.info("[SSE] [DONE]")
                            yield StreamEvent(event_type="done", data={})
                            return
                        try:
                            data = json.loads(data_str)
                            if event_type == "response.thinking.delta":
                                logger.info(f"[SSE] THINKING delta received, len={len(data_str)}")
                            elif event_type != "response.text.delta":
                                preview = data_str[:300]
                                logger.debug(f"[SSE] {event_type}: {preview}")
                            data["_type"] = event_type
                            yield StreamEvent(event_type=event_type, data=data)
                        except json.JSONDecodeError:
                            continue

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        model: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        if not self.session_token:
            await self.authenticate()

        body = self._build_request(messages, system_prompt=system_prompt, model=model)
        working_messages = list(messages)

        for loop_idx in range(MAX_TOOL_LOOPS):
            body["messages"] = working_messages

            text_parts = []
            tool_calls = []
            server_tool_results = []

            async for event in self._stream_single(body):
                if event.event_type == "error":
                    # Surface API-level errors (auth, quotas) instead of ending with an empty reply.
                    raise RuntimeError(f"Cortex Agent error {event.data.get('code', '')}: {event.data.get('message', event.data)}")

                if event.event_type == "response.text.delta":
                    yield event
                    text_parts.append(event.data.get("text", ""))

                elif event.event_type == "response.thinking.delta":
                    yield event

                elif event.event_type == "response.tool_use":
                    tool_use_inner = event.data.get("tool_use", {})
                    raw_name = event.data.get("name", "") or event.data.get("type", "") or tool_use_inner.get("name", "") or tool_use_inner.get("type", "")
                    tc_data = {
                        "tool_use_id": event.data.get("tool_use_id", "") or tool_use_inner.get("tool_use_id", ""),
                        "name": raw_name,
                        "input": event.data.get("input", {}) or tool_use_inner.get("input", {}),
                        "client_side": event.data.get("client_side_execute", True),
                    }
                    tool_calls.append(tc_data)
                    yield event

                elif event.event_type == "response.tool_result":
                    tool_use_id = event.data.get("tool_use_id", "")
                    content = event.data.get("content", [])
                    server_tool_results.append({
                        "tool_use_id": tool_use_id,
                        "content": content,
                    })
                    yield event

                elif event.event_type == "done":
                    logger.info(f"[STREAM] Got 'done' event from _stream_single")
                    pass

                elif event.event_type == "response":
                    stop_reason = event.data.get("stop_reason", "")
                    logger.info(f"[STREAM] Got 'response' event: stop_reason={stop_reason}")

            logger.info(f"[STREAM] Loop {loop_idx}: text_parts={len(text_parts)}, tool_calls={len(tool_calls)}, tools={[tc['name'] for tc in tool_calls]}")

            if not tool_calls:
                yield StreamEvent(event_type="done", data={})
                return

            needs_client_execution = [
                tc for tc in tool_calls
                if tc.get("client_side", False)
            ]

            if not needs_client_execution:
                logger.info(f"[STREAM] No client-side tools needed, ending. Server ran: {[tc['name'] for tc in tool_calls]}")
                yield StreamEvent(event_type="done", data={})
                return

            logger.info(f"[STREAM] Client-side tools to execute: {[tc['name'] for tc in needs_client_execution]}")

            assistant_content = []
            if text_parts:
                assistant_content.append({"type": "text", "text": "".join(text_parts)})
            for tc in tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "tool_use": {
                        "tool_use_id": tc["tool_use_id"],
                        "name": tc["name"],
                        "input": tc["input"],
                    },
                })
            working_messages.append({
                "role": "assistant",
                "id": f"msg_{uuid.uuid4().hex[:12]}",
                "content": assistant_content,
            })

            server_side_map = {tc["tool_use_id"]: tc["name"] for tc in tool_calls if not tc.get("client_side", False)}
            server_results_content = []
            for sr in server_tool_results:
                if sr["tool_use_id"] in server_side_map:
                    result_text = ""
                    for item in sr["content"]:
                        if "text" in item:
                            result_text = item["text"]
                        elif "json" in item:
                            result_text = json.dumps(item["json"])
                    server_results_content.append({
                        "type": "tool_result",
                        "tool_result": {
                            "tool_use_id": sr["tool_use_id"],
                            "name": server_side_map[sr["tool_use_id"]],
                            "content": [{"type": "text", "text": result_text}],
                            "status": "success",
                        },
                    })

            if server_results_content:
                all_results_content = server_results_content
            else:
                all_results_content = []

            tool_results_content = []
            for tc in needs_client_execution:
                tool_name = tc["name"]
                tool_input = tc["input"] or {}
                try:
                    if tool_name == "web_search":
                        result_text = await self._execute_web_search(tool_input.get("query", ""))
                    elif tool_name == "snowflake_sql_execute":
                        result_text = await self._execute_sql(tool_input)
                    else:
                        result_text = f"Unsupported client-side tool: {tool_name}"

                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_result": {
                            "tool_use_id": tc["tool_use_id"],
                            "name": tool_name,
                            "content": [{"type": "text", "text": result_text}],
                            "status": "success",
                        },
                    })
                    yield StreamEvent(
                        event_type="tool_result",
                        data={
                            "tool_use_id": tc["tool_use_id"],
                            "name": tool_name,
                            "status": "success",
                            "content": [{"type": "text", "text": result_text[:500] + ("..." if len(result_text) > 500 else "")}],
                        },
                    )
                except Exception as e:
                    err = f"{tool_name} failed: {e}"
                    logger.info(f"[STREAM] Tool error: {err}")
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_result": {
                            "tool_use_id": tc["tool_use_id"],
                            "name": tool_name,
                            "content": [{"type": "text", "text": err}],
                            "status": "error",
                        },
                    })
                    yield StreamEvent(
                        event_type="tool_result",
                        data={"tool_use_id": tc["tool_use_id"], "name": tool_name, "status": "error", "error": err},
                    )

            if tool_results_content:
                all_results_content.extend(tool_results_content)

            if all_results_content:
                working_messages.append({
                    "role": "user",
                    "id": f"msg_{uuid.uuid4().hex[:12]}",
                    "content": all_results_content,
                })

        yield StreamEvent(event_type="done", data={})

    async def _execute_web_search(self, query: str) -> str:
        if not query:
            return "error: query required"

        logger.info(f"[WEB_SEARCH] query={query[:100]}")

        messages = [
            {
                "role": "user",
                "id": f"msg_{uuid.uuid4().hex[:12]}",
                "content": [{"type": "text", "text": query}],
            }
        ]
        tools = [{"tool_spec": {"type": "web_search", "name": "web_search"}}]
        body = {
            "messages": messages,
            "model": settings.agent_model,
            "stream": True,
            "origin_application": "coding_agent",
            "tools": tools,
            "tool_choice": {"type": "auto"},
            "tool_resources": {"web_search": {"api_mode": "search", "max_results": 10}},
            "experimental": {
                "UseLegacyAnswersToolNames": False,
                "ResponseSchemaVersion": "v2",
                "EnableSingleAgentOrchestration": True,
                "EnableFunctionCallAPIForPlanning": True,
                "ReasoningAgentFlowType": "simple",
                "StopCondition": {"NumSteps": 5},
                "ThinkingEffort": "low",
                "EnableStepTrace": True,
                "CodingAgent": self._build_coding_agent_config(use_web_search_passthrough=True),
            },
        }

        tool_result_json = None
        all_events = []
        url = f"{self.base_url}/api/v2/cortex/agent:run"
        async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(60, connect=30)) as client:
            async with client.stream("POST", url, json=body, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    logger.info(f"[WEB_SEARCH] HTTP {resp.status_code}: {error_body.decode()[:500]}")
                    raise RuntimeError(f"web_search API error {resp.status_code}: {error_body.decode()[:500]}")

                event_type = ""
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                        continue
                    if line.startswith("data:"):
                        data_str = line.split(":", 1)[1].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            all_events.append({"type": event_type, "data": data})
                            logger.info(f"[WEB_SEARCH] SSE event: {event_type} -> {data_str[:300]}")
                            if event_type == "error":
                                msg = data.get("message") or json.dumps(data)
                                logger.info(f"[WEB_SEARCH] server error event: {msg}")
                                raise RuntimeError(f"web_search server error: {msg}")
                            if event_type == "response.tool_result":
                                for item in data.get("content", []):
                                    if "json" in item:
                                        result = item["json"]
                                        if isinstance(result, dict) and "error" in result and result["error"].get("message"):
                                            err_msg = result["error"]["message"]
                                            logger.info(f"[WEB_SEARCH] search backend error: {err_msg}")
                                            raise RuntimeError(f"web_search is currently unavailable ({err_msg}). Do NOT retry web_search — answer from your own knowledge instead.")
                                        tool_result_json = result
                                        break
                                    if "text" in item:
                                        logger.info(f"[WEB_SEARCH] tool_result text item: {item['text'][:500]}")
                        except json.JSONDecodeError:
                            logger.info(f"[WEB_SEARCH] JSON decode error on: {data_str[:200]}")
                            continue

        if tool_result_json is None:
            logger.info(f"[WEB_SEARCH] no tool_result received for query={query[:80]}. Events seen: {[e['type'] for e in all_events]}")
            raise RuntimeError("web_search returned no results (no tool_result event received)")
        result_str = json.dumps(tool_result_json)
        logger.info(f"[WEB_SEARCH] success, result_len={len(result_str)}, content={result_str[:500]}")
        return result_str

    async def _execute_sql(self, tool_input: dict) -> str:
        sql = tool_input.get("sql", "")
        if not sql:
            return json.dumps({"error": "No SQL provided"})

        description = tool_input.get("description", "")
        only_compile = tool_input.get("only_compile", False)
        logger.info(f"[SQL] Executing: {description or sql[:100]}")

        if self.oauth_token:
            from ..snowflake_oauth import run_sql, SnowflakeSqlError
            try:
                data = await run_sql(
                    self.oauth_token, sql, role=self.role,
                    secondary_roles="none" if settings.sf_oauth_disable_secondary_roles else "default",
                    user_label=self.user_label, warehouse=self.warehouse,
                    database=self.database or None, schema=self.schema or None,
                )
            except (SnowflakeSqlError, PermissionError, ValueError) as exc:
                return json.dumps({"error": str(exc)})
            return self._format_sql_result(data)

        url = f"{self.base_url}/api/v2/statements"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.pat}",
            "Accept": "application/json",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
        }
        payload = {
            "statement": sql,
            "timeout": 120,
            "resultSetMetaData": {"format": "jsonv2"},
        }
        if self.warehouse:
            payload["warehouse"] = self.warehouse.upper()
        if self.role:
            payload["role"] = self.role.upper()
        if self.database:
            payload["database"] = self.database.upper()
        if self.schema:
            payload["schema"] = self.schema.upper()

        async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(180, connect=30)) as client:
            resp = await client.post(url, json=payload, headers=headers)
            logger.info(f"[SQL] Response: {resp.status_code}")

            if resp.status_code == 202:
                handle = resp.json().get("statementHandle", "")
                if handle:
                    for _ in range(30):
                        await __import__("asyncio").sleep(2)
                        check = await client.get(
                            f"{url}/{handle}",
                            headers=headers,
                        )
                        check_data = check.json()
                        if check_data.get("data") is not None or check_data.get("resultSetMetaData", {}).get("rowType"):
                            return self._format_sql_result(check_data)
                    return json.dumps({"error": "Query timed out waiting for results"})

            if resp.status_code not in (200,):
                try:
                    err_data = resp.json()
                    msg = err_data.get("message", resp.text[:500])
                except Exception:
                    msg = resp.text[:500]
                return json.dumps({"error": f"SQL error ({resp.status_code}): {msg}"})

            data = resp.json()
            return self._format_sql_result(data)

    def _format_sql_result(self, data: dict) -> str:
        meta = data.get("resultSetMetaData", {})
        columns = [col.get("name", "") for col in meta.get("rowType", [])]
        rows = data.get("data", [])

        if not rows:
            return f"Query returned 0 rows. Columns: {' | '.join(columns)}"

        max_rows = 100
        truncated = len(rows) > max_rows
        display_rows = rows[:max_rows]

        header = " | ".join(columns)
        sep = "-" * len(header)
        lines = [header, sep]
        for row in display_rows:
            lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))

        if truncated:
            lines.append(f"... ({len(rows)} total rows, showing first {max_rows})")

        result_str = "\n".join(lines)
        logger.info(f"[SQL] Result: {len(rows)} rows, {len(result_str)} bytes")
        return result_str
