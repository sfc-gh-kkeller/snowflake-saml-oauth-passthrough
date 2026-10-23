import { useState, useEffect, useRef } from 'preact/hooks';
import { fetchFiles, fetchFileQuota, deleteFile, fileThumbnailUrl, fileContentUrl } from '../lib/api.js';

function AuthImage({ src, alt }) {
  const [blobUrl, setBlobUrl] = useState(null);
  useEffect(() => {
    const token = localStorage.getItem('ncx_token');
    fetch(src, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.blob())
      .then(blob => setBlobUrl(URL.createObjectURL(blob)))
      .catch(() => {});
    return () => { if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [src]);
  if (!blobUrl) return <div class="file-card-icon">...</div>;
  return <img src={blobUrl} alt={alt} />;
}

export function FileLibrary({ user, onClose }) {
  const [files, setFiles] = useState([]);
  const [quota, setQuota] = useState(null);

  useEffect(() => {
    load();
  }, []);

  const load = async () => {
    const [f, q] = await Promise.all([fetchFiles(), fetchFileQuota()]);
    setFiles(f);
    setQuota(q);
  };

  const handleDelete = async (id, name) => {
    if (!confirm(`Delete ${name}?`)) return;
    await deleteFile(id);
    await load();
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const handleView = async (id) => {
    const token = localStorage.getItem('ncx_token');
    const resp = await fetch(fileContentUrl(id), { headers: { Authorization: `Bearer ${token}` } });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
  };

  return (
    <div class="file-library">
      <div class="file-library-header">
        <h2>File Library</h2>
        {quota && (
          <div class="file-quota">
            <span>{quota.used} / {quota.limit} files</span>
            <span>{formatSize(quota.total_size_bytes)} used</span>
            <span>Max {quota.max_file_size_mb}MB per file</span>
          </div>
        )}
        {onClose && <button class="file-library-close" onClick={onClose}>✕</button>}
      </div>

      {files.length === 0 ? (
        <div class="file-library-empty">
          <p>No files uploaded yet. Attach files to chat messages to build your library.</p>
        </div>
      ) : (
        <div class="file-grid">
          {files.map(f => (
            <div key={f.id} class="file-card">
              <div class="file-card-preview">
                {(f.file_type === 'image' || (f.file_type === 'pdf' && f.pages)) ? (
                  <AuthImage src={fileThumbnailUrl(f.id)} alt={f.filename} />
                ) : f.file_type === 'pdf' ? (
                  <div class="file-card-icon">📄</div>
                ) : (
                  <div class="file-card-icon">📎</div>
                )}
              </div>
              <div class="file-card-info">
                <span class="file-card-name" title={f.filename}>{f.filename}</span>
                <span class="file-card-meta">
                  {formatSize(f.file_size)}
                  {f.pages && ` · ${f.pages} pages`}
                </span>
                <span class="file-card-date">{new Date(f.created_at).toLocaleDateString()}</span>
              </div>
              <div class="file-card-actions">
                <button class="file-card-btn" onClick={() => handleView(f.id)} title="View">👁</button>
                <button class="file-card-btn delete" onClick={() => handleDelete(f.id, f.filename)} title="Delete">🗑</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
