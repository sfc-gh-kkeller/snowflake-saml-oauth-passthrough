import { useState, useEffect, useRef, useCallback } from 'preact/hooks';
import {
  fetchSessions, fetchSession, deleteSession,
  createSessionStream, sendMessageStream,
} from '../lib/api.js';
import { NewTaskModal } from './NewTaskModal.jsx';
import { TaskDetail } from './TaskDetail.jsx';

function shortId(id) {
  if (!id) return '';
  return id.replace(/-/g, '').slice(0, 8).toUpperCase();
}

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function TaskCard({ task, selected, onClick, onClone, onDelete }) {
  const status = task.status || 'done';
  const badgeClass = status === 'running' ? 'running' :
                     status === 'cancelled' ? 'cancelled' :
                     status === 'done' ? 'done' : 'finished';
  const badgeLabel = status === 'running' ? 'Running' :
                     status === 'cancelled' ? 'Cancelled' :
                     status === 'done' ? 'Done' : 'Task finished';

  return (
    <div class={`task-card ${selected ? 'selected' : ''}`} onClick={onClick}>
      <div class="task-card-header">
        <span class="task-id">{shortId(task.id)}</span>
        <span class={`status-badge ${badgeClass}`}>
          <span class="dot" />
          {badgeLabel}
        </span>
      </div>
      <div class="task-card-title">{task.title}</div>
      <div class="task-card-footer">
        <span class="task-time">⏱ {timeAgo(task.created_at)}</span>
        <div class="task-actions">
          <button class="task-action-btn" title="Clone" onClick={(e) => { e.stopPropagation(); onClone(task); }}>↻</button>
          <button class="task-action-btn delete" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(task.id); }}>✕</button>
        </div>
      </div>
    </div>
  );
}

