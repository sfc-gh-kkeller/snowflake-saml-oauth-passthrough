"""
Configuration loaded from config/config.toml with env var overrides (AFE_ prefix).
Secrets are stored directly in the TOML file. Env vars take precedence for deployment flexibility.
"""
import os
import shutil
import tomllib
from pathlib import Path
from typing import Any

import tomli_w


# Locate config file relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.toml"

# Mapping from flat attribute name -> (toml_section, toml_key)
_FIELD_MAP: dict[str, tuple[str, str]] = {
    # [app]
    "app_name": ("app", "name"),
    "debug": ("app", "debug"),
    "dev_mode": ("app", "dev_mode"),
    "app_mode": ("app", "mode"),
    "app_title": ("app", "title"),
    "app_subtitle": ("app", "subtitle"),
    "app_logo_icon": ("app", "logo_icon"),
    "quick_questions": ("app", "quick_questions"),
    "seed_topics": ("app", "seed_topics"),
    "allowed_email_domain": ("app", "allowed_email_domain"),
    # [database]
    "database_backend": ("database", "backend"),
    "database_url": ("database", "url"),
    "database_url_sync": ("database", "url_sync"),
    "psql_path": ("database", "psql_path"),
    "pg_host": ("database", "host"),
    "pg_port": ("database", "port"),
    "pg_database": ("database", "name"),
    "pg_user": ("database", "user"),
    "pg_password": ("database", "password"),
    # [auth]
    "secret_key": ("auth", "secret_key"),
    "access_token_expire_minutes": ("auth", "access_token_expire_minutes"),
    "auth_mode": ("auth", "mode"),
    "auth_allow_registration": ("auth", "allow_registration"),
    # [snowflake]
    "snowflake_account": ("snowflake", "account"),
    "snowflake_user": ("snowflake", "user"),
    "snowflake_pat": ("snowflake", "pat"),
    "snowflake_warehouse": ("snowflake", "warehouse"),
    "snowflake_role": ("snowflake", "role"),
    "snowflake_database": ("snowflake", "database"),
    "snowflake_schema": ("snowflake", "schema"),
    # [agent]
    "agent_provider": ("agent", "provider"),
    "agent_model": ("agent", "model"),
    "agent_max_steps": ("agent", "max_steps"),
    "agent_thinking_effort": ("agent", "thinking_effort"),
    "agent_reflect": ("agent", "reflect"),
    "agent_max_reflect": ("agent", "max_reflect"),
    "agent_log_internal": ("agent", "log_internal"),
    "skill_path": ("agent", "skill_path"),
    "system_prefix": ("agent", "system_prompt"),
    # [openai]
    "openai_api_key": ("openai", "api_key"),
    "openai_base_url": ("openai", "base_url"),
    "openai_model": ("openai", "model"),
    # [anthropic]
    "anthropic_api_key": ("anthropic", "api_key"),
    "anthropic_model": ("anthropic", "model"),
    # [ollama]
    "ollama_base_url": ("ollama", "base_url"),
    "ollama_model": ("ollama", "model"),
    # [embeddings]
    "embedding_provider": ("embeddings", "provider"),
    "embedding_model": ("embeddings", "model"),
    "embedding_model_openai": ("embeddings", "model_openai"),
    "embedding_model_ollama": ("embeddings", "model_ollama"),
    "embedding_dimensions": ("embeddings", "dimensions"),
    "similarity_threshold": ("embeddings", "similarity_threshold"),
    # [assets]
    "asset_ttl_days": ("assets", "ttl_days"),
    # [files]
    "max_files_per_message": ("files", "max_per_message"),
    "max_file_size_mb": ("files", "max_size_mb"),
    "max_user_files": ("files", "max_user_files"),
    "allowed_file_types": ("files", "allowed_types"),
    "upload_dir": ("files", "upload_dir"),
    # [zettel]
    "zettel_provider": ("zettel", "provider"),
    "zettel_max_zettels": ("zettel", "max_zettels"),
    "zettel_persist_dir": ("zettel", "persist_dir"),
    "zettel_connection_threshold": ("zettel", "connection_threshold"),
    # [smtp]
    "smtp_host": ("smtp", "host"),
    "smtp_port": ("smtp", "port"),
    "smtp_user": ("smtp", "user"),
    "smtp_password": ("smtp", "password"),
    "smtp_from_email": ("smtp", "from_email"),
    "magic_link_expire_minutes": ("smtp", "magic_link_expire_minutes"),
    "magic_link_base_url": ("smtp", "magic_link_base_url"),
    # [oauth]
    "oauth_base_url": ("oauth", "base_url"),
    # [saml] - Entra SAML login (SP side)
    "saml_enabled": ("saml", "enabled"),
    "saml_idp_metadata_url": ("saml", "idp_metadata_url"),
    "saml_sp_entity_id": ("saml", "sp_entity_id"),
    # [entra] - confidential OIDC client used for the silent hop after SAML
    "entra_tenant_id": ("entra", "tenant_id"),
    "entra_client_id": ("entra", "client_id"),
    "entra_client_secret": ("entra", "client_secret"),
    "entra_snowflake_scope": ("entra", "snowflake_scope"),
    "entra_domain_hint": ("entra", "domain_hint"),
    # [snowflake_oauth] - per-user External OAuth calls
    "sf_oauth_enabled": ("snowflake_oauth", "enabled"),
    "sf_oauth_allowed_roles": ("snowflake_oauth", "allowed_roles"),
    "sf_oauth_default_role": ("snowflake_oauth", "default_role"),
    "sf_oauth_warehouse": ("snowflake_oauth", "warehouse"),
    "sf_oauth_disable_secondary_roles": ("snowflake_oauth", "disable_secondary_roles"),
    "token_encryption_key": ("snowflake_oauth", "token_encryption_key"),
    # [openai]
    "openai_api_key": ("openai", "api_key"),
    "openai_base_url": ("openai", "base_url"),
    "openai_model": ("openai", "model"),
    # [anthropic]
    "anthropic_api_key": ("anthropic", "api_key"),
    "anthropic_model": ("anthropic", "model"),
    # [ollama]
    "ollama_base_url": ("ollama", "base_url"),
    "ollama_model": ("ollama", "model"),
}

