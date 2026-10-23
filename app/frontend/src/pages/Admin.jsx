import { useState, useEffect, useRef } from 'preact/hooks';
import { marked } from 'marked';
import {
  fetchAdminStats, fetchAdminUsers, updateUserRole, toggleUserActive,
  updateUserEmail, resetUserPasskeys, deleteUser, fetchAdminTopics,
  fetchReuseAnalytics, fetchQuestionAnalytics, fetchUserQuestionStats, fetchFeedbackAnalytics,
  fetchAdminSessions, hardDeleteSession, fetchAdminFlags, fetchAdminAssets, deleteAdminAsset,
  deactivateAdminAsset, fixAssetExpiration, classifyAllAssets,
  fetchTopicsWithAssets, fetchAdminSettings, updateAdminSettings, createAdminUser,
  updateAssetLifecycle, refreshAdminAsset, refreshExpiredAssets,
  setLeadingAsset,
  fetchSystemPrompt, updateSystemPrompt, fetchSkills, updateSkillConfig,
  fetchSkillContent, updateSkillContent,
  fetchMcpServers, addMcpServer, removeMcpServer, toggleMcpServer,
} from '../lib/api.js';

export function Admin({ user }) {
  const [stats, setStats] = useState(null);
  const [topics, setTopics] = useState([]);
  const [tab, setTab] = useState('overview');
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadData(); }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [s, t] = await Promise.all([fetchAdminStats(), fetchAdminTopics()]);
      setStats(s);
      setTopics(t);
    } catch (e) {
      console.error('Admin load error:', e);
    }
    setLoading(false);
  }

  if (loading) return <div style="padding:2rem;color:#94a3b8;">Loading analytics...</div>;

  const tabs = ['overview', 'analytics', 'users', 'sessions', 'assets', 'classify', 'feedback', 'flags', 'settings'];

  return (
    <div style="flex:1;overflow-y:auto;padding:1.5rem;max-width:1200px;margin:0 auto;width:100%;">
      <div style="display:flex;gap:0.5rem;margin-bottom:1.5rem;flex-wrap:wrap;">
        {tabs.map(t => (
          <button
            key={t}
            class={`tab-btn ${tab === t ? 'active' : ''}`}
            onClick={() => setTab(t)}
            style={`padding:0.5rem 1rem;border-radius:6px;border:1px solid ${tab === t ? '#3b82f6' : '#334155'};background:${tab === t ? '#1e3a5f' : '#0f172a'};color:${tab === t ? '#60a5fa' : '#94a3b8'};cursor:pointer;font-size:0.875rem;`}
          >{t[0].toUpperCase() + t.slice(1)}</button>
        ))}
      </div>

      {tab === 'overview' && stats && <OverviewTab stats={stats} />}
      {tab === 'analytics' && <AnalyticsTab topics={topics} />}
      {tab === 'users' && <UsersTab currentUserId={user?.id} />}
      {tab === 'sessions' && <SessionsTab />}
      {tab === 'assets' && <AssetsTab />}
      {tab === 'classify' && <ClassifyTab />}
      {tab === 'feedback' && <FeedbackTab />}
      {tab === 'flags' && <FlagsTab />}
      {tab === 'settings' && <SettingsTab />}
    </div>
  );
}

function StatCard({ label, value, color, sub }) {
  return (
    <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1rem 1.25rem;display:flex;flex-direction:column;gap:0.25rem;">
      <span style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;">{label}</span>
      <span style={`color:${color || '#f1f5f9'};font-size:1.75rem;font-weight:700;`}>{value ?? '—'}</span>
      {sub && <span style="color:#64748b;font-size:0.7rem;">{sub}</span>}
    </div>
  );
}

