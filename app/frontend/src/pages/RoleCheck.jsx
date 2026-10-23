import { useState, useEffect } from 'preact/hooks';
import { fetchRoleCheck, fetchSsoStatus } from '../lib/api.js';

const ROLES = ['APP_ANALYST', 'APP_READER', 'APP_RESTRICTED', 'ACCOUNTADMIN'];

const PATH_LABELS = {
  rest_header: 'REST API + X-Snowflake-Role header',
  sql_default: 'SQL API, role in body',
  sql_no_secondary: 'SQL API, role in body + USE SECONDARY ROLES NONE wrapper (role-any only)',
};

function yesNo(v) {
  if (v === undefined || v === null) return '—';
  return v ? 'YES' : 'no';
}

// Roles worth calling out when they leak in as secondaries; the rest is summarised as a count.
const NOTABLE = ['APP_RESTRICTED', 'ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN'];

function summariseSecondaries(sec) {
  const list = (sec?.roles || '').split(',').map(s => s.trim()).filter(Boolean);
  if (!list.length) return 'none';
  const notable = NOTABLE.filter(r => list.includes(r));
  return `${list.length} active, incl. ${notable.join(', ') || '…'}`;
}

function PathRow({ name, r }) {
  if (!r) return null;
  const ctx = r.context || {};
  const secondary = r.visible_schemas
    ? `schemas: ${r.visible_schemas.join(', ')}`
    : summariseSecondaries(ctx.SECONDARY_ROLES);
  const truthy = (x) => x === true || x === 'true' || x === 1 || x === '1';
  const leak = r.secret_schema_visible || r.pii_table_readable || truthy(ctx.OTHER_ROLE_ACTIVE);
  return (
    <tr style={leak ? 'background:rgba(220,60,60,0.12)' : ''}>
      <td>{PATH_LABELS[name]}</td>
      <td>{r.error ? <span class="error">{r.error}</span> : (ctx.PRIMARY_ROLE || r.role_requested)}</td>
      <td style="font-family:monospace;font-size:12px;max-width:340px;word-break:break-all;">{r.error ? '' : secondary}</td>
      <td>{yesNo(r.app_table_readable ?? (r.visible_schemas ? r.visible_schemas.includes('APP') : undefined))}</td>
      <td>{yesNo(r.pii_table_readable ?? r.secret_schema_visible)}</td>
      <td>{r.context ? `${truthy(ctx.IS_AGENT_ACTIVATED) ? 'YES' : 'no'}${ctx.AGENT_TYPE ? ` (${ctx.AGENT_TYPE})` : ''}` : '—'}</td>
      <td style="font-family:monospace;font-size:12px;">{r.agent_masked_sample ?? (r.agent_masked_sample_error ? 'error' : '—')}</td>
    </tr>
  );
}

export function RoleCheck() {
  const [status, setStatus] = useState(null);
  const [role, setRole] = useState(ROLES[0]);
  const [bypass, setBypass] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => { fetchSsoStatus().then(setStatus).catch(e => setError(e.message)); }, []);

  const run = async () => {
    setLoading(true); setError(''); setResult(null);
    try { setResult(await fetchRoleCheck(role, bypass)); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div style="padding:24px;max-width:1100px;overflow:auto;">
      <h2>Snowflake role control check</h2>
      <p style="opacity:0.8">
        Token mode: <strong>{status?.token_mode === 'role-any' ? <code>session:role-any</code> : 'role-scoped (session:role:<ROLE> list)'}</strong>.
        This page shows which role context each Snowflake path actually gives you.{' '}
        <code>SSO_DEMO_DB.SECRET</code> is granted only to{' '}<code>APP_RESTRICTED</code>; if it's readable while another
        role is primary, secondary roles leaked.
      </p>
      {status && (
        <p>Snowflake session: <strong>{status.snowflake_connected ? 'connected' : `not connected (${status.reason})`}</strong>
          {status.allowed_roles && <> · app allowlist: <code>{status.allowed_roles.join(', ')}</code></>}
          {' '}· agent identity: <strong>{status.agent_identity ? 'on (IS_AGENTIC = TRUE)' : 'off'}</strong></p>
      )}
      <div style="display:flex;gap:12px;align-items:center;margin:16px 0;">
        <select value={role} onChange={e => setRole(e.target.value)}>
          {ROLES.map(r => <option value={r}>{r}</option>)}
        </select>
        <label style="display:flex;gap:6px;align-items:center;">
          <input type="checkbox" checked={bypass} onChange={e => setBypass(e.target.checked)} />
          bypass app allowlist (dev only; shows Snowflake-side cap)
        </label>
        <button onClick={run} disabled={loading}>{loading ? 'Running…' : 'Run check'}</button>
      </div>
      {error && <div class="error">{error}</div>}
      {result?.blocked_by && (
        <div class="error">Blocked by {result.blocked_by}: {result.error}</div>
      )}
      {result?.paths && (
        <table style="width:100%;border-collapse:collapse;" cellPadding="6">
          <thead>
            <tr style="text-align:left;border-bottom:1px solid #888;">
              <th>Path</th><th>Primary role</th><th>Secondary roles / visible</th><th>APP readable</th><th>SECRET (PII) readable</th><th>Agent activated</th><th>CUSTOMER_EMAIL (agent-masked)</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(result.paths)
              .filter(([k]) => !(k === 'sql_no_secondary' && status?.token_mode !== 'role-any'))
              .map(([k, v]) => <PathRow name={k} r={v} />)}
          </tbody>
        </table>
      )}
    </div>
  );
}