# Fields that are secrets (masked in API responses)
SECRET_FIELDS = {
    "secret_key", "snowflake_pat", "smtp_password", "pg_password",
    "openai_api_key", "anthropic_api_key",
    "entra_client_secret", "token_encryption_key",
}

# Type coercion for env var overrides
_FIELD_TYPES: dict[str, type] = {
    "debug": bool,
    "dev_mode": bool,
    "access_token_expire_minutes": int,
    "auth_allow_registration": bool,
    "agent_max_steps": int,
    "agent_reflect": bool,
    "agent_max_reflect": int,
    "agent_log_internal": bool,
    "embedding_dimensions": int,
    "similarity_threshold": float,
    "asset_ttl_days": int,
    "max_files_per_message": int,
    "max_file_size_mb": int,
    "max_user_files": int,
    "zettel_max_zettels": int,
    "zettel_connection_threshold": float,
    "pg_port": int,
    "smtp_port": int,
    "magic_link_expire_minutes": int,
    "saml_enabled": bool,
    "sf_oauth_enabled": bool,
    "sf_oauth_disable_secondary_roles": bool,
}

# Defaults (used when TOML key is missing)
_DEFAULTS: dict[str, Any] = {
    "app_name": "nanocortex-web-agent",
    "debug": False,
    "dev_mode": True,
    "app_mode": "chat",
    "app_title": "Acme Insurance",
    "app_subtitle": "Policy & Claims Knowledge Agent",
    "app_logo_icon": "🛡",
    "quick_questions": "What does my homeowners policy cover for water damage?,How do I file an auto claim after an accident?,Explain the difference between term and whole life insurance,What is a deductible and how does it affect my premium?,How does umbrella insurance work?,What's covered under a standard renters policy?",
    "seed_topics": "auto:liability collision comprehensive uninsured-motorist deductibles premiums;home:dwelling personal-property liability water-damage flood earthquake;life:term whole universal beneficiaries riders cash-value;health:HMO PPO deductible copay coinsurance out-of-pocket-max;claims:FNOL adjuster estimate subrogation settlement;underwriting:risk-assessment actuarial loss-history credit-score;billing:premium-payment grace-period lapse reinstatement;policy:declarations endorsements exclusions limits coverage;commercial:general-liability workers-comp BOP property cyber;regulatory:state-DOI compliance NAIC market-conduct",
    "allowed_email_domain": "",
    "database_backend": "postgres",
    "database_url": "postgresql+asyncpg://localhost:5433/nanocortex",
    "database_url_sync": "postgresql://localhost:5433/nanocortex",
    "psql_path": "",
    "pg_host": "localhost",
    "pg_port": 5433,
    "pg_database": "nanocortex",
    "pg_user": "",
    "pg_password": "",
    "secret_key": "change-me-in-production",
    "access_token_expire_minutes": 10080,
    "auth_mode": "password",
    "auth_allow_registration": True,
    "snowflake_account": "",
    "snowflake_user": "",
    "snowflake_pat": "",
    "snowflake_warehouse": "",
    "snowflake_role": "",
    "snowflake_database": "",
    "snowflake_schema": "",
    "agent_provider": "cortex",
    "agent_model": "auto",
    "agent_max_steps": 15,
    "agent_thinking_effort": "medium",
    "agent_reflect": True,
    "agent_max_reflect": 2,
    "agent_log_internal": True,
    "skill_path": "skills/knowledge_agent.md",
    "openai_api_key": "",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_model": "gpt-4o",
    "anthropic_api_key": "",
    "anthropic_model": "claude-sonnet-4-20250514",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "llama3.1",
    "embedding_provider": "snowflake",
    "embedding_model": "snowflake-arctic-embed-l-v2.0",
    "embedding_model_openai": "text-embedding-3-small",
    "embedding_model_ollama": "nomic-embed-text",
    "embedding_dimensions": 1024,
    "similarity_threshold": 0.70,
    "asset_ttl_days": 30,
    "max_files_per_message": 10,
    "max_file_size_mb": 5,
    "max_user_files": 10,
    "allowed_file_types": "image/png,image/jpeg,image/gif,image/webp,application/pdf",
    "upload_dir": "uploads",
    "zettel_provider": "snowflake",
    "zettel_max_zettels": 2000,
    "zettel_persist_dir": "data/zettel",
    "zettel_connection_threshold": 0.25,
    "system_prefix": "",
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from_email": "",
    "magic_link_expire_minutes": 180,
    "magic_link_base_url": "http://localhost:9000",
    "oauth_base_url": "http://localhost:9000",
    "saml_enabled": False,
    "saml_idp_metadata_url": "",
    "saml_sp_entity_id": "",
    "entra_tenant_id": "",
    "entra_client_id": "",
    "entra_client_secret": "",
    "entra_snowflake_scope": "",
    "entra_domain_hint": "",
    "sf_oauth_enabled": False,
    "sf_oauth_allowed_roles": "",
    "sf_oauth_default_role": "",
    "sf_oauth_warehouse": "",
    "sf_oauth_disable_secondary_roles": True,
    "token_encryption_key": "",
    "openai_api_key": "",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_model": "gpt-4o",
    "anthropic_api_key": "",
    "anthropic_model": "claude-sonnet-4-20250514",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "llama3.1",
}


