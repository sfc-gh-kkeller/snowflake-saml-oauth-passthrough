import { useState, useEffect, useRef, useCallback } from 'preact/hooks';
import { marked } from 'marked';
import {
  fetchSessions, fetchSession, deleteSession, renameSession,
  createSessionWithSuggestionCheck, createSessionStreamSkipSuggestion,
  sendMessageStream, useAsset, registerAssetFromSession,
  connectSessionStream, stopSession,
  createFlag, fetchAssetsBySession, submitFeedback, updateAssetStatus,
  uploadFiles, fileThumbnailUrl, fetchFiles,
  fetchProjects, createProject, deleteProject, updateProject,
  moveSessionToProject, copySession,
  fetchProjectMemory, updateProjectMemory,
  fetchZettelEntries, addZettelEntry, searchZettel, deleteZettelEntry,
  saveToCollection,
} from '../lib/api.js';
import { AssetPanel } from './AssetPanel.jsx';

const DEFAULT_QUICK_QUESTIONS = [
  'What does my homeowners policy cover for water damage?',
  'How do I file an auto claim after an accident?',
  'Explain the difference between term and whole life insurance',
  'What is a deductible and how does it affect my premium?',
  'How does umbrella insurance work?',
  "What's covered under a standard renters policy?",
];

function renderMd(text) {
  return { __html: marked.parse(text || '', { breaks: true }) };
}

function parseWizard(text) {
  const match = text.match(/<!--\s*WIZARD\s*\n([\s\S]*?)\n\s*-->/);
  if (!match) return null;
  try {
    return JSON.parse(match[1]);
  } catch {
    return null;
  }
}

function stripWizard(text) {
  return text.replace(/<!--\s*WIZARD\s*\n[\s\S]*?\n\s*-->/g, '').trim();
}

function stripWorkspaceUpdate(text) {
  return text.replace(/<!--\s*WORKSPACE_UPDATE\s*-->[\s\S]*?<!--\s*\/WORKSPACE_UPDATE\s*-->/g, '').trim();
}