export function TaskBoard({ user, onLogout }) {
  const [tasks, setTasks] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [cloneTask, setCloneTask] = useState(null);
  const [streamingTasks, setStreamingTasks] = useState({});
  const [liveMessages, setLiveMessages] = useState({});
  const controllersRef = useRef({});

  const loadTasks = useCallback(async () => {
    try {
      const s = await fetchSessions();
      setTasks(s);
    } catch {}
  }, []);

  useEffect(() => { loadTasks(); }, []);

  useEffect(() => {
    const interval = setInterval(loadTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadDetail = useCallback(async (id) => {
    try {
      const s = await fetchSession(id);
      setSelectedDetail(s);
    } catch {}
  }, []);

  useEffect(() => {
    if (selectedId) loadDetail(selectedId);
  }, [selectedId]);

  const handleSelectTask = (id) => {
    setSelectedId(id);
  };

  const handleDeleteTask = async (id) => {
    await deleteSession(id);
    if (selectedId === id) {
      setSelectedId(null);
      setSelectedDetail(null);
    }
    if (controllersRef.current[id]) {
      controllersRef.current[id].abort();
      delete controllersRef.current[id];
    }
    setStreamingTasks((p) => { const n = { ...p }; delete n[id]; return n; });
    setLiveMessages((p) => { const n = { ...p }; delete n[id]; return n; });
    await loadTasks();
  };

  const handleLaunchTask = async (prompt, settings = {}) => {
    setModalOpen(false);
    setCloneTask(null);

    const stream = createSessionStream(prompt, { title: prompt.slice(0, 80), model: settings.model });
    const tempId = 'pending_' + Date.now();

    setStreamingTasks((p) => ({ ...p, [tempId]: true }));
    setLiveMessages((p) => ({ ...p, [tempId]: [] }));
    controllersRef.current[tempId] = stream.controller;

    let realId = null;

    try {
      for await (const { event, data } of stream.events()) {
        const msgs = liveMessages[realId || tempId] || [];
        let entry = null;

        switch (event) {
          case 'session_created':
            realId = data.id;
            setStreamingTasks((p) => {
              const n = { ...p };
              delete n[tempId];
              n[realId] = true;
              return n;
            });
            setLiveMessages((p) => {
              const n = { ...p };
              const old = n[tempId] || [];
              delete n[tempId];
              n[realId] = old;
              return n;
            });
            controllersRef.current[realId] = controllersRef.current[tempId];
            delete controllersRef.current[tempId];
            setSelectedId(realId);
            await loadTasks();
            break;
          case 'thinking':
            entry = { type: 'thinking', label: 'Thinking', text: data.text || '' };
            break;
          case 'text':
            entry = { type: 'assistant', label: 'Assistant', text: data.text || '' };
            break;
          case 'tool_use':
            entry = mapToolToTimeline(data);
            break;
          case 'tool_result':
            entry = { type: 'tool', label: 'Tool Result', text: JSON.stringify(data).slice(0, 200) };
            break;
          case 'timing':
            entry = { type: 'heartbeat', label: `TTFT: ${data.ttft_ms}ms` };
            break;
          case 'done':
            entry = { type: 'result', label: 'Completed', text: `Task completed`, meta: `${data.total_ms}ms` };
            break;
          case 'error':
            entry = { type: 'error', label: 'Error', text: data.error || 'Unknown error' };
            break;
        }

        if (entry) {
          const key = realId || tempId;
          setLiveMessages((p) => {
            const prev = p[key] || [];
            if (entry.type === 'assistant') {
              const last = prev[prev.length - 1];
              if (last && last.type === 'assistant') {
                return { ...p, [key]: [...prev.slice(0, -1), { ...last, text: last.text + entry.text }] };
              }
            }
            if (entry.type === 'thinking') {
              const last = prev[prev.length - 1];
              if (last && last.type === 'thinking') {
                return { ...p, [key]: [...prev.slice(0, -1), { ...last, text: last.text + entry.text }] };
              }
            }
            return { ...p, [key]: [...prev, entry] };
          });
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        const key = realId || tempId;
        setLiveMessages((p) => ({
          ...p,
          [key]: [...(p[key] || []), { type: 'error', label: 'Error', text: err.message }],
        }));
      }
    } finally {
      const key = realId || tempId;
      setStreamingTasks((p) => { const n = { ...p }; delete n[key]; return n; });
      delete controllersRef.current[key];
      await loadTasks();
      if (realId) loadDetail(realId);
    }
  };

  const handleFollowUp = async (sessionId, message) => {
    const stream = sendMessageStream(sessionId, message);
    setStreamingTasks((p) => ({ ...p, [sessionId]: true }));
    controllersRef.current[sessionId] = stream.controller;

    try {
      for await (const { event, data } of stream.events()) {
        let entry = null;
        switch (event) {
          case 'thinking':
            entry = { type: 'thinking', label: 'Thinking', text: data.text || '' };
            break;
          case 'text':
            entry = { type: 'assistant', label: 'Assistant', text: data.text || '' };
            break;
          case 'tool_use':
            entry = mapToolToTimeline(data);
            break;
          case 'done':
            entry = { type: 'result', label: 'Completed', meta: `${data.total_ms}ms` };
            break;
          case 'error':
            entry = { type: 'error', label: 'Error', text: data.error || '' };
            break;
        }
        if (entry) {
          setLiveMessages((p) => {
            const prev = p[sessionId] || [];
            if ((entry.type === 'assistant' || entry.type === 'thinking') && prev.length) {
              const last = prev[prev.length - 1];
              if (last.type === entry.type) {
                return { ...p, [sessionId]: [...prev.slice(0, -1), { ...last, text: last.text + entry.text }] };
              }
            }
            return { ...p, [sessionId]: [...prev, entry] };
          });
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setLiveMessages((p) => ({
          ...p,
          [sessionId]: [...(p[sessionId] || []), { type: 'error', label: 'Error', text: err.message }],
        }));
      }
    } finally {
      setStreamingTasks((p) => { const n = { ...p }; delete n[sessionId]; return n; });
      delete controllersRef.current[sessionId];
      await loadTasks();
      loadDetail(sessionId);
    }
  };

  const handleStop = (id) => {
    if (controllersRef.current[id]) {
      controllersRef.current[id].abort();
      delete controllersRef.current[id];
    }
    setStreamingTasks((p) => { const n = { ...p }; delete n[id]; return n; });
  };

  const handleClone = (task) => {
    setCloneTask(task);
  };

  const runningTasks = tasks.filter((t) => t.status === 'running' || streamingTasks[t.id]);
  const doneTasks = tasks.filter((t) => t.status !== 'running' && !streamingTasks[t.id]);

  return (
    <div style="display:flex;flex-direction:column;flex:1;min-height:0;">
      <div class="board-layout">
        <div class="board-columns">
          <div class="board-column" style="max-width:320px;">
            <div class="column-header">Running</div>
            <div class="new-task-area">
              <button class="new-task-btn" onClick={() => setModalOpen(true)}>
                <span class="plus-icon">+</span>
                New Task
              </button>
            </div>
            <div class="column-scroll">
              {runningTasks.map((t) => (
                <TaskCard
                  key={t.id}
                  task={{ ...t, status: 'running' }}
                  selected={selectedId === t.id}
                  onClick={() => handleSelectTask(t.id)}
                  onClone={handleClone}
                  onDelete={handleDeleteTask}
                />
              ))}
            </div>
          </div>

          <div class="board-column" style="flex:2;">
            <div class="column-header">Done</div>
            <div class="column-scroll">
              <div class="done-grid">
                {doneTasks.map((t) => (
                  <TaskCard
                    key={t.id}
                    task={t}
                    selected={selectedId === t.id}
                    onClick={() => handleSelectTask(t.id)}
                    onClone={handleClone}
                    onDelete={handleDeleteTask}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>

        <div class="detail-panel">
          {selectedId && selectedDetail ? (
            <TaskDetail
              task={selectedDetail}
              isStreaming={!!streamingTasks[selectedId]}
              liveMessages={liveMessages[selectedId] || []}
              onFollowUp={(msg) => handleFollowUp(selectedId, msg)}
              onStop={() => handleStop(selectedId)}
              onClone={() => handleClone(selectedDetail)}
              onRestart={(prompt) => handleLaunchTask(prompt)}
            />
          ) : (
            <div class="detail-empty">Click a tile to view session details</div>
          )}
        </div>
      </div>

      {(modalOpen || cloneTask) && (
        <NewTaskModal
          cloneFrom={cloneTask}
          onLaunch={handleLaunchTask}
          onClose={() => { setModalOpen(false); setCloneTask(null); }}
        />
      )}
    </div>
  );
}

function mapToolToTimeline(data) {
  const name = (data.name || '').toLowerCase();
  if (name.includes('web_search')) {
    return { type: 'search', label: 'Web Search', text: JSON.stringify(data.input || {}).slice(0, 150) };
  }
  if (name.includes('sql') || name.includes('snowflake_sql')) {
    return { type: 'terminal', label: 'SQL Execute', text: (data.input?.sql || JSON.stringify(data.input || {})).slice(0, 200) };
  }
  if (name.includes('read')) {
    return { type: 'tool', label: 'read', text: data.input?.file_path || '' };
  }
  if (name.includes('glob')) {
    return { type: 'tool', label: 'glob', text: data.input?.pattern || '' };
  }
  if (name.includes('skill')) {
    return { type: 'skill', label: 'skill', text: data.input?.skill_name || data.input?.command || '' };
  }
  if (name.includes('bash') || name.includes('terminal')) {
    return { type: 'terminal', label: 'Terminal', text: (data.input?.command || '').slice(0, 200) };
  }
  return { type: 'tool', label: data.name || 'Tool', text: JSON.stringify(data.input || {}).slice(0, 150) };
}
