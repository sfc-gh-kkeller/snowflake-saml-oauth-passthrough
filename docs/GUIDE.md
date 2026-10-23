# Design Guide: SAML Web App → Snowflake as the Signed-In User (Entra ID)

**Audience:** application architects, identity (Entra ID) teams, Snowflake platform teams.
**Status:** every claim marked *verified* was tested against a real Entra tenant and Snowflake account with the code in this repo.

- **Recommended design:** §0, a dedicated v2 resource app with role-scoped tokens.
- **Fallback:** §4–§7, for when only `session:role-any` is possible.

---

## Contents

0. [Recommended design](#0-recommended-design)
1. [Problem statement](#1-problem-statement)
2. [Solution overview](#2-solution-overview)
3. [Identity flow: silent OIDC hop chained to the SAML login](#3-identity-flow-silent-oidc-hop-chained-to-the-saml-login)
4. [Token handling](#4-token-handling)
5. [Snowflake integration](#5-snowflake-integration)
6. [Per-request role control (role-any fallback)](#6-per-request-role-control-role-any-fallback)
7. [Backstops](#7-backstops)
8. [Alternatives](#8-alternatives)
9. [Validation checklist](#9-validation-checklist)
10. [Summary](#10-summary)

---

## 0. Recommended design

Three constraints are commonly assumed. All three are softer than they look:

| Assumed constraint | What actually happens (verified) |
|---|---|
| Only one External OAuth integration per Entra tenant | Snowflake keys integrations on the **issuer string**. Entra v1 tokens (`https://sts.windows.net/<tid>/`) and v2 tokens (`https://login.microsoftonline.com/<tid>/v2.0`) have different issuers, so a **second integration** is accepted. A same-issuer duplicate is rejected with error 003524. |
| Per-role scopes can't be used, because the central Snowflake app registration is owned by someone else | Leave the central registration alone. A **dedicated resource app** for your application, admin-consented once, can define its own `session:role:<ROLE>` scopes. |
| You need `role-any` plus after-the-fact restriction | A token scoped to app roles makes **Snowflake itself** disable secondary roles and reject every other role, on all surfaces (REST, SQL API, Cortex Agent). |

**Architecture**

1. Keep any existing central Snowflake app registration (v1 tokens) and its integration for BI tools. Nothing changes for them.
2. Create a **dedicated resource app** with `requestedAccessTokenVersion = 2` and scopes `session:role:APP_ANALYST` and `session:role:APP_READER`.
3. Admin-consent the web app to **only those role scopes**.
   - Entra puts **every consented scope** for a resource into the token, whatever the request asks for. The consent grant therefore *is* the role allowlist.
   - Never consent `session:role-any` on this resource.
4. Create a second Snowflake integration for the v2 issuer, with its own allowlist:

   ```sql
   CREATE SECURITY INTEGRATION ENTRA_SSO_SCOPED_V2
     TYPE = EXTERNAL_OAUTH  ENABLED = TRUE  EXTERNAL_OAUTH_TYPE = AZURE
     EXTERNAL_OAUTH_ISSUER = 'https://login.microsoftonline.com/<tid>/v2.0'
     EXTERNAL_OAUTH_JWS_KEYS_URL = 'https://login.microsoftonline.com/<tid>/discovery/v2.0/keys'
     EXTERNAL_OAUTH_AUDIENCE_LIST = ('<resource app client id GUID>')   -- v2 aud = GUID, not api://
     EXTERNAL_OAUTH_TOKEN_USER_MAPPING_CLAIM = 'preferred_username'     -- v2 tokens have no upn claim
     EXTERNAL_OAUTH_SNOWFLAKE_USER_MAPPING_ATTRIBUTE = 'LOGIN_NAME'
     EXTERNAL_OAUTH_ANY_ROLE_MODE = 'ENABLE'
     EXTERNAL_OAUTH_ALLOWED_ROLES_LIST = ('APP_ANALYST', 'APP_READER');
   ```

5. Keep the login flow from §3.
   - On the SQL API, the backend sets the role in the `role` body field of every request.
   - On REST and MCP, it sets the `X-Snowflake-Role` header.
   - It chooses from the scoped roles.

**Verified results with a two-role scoped token** (the test user holds ~40 roles, including ACCOUNTADMIN):

| Request | Result |
|---|---|
| SQL API `role: APP_ANALYST` / `APP_READER` | Runs; `CURRENT_SECONDARY_ROLES()` = `""`; restricted schema denied |
| REST API `X-Snowflake-Role` | Same; the restricted schema isn't even visible |
| Cortex Agent `agent:run` + SQL tool | Runs as `APP_ANALYST` with no secondary roles; restricted table denied |
| Any other role, even one in the integration allowlist | Rejected (390317) |
| No role given | Rejected: falls back to `DEFAULT_ROLE`, which isn't scoped. Always send the role |
| `USE SECONDARY ROLES ...` | Refused on a scoped token (error 3107), so the app can't widen it |

**What this gains you:**
- a per-app boundary enforced by Snowflake;
- a leaked token is limited to the scoped low-privilege roles;
- no session policy, so users' Snowsight and driver sessions are unaffected;
- no SQL rewriting, so bind variables work normally.

### Balancing flexibility and security: broad in Entra, narrow in Snowflake

Entra scopes are slow to change in most organisations; Snowflake configuration isn't. So put the **superset** in the token and do the **after-the-fact restriction** in Snowflake:

| Layer | Owner | Change frequency | Holds |
|---|---|---|---|
| Entra role scopes (consent grant) | Identity team | Rarely, ideally once | Every app role you can foresee, **including roles that don't exist in Snowflake yet** |
| `EXTERNAL_OAUTH_ALLOWED_ROLES_LIST` on the dedicated integration | Snowflake team | Any time, one `ALTER` | The roles actually allowed today |
| Grants to the app roles | Snowflake team | Any time | What each role can do. Most changes land here, with no Entra change |
| Backend role selection | App team | Per request | One role from the allowed set, sent explicitly |

**Verified** with a token scoped to `APP_READER`, `APP_ANALYST` and `APP_FUTURE`. The same token was used throughout and never re-issued:

| Step | Snowflake state | Request `APP_FUTURE` | Existing roles |
|---|---|---|---|
| 1 | Role doesn't exist | rejected | work normally; the unknown scope is harmless |
| 2 | Role created and granted to the user | still rejected (not allowlisted) | work |
| 3 | Role added to the allowlist | **runs**, no secondary roles | work |
| – | `APP_ANALYST` removed from the allowlist, still in the token | `APP_ANALYST` **rejected** | `APP_READER` works |

So roles can be **enabled and revoked entirely on the Snowflake side**, with no change in Entra.

**Why a list of role scopes beats `role-any`:** you keep the same Snowflake-side flexibility, and in addition:
- Snowflake disables secondary roles itself, so there's no wrapper and no session policy;
- the token stays capped at the scoped list, even if the Snowflake allowlist is widened by mistake.

Use `role-any` (§4–§7) only if even a one-time consent of a role superset isn't possible.

**Limits:** the v1/v2 split gives **two** integrations per tenant. If both are taken, use a Snowflake OAuth custom client (§8). The split relies on documented Entra token behaviour. Snowflake's issuer-keyed uniqueness, however, isn't formally documented, so confirm it with Snowflake before relying on it in production.

---

## 1. Problem statement

The web application authenticates users with **SAML 2.0 against Microsoft Entra ID**, and that can't change. The application now needs to call Snowflake **as the signed-in user**, for per-user identity, RBAC and audit.

Constraints:

- A SAML assertion **can't be exchanged** for an OAuth access token in Entra ID, and the app has no reusable session token or PRT.
- Per-role OAuth scopes may not be available on the shared Snowflake app registration. The token then carries `session:role-any`.
- Snowflake accepts **one External OAuth integration per issuer**, so a role allowlist on it applies to every Entra client using that issuer (BI tools, this app, ...).

The goal: obtain a per-user Snowflake token with no noticeable UX cost, and restrict which roles the app can actually use.

---

## 2. Solution overview

```
Browser ──SAML──► Entra ID ──assertion──► App ACS (backend)
                                             │ 302 (prompt=none, login_hint=<upn>)
                                             ▼
                                         Entra /authorize  (silent, existing session)
                                             │ auth code
                                             ▼
                                   App backend (confidential client)
                                   └─ code → access + refresh token for the Snowflake
                                      resource (stored server-side, encrypted)
                                             │
                                             ▼
                          Snowflake REST / SQL API / Cortex Agent
                          Bearer <user token>, role = <APP_ROLE>
                          recommended: role-scoped token → Snowflake drops secondaries
                          fallback:    role-any + USE SECONDARY ROLES NONE / session policy
```

---

## 3. Identity flow: silent OIDC hop chained to the SAML login

### Placement

Chain the OIDC step **directly onto the SAML Assertion Consumer Service (ACS)**:

1. The ACS validates the SAML assertion and creates the app session.
2. The ACS immediately sends the browser to Entra's `/authorize` endpoint with:
   - `prompt=none`;
   - `login_hint=<UPN from the SAML assertion>`;
   - `domain_hint=<tenant domain>`;
   - PKCE.

   The ACS receives a cross-site POST, so a tiny auto-submitting / meta-refresh page is more robust than a bare 302 with `SameSite` cookies.
3. The OIDC callback exchanges the code as a confidential client, stores the tokens server-side, and redirects to the user's original deep link.

The user perceives **one slightly longer login** (about a second extra) instead of a separate interruption later. No app state is lost, because the app hasn't rendered yet.

### Why server-side (confidential client)

- The backend holds a refresh token, so there are **no further redirects** for the rest of the session.
- A pure SPA is worse: SPA refresh tokens have a **24-hour lifetime**, after which MSAL falls back to the browser session again.

### Use a redirect, not a hidden iframe

Hidden-iframe silent auth fails on Safari, Firefox, iOS, private browsing and locked-down enterprise browsers, because they block third-party cookies. Use a top-level redirect.

### If the OIDC step must be triggered lazily (on the first Snowflake action)

- A full navigation loses SPA state, so persist the route and any unsaved input in session storage and restore them on return.
- Show an interstitial ("Connecting to your data…") so the hop doesn't look like a glitch.

### Failure paths (where UX design effort belongs)

When `prompt=none` returns `login_required` or `interaction_required`, the user sees real Entra UI: MFA, the account picker, or a consent screen.

| Mitigation | Effect |
|---|---|
| **Admin-consent** the app up front | Users never see a consent screen |
| Pass `login_hint` and `domain_hint` | Avoids the account picker |
| Handle Conditional Access sign-in frequency gracefully | Re-auth happens at a natural breakpoint, not mid-form |

### Smaller details

- **SAML NameID:** for non-gallery Entra apps, the default NameID is an opaque persistent ID, not the UPN.
  - Read the UPN from the `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name` attribute, or set NameID to `user.userprincipalname`.
  - Otherwise `login_hint` is wrong and the silent hop fails (`AADSTS50058`). *Verified.*
- **Bind the two identities:** check that the OIDC `id_token` `preferred_username` equals the SAML UPN before storing the Snowflake token.
- Use `location.replace()` or a server redirect, so the Entra hop doesn't enter browser history and the back button keeps working.
- If the app is ever embedded in an iframe (Teams, SharePoint, a portal), top-level redirects aren't allowed. You need a popup triggered by a user click.
- **Logout now spans two sessions** (SAML and OIDC). Clear the stored tokens on logout, and decide whether to also call the Entra logout endpoint.
- Each hop appears as a separate sign-in event in the Entra logs. That's harmless, but tell the identity team.

---

## 4. Token handling

- The backend obtains a token for the **Snowflake resource application** in one of two ways:
  - **recommended:** role scopes `api://<res>/session:role:<ROLE>`;
  - **fallback:** `api://<res>/session:role-any`.

  Use the authorization-code flow directly, or On-Behalf-Of.
- Tokens stay **server-side only**, are encrypted at rest, are refreshed by the backend, and are **never sent to the browser**.
- The same pattern works with other IdPs (e.g. Okta) on their own integration; the backend logic is IdP-agnostic.

---

## 5. Snowflake integration

The role-any fallback on the v1 issuer:

```sql
CREATE SECURITY INTEGRATION ENTRA_SSO_ROLE_ANY_V1
  TYPE = EXTERNAL_OAUTH
  ENABLED = TRUE
  EXTERNAL_OAUTH_TYPE = AZURE
  EXTERNAL_OAUTH_ISSUER = 'https://sts.windows.net/<tenant_id>/'
  EXTERNAL_OAUTH_JWS_KEYS_URL = 'https://login.microsoftonline.com/<tenant_id>/discovery/v2.0/keys'
  EXTERNAL_OAUTH_AUDIENCE_LIST = ('api://<snowflake_resource_app_id>')
  EXTERNAL_OAUTH_TOKEN_USER_MAPPING_CLAIM = 'upn'
  EXTERNAL_OAUTH_SNOWFLAKE_USER_MAPPING_ATTRIBUTE = 'LOGIN_NAME'   -- case-sensitive match
  EXTERNAL_OAUTH_ANY_ROLE_MODE = 'ENABLE'
  EXTERNAL_OAUTH_ALLOWED_ROLES_LIST = ('APP_ANALYST', 'APP_READER', ...)  -- union of all clients on this issuer
  -- ACCOUNTADMIN, ORGADMIN, SECURITYADMIN are blocked by default
;
```

- `EXTERNAL_OAUTH_ALLOWED_ROLES_LIST` is the **hard cap on the primary role**: no header or request can select a primary role outside it.
- **It doesn't limit secondary roles** (*verified*). With `role-any`, every role granted to the user, including ACCOUNTADMIN, stays active as a secondary role unless it's closed per request (§6) or by a session policy (§7). This is shown in `docs/images/02-rolecheck-role-any-leak.png`.
- **The user's `DEFAULT_ROLE` must also be allowed** if you use multi-statement SQL API requests (see §6).
- When the allowlist is shared by every client on the issuer, it's a coarse boundary, not a per-app one. That's the reason for §0.
- Optional: `EXTERNAL_OAUTH_ANY_ROLE_MODE = 'ENABLE_FOR_PRIVILEGE'` limits role switching to users who hold `USE_ANY_ROLE`.

---

## 6. Per-request role control (role-any fallback)

> **Key point:** with `session:role-any`, selecting a primary role does **not** isolate anything by itself. All of the user's other roles stay active as **secondary roles** unless explicitly closed.

### Primary role

| Surface | How |
|---|---|
| Snowflake REST APIs / MCP / Cortex Agent | `X-Snowflake-Role` header (takes precedence over `DEFAULT_ROLE`) |
| SQL API (`/api/v2/statements`) | `role` field in the request body |
| Drivers | `role=` connection parameter |

The REST resource APIs expose only `X-Snowflake-Role` and `X-Snowflake-Warehouse`; there is **no header for secondary roles**.

> **Verified:** the SQL API (`/api/v2/statements`) **ignores `X-Snowflake-Role`**. With only the header set, the statement runs under the user's `DEFAULT_ROLE`. If header and body conflict, the body `role` wins. Always set the `role` field on SQL API calls.

### Secondary roles: close them per request via the SQL API

**Recommended (*verified*): a single-statement Snowflake Scripting block** for queries.

```json
POST /api/v2/statements
{
  "statement": "EXECUTE IMMEDIATE $$ DECLARE res RESULTSET; BEGIN USE SECONDARY ROLES NONE; res := (SELECT ...); RETURN TABLE(res); END; $$",
  "role": "APP_ANALYST",
  "warehouse": "SSO_DEMO_WH",
  "parameters": { "QUERY_TAG": "app=sso-passthrough;user=<upn>" }
}
```

The result comes back in the same response, and the next request starts fresh (secondary roles back to the user default), so the control is strictly per request. See `run_sql()` in `app/backend/app/services/snowflake_oauth.py`.

**Alternative: multi-statement** (`"USE SECONDARY ROLES NONE; SELECT ..."` with `MULTI_STATEMENT_COUNT = 2`).

> **Caveat (verified):** in a multi-statement request, each child result is fetched with `GET /api/v2/statements/{handle}`. That GET opens a session with the user's **`DEFAULT_ROLE`**, and neither `X-Snowflake-Role` nor `?role=` changes this. If `DEFAULT_ROLE` isn't in `EXTERNAL_OAUTH_ALLOWED_ROLES_LIST`, the fetch fails with error 390186. Either set app users' `DEFAULT_ROLE` to an allowlisted app role, or use the scripting block above.

Both patterns share these properties:

- If `USE SECONDARY ROLES` fails, the query doesn't run, so the failure direction is safe.
- **Caveat:** neither pattern supports bind variables. Mitigate in the backend:
  - Use a vetted library's client-side binding, not hand-rolled escaping.
  - Remember that Snowflake treats backslash as an escape character in single-quoted strings; doubling quotes alone isn't enough.
  - Never put user input into identifiers (table, column, role names); map those through an allowlist.
  - Validate types before rendering (numbers as numbers, dates as dates).

### Why the REST / SQL API is the right fit

- It's stateless: the role is set explicitly on every request. There's no `USE ROLE` drift as in a long-lived driver session, and no connection pool leaking one user's role into another request.
- Role selection lives in **one place** in the backend, which is easy to review and log.
- Set `QUERY_TAG` per request for audit.
- On MCP endpoints, auth errors can come back as HTTP 200 with a JSON-RPC error body, so always inspect the body.

---

## 7. Backstops

These hold even if the backend errs.

1. **Session policy** with `ALLOWED_SECONDARY_ROLES` / `BLOCKED_SECONDARY_ROLES`:

   ```sql
   CREATE SESSION POLICY SSO_DEMO_DB.APP.NO_SECONDARY_ROLES
     ALLOWED_SECONDARY_ROLES = ();          -- or a curated list
   ALTER USER <user> SET SESSION POLICY SSO_DEMO_DB.APP.NO_SECONDARY_ROLES;
   ```

   - Even if `USE SECONDARY ROLES ALL` is issued, the active set is limited by the policy.
   - *Verified:* the policy also closes the REST API path (`X-Snowflake-Role`), which has no per-request secondary-role control. Allow a minute or two for an attached policy to reach new sessions.
   - Note that it applies per user or per account, so it also affects those users' Snowsight and driver sessions.
   - `DEFAULT_SECONDARY_ROLES` only accepts `('ALL')` or `()`, not a role list.

2. **Integration allow/block lists** cap which primary roles any request can choose.
3. **Lean role hierarchy.** Inherited grants still apply when secondary roles are off, so scoping is only as tight as the role design.
4. **Entra-side restrictions:**
   - turn on "Assignment required" on the enterprise apps;
   - pre-authorize only approved client apps.
5. **Authentication policies** in Snowflake limit which integrations a given user may authenticate through.

> **Security boundary, stated plainly:** with `role-any`, the **backend is the per-app enforcement point** and the **integration role allowlist is the hard boundary**. A leaked token can use any role inside the allowlist. Keep tokens server-side and short-lived, and log every role selection.

---

## 8. Alternatives

These give a true per-app role boundary.

| Option | Description | Trade-off |
|---|---|---|
| **v1/v2 issuer split** (recommended, §0, *verified*) | A second resource app with v2 tokens has a different issuer, so it gets a second External OAuth integration with its own allowlist; combine with role-scoped tokens | Two slots per tenant |
| **Snowflake OAuth (custom client)** | `TYPE = OAUTH, OAUTH_CLIENT = CUSTOM`, with its own `BLOCKED_ROLES_LIST` / `PRE_AUTHORIZED_ROLES_LIST`. Snowflake SSOs to Entra via SAML (silent if a session exists) | No OBO; Snowflake issues the tokens. Cleanest supported per-app boundary |
| **Custom token issuer** | A small service validates the Entra token and mints a Snowflake JWT with its own issuer, which gets its own integration | Most control, but you operate an IdP |

---

## 9. Validation checklist

- [x] Silent redirect after the SAML ACS: no visible prompt with an existing Entra session
- [x] `SELECT CURRENT_ROLE(), CURRENT_SECONDARY_ROLES();` via each path with a `role-any` token:
  - [x] REST API with `X-Snowflake-Role`: primary role set, **all secondary roles active**
  - [x] SQL API with `role` in the body: primary role set, **all secondary roles active**
  - [x] SQL API with secondary roles off (scripting block): primary role only, no secondaries
- [x] Role outside the allowlist rejected by Snowflake
- [x] Session policy `ALLOWED_SECONDARY_ROLES = ()` closes the REST and SQL default paths
- [x] The v1/v2 issuer split yields a second integration with its own allowlist
- [x] Role-scoped v2 token: no secondary roles; other roles rejected on SQL API, REST and Cortex Agent
- [x] Roles enabled and revoked via the Snowflake allowlist without re-issuing the token
- [ ] Silent redirect on Safari, iOS and private browsing
- [ ] Behaviour with Conditional Access sign-in frequency
- [ ] Logout clearing both SAML and OIDC sessions/tokens (implemented, not yet tested end to end)

---

## 10. Summary

**Recommended (§0):**
1. Keep the SAML login and chain a silent OIDC hop onto it.
2. Give the app a dedicated v2 resource app with `session:role:<APP_ROLE>` scopes, admin-consented to a superset of the roles you may need.
3. Add a second Snowflake integration on the v2 issuer whose allowlist decides what's enabled today.

Snowflake then enforces the role boundary and disables secondary roles itself.

**Fallback (`role-any`), if a dedicated app registration isn't possible:**

1. Keep SAML. Chain a silent `prompt=none` OIDC redirect onto the ACS; the backend is a confidential client and holds the refresh token.
2. Get a `session:role-any` token for Snowflake, server-side only.
3. Use the integration's allow/block role lists as the hard cap on the primary role.
4. Per request:
   - set the primary role (header or body);
   - close secondary roles with a `USE SECONDARY ROLES NONE` scripting block via the SQL API;
   - parameterize on the backend side.

   The integration allowlist does **not** cover secondary roles.
5. Add the backstops: a session policy (the only control that also covers the REST APIs), a lean role hierarchy, Entra assignment and authentication policies.
6. Validate every path with a real token before production.
