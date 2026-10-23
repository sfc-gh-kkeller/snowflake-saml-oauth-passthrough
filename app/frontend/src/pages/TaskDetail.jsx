import { useState, useRef, useEffect } from 'preact/hooks';
import { MessageTimeline } from './MessageTimeline.jsx';

function shortId(id) {
  if (!id) return '';
  return id.replace(/-/g, '').slice(0, 8).toUpperCase();
}

export function TaskDetail({ task, isStreaming, liveMessages, onFollowUp, onStop, onClone, onRestart }) {
  const [activeTab, setActiveTab] = useState('messages');
  const [followUp, setFollowUp] = useState('');
  const scrollRef = useRef(null);

  const status = isStreaming ? 'running' : (task.status || 'done');
  const badgeClass = status === 'running' ? 'running' :
                     status === 'cancelled' ? 'cancelled' : 'finished';
  const badgeLabel = status === 'running' ? 'Running' :
                     status === 'cancelled' ? 'Cancelled' : 'Task finished';

  const historyMessages = buildHistoryTimeline(task.history || []);
  const allMessages = [...historyMessages, ...liveMessages];
  const messageCount = allMessages.length;

  useEffect(() => {
    if (scrollRef.current && isStreaming) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [liveMessages, isStreaming]);

  const handleSendFollowUp = () => {
    if (!followUp.trim()) return;
    onFollowUp(followUp.trim());
    setFollowUp('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendFollowUp();
    }
  };

  return (
    <>
      <div class="detail-header">
        <div class="detail-header-row">
          <span class="detail-task-id">{shortId(task.id)}</span>
          <span class={`status-badge ${badgeClass}`}>
            <span class="dot" />
            {badgeLabel}
          </span>
          {!isStreaming && (
            <div class="detail-actions">
              <button class="detail-action-link" onClick={() => onRestart(task.title)}>↻ Restart</button>
              <button class="detail-action-link" onClick={onClone}>📋 Clone</button>
            </div>
          )}
        </div>
        <div class="detail-title">{task.title}</div>
      </div>

      <div class="detail-follow-up">
        <input
          type="text"
          placeholder="Send a follow-up message..."
          value={followUp}
          onInput={(e) => setFollowUp(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
        />
        <div class="follow-up-actions">
          {isStreaming ? (
            <button class="follow-up-btn follow-up-stop" onClick={onStop} title="Stop">■</button>
          ) : (
            <button
              class="follow-up-btn follow-up-send"
              onClick={handleSendFollowUp}
              disabled={!followUp.trim()}
              title="Send"
            >▶</button>
          )}
        </div>
      </div>

      <div class="detail-tabs">
        <button
          class={`detail-tab ${activeTab === 'messages' ? 'active' : ''}`}
          onClick={() => setActiveTab('messages')}
        >
          Messages<span class="detail-tab-count">({messageCount})</span>
        </button>
        <button
          class={`detail-tab ${activeTab === 'details' ? 'active' : ''}`}
          onClick={() => setActiveTab('details')}
        >
          Details
        </button>
      </div>

      <div class="detail-content" ref={scrollRef}>
        {activeTab === 'messages' ? (
          <MessageTimeline messages={allMessages} isStreaming={isStreaming} />
        ) : (
          <div class="details-tab-content">
            <div class="detail-field">
              <div class="detail-field-label">Task ID</div>
              <div class="detail-field-value">{task.id}</div>
            </div>
            <div class="detail-field">
              <div class="detail-field-label">Status</div>
              <div class="detail-field-value">{status}</div>
            </div>
            <div class="detail-field">
              <div class="detail-field-label">Created</div>
              <div class="detail-field-value">{task.created_at}</div>
            </div>
            <div class="detail-field">
              <div class="detail-field-label">Updated</div>
              <div class="detail-field-value">{task.updated_at}</div>
            </div>
            {task.total_time_ms > 0 && (
              <div class="detail-field">
                <div class="detail-field-label">Total Time</div>
                <div class="detail-field-value">{(task.total_time_ms / 1000).toFixed(1)}s</div>
              </div>
            )}
            <div class="detail-field">
              <div class="detail-field-label">Prompt</div>
              <div class="detail-field-value">{task.title}</div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function buildHistoryTimeline(history) {
  const entries = [];
  if (!history || !history.length) return entries;

  entries.push({ type: 'init', label: 'Initializing', text: 'Initializing session' });

  for (const msg of history) {
    if (msg.role === 'user') {
      const text = (msg.content || []).filter((c) => c.type === 'text').map((c) => c.text).join('');
      if (text) entries.push({ type: 'user', label: 'User', text });
    } else if (msg.role === 'assistant') {
      const textParts = (msg.content || []).filter((c) => c.type === 'text').map((c) => c.text).join('');
      const tools = (msg.content || []).filter((c) => c.type === 'tool_use');
      for (const tool of tools) {
        entries.push(mapToolEntry(tool));
      }
      if (textParts) {
        entries.push({ type: 'assistant', label: 'Assistant', text: textParts });
      }
    }
  }
  return entries;
}

function mapToolEntry(tool) {
  const name = (tool.name || '').toLowerCase();
  if (name.includes('web_search')) return { type: 'search', label: 'Web Search', text: JSON.stringify(tool.input || {}).slice(0, 150) };
  if (name.includes('sql')) return { type: 'terminal', label: 'SQL Execute', text: (tool.input?.sql || '').slice(0, 200) };
  if (name.includes('bash') || name.includes('terminal')) return { type: 'terminal', label: 'Terminal', text: (tool.input?.command || '').slice(0, 200) };
  if (name.includes('read')) return { type: 'tool', label: 'read', text: tool.input?.file_path || '' };
  if (name.includes('glob')) return { type: 'tool', label: 'glob', text: tool.input?.pattern || '' };
  if (name.includes('skill')) return { type: 'skill', label: 'skill', text: tool.input?.skill_name || tool.input?.command || '' };
  return { type: 'tool', label: tool.name || 'Tool', text: JSON.stringify(tool.input || {}).slice(0, 150) };
}
