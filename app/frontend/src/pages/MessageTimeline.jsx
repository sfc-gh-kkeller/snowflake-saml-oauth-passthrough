import { useState } from 'preact/hooks';
import { marked } from 'marked';

const ICON_MAP = {
  terminal: { icon: '>', cls: 'terminal' },
  assistant: { icon: '●', cls: 'assistant' },
  thinking: { icon: '◐', cls: 'thinking' },
  tool: { icon: '◆', cls: 'tool' },
  skill: { icon: '🔥', cls: 'skill' },
  search: { icon: '🔍', cls: 'search' },
  user: { icon: '◎', cls: 'user' },
  result: { icon: '●', cls: 'result' },
  error: { icon: '✕', cls: 'error' },
  init: { icon: '▷', cls: 'init' },
  heartbeat: { icon: '♡', cls: 'heartbeat' },
};

function renderMarkdown(text) {
  try {
    return { __html: marked.parse(text || '', { breaks: true }) };
  } catch {
    return { __html: text || '' };
  }
}

function TimelineEntry({ entry }) {
  const [expanded, setExpanded] = useState(false);
  const config = ICON_MAP[entry.type] || ICON_MAP.tool;

  if (entry.type === 'heartbeat') {
    return (
      <div class="timeline-heartbeats">
        <span>♡</span>
        <span>{entry.label || '1 heartbeat'}</span>
      </div>
    );
  }

  if (entry.type === 'result') {
    const isSuccess = !entry.text?.toLowerCase().includes('error');
    return (
      <div class="timeline-entry">
        <div class={`timeline-icon ${config.cls}`}>{config.icon}</div>
        <div class="timeline-body">
          <div class={`timeline-result`}>
            <div class={`timeline-result-status ${isSuccess ? 'success' : 'error'}`}>
              {entry.label || 'Result'}
            </div>
            {entry.meta && <div class="timeline-result-meta">{entry.meta}</div>}
            {entry.text && (
              <div class="timeline-result-text" dangerouslySetInnerHTML={renderMarkdown(entry.text)} />
            )}
          </div>
        </div>
      </div>
    );
  }

  if (entry.type === 'assistant') {
    return (
      <div class="timeline-entry">
        <div class={`timeline-icon ${config.cls}`}>{config.icon}</div>
        <div class="timeline-body">
          <div class="timeline-label">{entry.label || 'Assistant'}</div>
          <div
            class={`timeline-result-text`}
            dangerouslySetInnerHTML={renderMarkdown(entry.text || '')}
          />
        </div>
      </div>
    );
  }

  return (
    <div class="timeline-entry">
      <div class={`timeline-icon ${config.cls}`}>{config.icon}</div>
      <div class="timeline-body">
        <div class="timeline-label">{entry.label}</div>
        {entry.text && (
          <div
            class={`timeline-text ${expanded ? 'expanded' : ''}`}
            onClick={() => setExpanded(!expanded)}
          >
            {entry.text}
          </div>
        )}
        {entry.meta && <div class="timeline-meta">{entry.meta}</div>}
      </div>
    </div>
  );
}

export function MessageTimeline({ messages, isStreaming }) {
  if (!messages.length && !isStreaming) {
    return <div style="color:var(--text-muted);font-size:13px;padding:8px 0;">No messages yet</div>;
  }

  return (
    <div class="timeline">
      {messages.map((m, i) => (
        <TimelineEntry key={i} entry={m} />
      ))}
      {isStreaming && (
        <div class="timeline-entry">
          <div class="timeline-icon init">◐</div>
          <div class="timeline-body">
            <div class="typing-dots"><span /><span /><span /></div>
          </div>
        </div>
      )}
    </div>
  );
}
