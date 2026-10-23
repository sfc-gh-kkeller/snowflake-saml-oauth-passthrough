import { useState } from 'preact/hooks';

export function NewTaskModal({ cloneFrom, onLaunch, onClose }) {
  const [prompt, setPrompt] = useState(cloneFrom?.title || '');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [model, setModel] = useState('');

  const isClone = !!cloneFrom;

  const handleSubmit = () => {
    if (!prompt.trim()) return;
    onLaunch(prompt.trim(), { model: model || undefined });
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSubmit();
    }
    if (e.key === 'Escape') onClose();
  };

  return (
    <div class="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div class="modal" onKeyDown={handleKeyDown}>
        <div class="modal-title">{isClone ? 'Clone Task' : 'New Task'}</div>
        <div class="modal-label">Prompt</div>
        <textarea
          value={prompt}
          onInput={(e) => setPrompt(e.target.value)}
          placeholder="What would you like the agent to do?"
          autoFocus
        />

        <button
          class="modal-advanced-toggle"
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          <span class={`chevron ${showAdvanced ? 'open' : ''}`}>▶</span>
          Advanced Settings
        </button>

        {showAdvanced && (
          <div class="modal-advanced">
            <label>Model override</label>
            <input
              type="text"
              value={model}
              onInput={(e) => setModel(e.target.value)}
              placeholder="Leave empty for default"
            />
          </div>
        )}

        <div class="modal-footer">
          <button class="btn-cancel" onClick={onClose}>Cancel</button>
          {isClone ? (
            <button class="btn-clone" onClick={handleSubmit} disabled={!prompt.trim()}>
              📋 Clone & Launch
            </button>
          ) : (
            <button class="btn-launch" onClick={handleSubmit} disabled={!prompt.trim()}>
              ▶ Launch Task
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