def _coerce(value: Any, target_type: type) -> Any:
    """Coerce a string env var value to the target type."""
    if target_type == bool:
        return str(value).lower() in ("true", "1", "yes")
    return target_type(value)


class Settings:
    """Config loaded from TOML with env var overrides."""

    def __init__(self, config_path: Path = _CONFIG_PATH):
        self._config_path = config_path
        self._toml_data: dict[str, Any] = {}
        self._load()

    def _load(self):
        """Load TOML file and resolve all settings."""
        if self._config_path.exists():
            with open(self._config_path, "rb") as f:
                self._toml_data = tomllib.load(f)
        else:
            self._toml_data = {}

        # Resolve each field: env var > toml > default
        for attr_name, (section, key) in _FIELD_MAP.items():
            env_key = f"AFE_{attr_name.upper()}"
            env_val = os.environ.get(env_key)

            if env_val is not None:
                # Env var override
                target_type = _FIELD_TYPES.get(attr_name, str)
                value = _coerce(env_val, target_type)
            else:
                # TOML value
                section_data = self._toml_data.get(section, {})
                value = section_data.get(key, _DEFAULTS.get(attr_name))

            setattr(self, attr_name, value)

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Return all settings grouped by section (for admin API)."""
        sections: dict[str, dict[str, Any]] = {}
        for attr_name, (section, key) in _FIELD_MAP.items():
            if section not in sections:
                sections[section] = {}
            sections[section][key] = getattr(self, attr_name, _DEFAULTS.get(attr_name))
        return sections

    def get_schema(self) -> list[dict]:
        """Return field metadata for the admin UI."""
        schema = []
        for attr_name, (section, key) in _FIELD_MAP.items():
            target_type = _FIELD_TYPES.get(attr_name, str)
            schema.append({
                "key": attr_name,
                "section": section,
                "toml_key": key,
                "type": target_type.__name__,
                "secret": attr_name in SECRET_FIELDS,
                "default": _DEFAULTS.get(attr_name),
                "value": getattr(self, attr_name, _DEFAULTS.get(attr_name)),
            })
        return schema

    def update(self, changes: dict[str, Any]):
        """Update settings in memory and persist to TOML file."""
        for attr_name, value in changes.items():
            if attr_name not in _FIELD_MAP:
                continue
            target_type = _FIELD_TYPES.get(attr_name, str)
            if not isinstance(value, target_type):
                value = _coerce(value, target_type)
            setattr(self, attr_name, value)

            # Update TOML data structure
            section, key = _FIELD_MAP[attr_name]
            if section not in self._toml_data:
                self._toml_data[section] = {}
            self._toml_data[section][key] = value

        self._save()

    def _save(self):
        """Write current TOML data to disk."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "wb") as f:
            tomli_w.dump(self._toml_data, f)

    def get_psql_path(self) -> str:
        """Resolve the psql binary.

        Order:
          1. shutil.which('psql') on PATH (works inside `pixi run` shells)
          2. settings.psql_path override (set in [database].psql_path or AFE_PSQL_PATH env)
        Raises FileNotFoundError if neither is available.
        """
        found = shutil.which("psql")
        if found:
            return found
        configured = (self.psql_path or "").strip()
        if configured:
            if Path(configured).exists():
                return configured
            raise FileNotFoundError(
                f"Configured psql_path does not exist: {configured}"
            )
        raise FileNotFoundError(
            "psql not found on PATH. Install postgresql client or set "
            "[database].psql_path in config/config.toml (or AFE_PSQL_PATH env)."
        )

    def is_smtp_configured(self) -> bool:
        """True if SMTP is fully configured for sending magic links."""
        return bool(
            self.smtp_host and self.smtp_user
            and self.smtp_password and self.smtp_from_email
        )


settings = Settings()
