from pathlib import Path
from typing import Optional

from ..core.config import settings


SKILLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "skills"
COMPANIONS_DIR = SKILLS_DIR


def _discover_available_skills() -> set[str]:
    """Auto-discover skills from the companions directory.
    A skill is either a top-level .md file or a directory containing SKILL.md."""
    if not COMPANIONS_DIR.exists():
        return set()
    skills = set()
    for f in COMPANIONS_DIR.iterdir():
        if f.name.startswith("."):
            continue
        if f.is_file() and f.suffix == ".md":
            skills.add(f.stem)
        elif f.is_dir() and (f / "SKILL.md").exists():
            # Directory-based skill (has entry point SKILL.md inside)
            skills.add(f.name)
    return skills


# Auto-discovered from disk (refreshed via refresh_skills())
AVAILABLE_SKILLS = _discover_available_skills()


def refresh_skills():
    """Re-scan the companions directory and clear all caches.
    Call this after uploading/removing skill files or changing config at runtime."""
    global AVAILABLE_SKILLS
    AVAILABLE_SKILLS = _discover_available_skills()
    skill_loader._skill_cache.clear()

SKILL_KEYWORDS: dict[str, list[str]] = {
    "trust-center": [
        "trust center", "trust_center", "scanner", "findings", "security posture",
        "cis benchmark", "security essentials", "threat intelligence",
    ],
    "data-governance": [
        "masking policy", "row access", "classification", "governance",
        "tag-based", "sensitive data", "pii", "data policy", "horizon",
        "object tagging", "projection policy",
    ],
    "cost-intelligence": [
        "cost", "budget", "credit", "spending", "warehouse cost",
        "compute cost", "serverless cost", "resource monitor", "metering",
    ],
    "organization-management": [
        "organization", "orgadmin", "globalorgadmin", "org hub",
        "account list", "account inventory", "org security",
    ],
    "integrations": [
        "security integration", "external access", "storage integration",
        "api integration", "notification integration", "catalog integration",
    ],
    "cortex-agent": [
        "cortex agent", "snowflake intelligence", "create agent",
        "debug agent", "evaluate agent",
    ],
    "lineage": [
        "lineage", "column lineage", "data lineage", "dependency",
        "impact analysis", "upstream", "downstream",
    ],
    "data-quality": [
        "data quality", "data metric", "dmf", "quality score",
        "freshness", "completeness", "null rate",
    ],
    "security-ops": [
        "iam", "sso setup", "saml", "okta sso", "entra sso",
        "authorization", "authz", "tri-secret", "key management",
        "brute force", "login failure", "threat detection",
    ],
    "semantic-view": [
        "semantic view", "semantic model", "semantic layer",
    ],
    "network-security": [
        "network policy", "network rule", "privatelink", "private link",
        "ip whitelist", "allowed ip", "blocked ip",
    ],
    "dynamic-tables": [
        "dynamic table", "dynamic tables", "incremental refresh", "target lag",
    ],
    "iceberg": [
        "iceberg", "iceberg table", "apache iceberg", "external volume",
    ],
    "snowpark": [
        "snowpark", "snowpark python", "stored procedure python", "udf python",
    ],
    "alert": [
        "alert", "snowflake alert", "create alert", "alert condition",
    ],
    "warehouse": [
        "warehouse", "warehouse size", "auto suspend", "scaling policy",
        "multi-cluster", "warehouse utilization",
    ],
    "billing": [
        "billing", "invoice", "usage report", "account usage",
    ],
    "cortex-secrets": [
        "secret", "create secret", "external access secret",
    ],
    "data-cleanrooms": [
        "clean room", "cleanroom", "data clean room",
    ],
    "machine-learning": [
        "ml", "machine learning", "snowpark ml", "model registry", "feature store",
    ],
    "event-table": [
        "event table", "telemetry", "logging event",
    ],
    "snowpipe-streaming": [
        "snowpipe", "streaming", "snowpipe streaming", "ingest",
    ],
    "setup-snowflake-sso": [
        "sso", "single sign-on", "saml setup", "okta setup", "entra setup", "azure ad",
    ],
    "access-troubleshooter": [
        "access denied", "permission denied", "insufficient privileges", "grant",
        "cannot access", "no permission",
    ],
    "sql-author": [
        "write sql", "sql query", "generate sql", "sql help",
    ],
}

