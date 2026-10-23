import { useState, useEffect, useRef } from 'preact/hooks';
import { marked } from 'marked';
import {
  fetchReviewAssets, fetchReviewAsset, reviewAsset,
  fetchFlags, resolveFlag, updateAssetContent, restoreAssetVersion,
  claimReviewAsset, releaseReviewAsset, transferReviewAsset,
  fetchAdminUsers, updateAssetStatus,
} from '../lib/api.js';

function renderMd(text) {
  return { __html: marked.parse(text || '', { breaks: true }) };
}

function VersionPanel({ versions, onRestore, onViewDiff, activeVersionId }) {
  if (!versions?.length) return <div class="rv-versions-empty">No versions yet</div>;

  return (
    <div class="rv-version-list">
      {versions.map((v) => (
        <div key={v.id} class={`rv-version-item ${activeVersionId === v.id ? 'active' : ''}`}>
          <div class="rv-version-header">
            <span class="rv-version-num">v{v.version}</span>
            <span class="rv-version-date">{new Date(v.created_at).toLocaleString()}</span>
          </div>
          <div class="rv-version-comment">{v.comment || 'No comment'}</div>
          <div class="rv-version-actions">
            <button class="rv-version-btn" onClick={() => onViewDiff(v)}>View</button>
            <button class="rv-version-btn restore" onClick={() => onRestore(v)}>Restore</button>
          </div>
        </div>
      ))}
    </div>
  );
}

function EditorPane({ content, onChange, previewMode, onTogglePreview }) {
  const textareaRef = useRef(null);

  useEffect(() => {
    if (textareaRef.current && !previewMode) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px';
    }
  }, [content, previewMode]);

  return (
    <div class="rv-editor-pane">
      <div class="rv-editor-toolbar">
        <div class="rv-editor-tabs">
          <button class={`rv-editor-tab ${!previewMode ? 'active' : ''}`} onClick={() => onTogglePreview(false)}>
            Edit
          </button>
          <button class={`rv-editor-tab ${previewMode ? 'active' : ''}`} onClick={() => onTogglePreview(true)}>
            Preview
          </button>
        </div>
      </div>
      {previewMode ? (
        <div class="rv-preview-content" dangerouslySetInnerHTML={renderMd(content)} />
      ) : (
        <textarea
          ref={textareaRef}
          class="rv-editor-textarea"
          value={content}
          onInput={(e) => onChange(e.target.value)}
          spellcheck={true}
        />
      )}
    </div>
  );
}

