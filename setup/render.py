"""Render setup/snowflake_setup.sql and app/config/config.toml from setup/entra.env.

Usage (from repo root):
  pixi run --manifest-path app/pixi.toml python setup/render.py \
      --sf-account ORG-ACCOUNT --sf-user SNOWFLAKE_USER_NAME [--mode scoped|role-any] [--no-agent-identity]

--sf-user is the Snowflake user NAME that gets the demo roles; its LOGIN_NAME must equal the Entra UPN.
--mode picks which token the app requests (default: scoped, the recommended design).
--no-agent-identity renders IS_AGENTIC = FALSE on the integrations (default TRUE: sessions
are agent-activated, so agent-aware masking/row policies apply).
"""
import argparse
import secrets
import tomllib
from pathlib import Path

import tomli_w
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "setup"
APP_CFG = ROOT / "app" / "config"


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sf-account", required=True)
    p.add_argument("--sf-user", required=True)
    p.add_argument("--mode", choices=["scoped", "role-any"], default="scoped")
    p.add_argument("--no-agent-identity", action="store_true")
    a = p.parse_args()

    env = load_env(SETUP / "entra.env")
    secret = (SETUP / ".entra_secret").read_text().strip()
    roles = [r.strip() for r in env["ROLES"].split(",") if r.strip()]

    sql = (SETUP / "snowflake_setup.sql.tmpl").read_text()
    for k, v in {"TENANT_ID": env["TENANT_ID"], "RES_V2_APP_ID": env["RES_V2_APP_ID"],
                 "RES_V1_APP_ID": env.get("RES_V1_APP_ID", ""), "SF_LOGIN_USER": a.sf_user,
                 "IS_AGENTIC": "FALSE" if a.no_agent_identity else "TRUE"}.items():
        sql = sql.replace("{{" + k + "}}", v)
    (SETUP / "snowflake_setup.sql").write_text(sql)

    if a.mode == "scoped":
        scope = " ".join(f"api://{env['RES_V2_APP_ID']}/session:role:{r}" for r in roles)
    else:
        if not env.get("RES_V1_APP_ID"):
            raise SystemExit("role-any mode needs RES_V1_APP_ID (run entra_setup.sh with ENABLE_ROLE_ANY=1)")
        scope = f"api://{env['RES_V1_APP_ID']}/session:role-any"

    cfg_path = APP_CFG / "config.toml"
    cfg = tomllib.loads(cfg_path.read_text()) if cfg_path.exists() else tomllib.loads((APP_CFG / "config.toml.sample").read_text())
    cfg.setdefault("app", {}).update({"title": "SSO Passthrough", "subtitle": "SAML + Entra OAuth → Snowflake", "dev_mode": True})
    cfg.setdefault("auth", {})
    if cfg["auth"].get("secret_key", "change-me-in-production") == "change-me-in-production":
        cfg["auth"]["secret_key"] = secrets.token_hex(32)
    cfg["auth"]["allow_registration"] = False
    cfg["database"] = {**cfg.get("database", {}), "backend": "postgres",
                       "url": "postgresql+asyncpg://localhost:5432/nanocortex",
                       "url_sync": "postgresql://localhost:5432/nanocortex"}
    cfg["snowflake"] = {**cfg.get("snowflake", {}), "account": a.sf_account, "warehouse": "SSO_DEMO_WH",
                        "role": roles[0], "database": "SSO_DEMO_DB", "schema": "APP"}
    cfg["oauth"] = {"base_url": "http://localhost:9000"}
    cfg["saml"] = {"enabled": True, "idp_metadata_url": env["SAML_METADATA_URL"], "sp_entity_id": f"api://{env['WEB_APP_ID']}"}
    cfg["entra"] = {"tenant_id": env["TENANT_ID"], "client_id": env["WEB_APP_ID"], "client_secret": secret,
                    "snowflake_scope": scope, "domain_hint": env.get("DOMAIN_HINT", "")}
    so = cfg.get("snowflake_oauth", {})
    cfg["snowflake_oauth"] = {
        "enabled": True, "allowed_roles": ",".join(roles), "default_role": roles[0], "warehouse": "SSO_DEMO_WH",
        "disable_secondary_roles": a.mode == "role-any",
        "agent_identity": not a.no_agent_identity,
        "token_encryption_key": so.get("token_encryption_key") or Fernet.generate_key().decode(),
    }
    cfg_path.write_text(tomli_w.dumps(cfg))
    cfg_path.chmod(0o600)
    print(f"wrote {SETUP / 'snowflake_setup.sql'} and {cfg_path} (mode={a.mode}, agent_identity={not a.no_agent_identity})")


if __name__ == "__main__":
    main()