MAX_COMPANION_SIZE = 300_000


def _load_db_setting(key: str) -> Optional[str]:
    """Load a setting from app_settings table via psql subprocess."""
    import subprocess
    from ..core.config import settings
    try:
        psql = settings.get_psql_path()
    except FileNotFoundError:
        return None
    try:
        result = subprocess.run(
            [psql, "-h", "/tmp", "-p", "5433", "-d", "nanocortex",
             "-t", "-A", "-c", f"SELECT value FROM app_settings WHERE key = '{key}'"],
            capture_output=True, text=True, timeout=3
        )
        val = result.stdout.strip()
        return val if val else None
    except Exception:
        return None


class SkillLoader:
    def __init__(self):
        self._skill_cache: dict[str, str] = {}

    def _strip_frontmatter(self, raw: str) -> str:
        lines = raw.split("\n")
        in_frontmatter = False
        start_idx = 0
        for i, line in enumerate(lines):
            if line.strip() == "---" and i == 0:
                in_frontmatter = True
                continue
            if in_frontmatter and line.strip() == "---":
                start_idx = i + 1
                break
        return "\n".join(lines[start_idx:]).strip()

    def _get_disabled_skills(self) -> set:
        val = _load_db_setting("disabled_skills")
        if val:
            return set(v.strip() for v in val.split(",") if v.strip())
        return set()

    def _get_mandatory_skills(self) -> set:
        """Return set of skill names that should always be loaded."""
        val = _load_db_setting("mandatory_skills")
        if val is not None:
            return set(v.strip() for v in val.split(",") if v.strip())
        return set()

    def _get_custom_keywords(self) -> dict:
        val = _load_db_setting("skill_keywords")
        if val:
            import json
            try:
                return json.loads(val)
            except:
                pass
        return {}

    def _get_system_prefix(self) -> str:
        val = _load_db_setting("system_prefix")
        if val is not None:
            return val
        return settings.system_prefix

    def load_skill(self, name: str) -> str:
        """Load a skill by name. Supports both top-level skills (e.g., 'trust-center')
        and sub-skills (e.g., 'trust-center/findings-analysis')."""
        # Handle sub-skill paths like "trust-center/findings-analysis"
        parts = name.split("/", 1)
        base_name = parts[0]

        if base_name not in AVAILABLE_SKILLS:
            return f"Unknown skill: {base_name}. Available: {', '.join(sorted(AVAILABLE_SKILLS))}"

        if len(parts) == 2:
            # Sub-skill: load from subfolder
            sub_path = parts[1]
            sub_file = COMPANIONS_DIR / base_name / sub_path / "SKILL.md"
            if not sub_file.exists():
                # Try as direct .md file
                sub_file = COMPANIONS_DIR / base_name / f"{sub_path}.md"
            if not sub_file.exists():
                return f"Sub-skill not found: {name}"
            raw = sub_file.read_text(encoding="utf-8")
            return self._strip_frontmatter(raw)

        # Top-level skill
        cache_key = name
        if cache_key in self._skill_cache:
            return self._skill_cache[cache_key]

        # Resolve skill file: prefer name.md, fall back to name/SKILL.md
        skill_file = COMPANIONS_DIR / f"{name}.md"
        if not skill_file.exists():
            skill_file = COMPANIONS_DIR / name / "SKILL.md"
        if not skill_file.exists():
            return f"Skill file not found: {name}"

        raw = skill_file.read_text(encoding="utf-8")
        content = self._strip_frontmatter(raw)

        # List available sub-skills if the skill has a subfolder
        skill_subdir = COMPANIONS_DIR / name
        if skill_subdir.is_dir():
            sub_skills = []
            for item in sorted(skill_subdir.iterdir()):
                if item.is_dir() and (item / "SKILL.md").exists():
                    sub_skills.append(f"{name}/{item.name}")
                elif item.suffix == ".md" and not item.name.startswith("."):
                    sub_skills.append(f"{name}/{item.stem}")
            if sub_skills:
                content += (
                    f"\n\n### Available Sub-Skills\n\n"
                    f"This skill has sub-skills you can load for deeper detail:\n"
                    + "\n".join(f"- `{s}`" for s in sub_skills) + "\n\n"
                    f"To load a sub-skill, use: `<!-- LOAD_SKILL: {name}/sub-skill-name -->`\n"
                )

        self._skill_cache[cache_key] = content
        return content

    def detect_skill(self, question: str) -> Optional[str]:
        q_lower = question.lower()
        disabled = self._get_disabled_skills()
        custom_keywords = self._get_custom_keywords()

        scores: dict[str, int] = {}
        for skill_name, default_keywords in SKILL_KEYWORDS.items():
            if skill_name in disabled:
                continue
            keywords = custom_keywords.get(skill_name, default_keywords)
            score = sum(1 for kw in keywords if kw in q_lower)
            if score > 0:
                scores[skill_name] = score
        if not scores:
            return None
        return max(scores, key=scores.get)

    def list_skills(self) -> list[dict]:
        return [{"name": s} for s in sorted(AVAILABLE_SKILLS)]

    def build_system_prompt(self, extra_context: str = "", question: str = "") -> tuple[str, dict]:
        """Build the full system prompt and return (prompt_text, skills_info)."""
        parts = []
        mandatory = self._get_mandatory_skills()
        disabled = self._get_disabled_skills()
        skills_info = {
            "mandatory_skills": [],
            "detected_skill": None,
        }

        # System prompt from config FIRST (admin-editable)
        system_prefix = self._get_system_prefix()
        if system_prefix:
            parts.append(system_prefix)

        # Load mandatory skills
        for name in sorted(mandatory):
            if name in AVAILABLE_SKILLS and name not in disabled:
                content = self.load_skill(name)
                if content and not content.startswith("Unknown skill") and not content.startswith("Skill file not found"):
                    parts.append(
                        f"## Mandatory Skill: {name}\n\n" + content
                    )
                    skills_info["mandatory_skills"].append(name)

        # Keyword-detected skill (only if not already loaded as mandatory)
        if question:
            detected = self.detect_skill(question)
            if detected and detected not in mandatory:
                companion_content = self.load_skill(detected)
                if companion_content and len(companion_content) <= MAX_COMPANION_SIZE:
                    parts.append(
                        f"## Loaded Skill: {detected}\n\n"
                        "The following skill was loaded based on the user's question. "
                        "Use these SQL patterns and instructions to query the user's "
                        "Snowflake account directly via snowflake_sql_execute.\n\n"
                        + companion_content
                    )
                    skills_info["detected_skill"] = detected
                elif companion_content:
                    parts.append(
                        f"## Skill Available: {detected}\n\n"
                        f"The {detected} skill has detailed SQL patterns but is too large to include. "
                        "Use your knowledge and snowflake_sql_execute "
                        "to query the account directly."
                    )
                    skills_info["detected_skill"] = detected

        if extra_context:
            parts.append(extra_context)

        # Always append available skills list for dynamic loading
        parts.append(
            "## Available Skills for Dynamic Loading\n\n"
            "Load a skill with `<!-- LOAD_SKILL: skill-name -->` in your response. "
            "Sub-skills: `<!-- LOAD_SKILL: skill-name/sub-skill -->`\n\n"
            "Available: " + ", ".join(f"`{s}`" for s in sorted(AVAILABLE_SKILLS))
        )

        return "\n\n".join(parts), skills_info


skill_loader = SkillLoader()
