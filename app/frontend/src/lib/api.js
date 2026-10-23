const API_BASE = '/api';

function getToken() {
  return localStorage.getItem('ncx_token');
}

function headers(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra };
  const t = getToken();
  if (t) h['Authorization'] = `Bearer ${t}`;
  return h;
}

export async function requestMagicLink(email) {
  const resp = await fetch(`${API_BASE}/auth/magic-link`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ email }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Failed to send magic link');
  return resp.json();
}

export async function login(email, password) {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ email, password }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Login failed');
  const data = await resp.json();
  if (data.token) {
    localStorage.setItem('ncx_token', data.token);
    localStorage.setItem('ncx_user', JSON.stringify(data.user));
  }
  return data;
}

export async function register(email, password, displayName) {
  const resp = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Registration failed');
  const data = await resp.json();
  if (data.token) {
    localStorage.setItem('ncx_token', data.token);
    localStorage.setItem('ncx_user', JSON.stringify(data.user));
  }
  return data;
}

export async function verifyMagicLink(token) {
  const resp = await fetch(`${API_BASE}/auth/magic-link/verify`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ token }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Invalid or expired link');
  const data = await resp.json();
  if (data.token) {
    localStorage.setItem('ncx_token', data.token);
    localStorage.setItem('ncx_user', JSON.stringify(data.user));
  }
  return data;
}

export async function passkeyRegisterOptions(mfaToken) {
  const resp = await fetch(`${API_BASE}/auth/passkey/register-options`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ mfa_token: mfaToken || null }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Failed to get registration options');
  return resp.json();
}

export async function passkeyRegisterVerify(credential, mfaToken, deviceName) {
  const resp = await fetch(`${API_BASE}/auth/passkey/register-verify`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ credential, mfa_token: mfaToken || null, device_name: deviceName }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Registration verification failed');
  const data = await resp.json();
  if (data.token) {
    localStorage.setItem('ncx_token', data.token);
    localStorage.setItem('ncx_user', JSON.stringify(data.user));
  }
  return data;
}

export async function passkeyAuthOptions(mfaToken) {
  const resp = await fetch(`${API_BASE}/auth/passkey/auth-options`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ mfa_token: mfaToken }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Failed to get auth options');
  return resp.json();
}

export async function passkeyAuthVerify(mfaToken, credential) {
  const resp = await fetch(`${API_BASE}/auth/passkey/auth-verify`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ mfa_token: mfaToken, credential }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Auth verification failed');
  const data = await resp.json();
  if (data.token) {
    localStorage.setItem('ncx_token', data.token);
    localStorage.setItem('ncx_user', JSON.stringify(data.user));
  }
  return data;
}

export function logout() {
  localStorage.removeItem('ncx_token');
  localStorage.removeItem('ncx_user');
  localStorage.removeItem('ncx_sso');
}

// ---- SSO (SAML + silent Entra OIDC) ----

export function ssoLoginUrl() {
  // Preserve the deep link (hash route) through the SAML + OIDC hops.
  const next = '/' + (window.location.hash || '');
  return `${API_BASE}/auth/saml/login?next=${encodeURIComponent(next)}`;
}

