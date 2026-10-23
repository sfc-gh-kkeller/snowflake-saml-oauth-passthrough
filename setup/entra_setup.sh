#!/usr/bin/env bash
# Entra ID setup for SAML -> silent OIDC -> Snowflake per-user passthrough.
#
# Creates (idempotent, by display name):
#   1. "<PREFIX> Snowflake (scoped)"   resource app, v2 tokens, scopes session:role:<ROLE> per ROLES   [recommended]
#   2. "<PREFIX> Snowflake (role-any)" resource app, v1 tokens, scope session:role-any                 [fallback, ENABLE_ROLE_ANY=1]
#   3. "<PREFIX> Web"                  SAML SP + confidential OIDC client, admin-consented, assignment required
#
# Usage:  az login --tenant <tenant>; ./setup/entra_setup.sh
# Env:    PREFIX (default "SSO Passthrough"), BASE_URL (default http://localhost:9000),
#         ROLES (default "APP_ANALYST,APP_READER"), ENABLE_ROLE_ANY (default 1)
# Output: setup/entra.env (IDs, no secrets), setup/.entra_secret (client secret, chmod 600, gitignored)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-SSO Passthrough}"
BASE_URL="${BASE_URL:-http://localhost:9000}"
ROLES="${ROLES:-APP_ANALYST,APP_READER}"
ENABLE_ROLE_ANY="${ENABLE_ROLE_ANY:-1}"
GRAPH=https://graph.microsoft.com/v1.0
NON_GALLERY_TEMPLATE=8adf8e6e-67b2-4cf2-a259-e3dc5476c621
TENANT_ID="$(az account show --query tenantId -o tsv)"

log() { echo ">> $*" >&2; }

ensure_app() {  # $1 display name -> prints appId
  local id
  id="$(az ad app list --display-name "$1" --query '[0].appId' -o tsv)"
  if [[ -z "$id" ]]; then
    log "creating app '$1'"
    id="$(az ad app create --display-name "$1" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
  fi
  az ad sp show --id "$id" >/dev/null 2>&1 || az ad sp create --id "$id" >/dev/null
  echo "$id"
}

# Build the oauth2PermissionScopes JSON, reusing existing scope IDs so re-runs are stable.
scopes_json() {  # $1 appId, $2 comma-separated scope values
  local existing
  existing="$(az ad app show --id "$1" --query api.oauth2PermissionScopes -o json)"
  python3 - "$existing" "$2" <<'PY'
import json, sys, uuid
existing = {s["value"]: s["id"] for s in json.loads(sys.argv[1])}
out = []
for v in [x.strip() for x in sys.argv[2].split(",") if x.strip()]:
    out.append({"id": existing.get(v, str(uuid.uuid4())), "value": v, "type": "Admin", "isEnabled": True,
                "adminConsentDisplayName": f"Snowflake {v}", "adminConsentDescription": f"Snowflake {v}"})
print(json.dumps(out))
PY
}

configure_resource() {  # $1 appId, $2 token version, $3 scope values
  local obj scopes
  obj="$(az ad app show --id "$1" --query id -o tsv)"
  scopes="$(scopes_json "$1" "$3")"
  # Note: Graph refuses to remove an enabled scope in one step; to drop a role later,
  # first PATCH it with isEnabled=false, then remove it.
  az rest --method PATCH --url "$GRAPH/applications/$obj" --headers Content-Type=application/json \
    --body "{\"identifierUris\":[\"api://$1\"],\"api\":{\"requestedAccessTokenVersion\":$2,\"oauth2PermissionScopes\":$scopes}}" >/dev/null
}

# ---------- 1. scoped v2 resource (recommended) ----------
ROLE_SCOPES="$(echo "$ROLES" | tr ',' '\n' | sed 's/^ *//;s/ *$//' | sed 's/^/session:role:/' | paste -sd, -)"
RES_V2="$(ensure_app "$PREFIX Snowflake (scoped)")"
log "resource v2 $RES_V2 scopes: $ROLE_SCOPES"
configure_resource "$RES_V2" 2 "$ROLE_SCOPES"

# ---------- 2. role-any v1 resource (fallback) ----------
RES_V1=""
if [[ "$ENABLE_ROLE_ANY" == "1" ]]; then
  RES_V1="$(ensure_app "$PREFIX Snowflake (role-any)")"
  log "resource v1 $RES_V1 scope: session:role-any"
  configure_resource "$RES_V1" 1 "session:role-any"
fi

