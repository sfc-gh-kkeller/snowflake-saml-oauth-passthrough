import { useState, useEffect, useCallback } from 'preact/hooks';
import {
  fetchMcpServers, addMcpServer, removeMcpServer, toggleMcpServer,
} from '../lib/api.js';

export function Settings({ user }) {
  const [mcpServers, setMcpServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [addForm, setAddForm] = useState({ name: '', url: '', command: '', args: '' });

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const mcp = await fetchMcpServers().catch(() => []);
      setMcpServers(mcp);
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleAddMcp = async (e) => {
    e.preventDefault();
    if (!addForm.name || (!addForm.url && !addForm.command)) return;
    try {
      await addMcpServer(addForm.name, addForm.url, {
        command: addForm.command || undefined,
        args: addForm.args || undefined,
      });
      setAddForm({ name: '', url: '', command: '', args: '' });
      loadData();
    } catch (e) {
      setError(e.message);
    }
  };

  const handleRemoveMcp = async (name) => {
    try {
      await removeMcpServer(name);
      setMcpServers(prev => prev.filter(s => s.name !== name));
    } catch (e) {
      setError(e.message);
    }
  };

  const handleToggleMcp = async (name) => {
    try {
      const result = await toggleMcpServer(name);
      setMcpServers(prev => prev.map(s => s.name === name ? { ...s, enabled: result.enabled } : s));
    } catch (e) {
      setError(e.message);
    }
  };

  const cardStyle = 'background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1rem;';
  const btnPrimary = 'padding:0.4rem 1rem;border-radius:6px;border:none;background:#3b82f6;color:#fff;cursor:pointer;font-size:0.8rem;';
  const inputStyle = 'padding:0.4rem 0.6rem;border-radius:4px;border:1px solid #475569;background:#0f172a;color:#e2e8f0;font-size:0.85rem;';

  if (loading) return <div style="padding:2rem;color:#94a3b8;">Loading settings...</div>;

  return (
    <div style="flex:1;overflow-y:auto;padding:1.5rem;max-width:900px;margin:0 auto;width:100%;">
      {error && (
        <div style="background:#7f1d1d;border:1px solid #ef4444;border-radius:6px;padding:0.75rem;margin-bottom:1rem;color:#fca5a5;font-size:0.85rem;">
          {error}
          <button onClick={() => setError(null)} style="float:right;background:none;border:none;color:#fca5a5;cursor:pointer;">x</button>
        </div>
      )}

      <h3 style="color:#e2e8f0;margin:0 0 0.5rem;">MCP Servers</h3>
      <p style="color:#64748b;font-size:0.85rem;margin:0 0 1.5rem;">
        Model Context Protocol servers provide external tools and data sources to the AI agent.
        Add servers by URL (SSE/HTTP transport) or local command.
      </p>

      {mcpServers.length > 0 ? (
        <div style="display:grid;gap:0.75rem;margin-bottom:1.5rem;">
          {mcpServers.map(s => (
            <div key={s.name} style={cardStyle + 'display:flex;align-items:center;justify-content:space-between;'}>
              <div>
                <div style="display:flex;align-items:center;gap:0.5rem;">
                  <span style={`color:${s.enabled ? '#22c55e' : '#64748b'};`}>●</span>
                  <span style="color:#e2e8f0;font-weight:600;">{s.name}</span>
                </div>
                <div style="color:#64748b;font-size:0.8rem;margin-top:0.25rem;">
                  {s.url || s.command || 'No URL'}
                </div>
              </div>
              <div style="display:flex;gap:0.5rem;">
                <button
                  style="padding:0.3rem 0.6rem;border-radius:4px;border:1px solid #475569;background:transparent;color:#94a3b8;cursor:pointer;font-size:0.75rem;"
                  onClick={() => handleToggleMcp(s.name)}
                >{s.enabled ? 'Disable' : 'Enable'}</button>
                <button
                  style="padding:0.3rem 0.6rem;border-radius:4px;border:1px solid #7f1d1d;background:transparent;color:#ef4444;cursor:pointer;font-size:0.75rem;"
                  onClick={() => handleRemoveMcp(s.name)}
                >Remove</button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style="color:#64748b;margin-bottom:1.5rem;font-size:0.85rem;">No MCP servers configured yet.</div>
      )}

      <div style={cardStyle}>
        <h4 style="color:#e2e8f0;margin:0 0 0.75rem;">Add MCP Server</h4>
        <form onSubmit={handleAddMcp} style="display:grid;gap:0.5rem;">
          <div style="display:flex;gap:0.5rem;">
            <input
              style={inputStyle + 'flex:1;'}
              placeholder="Server name (e.g. my-tools)"
              value={addForm.name}
              onInput={e => setAddForm(p => ({ ...p, name: e.target.value }))}
            />
            <input
              style={inputStyle + 'flex:2;'}
              placeholder="URL (e.g. https://my-mcp-server.com/sse)"
              value={addForm.url}
              onInput={e => setAddForm(p => ({ ...p, url: e.target.value }))}
            />
          </div>
          <div style="display:flex;gap:0.5rem;align-items:center;">
            <input
              style={inputStyle + 'flex:1;'}
              placeholder="Or command (e.g. npx my-mcp-server)"
              value={addForm.command}
              onInput={e => setAddForm(p => ({ ...p, command: e.target.value }))}
            />
            <input
              style={inputStyle + 'flex:1;'}
              placeholder="Args (optional, JSON)"
              value={addForm.args}
              onInput={e => setAddForm(p => ({ ...p, args: e.target.value }))}
            />
            <button type="submit" style={btnPrimary}>Add</button>
          </div>
        </form>
        <p style="color:#475569;font-size:0.7rem;margin:0.5rem 0 0 0;">
          Provide either a URL (for remote SSE/HTTP servers) or a command (for local stdio servers). Not both.
        </p>
      </div>
    </div>
  );
}
