import { useState, useEffect, useRef, useCallback } from 'preact/hooks';
import { marked } from 'marked';
import {
  fetchAsset, fetchAssetVersions, fetchAssetVersion,
  saveAssetEdit, updateAssetStatus, downloadAssetUrl,
} from '../lib/api.js';

const STATUS_LABELS = {
  draft: 'Draft',
  in_review: 'In Review',
  approved: 'Approved',
  rejected: 'Rejected',
};

export function AssetPanel({ assetId, onClose }) {
  const [asset, setAsset] = useState(null);
  const [versions, setVersions] = useState([]);
  const [activeTab, setActiveTab] = useState('raw');
  const [editContent, setEditContent] = useState('');
  const [editComment, setEditComment] = useState('');
  const [dirty, setDirty] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [saving, setSaving] = useState(false);
  const [panelWidth, setPanelWidth] = useState(520);
  const resizing = useRef(false);
  const startX = useRef(0);
  const startW = useRef(0);

  const loadAsset = useCallback(async () => {
    if (!assetId) return;
    try {
      const [a, v] = await Promise.all([
        fetchAsset(assetId),
        fetchAssetVersions(assetId),
      ]);
      setAsset(a);
      setVersions(v);
      setEditContent(a.content || '');
      setDirty(false);
      if (v.length > 0) setSelectedVersion(v[0].version);
    } catch {}
  }, [assetId]);

  useEffect(() => { loadAsset(); }, [loadAsset]);

  const handleVersionChange = async (e) => {
    const ver = parseInt(e.target.value, 10);
    setSelectedVersion(ver);
    try {
      const v = await fetchAssetVersion(assetId, ver);
      setEditContent(v.content);
      setDirty(false);
    } catch {}
  };

  const handleSave = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      await saveAssetEdit(assetId, editContent, editComment || undefined);
      setEditComment('');
      await loadAsset();
    } catch (err) {
      alert('Save failed: ' + err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDiscard = () => {
    setEditContent(asset?.content || '');
    setDirty(false);
    setEditComment('');
  };

  const handleSubmitReview = async () => {
    try {
      await updateAssetStatus(assetId, 'in_review');
      await loadAsset();
    } catch (err) {
      alert('Failed: ' + err.message);
    }
  };

  const handleDownload = () => {
    window.open(downloadAssetUrl(assetId), '_blank');
  };

  const handleWithdraw = async () => {
    try {
      await updateAssetStatus(assetId, 'draft');
      await loadAsset();
    } catch (err) {
      alert('Failed to withdraw: ' + err.message);
    }
  };

  const isLocked = asset?.status === 'in_review';

  const onMouseDown = (e) => {
    resizing.current = true;
    startX.current = e.clientX;
    startW.current = panelWidth;
    e.preventDefault();
  };

  useEffect(() => {
    const onMove = (e) => {
      if (!resizing.current) return;
      const delta = startX.current - e.clientX;
      const w = Math.max(280, Math.min(startW.current + delta, window.innerWidth * 0.7));
      setPanelWidth(w);
    };
    const onUp = () => { resizing.current = false; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  if (!asset) {
    return (
      <div class="ap-panel" style={{ width: panelWidth + 'px' }}>
        <div class="ap-loading">Loading...</div>
      </div>
    );
  }

  const rawContent = activeTab === 'raw' || activeTab === 'preview'
    ? (selectedVersion && versions.length > 0 ? editContent : asset.content)
    : editContent;

  const isApprovedVersion = asset.status === 'approved' && asset.approved_version === selectedVersion;
  const versionStatusLabel = asset.status === 'approved'
    ? (isApprovedVersion ? 'Approved' : `v${asset.approved_version} Approved`)
    : (STATUS_LABELS[asset.status] || asset.status);
  const versionStatusClass = asset.status === 'approved'
    ? (isApprovedVersion ? 'approved' : 'draft')
    : asset.status;

  return (
    <div class="ap-panel" style={{ width: panelWidth + 'px' }}>
      <div class="ap-resize-handle" onMouseDown={onMouseDown} />
      <div class="ap-inner">
        <div class="ap-header">
          <div class="ap-header-row">
            <span class="ap-filename">{asset.filename}</span>
            <select class="ap-version-select" value={selectedVersion} onChange={handleVersionChange}>
              {versions.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version} ({v.edited_by?.split('@')[0] || 'system'})
                </option>
              ))}
            </select>
            <span class={`ap-status-badge ${versionStatusClass}`}>{versionStatusLabel}</span>
            {dirty && <span class="ap-dirty-badge">Unsaved</span>}
            <button class="ap-close-btn" onClick={onClose}>x</button>
          </div>
          <div class="ap-tabs">
            {(isLocked ? ['raw', 'preview'] : ['raw', 'edit', 'preview']).map((tab) => (
              <button
                key={tab}
                class={`ap-tab ${activeTab === tab ? 'active' : ''}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>
        </div>

        <div class="ap-content">
          {activeTab === 'raw' && (
            <div class="ap-raw">
              <pre class="ap-raw-content">{rawContent}</pre>
            </div>
          )}
          {activeTab === 'edit' && (
            <div class="ap-edit">
              <textarea
                class="ap-edit-textarea"
                value={editContent}
                onInput={(e) => { setEditContent(e.target.value); setDirty(true); }}
              />
              {dirty && (
                <div class="ap-save-bar">
                  <input
                    class="ap-comment-input"
                    value={editComment}
                    onInput={(e) => setEditComment(e.target.value)}
                    placeholder="Edit comment (optional)"
                  />
                  <button class="ap-save-btn" onClick={handleSave} disabled={saving}>
                    {saving ? 'Saving...' : 'Save'}
                  </button>
                  <button class="ap-discard-btn" onClick={handleDiscard}>Discard</button>
                </div>
              )}
            </div>
          )}
          {activeTab === 'preview' && (
            <div class="ap-preview">
              <div
                class="ap-preview-content"
                dangerouslySetInnerHTML={{ __html: marked.parse(rawContent || '', { breaks: true }) }}
              />
            </div>
          )}
        </div>

        <div class="ap-action-bar">
          {isLocked && (
            <div class="ap-locked-banner">
              <span>This asset is under review and cannot be edited.</span>
              <button class="ap-action-btn withdraw" onClick={handleWithdraw}>Withdraw from Review</button>
            </div>
          )}
          {asset.status === 'draft' && (
            <button class="ap-action-btn submit" onClick={handleSubmitReview}>Submit for Review</button>
          )}
          <button class="ap-action-btn download" onClick={handleDownload}>Download</button>
        </div>
      </div>
    </div>
  );
}