# ---------- 3. web app (SAML SP + OIDC client) ----------
WEB="$(az ad app list --display-name "$PREFIX Web" --query '[0].appId' -o tsv)"
if [[ -z "$WEB" ]]; then
  log "instantiating non-gallery SAML app"
  az rest --method POST --url "$GRAPH/applicationTemplates/$NON_GALLERY_TEMPLATE/instantiate" \
    --headers Content-Type=application/json --body "{\"displayName\":\"$PREFIX Web\"}" >/dev/null
  for _ in $(seq 1 20); do
    WEB="$(az ad app list --display-name "$PREFIX Web" --query '[0].appId' -o tsv)"
    [[ -n "$WEB" ]] && az ad sp show --id "$WEB" >/dev/null 2>&1 && break
    sleep 3
  done
fi
WEB_OBJ="$(az ad app show --id "$WEB" --query id -o tsv)"
WEB_SP="$(az ad sp show --id "$WEB" --query id -o tsv)"

RRA="$(python3 - "$RES_V2" "$(az ad app show --id "$RES_V2" --query 'api.oauth2PermissionScopes[].id' -o json)" \
                 "$RES_V1" "$( [[ -n "$RES_V1" ]] && az ad app show --id "$RES_V1" --query 'api.oauth2PermissionScopes[].id' -o json || echo '[]')" <<'PY'
import json, sys
rra = [{"resourceAppId": sys.argv[1], "resourceAccess": [{"id": i, "type": "Scope"} for i in json.loads(sys.argv[2])]}]
if sys.argv[3]:
    rra.append({"resourceAppId": sys.argv[3], "resourceAccess": [{"id": i, "type": "Scope"} for i in json.loads(sys.argv[4])]})
# Microsoft Graph: openid, offline_access, profile
rra.append({"resourceAppId": "00000003-0000-0000-c000-000000000000", "resourceAccess": [
    {"id": "37f7f235-527c-4136-accd-4a02d197296e", "type": "Scope"},
    {"id": "7427e0e9-2fba-42fe-b0c0-848c9e6a8182", "type": "Scope"},
    {"id": "14dad69e-099b-42c9-810b-d002981feec1", "type": "Scope"}]})
print(json.dumps(rra))
PY
)"

log "configuring web app $WEB"
az rest --method PATCH --url "$GRAPH/applications/$WEB_OBJ" --headers Content-Type=application/json --body "{
  \"identifierUris\": [\"api://$WEB\"],
  \"web\": {\"redirectUris\": [\"$BASE_URL/api/auth/saml/acs\", \"$BASE_URL/api/auth/oidc/callback\"], \"logoutUrl\": \"$BASE_URL/\"},
  \"requiredResourceAccess\": $RRA
}" >/dev/null

az rest --method PATCH --url "$GRAPH/servicePrincipals/$WEB_SP" --headers Content-Type=application/json \
  --body '{"preferredSingleSignOnMode":"saml","appRoleAssignmentRequired":true}' >/dev/null
if [[ "$(az rest --method GET --url "$GRAPH/servicePrincipals/$WEB_SP?\$select=keyCredentials" --query 'length(keyCredentials)' -o tsv)" == "0" ]]; then
  az rest --method POST --url "$GRAPH/servicePrincipals/$WEB_SP/addTokenSigningCertificate" \
    --headers Content-Type=application/json --body "{\"displayName\":\"CN=$PREFIX SAML\"}" >/dev/null
fi

log "assigning signed-in user"
ME="$(az ad signed-in-user show --query id -o tsv)"
az rest --method POST --url "$GRAPH/servicePrincipals/$WEB_SP/appRoleAssignedTo" --headers Content-Type=application/json \
  --body "{\"principalId\":\"$ME\",\"resourceId\":\"$WEB_SP\",\"appRoleId\":\"00000000-0000-0000-0000-000000000000\"}" >/dev/null 2>&1 || true

log "admin consent (the consent grant is the effective role allowlist: Entra emits all consented scopes)"
sleep 10
for _ in 1 2 3 4; do az ad app permission admin-consent --id "$WEB" 2>/dev/null && break; sleep 10; done

SECRET_FILE="$HERE/.entra_secret"
if [[ ! -s "$SECRET_FILE" ]]; then
  log "creating client secret"
  ( umask 077; az ad app credential reset --id "$WEB" --display-name sso-passthrough --years 1 --append \
      --query password -o tsv 2>/dev/null > "$SECRET_FILE" )
fi

DOMAIN="$(az rest --method GET --url "$GRAPH/domains" --query "value[?isDefault].id | [0]" -o tsv)"
cat > "$HERE/entra.env" <<ENV
TENANT_ID=$TENANT_ID
DOMAIN_HINT=$DOMAIN
WEB_APP_ID=$WEB
RES_V2_APP_ID=$RES_V2
RES_V1_APP_ID=$RES_V1
ROLES=$ROLES
SAML_METADATA_URL=https://login.microsoftonline.com/$TENANT_ID/federationmetadata/2007-06/federationmetadata.xml?appid=$WEB
ENV
log "wrote $HERE/entra.env"
