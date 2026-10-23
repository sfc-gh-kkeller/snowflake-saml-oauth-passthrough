# app/: reference implementation

A fork of [nanocortex-web-agent](https://github.com/sfc-gh-kkeller/nanocortex-web-agent) (FastAPI + Preact, MIT),
extended with SAML login, a silent Entra OIDC hop, and per-user Snowflake External OAuth.

Files added or changed for the passthrough:

| File | Purpose |
|---|---|
| `backend/app/api/auth_saml.py` | SAML SP (AuthnRequest, ACS validation) → silent `prompt=none` OIDC → token store → SPA hand-off |
| `backend/app/services/snowflake_oauth.py` | Encrypted token store and refresh; SQL API calls with Bearer/OAUTH, role allowlist, optional secondary-role wrapper |
| `backend/app/api/role_test.py` | `/api/poc/role-check`: compares role context across REST, SQL API and SQL API without secondary roles |
| `backend/app/services/llm/cortex.py` | Cortex Agent client accepts the user's OAuth token; SQL tool runs as the user |
| `backend/app/core/config.py` | `[saml]`, `[entra]`, `[snowflake_oauth]` settings |
| `frontend/src/pages/RoleCheck.jsx`, `Login.jsx`, `main.jsx`, `lib/api.js` | SSO button, `/sso-complete` hand-off, Role Check page, two-session logout |

See the [top-level README](../README.md) for setup.