export function Review({ user }) {
  const [tab, setTab] = useState('assets');
  const [assets, setAssets] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [showArchivedDrafts, setShowArchivedDrafts] = useState(false);
  const [flags, setFlags] = useState([]);
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [rejectReason, setRejectReason] = useState('');
  const [loading, setLoading] = useState(false);

  const [editContent, setEditContent] = useState('');
  const [editFilename, setEditFilename] = useState('');
  const [editComment, setEditComment] = useState('');
  const [previewMode, setPreviewMode] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [detailTab, setDetailTab] = useState('content');
  const [viewingVersion, setViewingVersion] = useState(null);
  const [reviewers, setReviewers] = useState([]);

  useEffect(() => {
    loadAssets();
    loadDrafts();
    loadFlags();
    loadReviewers();
  }, []);

  const loadReviewers = async () => {
    try {
      const data = await fetchAdminUsers();
      const users = data?.users || data || [];
      setReviewers(users.filter(u => u.role === 'reviewer' || u.role === 'admin'));
    } catch {}
  };

  const loadAssets = async () => {
    try {
      const a = await fetchReviewAssets('in_review');
      setAssets(a);
    } catch {}
  };

  const loadDrafts = async () => {
    try {
      const [d, archived] = await Promise.all([
        fetchReviewAssets('draft'),
        fetchReviewAssets('archived'),
      ]);
      setDrafts([...d, ...archived.map(a => ({ ...a, status: 'archived' }))]);
    } catch {}
  };

  const loadFlags = async () => {
    try {
      const f = await fetchFlags();
      setFlags(f);
    } catch {}
  };

  const selectAsset = async (id) => {
    if (dirty && !confirm('You have unsaved changes. Discard?')) return;
    try {
      const a = await fetchReviewAsset(id);
      setSelectedAsset(a);
      setEditContent(a.content || '');
      setEditFilename(a.filename || '');
      setEditComment('');
      setDirty(false);
      setRejectReason('');
      setPreviewMode(true);
      setDetailTab('content');
      setViewingVersion(null);
    } catch {}
  };

  const handleContentChange = (val) => {
    setEditContent(val);
    setDirty(val !== (selectedAsset?.content || ''));
  };

  const handleSaveContent = async () => {
    if (!selectedAsset || !dirty) return;
    setSaving(true);
    try {
      await updateAssetContent(selectedAsset.id, editContent, {
        comment: editComment || undefined,
        filename: editFilename !== selectedAsset.filename ? editFilename : undefined,
      });
      const a = await fetchReviewAsset(selectedAsset.id);
      setSelectedAsset(a);
      setEditContent(a.content || '');
      setDirty(false);
      setEditComment('');
      await loadAssets();
    } catch (err) {
      alert('Failed to save: ' + err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleRestore = async (version) => {
    if (!confirm(`Restore to v${version.version}? This creates a new version.`)) return;
    setLoading(true);
    try {
      const result = await restoreAssetVersion(selectedAsset.id, version.id);
      const a = await fetchReviewAsset(selectedAsset.id);
      setSelectedAsset(a);
      setEditContent(a.content || '');
      setDirty(false);
      setViewingVersion(null);
    } catch (err) {
      alert('Restore failed: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleViewVersion = (version) => {
    setViewingVersion(viewingVersion?.id === version.id ? null : version);
  };

  const handleApprove = async () => {
    if (!selectedAsset) return;
    if (dirty && !confirm('You have unsaved edits. Approve with current saved content?')) return;
    setLoading(true);
    try {
      await reviewAsset(selectedAsset.id, 'approved');
      setSelectedAsset(null);
      setDirty(false);
      await loadAssets();
    } catch (err) {
      alert('Failed to approve: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    if (!selectedAsset || !rejectReason.trim()) return;
    setLoading(true);
    try {
      await reviewAsset(selectedAsset.id, 'rejected', rejectReason.trim());
      setSelectedAsset(null);
      setRejectReason('');
      setDirty(false);
      await loadAssets();
    } catch (err) {
      alert('Failed to reject: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleResolveFlag = async (flagId, status) => {
    try {
      await resolveFlag(flagId, status);
      await loadFlags();
    } catch (err) {
      alert('Failed: ' + err.message);
    }
  };

  const handleClaim = async () => {
    if (!selectedAsset) return;
    setLoading(true);
    try {
      await claimReviewAsset(selectedAsset.id);
      const a = await fetchReviewAsset(selectedAsset.id);
      setSelectedAsset(a);
      await loadAssets();
    } catch (err) {
      alert('Failed to claim: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRelease = async () => {
    if (!selectedAsset) return;
    setLoading(true);
    try {
      await releaseReviewAsset(selectedAsset.id);
      const a = await fetchReviewAsset(selectedAsset.id);
      setSelectedAsset(a);
      await loadAssets();
    } catch (err) {
      alert('Failed to release: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleTransfer = async (targetUserId) => {
    if (!selectedAsset) return;
    setLoading(true);
    try {
      await transferReviewAsset(selectedAsset.id, targetUserId);
      const a = await fetchReviewAsset(selectedAsset.id);
      setSelectedAsset(a);
      await loadAssets();
    } catch (err) {
      alert('Failed to transfer: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div class="review-layout">
      <div class="review-tabs">
        <button class={`review-tab ${tab === 'assets' ? 'active' : ''}`} onClick={() => setTab('assets')}>
          In Review <span class="review-tab-count">{assets.length}</span>
        </button>
        <button class={`review-tab ${tab === 'drafts' ? 'active' : ''}`} onClick={() => setTab('drafts')}>
          Drafts <span class="review-tab-count">{drafts.filter(d => d.status !== 'archived').length}</span>
        </button>
        <button class={`review-tab ${tab === 'flags' ? 'active' : ''}`} onClick={() => setTab('flags')}>
          Flags <span class="review-tab-count">{flags.length}</span>
        </button>
      </div>

      {tab === 'assets' && (
        <div class="review-split">
          <div class="review-list">
            {assets.length === 0 && <div class="review-empty">No assets pending review</div>}
            {assets.map((a) => (
              <div
                key={a.id}
                class={`review-asset-card ${selectedAsset?.id === a.id ? 'selected' : ''}`}
                onClick={() => selectAsset(a.id)}
              >
                <div class="review-asset-header">
                  <span class="review-asset-filename">{a.filename}</span>
                  <span class={`review-asset-status ${a.status}`}>{a.status}</span>
                </div>
                {a.reviewer_id && <span class="review-asset-reviewer">Under review by {a.reviewer_id === user?.id ? 'you' : 'another reviewer'}</span>}
                {a.topic && <span class="review-asset-topic">{a.topic}</span>}
                <p class="review-asset-preview">{a.content}</p>
                <span class="review-asset-date">{new Date(a.created_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>

          <div class="review-detail">
            {selectedAsset ? (
              <div class="review-detail-inner">
                <div class="review-detail-header">
                  <div class="rv-header-row">
                    {previewMode || detailTab !== 'content' ? (
                      <h3>{selectedAsset.filename}</h3>
                    ) : (
                      <input
                        class="rv-filename-input"
                        value={editFilename}
                        onInput={(e) => setEditFilename(e.target.value)}
                      />
                    )}
                    <div class="review-detail-meta">
                      <span class={`review-asset-status ${selectedAsset.status}`}>{selectedAsset.status}</span>
                      {selectedAsset.topic && <span class="review-asset-topic">{selectedAsset.topic}</span>}
                      {dirty && <span class="rv-dirty-badge">Unsaved</span>}
                    </div>
                  </div>
                  {selectedAsset.status === 'in_review' && (
                    <div class="rv-claim-bar">
                      {selectedAsset.reviewer_id ? (
                        selectedAsset.reviewer_id === user?.id ? (
                          <>
                            <span class="rv-claim-badge yours">Claimed by you</span>
                            <button class="rv-release-btn" onClick={handleRelease} disabled={loading}>Release</button>
                            <select
                              class="rv-transfer-select"
                              onChange={(e) => { if (e.target.value) handleTransfer(e.target.value); e.target.value = ''; }}
                              disabled={loading}
                            >
                              <option value="">Transfer to...</option>
                              {reviewers.filter(r => r.id !== user?.id).map(r => (
                                <option key={r.id} value={r.id}>{r.display_name || r.email}</option>
                              ))}
                            </select>
                          </>
                        ) : (
                          <div style="display:flex;align-items:center;gap:0.5rem;">
                            <span class="rv-claim-badge other">Under review by another reviewer</span>
                            <button class="rv-claim-btn" onClick={handleClaim} disabled={loading} style="font-size:0.75rem;">
                              {loading ? 'Claiming...' : 'Claim to me'}
                            </button>
                          </div>
                        )
                      ) : (
                        <button class="rv-claim-btn" onClick={handleClaim} disabled={loading}>
                          {loading ? 'Claiming...' : 'Claim for Review'}
                        </button>
                      )}
                    </div>
                  )}
                  {selectedAsset.status !== 'in_review' && (
                    <div class="rv-claim-bar">
                      <button class="rv-claim-btn" onClick={async () => {
                        setLoading(true);
                        try {
                          await reviewAsset(selectedAsset.id, 'in_review');
                          await claimReviewAsset(selectedAsset.id);
                          const a = await fetchReviewAsset(selectedAsset.id);
                          setSelectedAsset(a);
                          await loadAssets();
                        } catch (err) {
                          alert('Failed: ' + err.message);
                        } finally {
                          setLoading(false);
                        }
                      }} disabled={loading}>
                        {loading ? 'Claiming...' : 'Claim for Review'}
                      </button>
                    </div>
                  )}
                </div>

                <div class="rv-detail-tabs">
                  <button class={`rv-dtab ${detailTab === 'content' ? 'active' : ''}`} onClick={() => { setDetailTab('content'); setViewingVersion(null); }}>
                    Content
                  </button>
                  <button class={`rv-dtab ${detailTab === 'versions' ? 'active' : ''}`} onClick={() => setDetailTab('versions')}>
                    Versions <span class="rv-dtab-count">{selectedAsset.versions?.length || 0}</span>
                  </button>
                </div>

                {detailTab === 'content' && (
                  <>
                    <EditorPane
                      content={editContent}
                      onChange={selectedAsset.reviewer_id === user?.id ? handleContentChange : () => {}}
                      previewMode={selectedAsset.reviewer_id !== user?.id ? true : previewMode}
                      onTogglePreview={selectedAsset.reviewer_id === user?.id ? setPreviewMode : () => {}}
                    />

                    {!previewMode && dirty && (
                      <div class="rv-save-bar">
                        <input
                          class="rv-comment-input"
                          value={editComment}
                          onInput={(e) => setEditComment(e.target.value)}
                          placeholder="Version comment (optional)..."
                        />
                        <button class="rv-save-btn" onClick={handleSaveContent} disabled={saving}>
                          {saving ? 'Saving...' : 'Save Changes'}
                        </button>
                        <button class="rv-discard-btn" onClick={() => {
                          setEditContent(selectedAsset.content || '');
                          setEditFilename(selectedAsset.filename || '');
                          setDirty(false);
                          setPreviewMode(true);
                        }}>
                          Discard
                        </button>
                      </div>
                    )}
                  </>
                )}

                {detailTab === 'versions' && (
                  <div class="rv-versions-panel">
                    <VersionPanel
                      versions={selectedAsset.versions}
                      onRestore={handleRestore}
                      onViewDiff={handleViewVersion}
                      activeVersionId={viewingVersion?.id}
                    />
                    {viewingVersion && (
                      <div class="rv-version-preview">
                        <div class="rv-version-preview-header">
                          <span>v{viewingVersion.version} — {viewingVersion.comment || 'No comment'}</span>
                          <span class="rv-version-preview-date">{new Date(viewingVersion.created_at).toLocaleString()}</span>
                        </div>
                        <div class="rv-preview-content" dangerouslySetInnerHTML={renderMd(viewingVersion.content)} />
                      </div>
                    )}
                  </div>
                )}

                <div class="review-actions">
                  {selectedAsset.reviewer_id === user?.id ? (
                    <>
                      <button class="review-btn approve" onClick={handleApprove} disabled={loading}>
                        Approve
                      </button>
                      <div class="review-reject-group">
                        <input
                          value={rejectReason}
                          onInput={(e) => setRejectReason(e.target.value)}
                          placeholder="Rejection reason..."
                        />
                        <button class="review-btn reject" onClick={handleReject} disabled={loading || !rejectReason.trim()}>
                          Reject
                        </button>
                      </div>
                      <button
                        class="review-btn draft"
                        onClick={async () => {
                          await reviewAsset(selectedAsset.id, 'draft');
                          setSelectedAsset(null);
                          setDirty(false);
                          await loadAssets();
                        }}
                        disabled={loading}
                      >
                        Return to Draft
                      </button>
                    </>
                  ) : (
                    <p class="review-actions-hint">Claim this asset to approve, reject, or edit it.</p>
                  )}
                </div>
              </div>
            ) : (
              <div class="review-detail-empty">Select an asset to review</div>
            )}
          </div>
        </div>
      )}

      {tab === 'drafts' && (
        <div class="review-flags">
          <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.75rem;">
            <button
              onClick={() => setShowArchivedDrafts(!showArchivedDrafts)}
              style={`background:none;border:1px solid #334155;border-radius:4px;padding:0.25rem 0.6rem;font-size:0.75rem;cursor:pointer;color:${showArchivedDrafts ? '#60a5fa' : '#64748b'};`}
            >{showArchivedDrafts ? 'Hide archived' : 'Show archived'}</button>
          </div>
          {drafts.filter(d => showArchivedDrafts || d.status !== 'archived').length === 0 && (
            <div class="review-empty">No draft assets</div>
          )}
          {drafts.filter(d => showArchivedDrafts || d.status !== 'archived').map((a) => (
            <div key={a.id} class="review-flag-card" style="display:flex;align-items:center;justify-content:space-between;">
              <div style="flex:1;min-width:0;">
                <div style="display:flex;align-items:center;gap:0.5rem;">
                  <span class="review-asset-filename" style="font-size:0.85rem;">{a.filename}</span>
                  {a.status === 'archived' && <span style="color:#64748b;font-size:0.65rem;background:#1e293b;padding:0.1rem 0.4rem;border-radius:3px;">archived</span>}
                </div>
                <div style="color:#64748b;font-size:0.75rem;margin-top:0.2rem;">
                  {a.topic && <span>{a.topic} · </span>}
                  {a.content?.slice(0, 100)}...
                </div>
              </div>
              <div style="display:flex;gap:0.4rem;flex-shrink:0;">
                <button
                  onClick={() => selectAsset(a.id)}
                  style="padding:0.25rem 0.5rem;border-radius:4px;border:1px solid #334155;background:transparent;color:#60a5fa;cursor:pointer;font-size:0.7rem;"
                >View</button>
                {a.status !== 'archived' ? (
                  <button
                    onClick={async () => { await updateAssetStatus(a.id, 'archived'); loadDrafts(); }}
                    style="padding:0.25rem 0.5rem;border-radius:4px;border:1px solid #475569;background:transparent;color:#94a3b8;cursor:pointer;font-size:0.7rem;"
                  >Archive</button>
                ) : (
                  <button
                    onClick={async () => { await updateAssetStatus(a.id, 'draft'); loadDrafts(); }}
                    style="padding:0.25rem 0.5rem;border-radius:4px;border:1px solid #475569;background:transparent;color:#34d399;cursor:pointer;font-size:0.7rem;"
                  >Unarchive</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'flags' && (
        <div class="review-flags">
          {flags.length === 0 && <div class="review-empty">No pending flags</div>}
          {flags.map((f) => (
            <div key={f.id} class="review-flag-card">
              <div class="review-flag-header">
                <span class="review-flag-session">Session: {f.session_id.slice(0, 8)}</span>
                <span class={`review-flag-status ${f.status}`}>{f.status}</span>
              </div>
              <p class="review-flag-reason">{f.reason}</p>
              <span class="review-flag-date">{new Date(f.created_at).toLocaleDateString()}</span>
              <div class="review-flag-actions">
                <button class="review-btn small" onClick={() => handleResolveFlag(f.id, 'reviewed')}>Mark Reviewed</button>
                <button class="review-btn small dismiss" onClick={() => handleResolveFlag(f.id, 'dismissed')}>Dismiss</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