function OverviewTab({ stats }) {
  return (
    <div>
      <h3 style="color:#f1f5f9;margin:0 0 1rem 0;font-size:1.1rem;">Platform Overview</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:1rem;margin-bottom:2rem;">
        <StatCard label="Total Users" value={stats.users} color="#60a5fa" />
        <StatCard label="Sessions" value={stats.sessions} color="#a78bfa" />
        <StatCard label="Sessions Today" value={stats.sessions_today} color="#818cf8" />
        <StatCard label="Questions Asked" value={stats.total_questions} color="#c084fc" />
        <StatCard label="Total Assets" value={stats.assets_total} color="#f1f5f9" />
        <StatCard label="Approved" value={stats.assets_approved} color="#34d399" />
        <StatCard label="In Review" value={stats.assets_in_review} color="#fbbf24" />
        <StatCard label="Rejected" value={stats.assets_rejected} color="#f87171" />
        <StatCard label="Drafts" value={stats.assets_draft} color="#94a3b8" />
        <StatCard label="With Embedding" value={stats.assets_with_embedding} color="#2dd4bf" />
        <StatCard label="Expired" value={stats.assets_expired} color="#fb923c" />
        <StatCard label="Versions" value={stats.versions_total} color="#818cf8" />
        <StatCard label="Feedback" value={stats.feedback_total} color="#c084fc" />
        <StatCard label="Pending Flags" value={stats.pending_flags} color={stats.pending_flags > 0 ? '#f87171' : '#64748b'} />
      </div>

      {stats.topics_breakdown && stats.topics_breakdown.length > 0 && (
        <div>
          <h3 style="color:#f1f5f9;margin:0 0 1rem 0;font-size:1.1rem;">Assets by Topic</h3>
          <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
            {stats.topics_breakdown.map(t => (
              <span key={t.topic} style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:0.4rem 0.75rem;color:#94a3b8;font-size:0.8rem;">
                <span style="color:#60a5fa;">{t.topic}</span>
                <span style="margin-left:0.5rem;color:#f1f5f9;font-weight:600;">{t.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AnalyticsTab({ topics }) {
  const [reuse, setReuse] = useState(null);
  const [userStats, setUserStats] = useState([]);
  const [questions, setQuestions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [topicFilter, setTopicFilter] = useState('');
  const [qSearch, setQSearch] = useState('');

  useEffect(() => { loadAnalytics(); }, []);

  async function loadAnalytics() {
    setLoading(true);
    try {
      const [r, u, q] = await Promise.all([
        fetchReuseAnalytics(),
        fetchUserQuestionStats(),
        fetchQuestionAnalytics({ limit: 25 }),
      ]);
      setReuse(r);
      setUserStats(u);
      setQuestions(q);
    } catch (e) {
      console.error('Analytics load error:', e);
    }
    setLoading(false);
  }

  async function searchQuestions() {
    try {
      const q = await fetchQuestionAnalytics({ topic: topicFilter || undefined, search: qSearch || undefined, limit: 25 });
      setQuestions(q);
    } catch (e) {
      console.error(e);
    }
  }

  if (loading) return <div style="padding:1rem;color:#94a3b8;">Loading analytics...</div>;

  const maxTopicCount = topics.length ? Math.max(...topics.map(t => t.question_count || 0), 1) : 1;

  return (
    <div style="display:flex;flex-direction:column;gap:2rem;">
      {reuse && (
        <div>
          <h3 style="color:#f1f5f9;margin:0 0 1rem 0;font-size:1.1rem;">Asset Reuse</h3>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:1rem;margin-bottom:1.5rem;">
            <StatCard label="Total Questions" value={reuse.total_questions} color="#f1f5f9" />
            <StatCard label="Reused Assets" value={reuse.reused_count} color="#34d399" />
            <StatCard label="Suggestions Made" value={reuse.suggested_count} color="#60a5fa" />
            <StatCard label="Reuse Rate" value={`${reuse.reuse_rate}%`} color="#34d399" sub="reused / total" />
            <StatCard label="Accept Rate" value={`${reuse.acceptance_rate}%`} color="#fbbf24" sub="reused / suggested" />
          </div>

          {reuse.top_reused_assets.length > 0 && (
            <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1rem;">
              <h4 style="color:#94a3b8;margin:0 0 0.75rem 0;font-size:0.85rem;text-transform:uppercase;letter-spacing:0.05em;">Top Reused Assets</h4>
              {reuse.top_reused_assets.map(a => (
                <div key={a.id} style="display:flex;justify-content:space-between;align-items:center;padding:0.4rem 0;border-bottom:1px solid #0f172a;">
                  <span style="color:#e2e8f0;font-size:0.85rem;">{a.filename}</span>
                  <span style="color:#34d399;font-weight:600;font-size:0.85rem;">{a.reuse_count}x</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div>
        <h3 style="color:#f1f5f9;margin:0 0 1rem 0;font-size:1.1rem;">Questions by Topic</h3>
        <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1rem;">
          {topics.map(t => (
            <div key={t.id} style="display:flex;align-items:center;gap:0.75rem;padding:0.4rem 0;">
              <span style="color:#94a3b8;font-size:0.8rem;min-width:120px;text-align:right;">{t.name}</span>
              <div style="flex:1;background:#0f172a;border-radius:999px;height:8px;overflow:hidden;">
                <div style={`background:#3b82f6;height:100%;border-radius:999px;width:${((t.question_count || 0) / maxTopicCount * 100)}%;transition:width 0.3s;`} />
              </div>
              <span style="color:#f1f5f9;font-size:0.8rem;min-width:30px;font-weight:600;">{t.question_count || 0}</span>
            </div>
          ))}
          {topics.length === 0 && <span style="color:#64748b;font-size:0.85rem;">No topics yet</span>}
        </div>
      </div>

      {userStats.length > 0 && (
        <div>
          <h3 style="color:#f1f5f9;margin:0 0 1rem 0;font-size:1.1rem;">User Question Stats</h3>
          <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;overflow:hidden;">
            <table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
              <thead>
                <tr style="border-bottom:1px solid #334155;">
                  <th style="text-align:left;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">User</th>
                  <th style="text-align:right;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">Questions</th>
                  <th style="text-align:right;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">Reused</th>
                  <th style="text-align:right;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">Reuse Rate</th>
                </tr>
              </thead>
              <tbody>
                {userStats.map(u => (
                  <tr key={u.id} style="border-bottom:1px solid #1e293b;">
                    <td style="padding:0.6rem 1rem;color:#e2e8f0;">{u.display_name || u.email}</td>
                    <td style="padding:0.6rem 1rem;color:#f1f5f9;text-align:right;font-weight:600;">{u.question_count}</td>
                    <td style="padding:0.6rem 1rem;color:#34d399;text-align:right;">{u.reuse_count}</td>
                    <td style="padding:0.6rem 1rem;color:#fbbf24;text-align:right;">{u.reuse_rate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {questions && (
        <div>
          <h3 style="color:#f1f5f9;margin:0 0 0.75rem 0;font-size:1.1rem;">Recent Questions ({questions.total})</h3>
          <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;">
            <input
              type="text"
              placeholder="Search questions..."
              value={qSearch}
              onInput={e => setQSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && searchQuestions()}
              style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;"
            />
            <select
              value={topicFilter}
              onChange={e => { setTopicFilter(e.target.value); }}
              style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.4rem 0.5rem;font-size:0.8rem;"
            >
              <option value="">All Topics</option>
              {topics.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
            </select>
            <button onClick={searchQuestions} style="background:#1e3a5f;color:#60a5fa;border:1px solid #3b82f6;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">Filter</button>
          </div>
          <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;overflow:hidden;">
            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
              <thead>
                <tr style="border-bottom:1px solid #334155;">
                  <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Question</th>
                  <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Topic</th>
                  <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">User</th>
                  <th style="text-align:center;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Reused</th>
                  <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Date</th>
                </tr>
              </thead>
              <tbody>
                {questions.questions.map(q => (
                  <tr key={q.id} style="border-bottom:1px solid #0f172a;">
                    <td style="padding:0.5rem 0.75rem;color:#e2e8f0;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{q.question_text}</td>
                    <td style="padding:0.5rem 0.75rem;">
                      {q.topic && <span style="background:#1e3a5f;color:#60a5fa;padding:0.15rem 0.4rem;border-radius:4px;font-size:0.7rem;">{q.topic}</span>}
                    </td>
                    <td style="padding:0.5rem 0.75rem;color:#94a3b8;">{q.user_name || q.user_email}</td>
                    <td style="padding:0.5rem 0.75rem;text-align:center;">
                      {q.reuse_accepted ? <span style="color:#34d399;">&#10003;</span> : <span style="color:#334155;">—</span>}
                    </td>
                    <td style="padding:0.5rem 0.75rem;color:#64748b;font-size:0.75rem;">
                      {q.created_at ? new Date(q.created_at).toLocaleDateString() : '—'}
                    </td>
                  </tr>
                ))}
                {questions.questions.length === 0 && (
                  <tr><td colspan="5" style="padding:1rem;color:#64748b;text-align:center;">No questions found</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function UsersTab({ currentUserId }) {
  const [data, setData] = useState(null);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newPass, setNewPass] = useState('');
  const [newName, setNewName] = useState('');
  const [newRole, setNewRole] = useState('user');

  useEffect(() => { loadUsers(); }, []);

  async function loadUsers(s, r) {
    setLoading(true);
    try {
      const d = await fetchAdminUsers({ search: s || undefined, role: r || undefined, limit: 100 });
      setData(d);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  function doSearch() {
    loadUsers(search, roleFilter);
  }

  async function handleRoleChange(userId, role) {
    try {
      await updateUserRole(userId, role);
      setData(prev => ({
        ...prev,
        users: prev.users.map(u => u.id === userId ? { ...u, role } : u),
      }));
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleToggleActive(userId) {
    try {
      const res = await toggleUserActive(userId);
      setData(prev => ({
        ...prev,
        users: prev.users.map(u => u.id === userId ? { ...u, is_active: res.is_active } : u),
      }));
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleChangeEmail(userId) {
    const newEmail = prompt('Enter new email address:');
    if (!newEmail) return;
    try {
      const res = await updateUserEmail(userId, newEmail);
      setData(prev => ({
        ...prev,
        users: prev.users.map(u => u.id === userId ? { ...u, email: res.email } : u),
      }));
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleResetPasskeys(userId) {
    if (!confirm('Reset all passkeys for this user? They will need to re-enroll on next login.')) return;
    try {
      await resetUserPasskeys(userId);
      alert('Passkeys reset successfully.');
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleDeleteUser(userId) {
    if (!confirm('Permanently delete this user? This cannot be undone.')) return;
    try {
      await deleteUser(userId);
      loadUsers(search, roleFilter);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleCreate() {
    if (!newEmail || !newPass) return alert('Email and password required');
    try {
      await createAdminUser(newEmail, newPass, newName, newRole);
      setShowCreate(false);
      setNewEmail(''); setNewPass(''); setNewName(''); setNewRole('user');
      loadUsers(search, roleFilter);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  if (loading) return <div style="padding:1rem;color:#94a3b8;">Loading users...</div>;
  const users = data?.users || [];

  return (
    <div>
      <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;">
        <h3 style="color:#f1f5f9;margin:0;font-size:1.1rem;">User Management ({data?.total || 0})</h3>
        <button onClick={() => setShowCreate(!showCreate)} style="margin-left:auto;background:#1e3a5f;color:#60a5fa;border:1px solid #3b82f6;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">+ Create User</button>
      </div>

      {showCreate && (
        <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1rem;margin-bottom:1rem;display:flex;gap:0.5rem;flex-wrap:wrap;align-items:end;">
          <div><label style="color:#94a3b8;font-size:0.7rem;display:block;">Email</label><input value={newEmail} onInput={e => setNewEmail(e.target.value)} style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.5rem;font-size:0.8rem;width:200px;" /></div>
          <div><label style="color:#94a3b8;font-size:0.7rem;display:block;">Password</label><input type="password" value={newPass} onInput={e => setNewPass(e.target.value)} style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.5rem;font-size:0.8rem;width:140px;" /></div>
          <div><label style="color:#94a3b8;font-size:0.7rem;display:block;">Name</label><input value={newName} onInput={e => setNewName(e.target.value)} style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.5rem;font-size:0.8rem;width:140px;" /></div>
          <div><label style="color:#94a3b8;font-size:0.7rem;display:block;">Role</label>
            <select value={newRole} onChange={e => setNewRole(e.target.value)} style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.5rem;font-size:0.8rem;">
              <option value="user">user</option><option value="reviewer">reviewer</option><option value="admin">admin</option>
            </select>
          </div>
          <button onClick={handleCreate} style="background:#059669;color:white;border:none;border-radius:4px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">Create</button>
        </div>
      )}

      <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;">
        <input type="text" placeholder="Search users..." value={search} onInput={e => setSearch(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()} style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;" />
        <select value={roleFilter} onChange={e => { setRoleFilter(e.target.value); loadUsers(search, e.target.value); }} style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.4rem 0.5rem;font-size:0.8rem;">
          <option value="">All Roles</option><option value="user">user</option><option value="reviewer">reviewer</option><option value="admin">admin</option>
        </select>
        <button onClick={doSearch} style="background:#1e3a5f;color:#60a5fa;border:1px solid #3b82f6;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">Search</button>
      </div>

      <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;overflow:hidden;">
        <table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
          <thead>
            <tr style="border-bottom:1px solid #334155;">
              <th style="text-align:left;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">Email</th>
              <th style="text-align:left;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">Name</th>
              <th style="text-align:left;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">Role</th>
              <th style="text-align:left;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">Status</th>
              <th style="text-align:left;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">Last Login</th>
              <th style="text-align:left;padding:0.75rem 1rem;color:#94a3b8;font-weight:500;">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} style="border-bottom:1px solid #1e293b;">
                <td style="padding:0.6rem 1rem;color:#e2e8f0;">{u.email}</td>
                <td style="padding:0.6rem 1rem;color:#cbd5e1;">{u.display_name || '—'}</td>
                <td style="padding:0.6rem 1rem;">
                  <span style={`padding:0.2rem 0.5rem;border-radius:4px;font-size:0.75rem;font-weight:600;${u.role === 'admin' ? 'background:#7c3aed22;color:#a78bfa;' : u.role === 'reviewer' ? 'background:#2563eb22;color:#60a5fa;' : 'background:#33415522;color:#94a3b8;'}`}>{u.role}</span>
                </td>
                <td style="padding:0.6rem 1rem;">
                  <span style={`color:${u.is_active ? '#34d399' : '#f87171'};font-size:0.8rem;`}>{u.is_active ? 'active' : 'inactive'}</span>
                </td>
                <td style="padding:0.6rem 1rem;color:#64748b;font-size:0.8rem;">{u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : 'never'}</td>
                <td style="padding:0.6rem 1rem;">
                  <div style="display:flex;gap:0.4rem;align-items:center;flex-wrap:wrap;">
                    <select value={u.role} onChange={e => handleRoleChange(u.id, e.target.value)} style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.25rem 0.5rem;font-size:0.75rem;">
                      <option value="user">user</option><option value="reviewer">reviewer</option><option value="admin">admin</option>
                    </select>
                    <button onClick={() => handleChangeEmail(u.id)} style="background:none;border:1px solid #334155;color:#60a5fa;border-radius:4px;padding:0.2rem 0.5rem;font-size:0.7rem;cursor:pointer;" title="Change email">
                      Email
                    </button>
                    <button onClick={() => handleResetPasskeys(u.id)} style="background:none;border:1px solid #334155;color:#a78bfa;border-radius:4px;padding:0.2rem 0.5rem;font-size:0.7rem;cursor:pointer;" title="Reset passkeys">
                      Reset PK
                    </button>
                    {u.id !== currentUserId && (
                      <>
                        <button onClick={() => handleToggleActive(u.id)} style={`background:none;border:1px solid #334155;border-radius:4px;padding:0.2rem 0.5rem;font-size:0.7rem;cursor:pointer;color:${u.is_active ? '#fbbf24' : '#34d399'};`}>
                          {u.is_active ? 'Block' : 'Unblock'}
                        </button>
                        <button onClick={() => handleDeleteUser(u.id)} style="background:none;border:1px solid #334155;color:#f87171;border-radius:4px;padding:0.2rem 0.5rem;font-size:0.7rem;cursor:pointer;" title="Delete user">
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SessionsTab() {
  const [data, setData] = useState(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [internalDialog, setInternalDialog] = useState(null);
  const [internalLoading, setInternalLoading] = useState(false);

  useEffect(() => { loadSessions(); }, []);

  async function loadSessions(s, p) {
    setLoading(true);
    try {
      const d = await fetchAdminSessions({ search: s || undefined, limit: 50, offset: (p || 0) * 50 });
      setData(d);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  function doSearch() {
    setPage(0);
    loadSessions(search, 0);
  }

  function goPage(p) {
    setPage(p);
    loadSessions(search, p);
  }

  async function handleHardDelete(id) {
    if (!confirm('Permanently delete this session? This cannot be undone.')) return;
    try {
      await hardDeleteSession(id);
      loadSessions(search, page);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleViewInternal(id) {
    setInternalLoading(true);
    try {
      const token = localStorage.getItem('ncx_token');
      const resp = await fetch(`/api/admin/sessions/${id}/internal`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) {
        const data = await resp.json();
        setInternalDialog(data);
      } else {
        setInternalDialog({ session_id: id, internal_dialogue: null });
      }
    } catch {
      setInternalDialog({ session_id: id, internal_dialogue: null });
    }
    setInternalLoading(false);
  }

  if (loading) return <div style="padding:1rem;color:#94a3b8;">Loading sessions...</div>;
  const sessions = data?.sessions || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / 50);

  return (
    <div>
      <h3 style="color:#f1f5f9;margin:0 0 1rem 0;font-size:1.1rem;">Sessions ({total})</h3>
      <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;">
        <input type="text" placeholder="Search by title or email..." value={search} onInput={e => setSearch(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()} style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;" />
        <button onClick={doSearch} style="background:#1e3a5f;color:#60a5fa;border:1px solid #3b82f6;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">Search</button>
      </div>

      <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;overflow:hidden;">
        <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
          <thead>
            <tr style="border-bottom:1px solid #334155;">
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Title</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">User</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Status</th>
              <th style="text-align:right;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Time (ms)</th>
              <th style="text-align:right;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Searches</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Created</th>
              <th style="text-align:center;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map(s => (
              <tr key={s.id} style={`border-bottom:1px solid #0f172a;${s.deleted_at ? 'opacity:0.6;' : ''}`}>
                <td style="padding:0.5rem 0.75rem;color:#e2e8f0;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                  <a href={`#/qa?session=${s.id}`} style="color:#e2e8f0;text-decoration:none;">{s.title}</a>
                </td>
                <td style="padding:0.5rem 0.75rem;color:#94a3b8;">{s.user_name || s.user_email}</td>
                <td style="padding:0.5rem 0.75rem;">
                  {s.deleted_at ? (
                    <span style="color:#f87171;font-size:0.75rem;" title={`Deleted: ${new Date(s.deleted_at).toLocaleString()}`}>deleted</span>
                  ) : (
                    <span style={`color:${s.status === 'done' ? '#34d399' : s.status === 'running' ? '#fbbf24' : '#94a3b8'};font-size:0.75rem;`}>{s.status}</span>
                  )}
                </td>
                <td style="padding:0.5rem 0.75rem;color:#f1f5f9;text-align:right;font-variant-numeric:tabular-nums;">{s.total_time_ms ?? '—'}</td>
                <td style="padding:0.5rem 0.75rem;color:#a78bfa;text-align:right;">{s.web_search_count || 0}</td>
                <td style="padding:0.5rem 0.75rem;color:#64748b;font-size:0.75rem;">{s.created_at ? new Date(s.created_at).toLocaleDateString() : '—'}</td>
                <td style="padding:0.5rem 0.75rem;text-align:center;white-space:nowrap;">
                  <button onClick={() => handleViewInternal(s.id)} style="background:none;border:1px solid #334155;color:#94a3b8;border-radius:4px;padding:0.2rem 0.4rem;font-size:0.7rem;cursor:pointer;margin-right:0.25rem;" title="View internal dialogue">
                    Debug
                  </button>
                  <button onClick={() => handleHardDelete(s.id)} style="background:none;border:1px solid #7f1d1d;color:#f87171;border-radius:4px;padding:0.2rem 0.4rem;font-size:0.7rem;cursor:pointer;" title="Permanently delete">
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {sessions.length === 0 && <tr><td colspan="7" style="padding:1rem;color:#64748b;text-align:center;">No sessions found</td></tr>}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div style="display:flex;gap:0.5rem;margin-top:0.75rem;justify-content:center;">
          {page > 0 && <button onClick={() => goPage(page - 1)} style="background:#0f172a;color:#60a5fa;border:1px solid #334155;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.75rem;cursor:pointer;">Prev</button>}
          <span style="color:#94a3b8;font-size:0.8rem;padding:0.3rem 0;">Page {page + 1} of {totalPages}</span>
          {page < totalPages - 1 && <button onClick={() => goPage(page + 1)} style="background:#0f172a;color:#60a5fa;border:1px solid #334155;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.75rem;cursor:pointer;">Next</button>}
        </div>
      )}

      {/* Internal Dialogue Modal */}
      {internalDialog && (
        <div style="position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center;padding:2rem;" onClick={() => setInternalDialog(null)}>
          <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;max-width:700px;width:100%;max-height:80vh;overflow-y:auto;padding:1.5rem;" onClick={e => e.stopPropagation()}>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
              <h3 style="color:#f1f5f9;margin:0;font-size:1rem;">Internal Dialogue</h3>
              <button onClick={() => setInternalDialog(null)} style="background:none;border:none;color:#94a3b8;font-size:1.2rem;cursor:pointer;">×</button>
            </div>
            <p style="color:#64748b;font-size:0.75rem;margin:0 0 1rem 0;">Session: {internalDialog.session_id}</p>
            {!internalDialog.internal_dialogue ? (
              <p style="color:#94a3b8;font-size:0.85rem;">No internal dialogue recorded for this session.</p>
            ) : (
              <div style="display:flex;flex-direction:column;gap:1rem;">
                {internalDialog.internal_dialogue.skills && (
                  <div>
                    <h4 style="color:#a78bfa;font-size:0.85rem;margin:0 0 0.5rem 0;">Skills Used</h4>
                    <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
                      {(internalDialog.internal_dialogue.skills.mandatory_skills || []).map(s => (
                        <span key={s} style="background:#1e293b;color:#94a3b8;font-size:0.7rem;padding:0.2rem 0.5rem;border-radius:10px;border:1px solid #334155;">
                          mandatory: {s}
                        </span>
                      ))}
                      {internalDialog.internal_dialogue.skills.detected_skill && (
                        <span style="background:#1e3a5f;color:#60a5fa;font-size:0.7rem;padding:0.2rem 0.5rem;border-radius:10px;border:1px solid #3b82f6;">
                          detected: {internalDialog.internal_dialogue.skills.detected_skill}
                        </span>
                      )}
                      {(internalDialog.internal_dialogue.skills.dynamic_loaded || []).map(s => (
                        <span key={s} style="background:#1a2e1a;color:#34d399;font-size:0.7rem;padding:0.2rem 0.5rem;border-radius:10px;border:1px solid #059669;">
                          dynamic: {s}
                        </span>
                      ))}
                      {(internalDialog.internal_dialogue.skills.requested_skills || []).map(s => (
                        <span key={s} style="background:#2e1a2e;color:#f472b6;font-size:0.7rem;padding:0.2rem 0.5rem;border-radius:10px;border:1px solid #ec4899;">
                          requested: {s}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {internalDialog.internal_dialogue.sanitized_parts?.length > 0 && (
                  <div>
                    <h4 style="color:#fbbf24;font-size:0.85rem;margin:0 0 0.5rem 0;">Sanitized (stripped from output)</h4>
                    <pre style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:0.75rem;color:#94a3b8;font-size:0.75rem;white-space:pre-wrap;overflow-x:auto;margin:0;">{internalDialog.internal_dialogue.sanitized_parts.join('\n---\n')}</pre>
                  </div>
                )}
                {internalDialog.internal_dialogue.reflect_exchanges?.length > 0 && (
                  <div>
                    <h4 style="color:#60a5fa;font-size:0.85rem;margin:0 0 0.5rem 0;">Reflection Exchanges</h4>
                    {internalDialog.internal_dialogue.reflect_exchanges.map((ex, i) => (
                      <div key={i} style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:0.75rem;margin-bottom:0.5rem;">
                        <div style="color:#94a3b8;font-size:0.7rem;margin-bottom:0.25rem;">Prompt: {ex.prompt}</div>
                        <div style="color:#e2e8f0;font-size:0.8rem;white-space:pre-wrap;">{ex.response}</div>
                        <div style={`color:${ex.accepted ? '#34d399' : '#f87171'};font-size:0.7rem;margin-top:0.25rem;`}>{ex.accepted ? 'Accepted as revision' : 'Rejected (kept original)'}</div>
                      </div>
                    ))}
                  </div>
                )}
                {internalDialog.internal_dialogue.reflect_exchanges?.length === 0 && !internalDialog.internal_dialogue.sanitized_parts?.length && (
                  <p style="color:#94a3b8;font-size:0.85rem;">No reflection ran for this session (no WORKSPACE_UPDATE in response).</p>
                )}
                {internalDialog.internal_dialogue.final_response_differs && (
                  <p style="color:#fbbf24;font-size:0.8rem;margin:0;">Final response was modified by reflection.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function AssetsTab() {
  const [data, setData] = useState(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('approved');
  const [visibilityFilter, setVisibilityFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);

  useEffect(() => { loadAssets(undefined, 'approved'); }, []);

  async function loadAssets(s, st, p, vis) {
    setLoading(true);
    try {
      const d = await fetchAdminAssets({ search: s || undefined, status: st || undefined, visibility: vis || undefined, limit: 50, offset: (p || 0) * 50 });
      setData(d);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  function doSearch() {
    setPage(0);
    loadAssets(search, statusFilter, 0, visibilityFilter);
  }

  async function handleDelete(id) {
    if (!confirm('Delete this asset and all its versions?')) return;
    try {
      await deleteAdminAsset(id);
      loadAssets(search, statusFilter, page, visibilityFilter);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleDeactivate(id) {
    try {
      await deactivateAdminAsset(id);
      loadAssets(search, statusFilter, page, visibilityFilter);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleFixExpiration() {
    try {
      const r = await fixAssetExpiration();
      alert(`Fixed ${r.fixed} assets`);
      loadAssets(search, statusFilter, page, visibilityFilter);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleRefresh(id) {
    try {
      await refreshAdminAsset(id);
      alert('Asset refreshed (embedding + topic re-classified)');
      loadAssets(search, statusFilter, page, visibilityFilter);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleRefreshExpired() {
    try {
      const r = await refreshExpiredAssets();
      alert(`Refreshed ${r.refreshed || 0} expired assets`);
      loadAssets(search, statusFilter, page, visibilityFilter);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleLifecycle(id, asset) {
    const newExpiry = prompt('Set new expiry date (YYYY-MM-DD) or leave empty to clear:', asset.expires_at ? asset.expires_at.split('T')[0] : '');
    if (newExpiry === null) return;
    try {
      await updateAssetLifecycle(id, { expires_at: newExpiry || null });
      loadAssets(search, statusFilter, page, visibilityFilter);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  if (loading) return <div style="padding:1rem;color:#94a3b8;">Loading assets...</div>;
  const assets = data?.assets || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / 50);

  return (
    <div>
      <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;">
        <h3 style="color:#f1f5f9;margin:0;font-size:1.1rem;">Assets ({total})</h3>
        <button onClick={handleRefreshExpired} style="margin-left:auto;background:#1e293b;color:#60a5fa;border:1px solid #1e3a5f;border-radius:6px;padding:0.35rem 0.6rem;font-size:0.75rem;cursor:pointer;">Refresh Expired</button>
        <button onClick={handleFixExpiration} style="background:#1e293b;color:#fb923c;border:1px solid #92400e;border-radius:6px;padding:0.35rem 0.6rem;font-size:0.75rem;cursor:pointer;">Fix Expiration</button>
      </div>

      <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;">
        <input type="text" placeholder="Search assets..." value={search} onInput={e => setSearch(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()} style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;" />
        <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(0); loadAssets(search, e.target.value, 0, visibilityFilter); }} style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.4rem 0.5rem;font-size:0.8rem;">
          <option value="">All Status</option><option value="draft">draft</option><option value="in_review">in_review</option><option value="approved">approved</option><option value="rejected">rejected</option>
        </select>
        <select value={visibilityFilter} onChange={e => { setVisibilityFilter(e.target.value); setPage(0); loadAssets(search, statusFilter, 0, e.target.value); }} style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.4rem 0.5rem;font-size:0.8rem;">
          <option value="">Shared + Private</option><option value="shared">Shared</option><option value="private">Private</option><option value="generated">Generated</option>
        </select>
        <button onClick={doSearch} style="background:#1e3a5f;color:#60a5fa;border:1px solid #3b82f6;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">Search</button>
      </div>

      <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;overflow:hidden;">
        <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
          <thead>
            <tr style="border-bottom:1px solid #334155;">
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Filename</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Status</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Topic</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Active</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Expires</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Git</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Actions</th>
            </tr>
          </thead>
          <tbody>
            {assets.map(a => (
              <tr key={a.id} style="border-bottom:1px solid #0f172a;">
                <td style="padding:0.5rem 0.75rem;color:#e2e8f0;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{a.filename}</td>
                <td style="padding:0.5rem 0.75rem;">
                  <span style={`font-size:0.75rem;color:${a.status === 'approved' ? '#34d399' : a.status === 'rejected' ? '#f87171' : a.status === 'in_review' ? '#fbbf24' : '#94a3b8'};`}>{a.status}</span>
                </td>
                <td style="padding:0.5rem 0.75rem;">
                  {a.topic ? <span style="background:#1e3a5f;color:#60a5fa;padding:0.1rem 0.35rem;border-radius:4px;font-size:0.7rem;">{a.topic}</span> : <span style="color:#334155;">—</span>}
                </td>
                <td style="padding:0.5rem 0.75rem;color:${a.is_active ? '#34d399' : '#f87171'};font-size:0.75rem;">{a.is_active ? 'yes' : 'no'}</td>
                <td style="padding:0.5rem 0.75rem;color:#64748b;font-size:0.75rem;">{a.expires_at ? new Date(a.expires_at).toLocaleDateString() : '—'}</td>
                <td style="padding:0.5rem 0.75rem;color:#64748b;font-size:0.75rem;">{a.git_backed_up_at ? new Date(a.git_backed_up_at).toLocaleDateString() : '—'}</td>
                <td style="padding:0.5rem 0.75rem;display:flex;gap:0.25rem;flex-wrap:wrap;">
                  <button onClick={() => handleDeactivate(a.id)} style="background:none;border:1px solid #334155;color:#fbbf24;border-radius:4px;padding:0.2rem 0.4rem;font-size:0.7rem;cursor:pointer;">{a.is_active ? 'Deact' : 'Activ'}</button>
                  <button onClick={() => handleBackup(a.id)} style="background:none;border:1px solid #334155;color:#60a5fa;border-radius:4px;padding:0.2rem 0.4rem;font-size:0.7rem;cursor:pointer;">Git</button>
                  <button onClick={() => handleRefresh(a.id)} style="background:none;border:1px solid #334155;color:#34d399;border-radius:4px;padding:0.2rem 0.4rem;font-size:0.7rem;cursor:pointer;">Refresh</button>
                  <button onClick={() => handleLifecycle(a.id, a)} style="background:none;border:1px solid #334155;color:#a78bfa;border-radius:4px;padding:0.2rem 0.4rem;font-size:0.7rem;cursor:pointer;">Expiry</button>
                  <button onClick={() => handleDelete(a.id)} style="background:none;border:1px solid #7f1d1d;color:#f87171;border-radius:4px;padding:0.2rem 0.4rem;font-size:0.7rem;cursor:pointer;">Del</button>
                </td>
              </tr>
            ))}
            {assets.length === 0 && <tr><td colspan="7" style="padding:1rem;color:#64748b;text-align:center;">No assets found</td></tr>}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div style="display:flex;gap:0.5rem;margin-top:0.75rem;justify-content:center;">
          {page > 0 && <button onClick={() => { setPage(page - 1); loadAssets(search, statusFilter, page - 1); }} style="background:#0f172a;color:#60a5fa;border:1px solid #334155;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.75rem;cursor:pointer;">Prev</button>}
          <span style="color:#94a3b8;font-size:0.8rem;padding:0.3rem 0;">Page {page + 1} of {totalPages}</span>
          {page < totalPages - 1 && <button onClick={() => { setPage(page + 1); loadAssets(search, statusFilter, page + 1); }} style="background:#0f172a;color:#60a5fa;border:1px solid #334155;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.75rem;cursor:pointer;">Next</button>}
        </div>
      )}
    </div>
  );
}

function ClassifyTab() {
  const [topicsData, setTopicsData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [classifyResult, setClassifyResult] = useState(null);
  const [selectedTopic, setSelectedTopic] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [questionsLoading, setQuestionsLoading] = useState(false);

  useEffect(() => { loadData(); }, []);

  async function loadData() {
    setLoading(true);
    try {
      const t = await fetchTopicsWithAssets();
      setTopicsData(t);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  async function handleClassifyAll() {
    try {
      const r = await classifyAllAssets();
      setClassifyResult(r);
      loadData();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleSetLeading(topicId, assetId) {
    try {
      await setLeadingAsset(topicId, assetId);
      loadData();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleTopicClick(topicName) {
    if (selectedTopic === topicName) {
      setSelectedTopic(null);
      setQuestions([]);
      return;
    }
    setSelectedTopic(topicName);
    setQuestionsLoading(true);
    try {
      const r = await fetchQuestionAnalytics({ topic: topicName, limit: 50 });
      setQuestions(r.questions || []);
    } catch (e) {
      console.error(e);
      setQuestions([]);
    }
    setQuestionsLoading(false);
  }

  if (loading) return <div style="padding:1rem;color:#94a3b8;">Loading classify data...</div>;

  return (
    <div style="display:flex;flex-direction:column;gap:1.5rem;">
      <div style="display:flex;align-items:center;gap:1rem;">
        <h3 style="color:#f1f5f9;margin:0;font-size:1.1rem;">Topic Classification</h3>
        <button onClick={handleClassifyAll} style="background:#1e3a5f;color:#60a5fa;border:1px solid #3b82f6;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">Auto-Classify Untagged</button>
        {classifyResult && (
          <span style="color:#34d399;font-size:0.8rem;">Classified {classifyResult.classified} of {classifyResult.total_unclassified}</span>
        )}
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1rem;">
        {topicsData.map(t => (
          <div key={t.id} style={`background:#1e293b;border:1px solid ${selectedTopic === t.name ? '#3b82f6' : '#334155'};border-radius:8px;padding:1rem;cursor:pointer;`} onClick={() => handleTopicClick(t.name)}>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
              <span style="color:#60a5fa;font-weight:600;font-size:0.9rem;">{t.name}</span>
            </div>
            <div style="display:flex;gap:1rem;color:#94a3b8;font-size:0.8rem;">
              <span>{t.question_count} questions</span>
              <span>{t.asset_count} assets</span>
            </div>
            {t.description && <p style="color:#64748b;font-size:0.75rem;margin:0.5rem 0 0 0;">{t.description}</p>}
            {t.assets && t.assets.length > 0 && (
              <div style="margin-top:0.5rem;border-top:1px solid #334155;padding-top:0.5rem;" onClick={e => e.stopPropagation()}>
                {t.assets.slice(0, 5).map(a => (
                  <div key={a.id} style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.25rem;">
                    <span style={`font-size:0.7rem;color:#e2e8f0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;${t.leading_asset_id === a.id ? 'font-weight:600;color:#34d399;' : ''}`}>
                      {t.leading_asset_id === a.id ? '★ ' : ''}{a.filename}
                    </span>
                    {t.leading_asset_id !== a.id && (
                      <button onClick={() => handleSetLeading(t.id, a.id)} style="background:none;border:1px solid #334155;color:#a78bfa;border-radius:3px;padding:0.1rem 0.3rem;font-size:0.65rem;cursor:pointer;white-space:nowrap;">
                        Set Lead
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {selectedTopic && (
        <div style="background:#0f172a;border:1px solid #334155;border-radius:8px;padding:1rem;">
          <h4 style="color:#f1f5f9;margin:0 0 0.75rem 0;font-size:1rem;">Questions in "{selectedTopic}"</h4>
          {questionsLoading ? (
            <div style="color:#94a3b8;font-size:0.85rem;">Loading questions...</div>
          ) : questions.length === 0 ? (
            <div style="color:#64748b;font-size:0.85rem;">No questions found for this topic.</div>
          ) : (
            <div style="display:flex;flex-direction:column;gap:0.5rem;max-height:400px;overflow-y:auto;">
              {questions.map(q => (
                <div key={q.id} style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:0.6rem 0.8rem;display:flex;align-items:center;gap:0.75rem;">
                  <div style="flex:1;min-width:0;">
                    <div style="color:#e2e8f0;font-size:0.82rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{q.question_text}</div>
                    <div style="color:#64748b;font-size:0.7rem;margin-top:0.2rem;">
                      {q.user_email} &middot; {q.created_at ? new Date(q.created_at).toLocaleDateString() : ''}
                    </div>
                  </div>
                  {q.session_id && (
                    <a href={`#/qa?session=${q.session_id}`} style="color:#60a5fa;font-size:0.7rem;white-space:nowrap;text-decoration:none;border:1px solid #3b82f6;border-radius:4px;padding:0.2rem 0.4rem;" onClick={e => e.stopPropagation()}>
                      View Chat
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FeedbackTab() {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadFeedback(); }, []);

  async function loadFeedback(f) {
    setLoading(true);
    try {
      const d = await fetchFeedbackAnalytics({ filter: f || undefined, limit: 50 });
      setData(d);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  function handleFilter(f) {
    setFilter(f);
    loadFeedback(f);
  }

  if (loading) return <div style="padding:1rem;color:#94a3b8;">Loading feedback...</div>;
  if (!data) return null;

  return (
    <div style="display:flex;flex-direction:column;gap:1.5rem;">
      <div>
        <h3 style="color:#f1f5f9;margin:0 0 1rem 0;font-size:1.1rem;">Feedback Summary</h3>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:1rem;">
          <StatCard label="Total Feedback" value={data.total} color="#f1f5f9" />
          <StatCard label="Positive" value={data.positive} color="#34d399" />
          <StatCard label="Negative" value={data.negative} color="#f87171" />
          <StatCard label="Satisfaction" value={`${data.satisfaction_rate}%`} color={data.satisfaction_rate >= 70 ? '#34d399' : '#fbbf24'} />
        </div>
      </div>

      <div>
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem;">
          <h3 style="color:#f1f5f9;margin:0;font-size:1.1rem;">Recent Feedback</h3>
          <div style="margin-left:auto;display:flex;gap:0.25rem;">
            {['', 'positive', 'negative'].map(f => (
              <button
                key={f}
                onClick={() => handleFilter(f)}
                style={`padding:0.3rem 0.6rem;border-radius:4px;font-size:0.75rem;border:1px solid ${filter === f ? '#3b82f6' : '#334155'};background:${filter === f ? '#1e3a5f' : '#0f172a'};color:${filter === f ? '#60a5fa' : '#94a3b8'};cursor:pointer;`}
              >{f || 'All'}</button>
            ))}
          </div>
        </div>
        <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
            <thead>
              <tr style="border-bottom:1px solid #334155;">
                <th style="text-align:center;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;width:50px;">Rating</th>
                <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Comment</th>
                <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">User</th>
                <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Date</th>
              </tr>
            </thead>
            <tbody>
              {data.feedback.map(f => (
                <tr key={f.id} style="border-bottom:1px solid #0f172a;">
                  <td style="padding:0.5rem 0.75rem;text-align:center;font-size:1.1rem;">
                    {f.rating === 1 ? <span title="Positive" style="color:#34d399;">&#x1F44D;</span> : <span title="Negative" style="color:#f87171;">&#x1F44E;</span>}
                  </td>
                  <td style="padding:0.5rem 0.75rem;color:#e2e8f0;">{f.comment || <span style="color:#64748b;font-style:italic;">No comment</span>}</td>
                  <td style="padding:0.5rem 0.75rem;color:#94a3b8;">{f.user_name || f.user_email}</td>
                  <td style="padding:0.5rem 0.75rem;color:#64748b;font-size:0.75rem;">
                    {f.created_at ? new Date(f.created_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
              {data.feedback.length === 0 && (
                <tr><td colspan="4" style="padding:1rem;color:#64748b;text-align:center;">No feedback yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function FlagsTab() {
  const [data, setData] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadFlags(); }, []);

  async function loadFlags(st) {
    setLoading(true);
    try {
      const d = await fetchAdminFlags({ status: st || undefined, limit: 50 });
      setData(d);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  if (loading) return <div style="padding:1rem;color:#94a3b8;">Loading flags...</div>;
  const flags = data?.flags || [];

  return (
    <div>
      <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;">
        <h3 style="color:#f1f5f9;margin:0;font-size:1.1rem;">Review Flags ({data?.total || 0})</h3>
        <div style="margin-left:auto;display:flex;gap:0.25rem;">
          {['', 'pending', 'reviewed', 'dismissed'].map(s => (
            <button
              key={s}
              onClick={() => { setStatusFilter(s); loadFlags(s); }}
              style={`padding:0.3rem 0.6rem;border-radius:4px;font-size:0.75rem;border:1px solid ${statusFilter === s ? '#3b82f6' : '#334155'};background:${statusFilter === s ? '#1e3a5f' : '#0f172a'};color:${statusFilter === s ? '#60a5fa' : '#94a3b8'};cursor:pointer;`}
            >{s || 'All'}</button>
          ))}
        </div>
      </div>

      <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;overflow:hidden;">
        <table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
          <thead>
            <tr style="border-bottom:1px solid #334155;">
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Reason</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">User</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Status</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Created</th>
              <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Resolved</th>
            </tr>
          </thead>
          <tbody>
            {flags.map(f => (
              <tr key={f.id} style="border-bottom:1px solid #0f172a;">
                <td style="padding:0.5rem 0.75rem;color:#e2e8f0;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{f.reason}</td>
                <td style="padding:0.5rem 0.75rem;color:#94a3b8;">{f.user_name || f.user_email}</td>
                <td style="padding:0.5rem 0.75rem;">
                  <span style={`font-size:0.75rem;color:${f.status === 'pending' ? '#fbbf24' : f.status === 'reviewed' ? '#34d399' : '#94a3b8'};`}>{f.status}</span>
                </td>
                <td style="padding:0.5rem 0.75rem;color:#64748b;font-size:0.75rem;">{f.created_at ? new Date(f.created_at).toLocaleDateString() : '—'}</td>
                <td style="padding:0.5rem 0.75rem;color:#64748b;font-size:0.75rem;">{f.resolved_at ? new Date(f.resolved_at).toLocaleDateString() : '—'}</td>
              </tr>
            ))}
            {flags.length === 0 && <tr><td colspan="5" style="padding:1rem;color:#64748b;text-align:center;">No flags found</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SettingsTab() {
  const [settings, setSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [zettelStatus, setZettelStatus] = useState(null);

  // MCP Servers state
  const [mcpServers, setMcpServers] = useState([]);
  const [mcpForm, setMcpForm] = useState({ name: '', url: '', command: '', args: '' });

  // Agent & Skills state
  const [systemPrefix, setSystemPrefix] = useState('');
  const [skills, setSkills] = useState([]);
  const [editingSkill, setEditingSkill] = useState(null);
  const [skillContent, setSkillContent] = useState('');
  const [skillSaving, setSkillSaving] = useState(false);
  const [editingKeywords, setEditingKeywords] = useState(null);
  const [keywordsText, setKeywordsText] = useState('');
  const [skillPreview, setSkillPreview] = useState(false);
  const [skillSearch, setSkillSearch] = useState('');
  const [skillOriginal, setSkillOriginal] = useState('');
  const [editingSkillName, setEditingSkillName] = useState(null);
  const [skillNameText, setSkillNameText] = useState('');
  const [reflectPrompts, setReflectPrompts] = useState([]);
  const [expandedSkills, setExpandedSkills] = useState(new Set());

  useEffect(() => { loadSettings(); loadAgentConfig(); loadMcp(); loadZettelStatus(); }, []);

  async function loadZettelStatus() {
    try {
      const token = localStorage.getItem('ncx_token');
      const res = await fetch('/api/admin/zettel/status', { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) setZettelStatus(await res.json());
    } catch {}
  }

  async function loadMcp() {
    try { setMcpServers(await fetchMcpServers()); } catch {}
  }

  async function loadSettings() {
    setLoading(true);
    try {
      const s = await fetchAdminSettings();
      // Flatten sections into a flat key-value map for editing
      const flat = {};
      if (s.schema) {
        for (const field of s.schema) {
          flat[field.key] = field.value ?? '';
        }
      } else if (s.settings) {
        // Backward compat: flat settings
        Object.assign(flat, s.settings);
      }
      setSettings(flat);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  async function loadAgentConfig() {
    try {
      const [p, sk] = await Promise.all([fetchSystemPrompt(), fetchSkills()]);
      setSystemPrefix(p.system_prefix || '');
      setSkills(sk.skills || []);
      // Load reflect prompts from settings
      const token = localStorage.getItem('ncx_token');
      const resp = await fetch('/api/admin/settings/reflect_prompts', { headers: { Authorization: `Bearer ${token}` } }).catch(() => null);
      if (resp && resp.ok) {
        const data = await resp.json();
        if (data.value) {
          try { setReflectPrompts(JSON.parse(data.value)); } catch { setReflectPrompts([]); }
        }
      }
    } catch (e) {
      console.error(e);
    }
  }

  function handleChange(key, value) {
    setSettings(prev => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await updateAdminSettings(settings);
      alert('Settings saved');
    } catch (e) {
      alert('Failed: ' + e.message);
    }
    setSaving(false);
  }

  async function handleSavePrompt() {
    try {
      await updateSystemPrompt(systemPrefix);
      alert('System prompt saved');
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleToggleSkill(name, currentEnabled) {
    try {
      await updateSkillConfig(name, { enabled: !currentEnabled });
      await loadAgentConfig();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleSetSkillMode(name, mode) {
    // mode: 'mandatory', 'enabled', 'disabled'
    try {
      if (mode === 'mandatory') {
        await updateSkillConfig(name, { mandatory: true, enabled: true });
      } else if (mode === 'enabled') {
        await updateSkillConfig(name, { mandatory: false, enabled: true });
      } else {
        await updateSkillConfig(name, { mandatory: false, enabled: false });
      }
      await loadAgentConfig();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleSaveSkillName(name) {
    try {
      await updateSkillConfig(name, { display_name: skillNameText });
      setEditingSkillName(null);
      await loadAgentConfig();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function handleEditSkill(name) {
    try {
      const data = await fetchSkillContent(name);
      setEditingSkill(name);
      setSkillContent(data.content || '');
      setSkillOriginal(data.content || '');
      setSkillPreview(false);
      setSkillSearch('');
    } catch (e) {
      alert('Failed to load: ' + e.message);
    }
  }

  async function handleSaveSkillContent() {
    setSkillSaving(true);
    try {
      await updateSkillContent(editingSkill, skillContent);
      setEditingSkill(null);
      setSkillContent('');
      await loadAgentConfig();
      alert('Skill content saved');
    } catch (e) {
      alert('Failed: ' + e.message);
    }
    setSkillSaving(false);
  }

  async function handleSaveKeywords(name) {
    const keywords = keywordsText.split(',').map(k => k.trim()).filter(Boolean);
    try {
      await updateSkillConfig(name, { keywords });
      setEditingKeywords(null);
      setKeywordsText('');
      await loadAgentConfig();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  if (loading) return <div style="padding:1rem;color:#94a3b8;">Loading settings...</div>;

  const settingSections = [
    { section: 'app', label: 'Application', fields: [
      { key: 'app_name', label: 'App Name' },
      { key: 'app_mode', label: 'Mode' },
      { key: 'app_title', label: 'Title' },
      { key: 'app_subtitle', label: 'Subtitle' },
      { key: 'app_logo_icon', label: 'Logo Icon' },
      { key: 'quick_questions', label: 'Quick Questions (comma-sep)' },
      { key: 'allowed_email_domain', label: 'Allowed Email Domain' },
      { key: 'debug', label: 'Debug', type: 'boolean' },
      { key: 'dev_mode', label: 'Dev Mode', type: 'boolean' },
    ]},
    { section: 'database', label: 'Database & Connection', fields: [
      { key: 'database_backend', label: 'Backend', type: 'select', options: ['snowflake', 'postgres'] },
      // Snowflake fields
      { key: 'snowflake_account', label: 'Account Identifier', showWhen: 'snowflake' },
      { key: 'snowflake_user', label: 'Username', showWhen: 'snowflake' },
      { key: 'snowflake_pat', label: 'Auth Token (PAT)', secret: true, showWhen: 'snowflake' },
      { key: 'snowflake_warehouse', label: 'Warehouse', showWhen: 'snowflake' },
      { key: 'snowflake_role', label: 'Role', showWhen: 'snowflake' },
      { key: 'snowflake_database', label: 'Database', showWhen: 'snowflake' },
      { key: 'snowflake_schema', label: 'Schema', showWhen: 'snowflake' },
      // PostgreSQL fields
      { key: 'pg_host', label: 'Host', showWhen: 'postgres', hint: 'e.g. localhost or db.example.com' },
      { key: 'pg_port', label: 'Port', showWhen: 'postgres', type: 'number' },
      { key: 'pg_database', label: 'Database', showWhen: 'postgres' },
      { key: 'pg_user', label: 'Username', showWhen: 'postgres' },
      { key: 'pg_password', label: 'Password', showWhen: 'postgres', secret: true },
    ]},
    { section: 'agent', label: 'Agent', fields: [
      { key: 'agent_provider', label: 'Provider', type: 'select', options: ['cortex', 'openai', 'anthropic', 'ollama'] },
      // Cortex model selector (only when provider = cortex)
      { key: 'agent_model', label: 'Model', type: 'select', showWhen: 'cortex', showWhenKey: 'agent_provider', hint: 'Thinking mode supported on Claude Sonnet 4.5+ and Opus 4.5+', options: [
        'claude-sonnet-4-6',
        'claude-sonnet-4-5',
        'claude-opus-4-8',
        'claude-opus-4-7',
        'claude-opus-4-6',
        'claude-opus-4-5',
        'gpt-5.5',
        'gpt-5.4',
        'gpt-5.2',
      ]},
      { key: 'agent_thinking_effort', label: 'Thinking Effort', type: 'select', showWhen: 'cortex', showWhenKey: 'agent_provider', options: ['low', 'medium', 'high'] },
      { key: 'agent_max_steps', label: 'Max Steps', type: 'number', showWhen: 'cortex', showWhenKey: 'agent_provider' },
      // OpenAI fields
      { key: 'openai_api_key', label: 'API Key', secret: true, showWhen: 'openai', showWhenKey: 'agent_provider' },
      { key: 'openai_base_url', label: 'Base URL', showWhen: 'openai', showWhenKey: 'agent_provider', hint: 'Default: https://api.openai.com/v1' },
      { key: 'openai_model', label: 'Model', showWhen: 'openai', showWhenKey: 'agent_provider' },
      // Anthropic fields
      { key: 'anthropic_api_key', label: 'API Key', secret: true, showWhen: 'anthropic', showWhenKey: 'agent_provider' },
      { key: 'anthropic_model', label: 'Model', showWhen: 'anthropic', showWhenKey: 'agent_provider' },
      // Ollama fields
      { key: 'ollama_base_url', label: 'Base URL', showWhen: 'ollama', showWhenKey: 'agent_provider', hint: 'Default: http://localhost:11434' },
      { key: 'ollama_model', label: 'Model', showWhen: 'ollama', showWhenKey: 'agent_provider' },
      // Common fields
      { key: 'agent_log_internal', label: 'Log Internal Dialogue', type: 'boolean' },
    ]},
    { section: 'embeddings', label: 'Embeddings', fields: [
      { key: 'embedding_provider', label: 'Provider', type: 'select', options: ['snowflake', 'openai', 'ollama', 'none'] },
      // Snowflake embedding
      { key: 'embedding_model', label: 'Model', showWhen: 'snowflake', showWhenKey: 'embedding_provider', hint: 'e.g. snowflake-arctic-embed-l-v2.0, e5-base-v2' },
      // OpenAI embedding
      { key: 'embedding_model_openai', label: 'Model', showWhen: 'openai', showWhenKey: 'embedding_provider', hint: 'e.g. text-embedding-3-small, text-embedding-3-large' },
      // Ollama embedding
      { key: 'embedding_model_ollama', label: 'Model', showWhen: 'ollama', showWhenKey: 'embedding_provider', hint: 'e.g. nomic-embed-text, mxbai-embed-large' },
      // Common
      { key: 'embedding_dimensions', label: 'Dimensions', type: 'number', hint: 'Must match the model output size' },
      { key: 'similarity_threshold', label: 'Similarity Threshold', type: 'number' },
    ]},
    { section: 'assets', label: 'Assets & Files', fields: [
      { key: 'asset_ttl_days', label: 'Asset TTL (days)', type: 'number' },
      { key: 'max_files_per_message', label: 'Files per Message', type: 'number' },
      { key: 'max_file_size_mb', label: 'Max File Size (MB)', type: 'number' },
      { key: 'max_user_files', label: 'Max User Files', type: 'number' },
      { key: 'allowed_file_types', label: 'Allowed File Types' },
      { key: 'upload_dir', label: 'Upload Directory' },
    ]},
    { section: 'smtp', label: 'Email (SMTP)', fields: [
      { key: 'smtp_host', label: 'Host' },
      { key: 'smtp_port', label: 'Port', type: 'number' },
      { key: 'smtp_user', label: 'User' },
      { key: 'smtp_password', label: 'Password', secret: true },
      { key: 'smtp_from_email', label: 'From Email' },
      { key: 'magic_link_expire_minutes', label: 'Magic Link Expiry (min)', type: 'number' },
      { key: 'magic_link_base_url', label: 'Magic Link Base URL' },
    ]},
    { section: 'auth', label: 'Auth', fields: [
      { key: 'secret_key', label: 'Secret Key', secret: true },
      { key: 'access_token_expire_minutes', label: 'Token Expiry (min)', type: 'number' },
      { key: 'oauth_base_url', label: 'OAuth Base URL' },
    ]},
    { section: 'zettel', label: 'Chat Memory Index', fields: [
      { key: 'zettel_provider', label: 'Provider' },
      { key: 'zettel_max_zettels', label: 'Max Zettels', type: 'number' },
      { key: 'zettel_persist_dir', label: 'Persist Dir' },
      { key: 'zettel_connection_threshold', label: 'Connection Threshold', type: 'number' },
    ]},
  ];

  return (
    <div style="display:flex;flex-direction:column;gap:1.5rem;">
      {/* Configuration - all sections */}
      <div>
        <div style="display:flex;align-items:center;gap:1rem;margin-bottom:1rem;">
          <h3 style="color:#f1f5f9;margin:0;font-size:1.1rem;">Configuration</h3>
          <span style="color:#64748b;font-size:0.7rem;">config.toml</span>
          <button onClick={handleSave} disabled={saving} style="margin-left:auto;background:#059669;color:white;border:none;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">{saving ? 'Saving...' : 'Save All'}</button>
        </div>

        {settingSections.map(sec => (
          <details key={sec.section} open={sec.section === 'agent' || sec.section === 'database' || sec.section === 'zettel'} style="margin-bottom:0.75rem;">
            <summary style="cursor:pointer;color:#e2e8f0;font-weight:600;font-size:0.9rem;padding:0.5rem 0.75rem;background:#1e293b;border:1px solid #334155;border-radius:6px;user-select:none;">
              {sec.label}
              {sec.section === 'zettel' && zettelStatus && (
                <span style={`margin-left:0.75rem;font-size:0.7rem;font-weight:500;padding:0.15rem 0.5rem;border-radius:9999px;${zettelStatus.active ? 'background:#065f46;color:#6ee7b7;' : 'background:#7f1d1d;color:#fca5a5;'}`}>
                  {zettelStatus.active ? 'ACTIVE' : 'INACTIVE'}
                </span>
              )}
            </summary>
            <div style="background:#1e293b;border:1px solid #334155;border-top:none;border-radius:0 0 6px 6px;padding:1rem;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:1rem;">
              {sec.fields.filter(f => {
                if (!f.showWhen) return true;
                const checkKey = f.showWhenKey || 'database_backend';
                return f.showWhen === settings[checkKey];
              }).map(f => (
                <div key={f.key}>
                  <label style="color:#94a3b8;font-size:0.75rem;display:block;margin-bottom:0.25rem;">{f.label}</label>
                  {f.hint && <span style="color:#64748b;font-size:0.7rem;display:block;margin-bottom:0.3rem;">{f.hint}</span>}
                  {f.type === 'boolean' ? (
                    <button
                      onClick={() => handleChange(f.key, settings[f.key] === true || settings[f.key] === 'true' ? 'false' : 'true')}
                      style={`background:none;border:1px solid #334155;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.8rem;cursor:pointer;color:${settings[f.key] === true || settings[f.key] === 'true' ? '#34d399' : '#f87171'};`}
                    >{settings[f.key] === true || settings[f.key] === 'true' ? 'true' : 'false'}</button>
                  ) : f.type === 'select' ? (
                    <select
                      value={settings[f.key] ?? ''}
                      onChange={e => handleChange(f.key, e.target.value)}
                      style="width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.4rem 0.6rem;font-size:0.85rem;box-sizing:border-box;"
                    >
                      {f.options.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input
                      type={f.secret ? 'password' : f.type || 'text'}
                      value={settings[f.key] ?? ''}
                      onInput={e => handleChange(f.key, e.target.value)}
                      style="width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.4rem 0.6rem;font-size:0.85rem;box-sizing:border-box;"
                      placeholder={f.secret ? '••••••••' : ''}
                    />
                  )}
                </div>
              ))}
            </div>
            {sec.section === 'zettel' && zettelStatus && (
              <div style="background:#0f172a;border:1px solid #334155;border-top:none;border-radius:0 0 6px 6px;padding:1rem;">
                <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.75rem;">
                  <span style={`display:inline-block;width:8px;height:8px;border-radius:50%;${zettelStatus.active ? 'background:#34d399;box-shadow:0 0 6px #34d399;' : 'background:#f87171;'}`}></span>
                  <span style="color:#e2e8f0;font-size:0.85rem;font-weight:600;">
                    {zettelStatus.active ? 'Plugin: zettelkasten' : 'Plugin not active'}
                  </span>
                </div>
                {zettelStatus.active && (
                  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.75rem;margin-bottom:0.75rem;">
                    <div style="background:#1e293b;border-radius:6px;padding:0.6rem 0.75rem;text-align:center;">
                      <div style="color:#94a3b8;font-size:0.65rem;text-transform:uppercase;letter-spacing:0.05em;">Chat Projects</div>
                      <div style="color:#f1f5f9;font-size:1.2rem;font-weight:700;">{zettelStatus.project_count || 0}</div>
                    </div>
                    <div style="background:#1e293b;border-radius:6px;padding:0.6rem 0.75rem;text-align:center;">
                      <div style="color:#94a3b8;font-size:0.65rem;text-transform:uppercase;letter-spacing:0.05em;">Total Memories</div>
                      <div style="color:#f1f5f9;font-size:1.2rem;font-weight:700;">{zettelStatus.total_entries || 0}</div>
                    </div>
                    <div style="background:#1e293b;border-radius:6px;padding:0.6rem 0.75rem;text-align:center;">
                      <div style="color:#94a3b8;font-size:0.65rem;text-transform:uppercase;letter-spacing:0.05em;">Assets Indexed</div>
                      <div style="color:#f1f5f9;font-size:1.2rem;font-weight:700;">{zettelStatus.assets_indexed || 0}</div>
                    </div>
                  </div>
                )}
                <p style="color:#64748b;font-size:0.7rem;margin:0;font-style:italic;">
                  Per-project chat memory — conversations build semantic knowledge graphs. Not used for general agent knowledge retrieval.
                </p>
                <p style="color:#475569;font-size:0.65rem;margin:0.4rem 0 0;">
                  Powered by <a href="https://github.com/KellerKev/zettelkasten-memory" target="_blank" rel="noopener" style="color:#60a5fa;text-decoration:none;">KellerKev/zettelkasten-memory</a>
                </p>
              </div>
            )}
          </details>
        ))}
      </div>

      {/* Agent Tools */}
      <AgentToolsPanel />

      {/* Skill Knowledge Graph */}
      <SkillKnowledgePanel />

      {/* System Prompt */}
      <div>
        <div style="display:flex;align-items:center;gap:1rem;margin-bottom:1rem;">
          <h3 style="color:#f1f5f9;margin:0;font-size:1.1rem;">System Prompt Prefix</h3>
          <button onClick={handleSavePrompt} style="margin-left:auto;background:#059669;color:white;border:none;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">Save Prompt</button>
        </div>
        <p style="color:#64748b;font-size:0.75rem;margin:0 0 0.5rem 0;">This text is prepended before mandatory skill content in every agent conversation.</p>
        <textarea
          value={systemPrefix}
          onInput={e => setSystemPrefix(e.target.value)}
          rows={6}
          style="width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:0.75rem;font-size:0.85rem;font-family:monospace;resize:vertical;box-sizing:border-box;"
          placeholder="e.g. You are an expert assistant. Always cite documentation links..."
        />
      </div>

      {/* Reflection Passes */}
      <div>
        <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.5rem;">
          <h3 style="color:#f1f5f9;margin:0;font-size:1.1rem;">Reflection Passes</h3>
          <button onClick={async () => {
            const token = localStorage.getItem('ncx_token');
            await fetch('/api/admin/settings/reflect_prompts', {
              method: 'PUT', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
              body: JSON.stringify({ settings: { reflect_prompts: JSON.stringify(reflectPrompts) } }),
            });
            alert('Reflection prompts saved');
          }} style="margin-left:auto;background:#059669;color:white;border:none;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">Save</button>
        </div>
        <p style="color:#64748b;font-size:0.75rem;margin:0 0 0.75rem 0;">
          Configure L1, L2, L3... reflection passes. Each pass reviews the agent's response before it's shown to the user. If the LLM responds "LGTM", the pass is done. Otherwise, the corrected response replaces the original.
        </p>
        <div style="display:flex;flex-direction:column;gap:0.5rem;">
          {reflectPrompts.map((prompt, i) => (
            <div key={i} style="display:flex;gap:0.5rem;align-items:flex-start;">
              <span style="color:#60a5fa;font-weight:600;font-size:0.8rem;min-width:24px;padding-top:0.4rem;">L{i + 1}</span>
              <textarea
                value={prompt}
                onInput={e => { const next = [...reflectPrompts]; next[i] = e.target.value; setReflectPrompts(next); }}
                rows={3}
                style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.5rem;font-size:0.8rem;font-family:monospace;resize:vertical;box-sizing:border-box;"
              />
              <button onClick={() => setReflectPrompts(reflectPrompts.filter((_, j) => j !== i))} style="background:none;border:1px solid #7f1d1d;color:#f87171;border-radius:4px;padding:0.2rem 0.4rem;font-size:0.7rem;cursor:pointer;">x</button>
            </div>
          ))}
          <button onClick={() => setReflectPrompts([...reflectPrompts, 'Review the response for accuracy and completeness. If correct, respond: LGTM. If issues found, produce the COMPLETE corrected response.'])} style="background:#1e293b;border:1px solid #334155;color:#94a3b8;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;align-self:flex-start;">+ Add Pass</button>
        </div>
      </div>

      {/* Skills Management */}
      <div>
        <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.5rem;">
          <h3 style="color:#f1f5f9;margin:0;font-size:1.1rem;">Skills & Engagement</h3>
          <label style="margin-left:auto;background:#1e3a5f;color:#60a5fa;border:1px solid #3b82f6;border-radius:6px;padding:0.3rem 0.6rem;font-size:0.75rem;cursor:pointer;">
            Upload Skill (.zip)
            <input type="file" accept=".zip" style="display:none;" onChange={async (e) => {
              const file = e.target.files[0];
              if (!file) return;
              const formData = new FormData();
              formData.append('file', file);
              const token = localStorage.getItem('ncx_token');
              try {
                const resp = await fetch('/api/admin/skills/upload', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: formData });
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.detail || 'Upload failed');
                alert(`Uploaded ${data.count} file(s): ${data.extracted.join(', ')}`);
                await loadAgentConfig();
              } catch (err) { alert('Upload failed: ' + err.message); }
              e.target.value = '';
            }} />
          </label>
          <button onClick={async () => {
            const token = localStorage.getItem('ncx_token');
            try {
              const resp = await fetch('/api/admin/skills/refresh', { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
              const data = await resp.json();
              if (!resp.ok) throw new Error(data.detail || 'Refresh failed');
              alert(`Skills refreshed: ${data.skills_found} found`);
              await loadAgentConfig();
            } catch (err) { alert('Refresh failed: ' + err.message); }
          }} style="background:#1e293b;color:#94a3b8;border:1px solid #334155;border-radius:6px;padding:0.3rem 0.6rem;font-size:0.75rem;cursor:pointer;">
            Refresh Skills
          </button>
        </div>
        <p style="color:#64748b;font-size:0.75rem;margin:0 0 0.75rem 0;">
          Skills are loaded as companion context when a user's question matches the configured keywords.
          Hover a skill name to see its file path. Upload a .zip to add new skills.
        </p>

        <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
            <thead>
              <tr style="border-bottom:1px solid #334155;">
                <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Skill</th>
                <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Mode</th>
                <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Keywords</th>
                <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Size</th>
                <th style="text-align:left;padding:0.6rem 0.75rem;color:#94a3b8;font-weight:500;">Actions</th>
              </tr>
            </thead>
            <tbody>
              {skills.map(s => (<>
                <tr key={s.name} style="border-bottom:1px solid #0f172a;">
                  <td style="padding:0.5rem 0.75rem;color:#e2e8f0;font-weight:500;">
                    <div style="display:flex;align-items:center;gap:0.3rem;">
                      {s.sub_skills?.length > 0 && (
                        <span
                          style="cursor:pointer;color:#64748b;font-size:0.7rem;width:14px;text-align:center;user-select:none;"
                          onClick={() => setExpandedSkills(prev => { const next = new Set(prev); next.has(s.name) ? next.delete(s.name) : next.add(s.name); return next; })}
                        >{expandedSkills.has(s.name) ? '▼' : '▶'}</span>
                      )}
                      {!s.sub_skills?.length && <span style="width:14px;" />}
                      {editingSkillName === s.name ? (
                        <div style="display:flex;gap:0.25rem;">
                          <input
                            value={skillNameText}
                            onInput={e => setSkillNameText(e.target.value)}
                            style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:3px;padding:0.2rem 0.4rem;font-size:0.75rem;min-width:80px;"
                          />
                          <button onClick={() => handleSaveSkillName(s.name)} style="background:#059669;color:white;border:none;border-radius:3px;padding:0.2rem 0.4rem;font-size:0.65rem;cursor:pointer;">OK</button>
                          <button onClick={() => setEditingSkillName(null)} style="background:none;border:1px solid #334155;color:#94a3b8;border-radius:3px;padding:0.2rem 0.4rem;font-size:0.65rem;cursor:pointer;">X</button>
                        </div>
                      ) : (
                        <span
                          style="cursor:pointer;"
                          onClick={() => { setEditingSkillName(s.name); setSkillNameText(s.display_name || s.name); }}
                          title={`${s.path || s.filename}\nClick to rename`}
                        >{s.display_name || s.name}{s.sub_skills?.length > 0 ? ` (${s.sub_skills.length})` : ''}</span>
                      )}
                    </div>
                  </td>
                  <td style="padding:0.5rem 0.75rem;">
                    <div style="display:flex;gap:2px;align-items:center;">
                      <button
                        onClick={() => handleSetSkillMode(s.name, 'mandatory')}
                        style={`border:1px solid #334155;border-radius:3px 0 0 3px;padding:0.15rem 0.4rem;font-size:0.65rem;cursor:pointer;${s.mandatory ? 'background:#059669;color:white;border-color:#059669;' : 'background:none;color:#64748b;'}`}
                      >MAND</button>
                      <button
                        onClick={() => handleSetSkillMode(s.name, 'enabled')}
                        style={`border:1px solid #334155;border-radius:0;padding:0.15rem 0.4rem;font-size:0.65rem;cursor:pointer;${!s.mandatory && s.enabled ? 'background:#1d4ed8;color:white;border-color:#1d4ed8;' : 'background:none;color:#64748b;'}`}
                      >ON</button>
                      <button
                        onClick={() => handleSetSkillMode(s.name, 'disabled')}
                        style={`border:1px solid #334155;border-radius:0 3px 3px 0;padding:0.15rem 0.4rem;font-size:0.65rem;cursor:pointer;${!s.mandatory && !s.enabled ? 'background:#dc2626;color:white;border-color:#dc2626;' : 'background:none;color:#64748b;'}`}
                      >OFF</button>
                      <button
                        onClick={async () => {
                          try {
                            await updateSkillConfig(s.name, { skip_reflect: !s.skip_reflect });
                            await loadAgentConfig();
                          } catch (e) { alert('Failed: ' + e.message); }
                        }}
                        style={`margin-left:4px;border:1px solid #334155;border-radius:3px;padding:0.15rem 0.4rem;font-size:0.6rem;cursor:pointer;${s.skip_reflect ? 'background:#92400e;color:#fbbf24;border-color:#92400e;' : 'background:none;color:#64748b;'}`}
                        title={s.skip_reflect ? "Verification skipped for this skill" : "Click to skip L1/L2 verification for this skill"}
                      >{s.skip_reflect ? 'NO-V' : 'V'}</button>
                    </div>
                  </td>
                  <td style="padding:0.5rem 0.75rem;max-width:250px;">
                    {editingKeywords === s.name ? (
                      <div style="display:flex;gap:0.25rem;">
                        <input
                          value={keywordsText}
                          onInput={e => setKeywordsText(e.target.value)}
                          style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:3px;padding:0.2rem 0.4rem;font-size:0.7rem;"
                          placeholder="keyword1, keyword2, ..."
                        />
                        <button onClick={() => handleSaveKeywords(s.name)} style="background:#059669;color:white;border:none;border-radius:3px;padding:0.2rem 0.4rem;font-size:0.65rem;cursor:pointer;">OK</button>
                        <button onClick={() => setEditingKeywords(null)} style="background:none;border:1px solid #334155;color:#94a3b8;border-radius:3px;padding:0.2rem 0.4rem;font-size:0.65rem;cursor:pointer;">X</button>
                      </div>
                    ) : (
                      <span
                        style="color:#64748b;font-size:0.7rem;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;max-width:250px;"
                        onClick={() => { setEditingKeywords(s.name); setKeywordsText(s.keywords.join(', ')); }}
                        title="Click to edit keywords"
                      >
                        {s.keywords.length > 0 ? s.keywords.slice(0, 4).join(', ') + (s.keywords.length > 4 ? '...' : '') : 'click to set'}
                      </span>
                    )}
                  </td>
                  <td style="padding:0.5rem 0.75rem;color:#64748b;font-size:0.75rem;">
                    {(s.size / 1024).toFixed(1)}KB
                  </td>
                  <td style="padding:0.5rem 0.75rem;">
                    <button onClick={() => handleEditSkill(s.name)} style="background:none;border:1px solid #334155;color:#60a5fa;border-radius:4px;padding:0.2rem 0.5rem;font-size:0.7rem;cursor:pointer;">
                      Edit
                    </button>
                  </td>
                </tr>
                {expandedSkills.has(s.name) && s.sub_skills?.map(sub => (
                  <tr key={sub.name} style="border-bottom:1px solid #0f172a;background:#0c1222;">
                    <td style="padding:0.3rem 0.75rem 0.3rem 2.5rem;color:#94a3b8;font-size:0.8rem;">
                      {sub.short_name}
                    </td>
                    <td style="padding:0.3rem 0.75rem;">
                      <button
                        onClick={async () => {
                          try {
                            await updateSkillConfig(sub.name, { skip_reflect: !sub.skip_reflect });
                            await loadAgentConfig();
                          } catch (e) { alert('Failed: ' + e.message); }
                        }}
                        style={`border:1px solid #334155;border-radius:3px;padding:0.15rem 0.4rem;font-size:0.6rem;cursor:pointer;${sub.skip_reflect ? 'background:#92400e;color:#fbbf24;border-color:#92400e;' : 'background:none;color:#64748b;'}`}
                        title={sub.skip_reflect ? "Verification skipped" : "Click to skip verification"}
                      >{sub.skip_reflect ? 'NO-V' : 'V'}</button>
                    </td>
                    <td style="padding:0.3rem 0.75rem;color:#475569;font-size:0.7rem;" colSpan="3">
                      sub-skill
                    </td>
                  </tr>
                ))}
              </>))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Skill Content Editor - Full Panel */}
      {editingSkill && (() => {
        const lines = skillContent.split('\n');
        const lineCount = lines.length;
        const wordCount = skillContent.split(/\s+/).filter(Boolean).length;
        const charCount = skillContent.length;
        const isDirty = skillContent !== skillOriginal;
        const headings = lines
          .map((line, i) => ({ line: i, text: line }))
          .filter(h => h.text.startsWith('#'));
        const searchMatches = skillSearch
          ? lines.reduce((acc, line, i) => line.toLowerCase().includes(skillSearch.toLowerCase()) ? acc + 1 : acc, 0)
          : 0;

        return (
          <div style="position:fixed;inset:0;background:#0f172a;display:flex;flex-direction:column;z-index:1000;">
            {/* Header */}
            <div style="display:flex;align-items:center;padding:0.75rem 1rem;border-bottom:1px solid #334155;background:#1e293b;gap:0.75rem;flex-shrink:0;">
              <h3 style="color:#f1f5f9;margin:0;font-size:1rem;white-space:nowrap;">
                {editingSkill}
              </h3>
              <div style="display:flex;gap:0.75rem;color:#64748b;font-size:0.7rem;align-items:center;">
                <span>{lineCount} lines</span>
                <span>{wordCount} words</span>
                <span>{(charCount / 1024).toFixed(1)}KB</span>
                {isDirty && <span style="color:#fbbf24;font-weight:600;">unsaved</span>}
              </div>

              {/* Tabs */}
              <div style="display:flex;gap:0.25rem;margin-left:1rem;">
                <button
                  onClick={() => setSkillPreview(false)}
                  style={`padding:0.3rem 0.6rem;border-radius:4px;font-size:0.75rem;cursor:pointer;border:1px solid #334155;${!skillPreview ? 'background:#334155;color:#e2e8f0;' : 'background:none;color:#64748b;'}`}
                >Edit</button>
                <button
                  onClick={() => setSkillPreview(true)}
                  style={`padding:0.3rem 0.6rem;border-radius:4px;font-size:0.75rem;cursor:pointer;border:1px solid #334155;${skillPreview ? 'background:#334155;color:#e2e8f0;' : 'background:none;color:#64748b;'}`}
                >Preview</button>
              </div>

              {/* Search */}
              <div style="display:flex;align-items:center;gap:0.25rem;margin-left:auto;">
                <input
                  type="text"
                  value={skillSearch}
                  onInput={e => setSkillSearch(e.target.value)}
                  placeholder="Search..."
                  style="background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.3rem 0.5rem;font-size:0.75rem;width:150px;"
                />
                {skillSearch && <span style="color:#64748b;font-size:0.65rem;white-space:nowrap;">{searchMatches} matches</span>}
              </div>

              <button onClick={handleSaveSkillContent} disabled={skillSaving || !isDirty} style={`background:#059669;color:white;border:none;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;opacity:${!isDirty ? '0.4' : '1'};`}>
                {skillSaving ? 'Saving...' : 'Save'}
              </button>
              <button onClick={() => { if (!isDirty || confirm('Discard unsaved changes?')) { setEditingSkill(null); setSkillContent(''); setSkillOriginal(''); }}} style="background:none;border:1px solid #334155;color:#94a3b8;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.8rem;cursor:pointer;">
                Close
              </button>
            </div>

            {/* Body */}
            <div style="flex:1;display:flex;overflow:hidden;">
              {/* Section Navigator */}
              <div style="width:220px;border-right:1px solid #334155;overflow-y:auto;padding:0.5rem;flex-shrink:0;background:#1a2332;">
                <div style="color:#94a3b8;font-size:0.65rem;font-weight:600;text-transform:uppercase;margin-bottom:0.5rem;padding:0.25rem 0.5rem;">Sections</div>
                {headings.length === 0 && <div style="color:#475569;font-size:0.7rem;padding:0.25rem 0.5rem;">No headings found</div>}
                {headings.map((h, i) => {
                  const level = h.text.match(/^#+/)[0].length;
                  const label = h.text.replace(/^#+\s*/, '');
                  return (
                    <div
                      key={i}
                      onClick={() => {
                        setSkillPreview(false);
                        const ta = document.getElementById('skill-editor-textarea');
                        if (ta) {
                          const pos = lines.slice(0, h.line).join('\n').length + 1;
                          ta.focus();
                          ta.setSelectionRange(pos, pos);
                          const lineHeight = 18;
                          ta.scrollTop = h.line * lineHeight - 100;
                        }
                      }}
                      style={`padding:0.2rem 0.5rem;padding-left:${(level - 1) * 0.75 + 0.5}rem;color:${level <= 2 ? '#e2e8f0' : '#94a3b8'};font-size:${level <= 2 ? '0.75rem' : '0.7rem'};cursor:pointer;border-radius:3px;margin-bottom:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;`}
                      title={label}
                    >
                      {label}
                    </div>
                  );
                })}
              </div>

              {/* Editor / Preview */}
              <div style="flex:1;overflow:auto;">
                {!skillPreview ? (
                  <textarea
                    id="skill-editor-textarea"
                    value={skillContent}
                    onInput={e => setSkillContent(e.target.value)}
                    style="width:100%;height:100%;background:#0f172a;color:#e2e8f0;border:none;padding:1rem 1.5rem;font-size:0.85rem;font-family:'JetBrains Mono',monospace;line-height:1.6;resize:none;outline:none;tab-size:2;box-sizing:border-box;"
                    spellcheck={false}
                  />
                ) : (
                  <div
                    style="padding:1.5rem 2rem;color:#e2e8f0;font-size:0.9rem;line-height:1.7;max-width:800px;"
                    dangerouslySetInnerHTML={{ __html: (() => { try { return marked.parse(skillContent, { breaks: true }); } catch { return skillContent; } })() }}
                  />
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* MCP Servers */}
      <div>
        <h3 style="color:#f1f5f9;margin:0 0 0.5rem;font-size:1.1rem;">MCP Servers</h3>
        <p style="color:#64748b;font-size:0.75rem;margin:0 0 0.75rem 0;">
          Model Context Protocol servers provide external tools and data sources to the agent.
        </p>

        {mcpServers.length > 0 && (
          <div style="display:grid;gap:0.5rem;margin-bottom:1rem;">
            {mcpServers.map(s => (
              <div key={s.name} style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:0.6rem 0.75rem;display:flex;align-items:center;justify-content:space-between;">
                <div>
                  <span style={`color:${s.enabled ? '#22c55e' : '#64748b'};margin-right:0.4rem;`}>●</span>
                  <span style="color:#e2e8f0;font-weight:600;font-size:0.85rem;">{s.name}</span>
                  <span style="color:#64748b;font-size:0.75rem;margin-left:0.5rem;">{s.url || s.command || ''}</span>
                </div>
                <div style="display:flex;gap:0.4rem;">
                  <button onClick={async () => { await toggleMcpServer(s.name); loadMcp(); }}
                    style="padding:0.2rem 0.5rem;border-radius:4px;border:1px solid #475569;background:transparent;color:#94a3b8;cursor:pointer;font-size:0.7rem;"
                  >{s.enabled ? 'Disable' : 'Enable'}</button>
                  <button onClick={async () => { await removeMcpServer(s.name); loadMcp(); }}
                    style="padding:0.2rem 0.5rem;border-radius:4px;border:1px solid #7f1d1d;background:transparent;color:#ef4444;cursor:pointer;font-size:0.7rem;"
                  >Remove</button>
                </div>
              </div>
            ))}
          </div>
        )}

        <form onSubmit={async (e) => { e.preventDefault(); if (!mcpForm.name || (!mcpForm.url && !mcpForm.command)) return; try { await addMcpServer(mcpForm.name, mcpForm.url, { command: mcpForm.command || undefined, args: mcpForm.args || undefined }); setMcpForm({ name: '', url: '', command: '', args: '' }); loadMcp(); } catch (err) { alert('Failed: ' + err.message); } }} style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:0.75rem;display:grid;gap:0.4rem;">
          <div style="display:flex;gap:0.4rem;">
            <input value={mcpForm.name} onInput={e => setMcpForm(p => ({...p, name: e.target.value}))} placeholder="Name" style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.5rem;font-size:0.8rem;" />
            <input value={mcpForm.url} onInput={e => setMcpForm(p => ({...p, url: e.target.value}))} placeholder="URL (https://...)" style="flex:2;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.5rem;font-size:0.8rem;" />
          </div>
          <div style="display:flex;gap:0.4rem;">
            <input value={mcpForm.command} onInput={e => setMcpForm(p => ({...p, command: e.target.value}))} placeholder="Or command" style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.5rem;font-size:0.8rem;" />
            <input value={mcpForm.args} onInput={e => setMcpForm(p => ({...p, args: e.target.value}))} placeholder="Args (JSON)" style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.5rem;font-size:0.8rem;" />
            <button type="submit" style="background:#3b82f6;color:white;border:none;border-radius:4px;padding:0.35rem 0.75rem;font-size:0.8rem;cursor:pointer;">Add</button>
          </div>
        </form>
      </div>
    </div>
  );
}


function AgentToolsPanel() {
  const [tools, setTools] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadTools(); }, []);

  async function loadTools() {
    setLoading(true);
    const token = localStorage.getItem('ncx_token');
    try {
      const res = await fetch('/api/admin/tools', { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) setTools((await res.json()).tools || []);
    } catch {}
    setLoading(false);
  }

  async function toggleTool(name, enabled) {
    const token = localStorage.getItem('ncx_token');
    await fetch(`/api/admin/tools/${name}`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    loadTools();
  }

  if (loading) return null;

  return (
    <div>
      <h3 style="color:#f1f5f9;margin:0 0 0.75rem 0;font-size:1.1rem;">Agent Tools</h3>
      <p style="color:#64748b;font-size:0.75rem;margin:0 0 0.75rem 0;">
        Tools available to the agent during conversations. Disable a tool to prevent the agent from using it.
      </p>
      <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
        {tools.map(t => (
          <div key={t.name} style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:0.6rem 1rem;display:flex;align-items:center;gap:0.75rem;">
            <span style={`display:inline-block;width:8px;height:8px;border-radius:50%;${t.enabled ? 'background:#34d399;' : 'background:#f87171;'}`}></span>
            <span style="color:#e2e8f0;font-size:0.85rem;font-weight:500;">{t.name}</span>
            <button
              onClick={() => toggleTool(t.name, !t.enabled)}
              style={`margin-left:0.5rem;border:1px solid ${t.enabled ? '#065f46' : '#7f1d1d'};background:none;color:${t.enabled ? '#6ee7b7' : '#fca5a5'};border-radius:4px;padding:0.2rem 0.5rem;font-size:0.7rem;cursor:pointer;`}
            >
              {t.enabled ? 'Enabled' : 'Disabled'}
            </button>
          </div>
        ))}
        {tools.length === 0 && <span style="color:#64748b;font-size:0.8rem;">No tools configured</span>}
      </div>
    </div>
  );
}


function SkillKnowledgePanel() {
  const [kgStats, setKgStats] = useState(null);
  const [kgConfig, setKgConfig] = useState(null);
  const [kgQuery, setKgQuery] = useState('');
  const [kgDomain, setKgDomain] = useState('');
  const [kgResults, setKgResults] = useState(null);
  const [kgEntries, setKgEntries] = useState(null);
  const [kgLoading, setKgLoading] = useState(false);
  const [kgOpen, setKgOpen] = useState(true);
  const [kgGraph, setKgGraph] = useState(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const canvasRef = useRef(null);

  const DOMAIN_COLORS = {
    'knowledge-agent': '#3b82f6', 'interactive': '#10b981', 'investigation': '#8b5cf6',
    'sql-author': '#f59e0b', 'skill_development': '#ec4899', 'find-skill': '#06b6d4',
    'unknown': '#475569',
  };

  useEffect(() => { loadKgStats(); }, []);

  async function loadKgStats() {
    const token = localStorage.getItem('ncx_token');
    const headers = { Authorization: `Bearer ${token}` };
    try {
      const [stats, config] = await Promise.all([
        fetch('/api/admin/knowledge/stats', { headers }).then(r => r.json()),
        fetch('/api/admin/knowledge/config', { headers }).then(r => r.json()),
      ]);
      setKgStats(stats);
      setKgConfig(config);
    } catch (e) { console.error('KG stats error:', e); }
  }

  async function handleSearch() {
    if (!kgQuery.trim()) return;
    setKgLoading(true);
    const token = localStorage.getItem('ncx_token');
    try {
      const res = await fetch('/api/admin/knowledge/search', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: kgQuery, domain: kgDomain || undefined, limit: 10, min_score: 0.1 }),
      });
      if (res.ok) setKgResults(await res.json());
    } catch (e) { alert('Search failed: ' + e.message); }
    setKgLoading(false);
  }

  async function handleLoadEntries() {
    setKgLoading(true);
    const token = localStorage.getItem('ncx_token');
    try {
      const url = '/api/admin/knowledge/entries' + (kgDomain ? `?domain=${kgDomain}&limit=50` : '?limit=50');
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) setKgEntries(await res.json());
    } catch (e) { alert('Load entries failed: ' + e.message); }
    setKgLoading(false);
  }

  async function handleReindexAll() {
    if (!confirm('Re-index all skills? This may take a moment.')) return;
    setKgLoading(true);
    const token = localStorage.getItem('ncx_token');
    try {
      const res = await fetch('/api/admin/knowledge/reindex-all', {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        alert(`Re-indexed ${data.skills_indexed} skill(s): ${data.total_entries} total entries`);
        await loadKgStats();
      }
    } catch (e) { alert('Re-index failed: ' + e.message); }
    setKgLoading(false);
  }

  async function handleClear() {
    if (!confirm('Clear ALL knowledge graph entries? This cannot be undone.')) return;
    setKgLoading(true);
    const token = localStorage.getItem('ncx_token');
    try {
      await fetch('/api/admin/knowledge/clear', { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
      alert('Knowledge graph cleared');
      setKgEntries(null);
      setKgResults(null);
      setKgGraph(null);
      await loadKgStats();
    } catch (e) { alert('Clear failed: ' + e.message); }
    setKgLoading(false);
  }

  async function handleSaveConfig() {
    const token = localStorage.getItem('ncx_token');
    try {
      await fetch('/api/admin/knowledge/config', {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(kgConfig),
      });
      alert('Configuration saved');
    } catch (e) { alert('Save failed: ' + e.message); }
  }

  async function handleLoadGraph() {
    setKgLoading(true);
    const token = localStorage.getItem('ncx_token');
    try {
      const res = await fetch('/api/admin/knowledge/graph', { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) setKgGraph(await res.json());
    } catch (e) { alert('Failed to load graph: ' + e.message); }
    setKgLoading(false);
  }

  useEffect(() => {
    if (!kgGraph || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const W = canvas.width = canvas.parentElement.clientWidth || 800;
    const H = canvas.height = 550;
    const { nodes, edges } = kgGraph;
    if (!nodes.length) return;

    function hashCode(str) {
      let h = 0;
      for (let i = 0; i < str.length; i++) h = ((h << 5) - h + str.charCodeAt(i)) | 0;
      return h;
    }
    function seededRandom(seed) {
      const x = Math.sin(seed * 9301 + 49297) * 49297;
      return x - Math.floor(x);
    }

    const domainGroups = {};
    nodes.forEach(n => { (domainGroups[n.domain] = domainGroups[n.domain] || []).push(n); });
    const domains = Object.keys(domainGroups).sort();
    const positions = {};
    const cx = W / 2, cy = H / 2;
    const outerRadius = Math.min(W, H) * 0.38;

    domains.forEach((d, di) => {
      const angle0 = (2 * Math.PI * di) / domains.length;
      const groupNodes = domainGroups[d];
      const groupRadius = 20 + groupNodes.length * 8;
      groupNodes.forEach((n, ni) => {
        const innerAngle = (2 * Math.PI * ni) / groupNodes.length;
        const seed = hashCode(n.id);
        const jitterX = (seededRandom(seed) - 0.5) * 15;
        const jitterY = (seededRandom(seed + 1) - 0.5) * 15;
        positions[n.id] = {
          x: cx + Math.cos(angle0) * outerRadius + Math.cos(innerAngle) * groupRadius + jitterX,
          y: cy + Math.sin(angle0) * outerRadius + Math.sin(innerAngle) * groupRadius + jitterY,
          vx: 0, vy: 0,
        };
      });
    });

    // Force simulation (250 iterations)
    for (let iter = 0; iter < 250; iter++) {
      const cooling = 1 - iter / 250;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = positions[nodes[i].id], b = positions[nodes[j].id];
          let dx = a.x - b.x, dy = a.y - b.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;
          let force = 2000 / (dist * dist);
          const fx = (dx / dist) * force * cooling;
          const fy = (dy / dist) * force * cooling;
          a.vx += fx; a.vy += fy;
          b.vx -= fx; b.vy -= fy;
        }
      }
      const step = Math.max(1, Math.floor(edges.length / 1000));
      for (let i = 0; i < edges.length; i += step) {
        const e = edges[i];
        const a = positions[e.source], b = positions[e.target];
        if (!a || !b) continue;
        let dx = b.x - a.x, dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        let force = (dist - 100) * 0.003 * cooling;
        a.vx += (dx / dist) * force; a.vy += (dy / dist) * force;
        b.vx -= (dx / dist) * force; b.vy -= (dy / dist) * force;
      }
      nodes.forEach(n => {
        const p = positions[n.id];
        p.x += p.vx * 0.3; p.y += p.vy * 0.3;
        p.vx *= 0.5; p.vy *= 0.5;
        p.x = Math.max(50, Math.min(W - 50, p.x));
        p.y = Math.max(50, Math.min(H - 50, p.y));
      });
    }

    const nodeData = nodes.map(n => ({
      ...positions[n.id], ...n,
      r: Math.max(6, Math.min(16, 5 + n.connections * 0.1)),
    }));
    canvas._graphData = { nodeData, edges, positions, W, H };
    canvas._view = canvas._view || { zoom: 1, panX: 0, panY: 0 };
    renderGraph(canvas);
  }, [kgGraph]);

  function renderGraph(canvas) {
    if (!canvas || !canvas._graphData) return;
    const ctx = canvas.getContext('2d');
    const { nodeData, edges, positions, W, H } = canvas._graphData;
    const { zoom, panX, panY } = canvas._view;
    const highlightId = canvas._dragNode ? canvas._dragNode.id : (hoveredNode ? hoveredNode.id : null);

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, W, H);
    ctx.save();
    ctx.translate(panX + W / 2, panY + H / 2);
    ctx.scale(zoom, zoom);
    ctx.translate(-W / 2, -H / 2);

    edges.forEach(e => {
      const a = positions[e.source], b = positions[e.target];
      if (!a || !b) return;
      const isHighlighted = highlightId && (e.source === highlightId || e.target === highlightId);
      ctx.strokeStyle = isHighlighted ? 'rgba(96, 165, 250, 0.5)' : 'rgba(100, 116, 139, 0.08)';
      ctx.lineWidth = isHighlighted ? (1.5 / zoom) : (0.4 / zoom);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    });

    nodeData.forEach(n => {
      const color = DOMAIN_COLORS[n.domain] || DOMAIN_COLORS['unknown'];
      const isActive = n.id === highlightId;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = color; ctx.fill();
      ctx.strokeStyle = isActive ? '#ffffff' : 'rgba(255,255,255,0.3)';
      ctx.lineWidth = isActive ? (2.5 / zoom) : (0.6 / zoom);
      ctx.stroke();
      if (zoom >= 0.5) {
        const label = n.label.replace('skill-' + n.domain + '-', '').replace(/^section:/, '');
        const fontSize = Math.max(6, Math.min(10, 8 / Math.sqrt(zoom)));
        ctx.font = `${fontSize}px sans-serif`;
        ctx.fillStyle = isActive ? '#ffffff' : 'rgba(203, 213, 225, 0.75)';
        ctx.fillText(label, n.x + n.r + 3, n.y + fontSize / 3);
      }
    });

    ctx.restore();
    ctx.fillStyle = '#475569'; ctx.font = '10px sans-serif';
    ctx.fillText(`Zoom: ${zoom.toFixed(1)}x  |  Scroll=zoom  Drag=pan  Hover=details`, 8, H - 8);
  }

  function handleCanvasWheel(e) {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas || !canvas._view) return;
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    canvas._view.zoom = Math.max(0.3, Math.min(5, canvas._view.zoom * delta));
    renderGraph(canvas);
  }

  function handleCanvasMouseDown(e) {
    const canvas = canvasRef.current;
    if (!canvas || !canvas._graphData) return;
    const rect = canvas.getBoundingClientRect();
    const { zoom, panX, panY } = canvas._view;
    const W = canvas._graphData.W, H = canvas._graphData.H;
    const mx = ((e.clientX - rect.left) - panX - W / 2) / zoom + W / 2;
    const my = ((e.clientY - rect.top) - panY - H / 2) / zoom + H / 2;
    const hit = canvas._graphData.nodeData.find(n => Math.hypot(n.x - mx, n.y - my) <= n.r + 3);
    if (hit) { canvas._dragNode = hit; canvas._dragging = null; }
    else { canvas._dragNode = null; canvas._dragging = { startX: e.clientX, startY: e.clientY, startPanX: canvas._view.panX, startPanY: canvas._view.panY }; }
  }

  function handleCanvasMouseMove(e) {
    const canvas = canvasRef.current;
    if (!canvas || !canvas._graphData) return;
    const rect = canvas.getBoundingClientRect();
    const { zoom, panX, panY } = canvas._view;
    const W = canvas._graphData.W, H = canvas._graphData.H;
    if (canvas._dragNode) {
      const mx = ((e.clientX - rect.left) - panX - W / 2) / zoom + W / 2;
      const my = ((e.clientY - rect.top) - panY - H / 2) / zoom + H / 2;
      canvas._dragNode.x = mx; canvas._dragNode.y = my;
      canvas._graphData.positions[canvas._dragNode.id] = { x: mx, y: my };
      renderGraph(canvas); return;
    }
    if (canvas._dragging) {
      canvas._view.panX = canvas._dragging.startPanX + (e.clientX - canvas._dragging.startX);
      canvas._view.panY = canvas._dragging.startPanY + (e.clientY - canvas._dragging.startY);
      renderGraph(canvas); return;
    }
    const mx = ((e.clientX - rect.left) - panX - W / 2) / zoom + W / 2;
    const my = ((e.clientY - rect.top) - panY - H / 2) / zoom + H / 2;
    const hit = canvas._graphData.nodeData.find(n => Math.hypot(n.x - mx, n.y - my) <= n.r + 3);
    if (hit !== hoveredNode) { setHoveredNode(hit || null); renderGraph(canvas); }
    canvas.style.cursor = hit ? 'pointer' : 'grab';
  }

  function handleCanvasMouseUp() {
    const canvas = canvasRef.current;
    if (canvas) { canvas._dragging = null; canvas._dragNode = null; }
  }

  return (
    <div style="margin-top:1.5rem;">
      <div
        onClick={() => { setKgOpen(!kgOpen); if (!kgOpen && !kgStats) loadKgStats(); }}
        style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;padding:0.75rem 1rem;background:#1e293b;border:1px solid #334155;border-radius:8px;user-select:none;"
      >
        <span style="color:#64748b;font-size:0.8rem;">{kgOpen ? '\u25BC' : '\u25B6'}</span>
        <h3 style="margin:0;color:#e2e8f0;font-size:0.9rem;">Skill Knowledge Index & Graph</h3>
        {kgStats && (
          <span style="color:#64748b;font-size:0.75rem;margin-left:auto;">
            {kgStats.total_entries} entries &bull; {kgStats.status}
          </span>
        )}
      </div>

      {kgOpen && (
        <div style="border:1px solid #334155;border-top:none;border-radius:0 0 8px 8px;padding:1rem;background:#0f172a;">
          {/* Stats Bar */}
          {kgStats && (
            <div style="display:flex;gap:1.5rem;margin-bottom:1rem;flex-wrap:wrap;">
              <div style="color:#94a3b8;font-size:0.75rem;"><span style="color:#e2e8f0;font-weight:600;">{kgStats.total_entries}</span> entries</div>
              <div style="color:#94a3b8;font-size:0.75rem;"><span style="color:#e2e8f0;font-weight:600;">{Object.keys(kgStats.domains || {}).length}</span> domains</div>
              <div style="color:#94a3b8;font-size:0.75rem;"><span style="color:#e2e8f0;font-weight:600;">{kgStats.connections || 0}</span> connections</div>
              <div style="color:#94a3b8;font-size:0.75rem;"><span style="color:#e2e8f0;font-weight:600;">{((kgStats.index_size_bytes || 0) / 1024).toFixed(1)}</span>KB index</div>
              <div style="color:#94a3b8;font-size:0.75rem;">Plugin: <span style="color:#60a5fa;">{kgStats.plugin || 'none'}</span></div>
            </div>
          )}

          {/* Domain breakdown */}
          {kgStats?.domains && Object.keys(kgStats.domains).length > 0 && (
            <div style="display:flex;gap:0.4rem;margin-bottom:1rem;flex-wrap:wrap;">
              {Object.entries(kgStats.domains).sort((a, b) => b[1] - a[1]).map(([d, count]) => (
                <span key={d} style="background:#1e293b;border:1px solid #334155;border-radius:4px;padding:0.15rem 0.4rem;font-size:0.65rem;color:#94a3b8;">
                  {d}: <span style="color:#e2e8f0;">{count}</span>
                </span>
              ))}
            </div>
          )}

          {/* Actions */}
          <div style="display:flex;gap:0.5rem;margin-bottom:1rem;flex-wrap:wrap;">
            <button onClick={handleReindexAll} disabled={kgLoading}
              style="background:#1d4ed8;color:white;border:none;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.7rem;cursor:pointer;">
              {kgLoading ? '...' : 'Re-index All'}
            </button>
            <button onClick={handleLoadEntries} disabled={kgLoading}
              style="background:#1e293b;color:#94a3b8;border:1px solid #334155;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.7rem;cursor:pointer;">
              Browse Entries
            </button>
            <button onClick={handleClear} disabled={kgLoading}
              style="background:none;color:#ef4444;border:1px solid #7f1d1d;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.7rem;cursor:pointer;">
              Clear All
            </button>
            <button onClick={loadKgStats} disabled={kgLoading}
              style="background:none;color:#64748b;border:1px solid #334155;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.7rem;cursor:pointer;">
              Refresh Stats
            </button>
            <button onClick={handleLoadGraph} disabled={kgLoading}
              style="background:#1e293b;color:#a78bfa;border:1px solid #5b21b6;border-radius:4px;padding:0.3rem 0.6rem;font-size:0.7rem;cursor:pointer;">
              {kgGraph ? 'Reload Graph' : 'Show Graph'}
            </button>
          </div>

          {/* Graph Visualization */}
          {kgGraph && (
            <div style="margin-bottom:1rem;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.4rem;">
                <span style="color:#94a3b8;font-size:0.7rem;">{kgGraph.nodes.length} nodes, {kgGraph.edges.length} edges</span>
                <button onClick={() => { setKgGraph(null); setHoveredNode(null); }} style="background:none;border:none;color:#64748b;font-size:0.65rem;cursor:pointer;">Close</button>
              </div>
              <div style="position:relative;background:#0f172a;border:1px solid #334155;border-radius:6px;overflow:hidden;">
                <canvas
                  ref={canvasRef}
                  onWheel={handleCanvasWheel}
                  onMouseDown={handleCanvasMouseDown}
                  onMouseMove={handleCanvasMouseMove}
                  onMouseUp={handleCanvasMouseUp}
                  onMouseLeave={() => { handleCanvasMouseUp(); setHoveredNode(null); }}
                  style="width:100%;display:block;cursor:grab;"
                />
              </div>
              {hoveredNode && (
                <div style="margin-top:0.5rem;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:0.6rem 0.75rem;font-size:0.7rem;">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.3rem;">
                    <span style="color:#e2e8f0;font-weight:600;font-size:0.8rem;">{hoveredNode.label.replace(/^section:/, '')}</span>
                    <span style={`padding:0.1rem 0.35rem;border-radius:3px;font-size:0.6rem;color:white;background:${DOMAIN_COLORS[hoveredNode.domain] || '#475569'};`}>{hoveredNode.domain}</span>
                  </div>
                  <div style="color:#94a3b8;margin-bottom:0.4rem;line-height:1.4;">{hoveredNode.summary}</div>
                  <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(140px, 1fr));gap:0.3rem;">
                    <span style="color:#64748b;">Source: <span style="color:#cbd5e1;">{hoveredNode.source}</span></span>
                    <span style="color:#64748b;">Importance: <span style="color:#fbbf24;">{hoveredNode.importance}</span></span>
                    <span style="color:#64748b;">Connections: <span style="color:#60a5fa;">{hoveredNode.connections}</span></span>
                    <span style="color:#64748b;">Accessed: <span style="color:#cbd5e1;">{hoveredNode.access_count}x</span></span>
                  </div>
                  {hoveredNode.tags && hoveredNode.tags.length > 0 && (
                    <div style="display:flex;flex-wrap:wrap;gap:0.2rem;margin-top:0.3rem;">
                      {hoveredNode.tags.slice(0, 12).map(t => (
                        <span key={t} style="background:#0f172a;border:1px solid #334155;border-radius:2px;padding:0.05rem 0.25rem;font-size:0.55rem;color:#94a3b8;">{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {/* Legend */}
              <div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-top:0.4rem;">
                {Object.entries(DOMAIN_COLORS).filter(([d]) => kgGraph.nodes.some(n => n.domain === d)).map(([d, color]) => (
                  <span key={d} style="display:flex;align-items:center;gap:0.2rem;font-size:0.6rem;color:#94a3b8;">
                    <span style={`width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;`} />
                    {d}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Test Search */}
          <div style="margin-bottom:1rem;">
            <div style="display:flex;gap:0.4rem;margin-bottom:0.5rem;">
              <input type="text" value={kgQuery} onInput={e => setKgQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                placeholder="Test search query..."
                style="flex:1;background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.5rem;font-size:0.75rem;" />
              <select value={kgDomain} onChange={e => setKgDomain(e.target.value)}
                style="background:#1e293b;color:#94a3b8;border:1px solid #334155;border-radius:4px;padding:0.35rem 0.4rem;font-size:0.7rem;">
                <option value="">All domains</option>
                {kgStats?.domains && Object.keys(kgStats.domains).sort().map(d => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
              <button onClick={handleSearch} disabled={kgLoading || !kgQuery.trim()}
                style="background:#059669;color:white;border:none;border-radius:4px;padding:0.35rem 0.6rem;font-size:0.7rem;cursor:pointer;">
                Search
              </button>
            </div>
            {kgResults && (
              <div style="background:#1e293b;border:1px solid #334155;border-radius:6px;max-height:300px;overflow-y:auto;">
                <div style="padding:0.4rem 0.6rem;border-bottom:1px solid #334155;color:#64748b;font-size:0.65rem;">
                  {kgResults.count} result(s) for \"{kgResults.query}\"{kgResults.domain ? ` in ${kgResults.domain}` : ''}
                </div>
                {kgResults.results.map((r, i) => (
                  <div key={i} style="padding:0.5rem 0.6rem;border-bottom:1px solid #0f172a;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:0.2rem;">
                      <span style="color:#60a5fa;font-size:0.7rem;font-weight:500;">{r.tags?.find(t => t.startsWith('section:'))?.slice(8) || r.id?.slice(0, 8)}</span>
                      <span style="color:#fbbf24;font-size:0.65rem;font-weight:600;">{((r.score || 0) * 100).toFixed(1)}%</span>
                    </div>
                    <div style="color:#cbd5e1;font-size:0.7rem;line-height:1.3;white-space:pre-wrap;max-height:80px;overflow:hidden;">{r.content?.slice(0, 200)}</div>
                    <div style="display:flex;gap:0.25rem;margin-top:0.3rem;flex-wrap:wrap;">
                      {r.tags?.filter(t => t.startsWith('domain:')).map(t => (
                        <span key={t} style="background:#1d4ed8;color:#93c5fd;padding:0 0.3rem;border-radius:2px;font-size:0.55rem;">{t.slice(7)}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Entries Browser */}
          {kgEntries && (
            <div style="margin-bottom:1rem;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.4rem;">
                <span style="color:#94a3b8;font-size:0.7rem;">{kgEntries.count} entries</span>
                <button onClick={() => setKgEntries(null)} style="background:none;border:none;color:#64748b;font-size:0.65rem;cursor:pointer;">Close</button>
              </div>
              <div style="background:#1e293b;border:1px solid #334155;border-radius:6px;max-height:250px;overflow-y:auto;">
                <table style="width:100%;border-collapse:collapse;font-size:0.7rem;">
                  <thead>
                    <tr style="border-bottom:1px solid #334155;">
                      <th style="text-align:left;padding:0.3rem 0.5rem;color:#64748b;">Section</th>
                      <th style="text-align:left;padding:0.3rem 0.5rem;color:#64748b;">Domain</th>
                      <th style="text-align:left;padding:0.3rem 0.5rem;color:#64748b;">Content</th>
                      <th style="text-align:right;padding:0.3rem 0.5rem;color:#64748b;">Importance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {kgEntries.entries.map((e, i) => (
                      <tr key={i} style="border-bottom:1px solid #0f172a;">
                        <td style="padding:0.25rem 0.5rem;color:#60a5fa;white-space:nowrap;">{e.section_id || e.id?.slice(0, 8)}</td>
                        <td style="padding:0.25rem 0.5rem;color:#94a3b8;white-space:nowrap;">{e.domain}</td>
                        <td style="padding:0.25rem 0.5rem;color:#cbd5e1;max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{e.content}</td>
                        <td style="padding:0.25rem 0.5rem;color:#fbbf24;text-align:right;">{e.importance}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Configuration */}
          {kgConfig && (
            <div style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:0.75rem;">
              <div style="color:#94a3b8;font-size:0.7rem;font-weight:600;margin-bottom:0.5rem;">Retrieval Configuration</div>
              <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(180px, 1fr));gap:0.5rem;">
                <label style="display:flex;align-items:center;gap:0.4rem;color:#94a3b8;font-size:0.7rem;">
                  <input type="checkbox" checked={kgConfig.enabled}
                    onChange={e => setKgConfig({ ...kgConfig, enabled: e.target.checked })} />
                  Enabled
                </label>
                <label style="color:#94a3b8;font-size:0.7rem;">
                  Max results
                  <input type="number" min="1" max="20" value={kgConfig.limit}
                    onInput={e => setKgConfig({ ...kgConfig, limit: parseInt(e.target.value) || 5 })}
                    style="width:50px;margin-left:0.3rem;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:3px;padding:0.15rem 0.3rem;font-size:0.7rem;" />
                </label>
                <label style="color:#94a3b8;font-size:0.7rem;">
                  Min score
                  <input type="number" min="0" max="1" step="0.05" value={kgConfig.min_score}
                    onInput={e => setKgConfig({ ...kgConfig, min_score: parseFloat(e.target.value) || 0.25 })}
                    style="width:55px;margin-left:0.3rem;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:3px;padding:0.15rem 0.3rem;font-size:0.7rem;" />
                </label>
                <label style="color:#94a3b8;font-size:0.7rem;">
                  Max content
                  <input type="number" min="100" max="3000" step="100" value={kgConfig.max_content_len}
                    onInput={e => setKgConfig({ ...kgConfig, max_content_len: parseInt(e.target.value) || 800 })}
                    style="width:60px;margin-left:0.3rem;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:3px;padding:0.15rem 0.3rem;font-size:0.7rem;" />
                </label>
              </div>
              <button onClick={handleSaveConfig} style="margin-top:0.5rem;background:#059669;color:white;border:none;border-radius:4px;padding:0.25rem 0.5rem;font-size:0.7rem;cursor:pointer;">
                Save Config
              </button>
            </div>
          )}

          <p style="color:#475569;font-size:0.65rem;margin:1rem 0 0;">
            Powered by <a href="https://github.com/KellerKev/zettelkasten-memory" target="_blank" rel="noopener" style="color:#60a5fa;text-decoration:none;">KellerKev/zettelkasten-memory</a>
          </p>
        </div>
      )}
    </div>
  );
}