export function completeSsoLogin(hash) {
  const params = new URLSearchParams((hash || '').replace(/^#/, ''));
  const token = params.get('token');
  const user = params.get('user');
  let next = params.get('next') || '/';
  if (!next.startsWith('/') || next.startsWith('//')) next = '/';
  if (token && user) {
    const json = atob(user.replace(/-/g, '+').replace(/_/g, '/'));
    localStorage.setItem('ncx_token', token);
    localStorage.setItem('ncx_user', json);
    localStorage.setItem('ncx_sso', '1');
  }
  window.location.replace(next);
}

export async function ssoLogout() {
  if (!localStorage.getItem('ncx_sso')) return null;
  try {
    const resp = await fetch(`${API_BASE}/auth/sso/logout`, { method: 'POST', headers: headers() });
    if (!resp.ok) return null;
    return (await resp.json()).entra_logout_url || null;
  } catch {
    return null;
  }
}

export async function fetchSsoStatus() {
  return apiFetch(`${API_BASE}/auth/sso/status`);
}

export async function fetchRoleCheck(role, bypassAppAllowlist = false) {
  const qs = new URLSearchParams({ role, bypass_app_allowlist: String(bypassAppAllowlist) });
  return apiFetch(`${API_BASE}/poc/role-check?${qs}`);
}

export function getUser() {
  const u = localStorage.getItem('ncx_user');
  return u ? JSON.parse(u) : null;
}

export function isAuthenticated() {
  return !!getToken();
}

async function apiFetch(url, opts = {}) {
  const resp = await fetch(url, { headers: headers(), ...opts });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${resp.status}`);
  }
  return resp.json();
}

export async function fetchSessions() {
  return apiFetch(`${API_BASE}/sessions`);
}

export async function fetchSession(id) {
  return apiFetch(`${API_BASE}/sessions/${id}`);
}

export async function deleteSession(id) {
  await fetch(`${API_BASE}/sessions/${id}`, { method: 'DELETE', headers: headers() });
}

export async function renameSession(id, title) {
  await fetch(`${API_BASE}/sessions/${id}/rename`, {
    method: 'PUT',
    headers: headers(),
    body: JSON.stringify({ title }),
  });
}

export async function cancelSession(id) {
  await fetch(`${API_BASE}/sessions/${id}/cancel`, {
    method: 'POST',
    headers: headers(),
  });
}

export function createSessionStream(message, { title, model, skip_suggestion, file_ids } = {}) {
  // New approach: POST creates session and launches background task, then connect to SSE
  const controller = new AbortController();
  return {
    controller,
    async *events() {
      const resp = await fetch(`${API_BASE}/sessions`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ message, title, model, skip_suggestion, file_ids }),
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error('Failed to create session');
      const result = await resp.json();

      if (result.type === 'suggestion') {
        yield { event: 'suggestion', data: result };
        return;
      }

      // result.type === 'session'
      const sessionId = result.id;
      yield { event: 'session_created', data: { id: sessionId } };

      // Connect to SSE stream
      const streamResp = await fetch(`${API_BASE}/sessions/${sessionId}/stream`, {
        headers: headers(),
        signal: controller.signal,
      });
      if (!streamResp.ok) throw new Error('Stream connection failed');

      const reader = streamResp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';

      function* parseLines(lines) {
        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            const data = line.slice(5).trim();
            if (data) {
              try {
                yield { event: currentEvent, data: JSON.parse(data) };
              } catch {}
            }
          }
        }
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          if (buffer.trim()) {
            yield* parseLines(buffer.split('\n'));
          }
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        yield* parseLines(lines);
      }
    },
  };
}

export async function createSessionWithSuggestionCheck(message, { title, model, file_ids } = {}) {
  const resp = await fetch(`${API_BASE}/sessions`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ message, title, model, skip_suggestion: false, file_ids }),
  });
  if (!resp.ok) throw new Error('Failed to create session');
  return await resp.json();
}

export function createSessionStreamSkipSuggestion(message, { title, model, question_id, file_ids } = {}) {
  return createSessionSkipAndStream(message, { title, model, question_id, file_ids });
}

export async function createSessionSkipAndStream(message, { title, model, question_id, file_ids } = {}) {
  const resp = await fetch(`${API_BASE}/sessions`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ message, title, model, skip_suggestion: true, question_id, file_ids }),
  });
  if (!resp.ok) throw new Error('Failed to create session');
  return await resp.json();
}

export async function sendMessage(sessionId, message, { model, file_ids } = {}) {
  const resp = await fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ message, model, file_ids }),
  });
  if (!resp.ok) throw new Error('Failed to send message');
  return await resp.json();
}

export function connectSessionStream(sessionId) {
  const controller = new AbortController();

  return {
    controller,
    async *events() {
      const resp = await fetch(`${API_BASE}/sessions/${sessionId}/stream`, {
        headers: headers(),
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error('Stream connection failed');

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';

      function* parseLines(lines) {
        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            const data = line.slice(5).trim();
            if (data) {
              try {
                yield { event: currentEvent, data: JSON.parse(data) };
              } catch {}
            }
          }
        }
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          // Flush remaining buffer on stream close
          if (buffer.trim()) {
            yield* parseLines(buffer.split('\n'));
          }
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        yield* parseLines(lines);
      }
    },
  };
}

export async function stopSession(sessionId) {
  return apiFetch(`${API_BASE}/sessions/${sessionId}/stop`, { method: 'POST' });
}

export async function useAsset(question_id, asset_id) {
  return apiFetch(`${API_BASE}/sessions/use-asset`, {
    method: 'POST',
    body: JSON.stringify({ question_id, asset_id }),
  });
}

export async function registerAssetFromSession(sessionId, { filename, topic } = {}) {
  return apiFetch(`${API_BASE}/sessions/${sessionId}/register-asset`, {
    method: 'POST',
    body: JSON.stringify({ filename, topic }),
  });
}

export function sendMessageStream(sessionId, message, { model, file_ids } = {}) {
  // New approach: POST to launch background task, then connect to SSE stream
  const controller = new AbortController();
  return {
    controller,
    async *events() {
      // First, send the message (launches background task)
      const resp = await fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ message, model, file_ids }),
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error('Failed to send message');

      // Then connect to the SSE stream to get events
      const streamResp = await fetch(`${API_BASE}/sessions/${sessionId}/stream`, {
        headers: headers(),
        signal: controller.signal,
      });
      if (!streamResp.ok) throw new Error('Stream connection failed');

      const reader = streamResp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';

      function* parseLines(lines) {
        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            const data = line.slice(5).trim();
            if (data) {
              try {
                yield { event: currentEvent, data: JSON.parse(data) };
              } catch {}
            }
          }
        }
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          if (buffer.trim()) {
            yield* parseLines(buffer.split('\n'));
          }
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        yield* parseLines(lines);
      }
    },
  };
}

export function resumeStream(response) {
  // resumeStream is no longer used with the background task approach
  // Keep for backward compatibility but unlikely to be called
  return connectSessionStream(response);
}

export async function fetchConfig() {
  const resp = await fetch(`${API_BASE}/config`);
  if (!resp.ok) return { app_mode: 'chat', features: { tasks: false, review: true, qa: true } };
  return resp.json();
}

export async function searchAssets(query) {
  const resp = await fetch(`${API_BASE}/assets/search?query=${encodeURIComponent(query)}`, {
    headers: headers(),
  });
  if (!resp.ok) return [];
  return resp.json();
}

export async function fetchAssets(status) {
  const params = status ? `?status=${status}` : '';
  return apiFetch(`${API_BASE}/assets${params}`);
}

export async function fetchAsset(id) {
  return apiFetch(`${API_BASE}/assets/${id}`);
}

export async function updateAssetStatus(id, status, review_notes) {
  return apiFetch(`${API_BASE}/assets/${id}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status, review_notes }),
  });
}