export function QAChat({ user, onLogout, homeSignal, initialSessionId, quickQuestions, features }) {
  const QUICK_QUESTIONS = quickQuestions && quickQuestions.length > 0 ? quickQuestions : DEFAULT_QUICK_QUESTIONS;
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [thinkingText, setThinkingText] = useState('');
  const [showThinking, setShowThinking] = useState(false);
  const [toolCalls, setToolCalls] = useState([]);
  const [activeSkills, setActiveSkills] = useState(null);
  const [reflectPass, setReflectPass] = useState(null);
  const [suggestions, setSuggestions] = useState(null);
  const [questionId, setQuestionId] = useState(null);
  const [assetSaved, setAssetSaved] = useState({});
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [flagReason, setFlagReason] = useState('');
  const [showFlag, setShowFlag] = useState(false);
  const [openAssetId, setOpenAssetId] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [feedbackModal, setFeedbackModal] = useState(null); // {rating: 0|1}
  const [feedbackComment, setFeedbackComment] = useState('');

  const [attachedFiles, setAttachedFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadedFileIds, setUploadedFileIds] = useState([]);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [userFiles, setUserFiles] = useState([]);
  const [projects, setProjects] = useState([]);
  const [activeProject, setActiveProject] = useState(null);
  const [showNewProject, setShowNewProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [showMemory, setShowMemory] = useState(false);
  const [memoryText, setMemoryText] = useState('');
  const [memoryTab, setMemoryTab] = useState('instructions');
  const [zettelEntries, setZettelEntries] = useState([]);
  const [zettelStats, setZettelStats] = useState(null);
  const [zettelSearch, setZettelSearch] = useState('');
  const [zettelResults, setZettelResults] = useState(null);
  const [zettelNewContent, setZettelNewContent] = useState('');

  const [contextMenu, setContextMenu] = useState(null);
  const [showMoveDialog, setShowMoveDialog] = useState(null);
  const [showArchived, setShowArchived] = useState(false);
  const [promptHistory, setPromptHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem('ncx_prompt_history') || '[]'); } catch { return []; }
  });
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [savedInput, setSavedInput] = useState('');
  const [wizardData, setWizardData] = useState(null);
  const [wizardAnswers, setWizardAnswers] = useState({});

  const messagesEnd = useRef(null);
  const inputRef = useRef(null);
  const controllerRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    loadSessions();
    loadProjects();
    if (initialSessionId) {
      selectSession(initialSessionId);
    }
  }, []);

  // React to navigation from other tabs (e.g. Admin clicking a session link)
  useEffect(() => {
    if (initialSessionId) {
      selectSession(initialSessionId);
    }
  }, [initialSessionId]);

  useEffect(() => {
    loadSessions();
  }, [showArchived]);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamText]);

  useEffect(() => {
    if (activeSession?.id && activeSession.status !== 'running') {
      loadSessionAsset(activeSession.id);
    } else {
      setOpenAssetId(null);
    }
  }, [activeSession?.id]);

  useEffect(() => {
    const handler = () => setContextMenu(null);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, []);

  const loadSessionAsset = async (sessionId) => {
    try {
      const assets = await fetchAssetsBySession(sessionId);
      if (assets.length > 0) {
        setOpenAssetId(assets[0].id);
        setAssetSaved((p) => ({ ...p, [sessionId]: assets[0] }));
      }
    } catch (err) {
      console.error('[loadSessionAsset] failed:', err);
    }
  };

  const loadSessions = async () => {
    try {
      const url = showArchived ? '/api/sessions?include_archived=true' : '/api/sessions';
      const token = localStorage.getItem('ncx_token');
      const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      const s = await resp.json();
      setSessions(s);
    } catch {}
  };

  const loadProjects = async () => {
    try {
      const p = await fetchProjects();
      setProjects(p);
    } catch {}
  };

  const selectSession = async (id) => {
    try {
      const s = await fetchSession(id);
      setActiveSession(s);
      setSuggestions(null);
      setQuestionId(null);
      setAttachedFiles([]);
      setUploadedFileIds([]);
      setFeedback(s.feedback ? s.feedback.rating : null);
      setWizardData(null);
      setWizardAnswers({});
      const msgs = [];
      for (const h of s.history || []) {
        const textParts = (h.content || [])
          .filter((c) => c.type === 'text')
          .map((c) => c.text)
          .join('');
        const tools = (h.content || []).filter((c) => c.type === 'tool_use');
        const images = (h.content || []).filter((c) => c.type === 'image');
        if (textParts || tools.length) {
          msgs.push({ role: h.role, text: textParts, tools, imageCount: images.length });
        }
      }
      setMessages(msgs);

      // Re-display wizard if the last message is an assistant wizard (no user reply after it)
      const lastMsg = msgs[msgs.length - 1];
      if (lastMsg && lastMsg.role === 'assistant') {
        const wizard = parseWizard(lastMsg.text);
        if (wizard && wizard.questions) {
          setWizardData(wizard);
          setWizardAnswers({});
        }
      }

      // If session is still running, reconnect to the stream
      if (s.is_running) {
        setStreaming(true);
        setStreamText('');
        setThinkingText('');
        setToolCalls([]);
        const stream = connectSessionStream(id);
        await processStream(stream, id);
      }
    } catch {}
  };


  const processStream = async (stream, sessionId) => {
    controllerRef.current = stream.controller;
    let fullText = '';
    let fullThinking = '';
    let tools = [];

    try {
      for await (const { event, data } of stream.events()) {
        switch (event) {
          case 'session_created':
            if (data.id) {
              sessionId = data.id;
              const s = await fetchSession(data.id);
              setActiveSession(s);
              await loadSessions();
            }
            break;
          case 'text':
            fullText += data.text || '';
            setStreamText(fullText);
            break;
          case 'skills_loaded':
            setActiveSkills(data);
            break;
          case 'reflecting':
            setReflectPass(data);
            break;
          case 'thinking':
            fullThinking += data.text || '';
            setThinkingText(fullThinking);
            break;
          case 'tool_use':
            tools = [...tools, data];
            setToolCalls([...tools]);
            break;
          case 'tool_result':
            break;
          case 'timing':
            break;
          case 'done':
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', text: fullText, thinking: fullThinking, tools },
            ]);
            setStreamText('');
            setThinkingText('');
            setToolCalls([]);
            // Check for wizard block in response
            const wizard = parseWizard(fullText);
            if (wizard && wizard.questions) {
              setWizardData(wizard);
              setWizardAnswers({});
            }
            await loadSessions();
            if (sessionId) {
              const s = await fetchSession(sessionId);
              setActiveSession(s);
            }
            break;
          case 'workspace_created':
            if (data.asset_id) {
              setAssetSaved((p) => ({ ...p, [sessionId]: { id: data.asset_id, filename: data.filename, status: 'draft' } }));
              setOpenAssetId(data.asset_id);
            }
            break;
          case 'workspace_updated':
            if (data.asset_id) {
              setAssetSaved((p) => ({ ...p, [sessionId]: { ...p[sessionId], id: data.asset_id, filename: data.filename, version: data.version } }));
              // Force AssetPanel to refresh by toggling the id
              setOpenAssetId(null);
              setTimeout(() => setOpenAssetId(data.asset_id), 50);
            }
            break;
          case 'error':
            setMessages((prev) => [
              ...prev,
              { role: 'error', text: data.error || 'Unknown error' },
            ]);
            break;
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setMessages((prev) => [...prev, { role: 'error', text: err.message }]);
      }
    } finally {
      setStreaming(false);
      setActiveSkills(null);
      setReflectPass(null);
      controllerRef.current = null;
    }
  };

  const handleFileSelect = async (fileList) => {
    const arr = Array.from(fileList);
    if (arr.length + attachedFiles.length > 10) {
      alert('Max 10 files per message');
      return;
    }
    for (const f of arr) {
      if (f.size > 5 * 1024 * 1024) {
        alert(`File too large: ${f.name} (max 5MB)`);
        return;
      }
    }

    const previews = arr.map(f => ({
      file: f,
      name: f.name,
      type: f.type,
      preview: f.type.startsWith('image/') ? URL.createObjectURL(f) : null,
      isPdf: f.type === 'application/pdf',
    }));
    setAttachedFiles(prev => [...prev, ...previews]);
  };

  const handleRemoveAttachment = (idx) => {
    setAttachedFiles(prev => {
      const next = [...prev];
      if (next[idx].preview) URL.revokeObjectURL(next[idx].preview);
      next.splice(idx, 1);
      return next;
    });
  };

  const handleOpenFilePicker = async () => {
    const files = await fetchFiles();
    setUserFiles(files);
    setShowFilePicker(true);
  };

  const handlePickFile = (f) => {
    // Don't add duplicates
    if (attachedFiles.some(a => a.existingId === f.id)) return;
    setAttachedFiles(prev => [...prev, {
      file: null,
      existingId: f.id,
      name: f.filename,
      type: f.content_type,
      preview: null,
      isPdf: f.file_type === 'pdf',
      isImage: f.file_type === 'image',
    }]);
    setShowFilePicker(false);
  };

  const handleSend = async () => {
    if ((!input.trim() && attachedFiles.length === 0) || streaming) return;
    const msg = input.trim();
    setInput('');

    // Save to prompt history
    if (msg) {
      const newHistory = [msg, ...promptHistory.filter(h => h !== msg)].slice(0, 50);
      setPromptHistory(newHistory);
      localStorage.setItem('ncx_prompt_history', JSON.stringify(newHistory));
    }
    setHistoryIdx(-1);
    setSavedInput('');

    let fileIds = [];
    if (attachedFiles.length > 0) {
      // Separate already-uploaded files (from file picker) from new files (from PC)
      const existingIds = attachedFiles.filter(a => a.existingId).map(a => a.existingId);
      const newFiles = attachedFiles.filter(a => a.file);

      if (newFiles.length > 0) {
        setUploading(true);
        try {
          const rawFiles = newFiles.map(a => a.file);
          const uploaded = await uploadFiles(rawFiles);
          fileIds = uploaded.map(u => u.id);
        } catch (err) {
          alert('Upload failed: ' + err.message);
          setUploading(false);
          return;
        }
        setUploading(false);
      }
      fileIds = [...existingIds, ...fileIds];
    }

    const fileCount = attachedFiles.length;
    setAttachedFiles([]);
    setUploadedFileIds([]);

    setMessages((prev) => [...prev, { role: 'user', text: msg, fileCount }]);
    setSuggestions(null);
    setOpenAssetId(null);

    if (activeSession) {
      setStreaming(true);
      setStreamText('');
      setThinkingText('');
      setToolCalls([]);
      const stream = sendMessageStream(activeSession.id, msg, { file_ids: fileIds.length ? fileIds : undefined });
      await processStream(stream, activeSession.id);
    } else {
      try {
        const result = await createSessionWithSuggestionCheck(msg, {
          file_ids: fileIds.length ? fileIds : undefined,
        });
        if (result.type === 'suggestion') {
          setSuggestions(result.suggestions);
          setQuestionId(result.question_id);
          return;
        }
        if (result.type === 'session') {
          setStreaming(true);
          setStreamText('');
          setThinkingText('');
          setToolCalls([]);
          const sessionId = result.id;
          const s = await fetchSession(sessionId);
          setActiveSession(s);
          await loadSessions();
          const stream = connectSessionStream(sessionId);
          await processStream(stream, sessionId);
        }
      } catch (err) {
        setMessages((prev) => [...prev, { role: 'error', text: err.message }]);
      }
    }
  };

  const handleAcceptSuggestion = async (assetId) => {
    try {
      const result = await useAsset(questionId, assetId);
      setSuggestions(null);
      setQuestionId(null);
      const s = await fetchSession(result.id);
      setActiveSession(s);
      setMessages([
        { role: 'user', text: messages[messages.length - 1]?.text || '' },
        { role: 'assistant', text: result.content, reused: true },
      ]);
      setOpenAssetId(assetId);
      await loadSessions();
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'error', text: err.message }]);
    }
  };

  const handleRejectSuggestion = async () => {
    setSuggestions(null);
    const msg = messages[messages.length - 1]?.text || '';
    setStreaming(true);
    setStreamText('');
    setThinkingText('');
    setToolCalls([]);
    try {
      const result = await createSessionStreamSkipSuggestion(msg, { title: msg.slice(0, 80), question_id: questionId });
      if (result.type === 'session') {
        const sessionId = result.id;
        const s = await fetchSession(sessionId);
        setActiveSession(s);
        await loadSessions();
        const stream = connectSessionStream(sessionId);
        await processStream(stream, sessionId);
      }
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'error', text: err.message }]);
      setStreaming(false);
    }
  };

  const handleStop = () => {
    controllerRef.current?.abort();
    setStreaming(false);
    // Also stop the background task on the server
    if (activeSession) {
      stopSession(activeSession.id).catch(() => {});
    }
  };

  const handleNewSession = () => {
    setActiveSession(null);
    setMessages([]);
    setStreamText('');
    setSuggestions(null);
    setQuestionId(null);
    setOpenAssetId(null);
    setAttachedFiles([]);
    setUploadedFileIds([]);
    setFeedback(null);
    setWizardData(null);
    setWizardAnswers({});
    inputRef.current?.focus();
  };

  useEffect(() => {
    if (homeSignal) handleNewSession();
  }, [homeSignal]);

  const handleDeleteSession = async (id) => {
    await deleteSession(id);
    if (activeSession?.id === id) handleNewSession();
    await loadSessions();
  };

  const handleArchiveSession = async (id) => {
    const token = localStorage.getItem('ncx_token');
    await fetch(`/api/sessions/${id}/archive`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    await loadSessions();
  };

  const handleSetSessionStatus = async (id, status) => {
    const token = localStorage.getItem('ncx_token');
    await fetch(`/api/sessions/${id}/status`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    await loadSessions();
    if (activeSession?.id === id) {
      setActiveSession(prev => ({ ...prev, status }));
    }
  };

  const handleSaveAsset = async () => {
    if (!activeSession) return;
    const saved = assetSaved[activeSession.id];
    try {
      if (saved && saved.id) {
        // Asset already exists (auto-created), submit for review
        await updateAssetStatus(saved.id, 'in_review');
        setAssetSaved((p) => ({ ...p, [activeSession.id]: { ...saved, status: 'in_review' } }));
        setOpenAssetId(saved.id);
      } else {
        // Fallback: create asset from session (legacy path)
        const result = await registerAssetFromSession(activeSession.id);
        setAssetSaved((p) => ({ ...p, [activeSession.id]: result }));
        setOpenAssetId(result.id);
      }
    } catch (err) {
      alert('Failed to submit for review: ' + err.message);
    }
  };

  const handleSaveToCollection = async () => {
    if (!activeSession) return;
    try {
      const result = await saveToCollection(activeSession.id);
      if (result.already) {
        alert('Already in your collection');
      } else {
        await loadProjects();
        await loadSessions();
        const s = await fetchSession(activeSession.id);
        setActiveSession(s);
        alert('Saved to your collection');
      }
    } catch (err) {
      alert('Failed to save to collection: ' + err.message);
    }
  };

  const handleFlagSession = async () => {
    if (!activeSession || !flagReason.trim()) return;
    try {
      await createFlag(activeSession.id, flagReason.trim());
      setShowFlag(false);
      setFlagReason('');
      alert('Session flagged for review');
    } catch (err) {
      alert('Failed to flag: ' + err.message);
    }
  };

  const handleFeedback = async (rating) => {
    if (!activeSession || feedback !== null) return;
    setFeedbackModal({ rating });
    setFeedbackComment('');
  };

  const handleFeedbackSubmit = async () => {
    if (!activeSession || !feedbackModal) return;
    try {
      await submitFeedback(activeSession.id, feedbackModal.rating, feedbackComment.trim() || undefined);
      setFeedback(feedbackModal.rating);
      setFeedbackModal(null);
      setFeedbackComment('');
    } catch (err) {
      alert('Failed to submit feedback: ' + err.message);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    } else if (e.key === 'ArrowUp' && !e.shiftKey) {
      // Only navigate history if cursor is at start of input
      const el = e.target;
      if (el.selectionStart === 0 && el.selectionEnd === 0) {
        e.preventDefault();
        if (historyIdx === -1) setSavedInput(input);
        const nextIdx = Math.min(historyIdx + 1, promptHistory.length - 1);
        if (nextIdx >= 0 && nextIdx < promptHistory.length) {
          setHistoryIdx(nextIdx);
          setInput(promptHistory[nextIdx]);
        }
      }
    } else if (e.key === 'ArrowDown' && !e.shiftKey) {
      const el = e.target;
      if (el.selectionStart === el.value.length) {
        e.preventDefault();
        if (historyIdx > 0) {
          const nextIdx = historyIdx - 1;
          setHistoryIdx(nextIdx);
          setInput(promptHistory[nextIdx]);
        } else if (historyIdx === 0) {
          setHistoryIdx(-1);
          setInput(savedInput);
        }
      }
    }
  };

  const handleWizardSelect = (qId, option) => {
    setWizardAnswers(prev => ({ ...prev, [qId]: option }));
  };

  const handleWizardCustom = (qId, value) => {
    setWizardAnswers(prev => ({ ...prev, [qId]: value }));
  };

  const handleWizardSubmit = () => {
    if (!wizardData) return;
    const lines = wizardData.questions.map((q, i) => {
      const answer = wizardAnswers[q.id] || '(no answer)';
      return `${i + 1}. ${q.question} → ${answer}`;
    });
    const msg = lines.join('\n');
    setWizardData(null);
    setWizardAnswers({});
    setInput('');
    setMessages(prev => [...prev, { role: 'user', text: msg }]);
    if (activeSession) {
      setStreaming(true);
      setStreamText('');
      setThinkingText('');
      setToolCalls([]);
      const stream = sendMessageStream(activeSession.id, msg, {});
      processStream(stream, activeSession.id);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.files.length) {
      handleFileSelect(e.dataTransfer.files);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handlePaste = (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    const imageFiles = [];
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile();
        if (file) imageFiles.push(file);
      }
    }

    if (imageFiles.length > 0) {
      e.preventDefault();
      handleFileSelect(imageFiles);
    }
  };

  const handleCreateProject = async () => {
    if (!newProjectName.trim()) return;
    await createProject(newProjectName.trim());
    setNewProjectName('');
    setShowNewProject(false);
    await loadProjects();
  };

  const handleDeleteProject = async (id) => {
    if (!confirm('Delete project? Chats will be unassigned.')) return;
    await deleteProject(id);
    if (activeProject === id) setActiveProject(null);
    await loadProjects();
    await loadSessions();
  };

  const handleMoveSession = async (sessionId, projectId) => {
    await moveSessionToProject(sessionId, projectId);
    setShowMoveDialog(null);
    await loadSessions();
    await loadProjects();
  };

  const handleCopySession = async (sessionId, projectId) => {
    await copySession(sessionId, projectId);
    setShowMoveDialog(null);
    await loadSessions();
    await loadProjects();
  };

  const handleOpenMemory = async (projectId) => {
    try {
      const data = await fetchProjectMemory(projectId);
      setMemoryText(data.memory || '');
      setShowMemory(projectId);
      setMemoryTab('instructions');
      setZettelResults(null);
      setZettelSearch('');
      setZettelNewContent('');
      loadZettelEntries(projectId);
    } catch {}
  };

  const loadZettelEntries = async (projectId) => {
    try {
      const data = await fetchZettelEntries(projectId);
      setZettelEntries(data.entries || []);
      setZettelStats(data.stats || null);
    } catch {}
  };

  const handleZettelSearch = async () => {
    if (!zettelSearch.trim() || !showMemory) return;
    try {
      const data = await searchZettel(showMemory, zettelSearch.trim());
      setZettelResults(data.results || []);
    } catch {}
  };

  const handleAddZettel = async () => {
    if (!zettelNewContent.trim() || !showMemory) return;
    try {
      await addZettelEntry(showMemory, zettelNewContent.trim());
      setZettelNewContent('');
      await loadZettelEntries(showMemory);
    } catch (err) {
      alert('Failed to add memory: ' + err.message);
    }
  };

  const handleDeleteZettel = async (zettelId) => {
    if (!showMemory) return;
    try {
      await deleteZettelEntry(showMemory, zettelId);
      await loadZettelEntries(showMemory);
      if (zettelResults) setZettelResults(zettelResults.filter(r => r.id !== zettelId));
    } catch {}
  };

  const handleSaveMemory = async () => {
    if (!showMemory) return;
    await updateProjectMemory(showMemory, memoryText);
    setShowMemory(false);
    await loadProjects();
  };

  const handleContextMenu = (e, sessionId) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, sessionId });
  };

  const filteredSessions = activeProject
    ? sessions.filter(s => s.project_id === activeProject)
    : sessions;

  const hasResponse = activeSession?.status !== 'running' && messages.some((m) => m.role === 'assistant');

  return (
    <div class={`qa-layout ${openAssetId ? 'panel-open' : ''}`}>
      <aside class={`qa-sidebar ${sidebarOpen && !openAssetId ? 'open' : ''}`}>
        <div class="qa-sidebar-header">
          <button class="new-session-btn" onClick={handleNewSession}>+ New Chat</button>
        </div>

        {/* Project filter bar */}
        <div class="project-bar">
          <div class="project-tabs">
            <button
              class={`project-tab ${!activeProject ? 'active' : ''}`}
              onClick={() => setActiveProject(null)}
            >All</button>
            {projects.map(p => (
              <button
                key={p.id}
                class={`project-tab ${activeProject === p.id ? 'active' : ''}`}
                onClick={() => setActiveProject(p.id)}
                title={p.description || p.name}
              >
                {p.name}
                <span class="project-count">{p.session_count}</span>
              </button>
            ))}
            {!showNewProject ? (
              <button class="project-tab project-add" onClick={() => setShowNewProject(true)}>+</button>
            ) : (
              <div class="project-new-inline">
                <input
                  value={newProjectName}
                  onInput={e => setNewProjectName(e.target.value)}
                  placeholder="Name..."
                  onKeyDown={e => e.key === 'Enter' && handleCreateProject()}
                  autoFocus
                />
                <button onClick={handleCreateProject}>✓</button>
                <button onClick={() => { setShowNewProject(false); setNewProjectName(''); }}>✕</button>
              </div>
            )}
          </div>
          {activeProject && (
            <div class="project-actions">
              <button class="project-action-btn" onClick={() => handleOpenMemory(activeProject)} title="Project memory">🧠</button>
              <button class="project-action-btn" onClick={() => handleDeleteProject(activeProject)} title="Delete project">🗑</button>
            </div>
          )}
        </div>

        <div class="qa-session-list">
          <button
            class="qa-archive-toggle"
            onClick={() => { setShowArchived(!showArchived); }}
            style={`display:block;width:100%;text-align:left;background:none;border:none;color:${showArchived ? '#60a5fa' : '#475569'};font-size:0.7rem;padding:0.3rem 0.75rem;cursor:pointer;`}
          >{showArchived ? '▼ Showing archived' : '▶ Show archived'}</button>
          {filteredSessions.map((s) => (
            <div
              key={s.id}
              class={`qa-session-item ${activeSession?.id === s.id ? 'active' : ''}`}
              onClick={() => selectSession(s.id)}
              onContextMenu={(e) => handleContextMenu(e, s.id)}
            >
              <span class="qa-session-title">{s.title}</span>
              <div class="qa-session-meta">
                {s.project_id && !activeProject && (
                  <span class="qa-session-project">{projects.find(p => p.id === s.project_id)?.name || '📁'}</span>
                )}
                {s.status === 'running' && <span class="qa-session-status running">●</span>}
                {s.status === 'done' && <span class="qa-session-status done">✓</span>}
                {s.status === 'archived' && <span class="qa-session-status archived">archived</span>}
                <button
                  class="qa-session-delete"
                  onClick={(e) => { e.stopPropagation(); handleDeleteSession(s.id); }}
                >x</button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      {/* Context menu */}
      {contextMenu && (
        <div class="context-menu" style={{ left: contextMenu.x, top: contextMenu.y }}>
          <button onClick={() => { handleSetSessionStatus(contextMenu.sessionId, 'done'); setContextMenu(null); }}>Mark done ✓</button>
          <button onClick={() => { setShowMoveDialog({ sessionId: contextMenu.sessionId, mode: 'move' }); setContextMenu(null); }}>Move to project...</button>
          <button onClick={() => { setShowMoveDialog({ sessionId: contextMenu.sessionId, mode: 'copy' }); setContextMenu(null); }}>Copy to project...</button>
          <button onClick={() => { handleMoveSession(contextMenu.sessionId, null); setContextMenu(null); }}>Remove from project</button>
          <button onClick={() => { handleArchiveSession(contextMenu.sessionId); setContextMenu(null); }}>Archive</button>
          <button onClick={() => { handleDeleteSession(contextMenu.sessionId); setContextMenu(null); }}>Delete chat</button>
        </div>
      )}

      {/* Move/Copy dialog */}
      {showMoveDialog && (
        <div class="modal-backdrop" onClick={() => setShowMoveDialog(null)}>
          <div class="modal-dialog" onClick={e => e.stopPropagation()}>
            <h3>{showMoveDialog.mode === 'move' ? 'Move' : 'Copy'} to project</h3>
            <div class="modal-list">
              {projects.map(p => (
                <button
                  key={p.id}
                  class="modal-list-item"
                  onClick={() => showMoveDialog.mode === 'move'
                    ? handleMoveSession(showMoveDialog.sessionId, p.id)
                    : handleCopySession(showMoveDialog.sessionId, p.id)
                  }
                >{p.name}</button>
              ))}
              {projects.length === 0 && <p class="modal-empty">No projects yet</p>}
            </div>
            <button class="modal-cancel" onClick={() => setShowMoveDialog(null)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Memory editor modal */}
      {showMemory && (
        <div class="modal-backdrop" onClick={() => setShowMemory(false)}>
          <div class="modal-dialog modal-large" onClick={e => e.stopPropagation()}>
            <h3>Project Memory</h3>
            <div class="memory-tabs">
              <button class={`memory-tab ${memoryTab === 'instructions' ? 'active' : ''}`} onClick={() => setMemoryTab('instructions')}>Instructions</button>
              <button class={`memory-tab ${memoryTab === 'zettel' ? 'active' : ''}`} onClick={() => setMemoryTab('zettel')}>
                Semantic Memory {zettelStats?.total_zettels > 0 && <span class="memory-tab-badge">{zettelStats.total_zettels}</span>}
              </button>
            </div>

            {memoryTab === 'instructions' && (
              <div class="memory-panel">
                <p class="modal-hint">Manual instructions injected into every chat in this project.</p>
                <textarea
                  class="memory-editor"
                  value={memoryText}
                  onInput={e => setMemoryText(e.target.value)}
                  placeholder="Add context that should be shared across all chats in this project..."
                  rows={10}
                />
                <div class="modal-actions">
                  <button class="modal-cancel" onClick={() => setShowMemory(false)}>Cancel</button>
                  <button class="modal-save" onClick={handleSaveMemory}>Save</button>
                </div>
              </div>
            )}

            {memoryTab === 'zettel' && (
              <div class="memory-panel">
                <p class="modal-hint">
                  Auto-collected semantic memories from conversations. Relevant memories are injected into new chats.
                  {zettelStats?.plugin === 'none' && <strong> (Plugin not active — install zettelkasten-memory)</strong>}
                </p>

                {zettelStats && zettelStats.plugin !== 'none' && (
                  <div class="zettel-stats">
                    <span>{zettelStats.total_zettels} memories</span>
                    <span>{zettelStats.total_connections} connections</span>
                  </div>
                )}

                <div class="zettel-search">
                  <input
                    value={zettelSearch}
                    onInput={e => setZettelSearch(e.target.value)}
                    placeholder="Search memories..."
                    onKeyDown={e => e.key === 'Enter' && handleZettelSearch()}
                  />
                  <button onClick={handleZettelSearch}>Search</button>
                </div>

                {zettelResults && (
                  <div class="zettel-results">
                    <h4>Search Results ({zettelResults.length})</h4>
                    {zettelResults.map(r => (
                      <div key={r.id} class="zettel-entry">
                        <div class="zettel-score">Score: {r.score}</div>
                        <div class="zettel-content">{r.content}</div>
                        <div class="zettel-meta">
                          {r.tags.length > 0 && r.tags.map(t => <span key={t} class="zettel-tag">{t}</span>)}
                          <button class="zettel-delete" onClick={() => handleDeleteZettel(r.id)}>x</button>
                        </div>
                      </div>
                    ))}
                    {zettelResults.length === 0 && <p class="zettel-empty">No matching memories</p>}
                    <button class="zettel-clear-search" onClick={() => setZettelResults(null)}>Back to list</button>
                  </div>
                )}

                {!zettelResults && (
                  <div class="zettel-list">
                    {zettelEntries.map(z => (
                      <div key={z.id} class="zettel-entry">
                        <div class="zettel-content">{z.content}</div>
                        <div class="zettel-meta">
                          {z.tags.length > 0 && z.tags.slice(0, 5).map(t => <span key={t} class="zettel-tag">{t}</span>)}
                          <span class="zettel-importance">imp: {z.importance}</span>
                          <span class="zettel-connections">{z.connections} links</span>
                          <button class="zettel-delete" onClick={() => handleDeleteZettel(z.id)}>x</button>
                        </div>
                      </div>
                    ))}
                    {zettelEntries.length === 0 && <p class="zettel-empty">No memories yet. Chat within this project to auto-collect memories.</p>}
                  </div>
                )}

                <div class="zettel-add">
                  <input
                    value={zettelNewContent}
                    onInput={e => setZettelNewContent(e.target.value)}
                    placeholder="Manually add a memory..."
                    onKeyDown={e => e.key === 'Enter' && handleAddZettel()}
                  />
                  <button onClick={handleAddZettel} disabled={!zettelNewContent.trim()}>Add</button>
                </div>

                <div class="modal-actions">
                  <button class="modal-cancel" onClick={() => setShowMemory(false)}>Close</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <main class="qa-main">
        <div class="qa-messages">
          {messages.length === 0 && !streaming && !suggestions && (
            <div class="qa-empty">
              <div class="qa-empty-icon">🛡</div>
              <h2>Q&A</h2>
              <p>Ask a question. Attach images or PDFs for visual context. AI-powered agent with configurable knowledge categories.</p>
              <div class="qa-quick-grid">
                {QUICK_QUESTIONS.map((q) => (
                  <button key={q} class="qa-quick-btn" onClick={() => setInput(q)}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {suggestions && (
            <div class="qa-suggestions">
              <div class="qa-suggestion-header">
                <span class="qa-suggestion-icon">📋</span>
                <span>Similar approved answers found</span>
              </div>
              <p class="qa-suggestion-desc">We found existing approved responses that may answer your question. You can reuse one or generate a new response.</p>
              {suggestions.map((s) => (
                <div key={s.id} class="qa-suggestion-card">
                  <div class="qa-suggestion-card-header">
                    <span class="qa-suggestion-filename">{s.filename}</span>
                    {s.topic && <span class="qa-suggestion-topic">{s.topic}</span>}
                    <span class="qa-suggestion-score">{(s.similarity * 100).toFixed(0)}% match</span>
                  </div>
                  <p class="qa-suggestion-preview">{s.preview}</p>
                  <button class="qa-suggestion-accept" onClick={() => handleAcceptSuggestion(s.id)}>Use this answer</button>
                </div>
              ))}
              <button class="qa-suggestion-reject" onClick={handleRejectSuggestion}>Generate new response instead</button>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} class={`qa-message ${m.role}`}>
              <div class="qa-message-role">
                {m.role === 'user' ? 'You' : m.role === 'error' ? 'Error' : 'Agent'}
                {m.reused && <span class="qa-reused-badge">Reused</span>}
                {m.fileCount > 0 && <span class="qa-file-badge">{m.fileCount} file{m.fileCount > 1 ? 's' : ''}</span>}
              </div>
              {showThinking && m.thinking && (
                <details class="qa-thinking">
                  <summary>Thinking...</summary>
                  <div dangerouslySetInnerHTML={renderMd(m.thinking)} />
                </details>
              )}
              {m.tools?.length > 0 && (
                <div class="qa-tool-calls">
                  {m.tools.map((t, j) => (
                    <div key={j} class="qa-tool-call">
                      <span class="qa-tool-name">{t.name}</span>
                      <code>{JSON.stringify(t.input, null, 2).slice(0, 200)}</code>
                    </div>
                  ))}
                </div>
              )}
              <div class="qa-message-content" dangerouslySetInnerHTML={renderMd(m.role === 'assistant' ? stripWorkspaceUpdate(stripWizard(m.text)) : m.text)} />
            </div>
          ))}

          {streaming && (
            <div class="qa-message assistant streaming">
              <div class="qa-message-role">Agent</div>
              {activeSkills && (activeSkills.mandatory_skills?.length > 0 || activeSkills.detected_skill || activeSkills.dynamic_loaded?.length > 0) && (
                <div style="display:flex;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.5rem;">
                  {(activeSkills.mandatory_skills || []).map(s => (
                    <span key={s} style="background:#1e293b;color:#94a3b8;font-size:0.7rem;padding:0.15rem 0.5rem;border-radius:10px;border:1px solid #334155;">
                      {s}
                    </span>
                  ))}
                  {activeSkills.detected_skill && (
                    <span style="background:#1e3a5f;color:#60a5fa;font-size:0.7rem;padding:0.15rem 0.5rem;border-radius:10px;border:1px solid #3b82f6;">
                      {activeSkills.detected_skill}
                    </span>
                  )}
                  {(activeSkills.dynamic_loaded || []).map(s => (
                    <span key={s} style="background:#1a2e1a;color:#34d399;font-size:0.7rem;padding:0.15rem 0.5rem;border-radius:10px;border:1px solid #059669;">
                      {s}
                    </span>
                  ))}
                </div>
              )}
              {showThinking && thinkingText && (
                <details class="qa-thinking" open>
                  <summary>Thinking...</summary>
                  <div dangerouslySetInnerHTML={renderMd(thinkingText)} />
                </details>
              )}
              {toolCalls.length > 0 && (
                <div class="qa-tool-calls">
                  {toolCalls.map((t, j) => (
                    <div key={j} class="qa-tool-call">
                      <span class="qa-tool-name">{t.name}</span>
                    </div>
                  ))}
                </div>
              )}
              {reflectPass && !streamText && (
                <div style="display:flex;align-items:center;gap:0.5rem;margin:0.5rem 0;">
                  <span style="background:#2e1a3e;color:#c084fc;font-size:0.7rem;padding:0.2rem 0.6rem;border-radius:10px;border:1px solid #7c3aed;animation:pulse 1.5s infinite;">
                    L{reflectPass.pass} verification{reflectPass.total > 1 ? ` (${reflectPass.pass}/${reflectPass.total})` : ''}
                  </span>
                </div>
              )}
              {streamText ? (
                <div class="qa-message-content" dangerouslySetInnerHTML={renderMd(stripWorkspaceUpdate(streamText))} />
              ) : !thinkingText ? (
                <div class="typing-dots"><span /><span /><span /></div>
              ) : null}
            </div>
          )}

          {wizardData && !streaming && (
            <div style="background:#0f172a;border:1px solid #3b82f6;border-radius:10px;padding:1.25rem;margin:0.75rem 0;">
              <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;">
                <span style="font-size:1.2rem;">🧙</span>
                <span style="color:#60a5fa;font-weight:600;font-size:0.95rem;">Clarification Needed</span>
              </div>
              {wizardData.questions.map((q, qi) => (
                <div key={q.id} style="margin-bottom:1rem;">
                  <div style="color:#e2e8f0;font-size:0.88rem;margin-bottom:0.5rem;font-weight:500;">{qi + 1}. {q.question}</div>
                  <div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:0.4rem;">
                    {q.options.map(opt => (
                      <button
                        key={opt}
                        onClick={() => handleWizardSelect(q.id, opt)}
                        style={`padding:0.35rem 0.7rem;border-radius:6px;font-size:0.8rem;cursor:pointer;border:1px solid ${wizardAnswers[q.id] === opt ? '#3b82f6' : '#334155'};background:${wizardAnswers[q.id] === opt ? '#1e3a5f' : '#1e293b'};color:${wizardAnswers[q.id] === opt ? '#93c5fd' : '#94a3b8'};`}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                  <input
                    type="text"
                    placeholder="Or type a custom answer..."
                    value={wizardAnswers[q.id] && !q.options.includes(wizardAnswers[q.id]) ? wizardAnswers[q.id] : ''}
                    onInput={e => { if (e.target.value) handleWizardCustom(q.id, e.target.value); }}
                    style="width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:0.35rem 0.6rem;font-size:0.8rem;margin-top:0.3rem;"
                  />
                </div>
              ))}
              <div style="display:flex;gap:0.5rem;margin-top:0.75rem;">
                <button
                  onClick={handleWizardSubmit}
                  style="background:#3b82f6;color:white;border:none;border-radius:6px;padding:0.5rem 1.2rem;font-size:0.85rem;font-weight:500;cursor:pointer;"
                >
                  Submit Answers
                </button>
                <button
                  onClick={() => { setWizardData(null); setWizardAnswers({}); }}
                  style="background:none;color:#64748b;border:1px solid #334155;border-radius:6px;padding:0.5rem 1rem;font-size:0.85rem;cursor:pointer;"
                >
                  Skip
                </button>
              </div>
            </div>
          )}

          <div ref={messagesEnd} />
        </div>

        {hasResponse && !streaming && (
          <div class="qa-action-bar">
            <div class="qa-feedback-group">
              <button
                class={`qa-feedback-btn like ${feedback === 1 ? 'active' : ''}`}
                onClick={() => handleFeedback(1)}
                disabled={feedback !== null}
                title="Good response"
              >&#x1F44D;</button>
              <button
                class={`qa-feedback-btn dislike ${feedback === 0 ? 'active' : ''}`}
                onClick={() => handleFeedback(0)}
                disabled={feedback !== null}
                title="Bad response"
              >&#x1F44E;</button>
            </div>
            {!assetSaved[activeSession.id] || assetSaved[activeSession.id].status === 'draft' ? (
              <div style="display:flex;gap:0.4rem;">
                <button class="qa-action-btn save" onClick={handleSaveAsset}>Submit for Review</button>
                <button class="qa-action-btn save" onClick={handleSaveToCollection} style="background:#1e293b;border:1px solid #334155;">Save to Collection</button>
              </div>
            ) : (
              <span class="qa-action-saved">
                {assetSaved[activeSession.id].filename}
                {assetSaved[activeSession.id].visibility === 'private' ? ' (private)' : ` (${assetSaved[activeSession.id].status})`}
              </span>
            )}
            <button class="qa-action-btn flag" onClick={() => setShowFlag(!showFlag)}>Flag for Review</button>
            {activeSession.status !== 'done' ? (
              <button class="qa-action-btn" onClick={() => handleSetSessionStatus(activeSession.id, 'done')} style="background:#059669;color:white;">Mark Done</button>
            ) : (
              <button class="qa-action-btn" onClick={() => handleSetSessionStatus(activeSession.id, 'active')} style="background:#1e293b;border:1px solid #334155;color:#34d399;">✓ Done</button>
            )}
            {showFlag && (
              <div class="qa-flag-input">
                <input
                  value={flagReason}
                  onInput={(e) => setFlagReason(e.target.value)}
                  placeholder="Reason for flagging..."
                  onKeyDown={(e) => e.key === 'Enter' && handleFlagSession()}
                />
                <button onClick={handleFlagSession}>Submit</button>
              </div>
            )}
          </div>
        )}

        {/* Feedback Modal */}
        {feedbackModal && (
          <div style="position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:1000;display:flex;align-items:center;justify-content:center;padding:2rem;" onClick={() => setFeedbackModal(null)}>
            <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;max-width:400px;width:100%;padding:1.5rem;" onClick={e => e.stopPropagation()}>
              <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;">
                <span style="font-size:1.5rem;">{feedbackModal.rating === 1 ? '\u{1F44D}' : '\u{1F44E}'}</span>
                <h3 style="color:#f1f5f9;margin:0;font-size:1rem;">
                  {feedbackModal.rating === 1 ? 'Glad this was helpful!' : 'Sorry about that'}
                </h3>
              </div>
              <p style="color:#94a3b8;font-size:0.85rem;margin:0 0 1rem 0;">
                Want to add a comment? (optional)
              </p>
              <textarea
                value={feedbackComment}
                onInput={e => setFeedbackComment(e.target.value)}
                rows={3}
                placeholder={feedbackModal.rating === 1 ? 'What was good about this response?' : 'What could be improved?'}
                style="width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:0.75rem;font-size:0.85rem;resize:vertical;box-sizing:border-box;margin-bottom:1rem;"
              />
              <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
                <button onClick={() => setFeedbackModal(null)} style="background:none;border:1px solid #334155;color:#94a3b8;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.85rem;cursor:pointer;">Cancel</button>
                <button onClick={handleFeedbackSubmit} style="background:#059669;color:white;border:none;border-radius:6px;padding:0.4rem 0.75rem;font-size:0.85rem;cursor:pointer;">Submit Feedback</button>
              </div>
            </div>
          </div>
        )}

        {/* Attachment previews */}
        {attachedFiles.length > 0 && (
          <div class="qa-attachments">
            {attachedFiles.map((a, i) => (
              <div key={i} class="qa-attachment">
                {a.preview ? (
                  <img src={a.preview} class="qa-attachment-thumb" />
                ) : (
                  <div class="qa-attachment-icon">{a.isImage ? '🖼' : a.isPdf ? '📄' : '📎'}</div>
                )}
                <span class="qa-attachment-name">{a.name}</span>
                <button class="qa-attachment-remove" onClick={() => handleRemoveAttachment(i)}>✕</button>
              </div>
            ))}
          </div>
        )}

        <div class="qa-input-area" onDrop={handleDrop} onDragOver={handleDragOver}>
          <input
            type="file"
            ref={fileInputRef}
            style="display:none"
            multiple
            accept="image/png,image/jpeg,image/gif,image/webp,application/pdf"
            onChange={e => { handleFileSelect(e.target.files); e.target.value = ''; }}
          />
          <button
            class="qa-attach-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={streaming || uploading}
            title="Attach files from your computer"
          >📎</button>
          <button
            class="qa-attach-btn qa-files-btn"
            onClick={handleOpenFilePicker}
            disabled={streaming || uploading}
            title="Pick from your Files library"
          >📁</button>
          {features?.thinking && (
            <button
              class={`qa-attach-btn qa-thinking-toggle ${showThinking ? 'active' : ''}`}
              onClick={() => setShowThinking(t => !t)}
              title={showThinking ? "Hide thinking" : "Show thinking"}
            >🧠</button>
          )}

          {showFilePicker && (
            <div class="qa-file-picker-overlay" onClick={() => setShowFilePicker(false)}>
              <div class="qa-file-picker" onClick={e => e.stopPropagation()}>
                <div class="qa-file-picker-header">
                  <span>Pick from Files</span>
                  <button onClick={() => setShowFilePicker(false)}>✕</button>
                </div>
                {userFiles.length === 0 ? (
                  <div class="qa-file-picker-empty">No files in your library yet.</div>
                ) : (
                  <div class="qa-file-picker-list">
                    {userFiles.map(f => (
                      <div
                        key={f.id}
                        class="qa-file-picker-item"
                        onClick={() => handlePickFile(f)}
                      >
                        <span class="qa-file-picker-icon">{f.file_type === 'image' ? '🖼' : f.file_type === 'pdf' ? '📄' : '📎'}</span>
                        <span class="qa-file-picker-name" title={f.filename}>{f.filename}</span>
                        <span class="qa-file-picker-size">{f.file_size < 1024*1024 ? (f.file_size/1024).toFixed(0) + ' KB' : (f.file_size/(1024*1024)).toFixed(1) + ' MB'}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
          <textarea
            ref={inputRef}
            value={input}
            onInput={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={uploading ? 'Uploading files...' : 'Ask a question... (paste or drop images here)'}
            rows={2}
            disabled={streaming || uploading}
          />
          <div class="qa-input-actions">
            {streaming ? (
              <button class="qa-stop-btn" onClick={handleStop}>Stop</button>
            ) : (
              <button class="qa-send-btn" onClick={handleSend} disabled={(!input.trim() && attachedFiles.length === 0) || uploading}>
                {uploading ? '...' : 'Send'}
              </button>
            )}
          </div>
        </div>
      </main>

      {openAssetId && (
        <AssetPanel assetId={openAssetId} onClose={() => setOpenAssetId(null)} />
      )}
    </div>
  );
}