export async function fetchReviewAssets(status) {
  const params = status ? `?status=${status}` : '';
  return apiFetch(`${API_BASE}/review/assets${params}`);
}

export async function fetchReviewAsset(id) {
  return apiFetch(`${API_BASE}/review/assets/${id}`);
}

export async function reviewAsset(id, status, reject_reason) {
  return apiFetch(`${API_BASE}/review/assets/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ status, reject_reason }),
  });
}

export async function updateAssetContent(id, content, { comment, filename, topic } = {}) {
  return apiFetch(`${API_BASE}/review/assets/${id}/content`, {
    method: 'PATCH',
    body: JSON.stringify({ content, comment, filename, topic }),
  });
}

export async function restoreAssetVersion(assetId, versionId) {
  return apiFetch(`${API_BASE}/review/assets/${assetId}/restore/${versionId}`, {
    method: 'POST',
  });
}

export async function claimReviewAsset(id) {
  return apiFetch(`${API_BASE}/review/assets/${id}/claim`, { method: 'POST' });
}

export async function releaseReviewAsset(id) {
  return apiFetch(`${API_BASE}/review/assets/${id}/claim`, { method: 'DELETE' });
}

export async function transferReviewAsset(id, targetUserId) {
  return apiFetch(`${API_BASE}/review/assets/${id}/claim`, {
    method: 'PUT',
    body: JSON.stringify({ target_user_id: targetUserId }),
  });
}

export async function fetchFlags(status) {
  const params = status ? `?status=${status}` : '';
  return apiFetch(`${API_BASE}/review/flags${params}`);
}

export async function createFlag(session_id, reason) {
  return apiFetch(`${API_BASE}/review/flags`, {
    method: 'POST',
    body: JSON.stringify({ session_id, reason }),
  });
}

export async function resolveFlag(id, status) {
  return apiFetch(`${API_BASE}/review/flags/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
}

export async function fetchAdminStats() {
  return apiFetch(`${API_BASE}/admin/stats`);
}

export async function fetchAdminUsers({ search, role, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (role) params.set('role', role);
  if (limit) params.set('limit', limit);
  if (offset) params.set('offset', offset);
  const qs = params.toString();
  return apiFetch(`${API_BASE}/admin/users${qs ? '?' + qs : ''}`);
}

export async function updateUserRole(userId, role) {
  return apiFetch(`${API_BASE}/admin/users/${userId}/role`, {
    method: 'PUT',
    body: JSON.stringify({ role }),
  });
}

export async function toggleUserActive(userId) {
  return apiFetch(`${API_BASE}/admin/users/${userId}/toggle-active`, {
    method: 'PUT',
  });
}

export async function updateUserEmail(userId, email) {
  return apiFetch(`${API_BASE}/admin/users/${userId}/email`, {
    method: 'PUT',
    body: JSON.stringify({ email }),
  });
}

export async function resetUserPasskeys(userId) {
  return apiFetch(`${API_BASE}/admin/users/${userId}/passkeys`, {
    method: 'DELETE',
  });
}

export async function deleteUser(userId) {
  return apiFetch(`${API_BASE}/admin/users/${userId}`, {
    method: 'DELETE',
  });
}

export async function fetchAdminTopics() {
  return apiFetch(`${API_BASE}/admin/topics`);
}

export async function fetchReuseAnalytics() {
  return apiFetch(`${API_BASE}/admin/analytics/reuse`);
}

export async function fetchQuestionAnalytics({ topic, search, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (topic) params.set('topic', topic);
  if (search) params.set('search', search);
  if (limit) params.set('limit', limit);
  if (offset) params.set('offset', offset);
  const qs = params.toString();
  return apiFetch(`${API_BASE}/admin/analytics/questions${qs ? '?' + qs : ''}`);
}

export async function fetchUserQuestionStats() {
  return apiFetch(`${API_BASE}/admin/analytics/users`);
}

export async function fetchFeedbackAnalytics({ filter, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (filter) params.set('filter', filter);
  if (limit) params.set('limit', limit);
  if (offset) params.set('offset', offset);
  const qs = params.toString();
  return apiFetch(`${API_BASE}/admin/analytics/feedback${qs ? '?' + qs : ''}`);
}

export async function fetchAssetsBySession(sessionId) {
  return apiFetch(`${API_BASE}/assets/by-session/${sessionId}`);
}

export async function fetchMyAssets(visibility) {
  const params = visibility ? `?visibility=${visibility}` : '';
  return apiFetch(`${API_BASE}/assets/mine${params}`);
}

export async function promoteAsset(id) {
  return apiFetch(`${API_BASE}/assets/${id}/promote`, { method: 'PUT' });
}

export async function saveToCollection(sessionId) {
  return apiFetch(`${API_BASE}/sessions/${sessionId}/save-to-collection`, {
    method: 'POST',
  });
}

export async function fetchAssetVersions(assetId) {
  return apiFetch(`${API_BASE}/assets/${assetId}/versions`);
}

export async function fetchAssetVersion(assetId, versionNum) {
  return apiFetch(`${API_BASE}/assets/${assetId}/versions/${versionNum}`);
}

export async function saveAssetEdit(assetId, content, comment) {
  return apiFetch(`${API_BASE}/assets/${assetId}`, {
    method: 'PUT',
    body: JSON.stringify({ content, comment }),
  });
}

export function downloadAssetUrl(assetId) {
  return `${API_BASE}/assets/${assetId}/download`;
}

// --- Files ---

export async function uploadFiles(fileList) {
  const formData = new FormData();
  for (const f of fileList) {
    formData.append('files', f);
  }
  const t = getToken();
  const resp = await fetch(`${API_BASE}/files/upload`, {
    method: 'POST',
    headers: t ? { Authorization: `Bearer ${t}` } : {},
    body: formData,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || 'Upload failed');
  }
  return resp.json();
}

export async function fetchFiles() {
  return apiFetch(`${API_BASE}/files`);
}

export async function fetchFileQuota() {
  return apiFetch(`${API_BASE}/files/quota`);
}

export async function deleteFile(id) {
  return apiFetch(`${API_BASE}/files/${id}`, { method: 'DELETE' });
}

export function fileThumbnailUrl(id) {
  return `${API_BASE}/files/${id}/thumbnail`;
}

export function fileContentUrl(id) {
  return `${API_BASE}/files/${id}/content`;
}

// --- Projects ---

export async function fetchProjects() {
  return apiFetch(`${API_BASE}/projects`);
}

export async function createProject(name, description) {
  return apiFetch(`${API_BASE}/projects`, {
    method: 'POST',
    body: JSON.stringify({ name, description }),
  });
}

export async function updateProject(id, data) {
  return apiFetch(`${API_BASE}/projects/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteProject(id) {
  return apiFetch(`${API_BASE}/projects/${id}`, { method: 'DELETE' });
}

export async function fetchProjectMemory(id) {
  return apiFetch(`${API_BASE}/projects/${id}/memory`);
}

export async function updateProjectMemory(id, memory) {
  return apiFetch(`${API_BASE}/projects/${id}/memory`, {
    method: 'PUT',
    body: JSON.stringify({ memory }),
  });
}

export async function fetchProjectSessions(id) {
  return apiFetch(`${API_BASE}/projects/${id}/sessions`);
}

// --- Session operations ---

export async function moveSessionToProject(sessionId, projectId) {
  return apiFetch(`${API_BASE}/sessions/${sessionId}/project`, {
    method: 'PUT',
    body: JSON.stringify({ project_id: projectId }),
  });
}

export async function copySession(sessionId, projectId) {
  return apiFetch(`${API_BASE}/sessions/${sessionId}/copy`, {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  });
}

// --- Admin: Sessions ---

export async function fetchAdminSessions({ search, status, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (status) params.set('status', status);
  if (limit) params.set('limit', limit);
  if (offset) params.set('offset', offset);
  const qs = params.toString();
  return apiFetch(`${API_BASE}/admin/sessions${qs ? '?' + qs : ''}`);
}

export async function hardDeleteSession(sessionId) {
  return apiFetch(`${API_BASE}/admin/sessions/${sessionId}`, { method: 'DELETE' });
}

// --- Admin: Flags ---

export async function fetchAdminFlags({ status, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (limit) params.set('limit', limit);
  if (offset) params.set('offset', offset);
  const qs = params.toString();
  return apiFetch(`${API_BASE}/admin/flags${qs ? '?' + qs : ''}`);
}

// --- Admin: Assets ---

export async function fetchAdminAssets({ status, topic, search, visibility, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (topic) params.set('topic', topic);
  if (search) params.set('search', search);
  if (visibility) params.set('visibility', visibility);
  if (limit) params.set('limit', limit);
  if (offset) params.set('offset', offset);
  const qs = params.toString();
  return apiFetch(`${API_BASE}/admin/assets${qs ? '?' + qs : ''}`);
}

export async function deleteAdminAsset(id) {
  return apiFetch(`${API_BASE}/admin/assets/${id}`, { method: 'DELETE' });
}

export async function classifyAdminAsset(id, topic) {
  return apiFetch(`${API_BASE}/admin/assets/${id}/classify`, {
    method: 'PATCH',
    body: JSON.stringify({ topic: topic || null }),
  });
}

export async function deactivateAdminAsset(id) {
  return apiFetch(`${API_BASE}/admin/assets/${id}/deactivate`, { method: 'POST' });
}

export async function fixAssetExpiration() {
  return apiFetch(`${API_BASE}/admin/assets/fix-expiration`, { method: 'POST' });
}

export async function classifyAllAssets() {
  return apiFetch(`${API_BASE}/admin/assets/classify-all`, { method: 'POST' });
}

export async function fetchTopicsWithAssets() {
  return apiFetch(`${API_BASE}/admin/topics/with-assets`);
}

// --- Admin: Settings ---

export async function fetchAdminSettings() {
  return apiFetch(`${API_BASE}/admin/settings`);
}

export async function updateAdminSettings(settingsObj) {
  return apiFetch(`${API_BASE}/admin/settings`, {
    method: 'PUT',
    body: JSON.stringify({ settings: settingsObj }),
  });
}

// --- Admin: User Creation ---

export async function createAdminUser(email, password, display_name, role) {
  return apiFetch(`${API_BASE}/admin/users`, {
    method: 'POST',
    body: JSON.stringify({ email, password, display_name, role }),
  });
}

export async function updateAssetLifecycle(assetId, { is_active, expires_at } = {}) {
  return apiFetch(`${API_BASE}/admin/assets/${assetId}/lifecycle`, {
    method: 'PATCH',
    body: JSON.stringify({ is_active, expires_at }),
  });
}

export async function refreshAdminAsset(assetId) {
  return apiFetch(`${API_BASE}/admin/assets/${assetId}/refresh`, { method: 'POST' });
}

export async function refreshExpiredAssets() {
  return apiFetch(`${API_BASE}/admin/assets/refresh-expired`, { method: 'POST' });
}

export async function setLeadingAsset(topicId, assetId) {
  return apiFetch(`${API_BASE}/admin/topics/${topicId}/leading-asset?asset_id=${assetId}`, { method: 'PATCH' });
}

// --- System Prompt & Skills ---

export async function fetchSystemPrompt() {
  return apiFetch(`${API_BASE}/admin/system-prompt`);
}

export async function updateSystemPrompt(systemPrefix) {
  return apiFetch(`${API_BASE}/admin/system-prompt`, {
    method: 'PUT',
    body: JSON.stringify({ system_prefix: systemPrefix }),
  });
}

export async function fetchSkills() {
  return apiFetch(`${API_BASE}/admin/skills`);
}

export async function updateSkillConfig(name, { enabled, keywords, mandatory, display_name, skip_reflect } = {}) {
  return apiFetch(`${API_BASE}/admin/skills/${name}`, {
    method: 'PUT',
    body: JSON.stringify({ enabled, keywords, mandatory, display_name, skip_reflect }),
  });
}

export async function fetchSkillContent(name) {
  return apiFetch(`${API_BASE}/admin/skills/${name}/content`);
}

export async function updateSkillContent(name, content) {
  return apiFetch(`${API_BASE}/admin/skills/${name}/content`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

// --- Feedback ---

export async function submitFeedback(sessionId, rating, comment) {
  return apiFetch(`${API_BASE}/sessions/${sessionId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ rating, comment }),
  });
}

export function downloadSessionUrl(sessionId) {
  return `${API_BASE}/sessions/${sessionId}/download`;
}

// --- Zettel Memory (plugin) ---

export async function fetchZettelEntries(projectId, limit = 50) {
  return apiFetch(`${API_BASE}/projects/${projectId}/zettel?limit=${limit}`);
}

export async function addZettelEntry(projectId, content, { tags, importance } = {}) {
  return apiFetch(`${API_BASE}/projects/${projectId}/zettel`, {
    method: 'POST',
    body: JSON.stringify({ content, tags, importance }),
  });
}

export async function searchZettel(projectId, query, limit = 5) {
  return apiFetch(`${API_BASE}/projects/${projectId}/zettel/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}

export async function fetchZettelStats(projectId) {
  return apiFetch(`${API_BASE}/projects/${projectId}/zettel/stats`);
}

export async function deleteZettelEntry(projectId, zettelId) {
  return apiFetch(`${API_BASE}/projects/${projectId}/zettel/${zettelId}`, { method: 'DELETE' });
}

// --- OAuth ---

export async function fetchOAuthStatus() {
  return apiFetch(`${API_BASE}/oauth/status`);
}

export async function startOAuth(provider) {
  return apiFetch(`${API_BASE}/oauth/${provider}/start`);
}

export async function disconnectOAuth(provider) {
  return apiFetch(`${API_BASE}/oauth/${provider}/disconnect`, { method: 'DELETE' });
}

export async function pasteOAuthToken(provider, accessToken, refreshToken) {
  return apiFetch(`${API_BASE}/oauth/${provider}/token`, {
    method: 'PUT',
    body: JSON.stringify({ access_token: accessToken, refresh_token: refreshToken || null }),
  });
}

// --- MCP Servers ---

export async function fetchMcpServers() {
  return apiFetch(`${API_BASE}/mcp`);
}

export async function addMcpServer(name, url, { command, args, auth_type, oauth_provider } = {}) {
  return apiFetch(`${API_BASE}/mcp`, {
    method: 'POST',
    body: JSON.stringify({ name, url, command, args, auth_type, oauth_provider }),
  });
}

export async function removeMcpServer(name) {
  return apiFetch(`${API_BASE}/mcp/${name}`, { method: 'DELETE' });
}

export async function toggleMcpServer(name) {
  return apiFetch(`${API_BASE}/mcp/${name}/toggle`, { method: 'PATCH' });
}
