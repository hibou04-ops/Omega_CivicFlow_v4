import { useEffect, useRef, useState } from 'react';
import { panelAPI } from '../api/client';

const BOT_STYLE = `
@keyframes omega-chat-slide-up {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes omega-chat-pulse {
  0%, 80%, 100% { opacity: 0.25; transform: scale(0.9); }
  40% { opacity: 1; transform: scale(1); }
}
.omega-chat-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}
.omega-chat-table th,
.omega-chat-table td {
  padding: 0.55rem 0.7rem;
  border-bottom: 1px solid rgba(192, 160, 96, 0.12);
  text-align: left;
  white-space: nowrap;
}
.omega-chat-table th {
  color: rgba(192, 160, 96, 0.95);
  font-weight: 700;
}
.omega-chat-table td {
  color: rgba(255, 255, 255, 0.82);
  white-space: normal;
  word-break: break-word;
}
`;

const TOOL_LABELS = {
  search_my_documents: '내 문서 검색',
  semantic_search: '시맨틱 검색',
  search_dart_filings: 'DART 공시',
  get_document_detail: '문서 상세',
  get_document_stats: '문서 통계',
  structured_facts: '구조화 팩트',
  chromadb_search: '문서 검색',
  metadata_search: '메타데이터 검색',
};

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function decodeUnicodeEscapes(value) {
  if (typeof value !== 'string' || !value.includes('\\')) {
    return value;
  }

  return value
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t');
}

function normalizeServerValue(value) {
  if (Array.isArray(value)) {
    return value.map(normalizeServerValue);
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalizeServerValue(item)]));
  }
  return decodeUnicodeEscapes(value);
}

function renderMarkdown(text) {
  const escaped = escapeHtml(text);

  // Inline formatting (applied to each line)
  function inlineFmt(s) {
    return s
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" style="color:rgba(192,160,96,0.95);text-decoration:underline;">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer" style="color:rgba(192,160,96,0.95);text-decoration:underline;">$2</a>')
      .replace(/\*\*(.+?)\*\*/g, '<strong style="color:rgba(255,255,255,0.95);">$1</strong>');
  }

  const lines = escaped.split('\n');
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // Empty line → paragraph gap
    if (trimmed === '') {
      out.push('<div style="height:8px;"></div>');
      i++;
      continue;
    }

    // Section header: standalone bold label (e.g. **근거** or **결론**:)
    if (/^\*\*[^*]+\*\*:?\s*$/.test(trimmed)) {
      const label = trimmed.replace(/^\*\*/, '').replace(/\*\*:?\s*$/, '');
      out.push(`<div style="margin-top:4px;padding-bottom:3px;border-bottom:1px solid rgba(192,160,96,0.15);color:rgba(192,160,96,0.95);font-weight:600;font-size:0.82rem;">${escapeHtml(label)}</div>`);
      i++;
      continue;
    }

    // List item: starts with - or • or 1. 2. etc
    if (/^\s*[-•]\s+/.test(trimmed) || /^\s*\d+[.)]\s+/.test(trimmed)) {
      // Collect consecutive list items
      const items = [];
      while (i < lines.length) {
        const li = lines[i].trim();
        if (/^[-•]\s+/.test(li) || /^\d+[.)]\s+/.test(li)) {
          const content = li.replace(/^[-•]\s+/, '').replace(/^\d+[.)]\s+/, '');
          items.push(inlineFmt(content));
          i++;
        } else {
          break;
        }
      }
      const listHtml = items.map(
        (item) => `<div style="display:flex;gap:7px;align-items:baseline;padding:2px 0;"><span style="color:rgba(192,160,96,0.65);flex-shrink:0;font-size:0.7rem;">●</span><span>${item}</span></div>`
      ).join('');
      out.push(`<div style="display:flex;flex-direction:column;gap:1px;padding-left:2px;">${listHtml}</div>`);
      continue;
    }

    // Bold-prefixed line: **결론**: some text → styled inline header
    if (/^\*\*[^*]+\*\*/.test(trimmed)) {
      out.push(`<div style="padding:1px 0;">${inlineFmt(trimmed)}</div>`);
      i++;
      continue;
    }

    // Regular text line
    out.push(`<div style="padding:1px 0;">${inlineFmt(trimmed)}</div>`);
    i++;
  }

  return out.join('');
}

function TypingIndicator() {
  return (
    <div style={{ display: 'flex', gap: 6, padding: '0.7rem 0.85rem' }}>
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: 'rgba(192,160,96,0.85)',
            animation: `omega-chat-pulse 1.2s ease-in-out ${index * 0.16}s infinite`,
          }}
        />
      ))}
    </div>
  );
}

function PayloadTable({ columns, rows }) {
  if (!rows?.length) {
    return null;
  }

  return (
    <div
      style={{
        marginTop: 12,
        overflowX: 'auto',
        borderRadius: 10,
        border: '1px solid rgba(192,160,96,0.18)',
        background: 'rgba(0,0,0,0.22)',
      }}
    >
      <table className="omega-chat-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.document_id || row.company_name || 'row'}-${index}`}>
              {columns.map((column) => (
                <td key={column.key}>{row[column.key] ?? '-'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TrendTable({ series }) {
  if (!series?.length) {
    return null;
  }

  const years = [...new Set(series.flatMap((item) => (item.points || []).map((point) => point.year)))].sort();
  const rows = series.map((item) => {
    const row = { company_name: item.company_name };
    years.forEach((year) => {
      const point = (item.points || []).find((candidate) => candidate.year === year);
      row[`year_${year}`] = point?.value_display || '-';
    });
    return row;
  });

  const columns = [
    { key: 'company_name', label: '회사' },
    ...years.map((year) => ({ key: `year_${year}`, label: `${year}년` })),
  ];

  return <PayloadTable columns={columns} rows={rows} />;
}

function CitationPanel({ citations }) {
  if (!citations?.length) {
    return null;
  }

  return (
    <div
      style={{
        marginTop: 12,
        padding: '0.8rem',
        borderRadius: 10,
        background: 'rgba(0,0,0,0.18)',
        border: '1px solid rgba(192,160,96,0.16)',
      }}
    >
      <div
        style={{
          marginBottom: 10,
          fontSize: '0.72rem',
          fontWeight: 700,
          color: 'rgba(192,160,96,1)',
          letterSpacing: '0.03em',
        }}
      >
        근거 문서
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {citations.slice(0, 5).map((citation, index) => {
          const filename = citation.filename || '문서';
          const sourceText = String(citation.source_text || '').replace(/\s+/g, ' ').trim();

          return (
            <div
              key={`${citation.document_id || filename}-${index}`}
              style={{
                padding: '0.7rem 0.8rem',
                borderRadius: 8,
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(192,160,96,0.12)',
              }}
            >
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                {citation.document_id ? (
                  <a
                    href={`/view/${citation.document_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: 'rgba(192,160,96,0.95)',
                      textDecoration: 'underline',
                      fontSize: '0.7rem',
                    }}
                  >
                    {filename}
                  </a>
                ) : (
                  <span style={{ color: 'rgba(192,160,96,0.95)', fontSize: '0.7rem' }}>{filename}</span>
                )}
                {citation.company ? (
                  <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.68rem' }}>
                    {citation.company}
                  </span>
                ) : null}
              </div>
              {sourceText ? (
                <div
                  style={{
                    marginTop: 6,
                    color: 'rgba(255,255,255,0.7)',
                    fontSize: '0.7rem',
                    lineHeight: 1.55,
                    wordBreak: 'break-word',
                  }}
                >
                  {sourceText.length > 180 ? `${sourceText.slice(0, 180)}...` : sourceText}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StructuredPayload({ payload }) {
  if (!payload) {
    return null;
  }

  if (payload.type === 'ranking' || payload.type === 'summary') {
    const rows = (payload.rows || []).map((row, index) => ({
      rank: payload.type === 'ranking' ? index + 1 : undefined,
      company_name: row.company_name || '-',
      metric_label: row.metric_label || '-',
      value_display: row.value_display || '-',
      fiscal_year: row.fiscal_year ? `${row.fiscal_year}년` : '-',
      statement_scope: row.statement_scope || '-',
    }));

    const columns =
      payload.type === 'ranking'
        ? [
            { key: 'rank', label: '#' },
            { key: 'company_name', label: '회사' },
            { key: 'value_display', label: payload.criteria?.metric_label || '값' },
            { key: 'fiscal_year', label: '연도' },
            { key: 'statement_scope', label: '기준' },
          ]
        : [
            { key: 'metric_label', label: '지표' },
            { key: 'value_display', label: '값' },
            { key: 'fiscal_year', label: '연도' },
            { key: 'statement_scope', label: '기준' },
          ];

    return (
      <>
        <PayloadTable columns={columns} rows={rows} />
        <CitationPanel citations={payload.citations} />
      </>
    );
  }

  if (payload.type === 'trend') {
    return (
      <>
        <TrendTable series={payload.series} />
        <CitationPanel citations={payload.citations} />
      </>
    );
  }

  if (payload.type === 'qa') {
    return <CitationPanel citations={payload.citations} />;
  }

  return null;
}

function MessageBubble({ msg }) {
  const isBot = msg.role === 'assistant';

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isBot ? 'flex-start' : 'flex-end',
        marginBottom: '0.7rem',
      }}
    >
      {isBot ? (
        <div
          style={{
            width: 24,
            height: 24,
            borderRadius: '50%',
            flexShrink: 0,
            marginRight: 8,
            alignSelf: 'flex-end',
            background: 'linear-gradient(135deg, rgba(192,160,96,0.95), rgba(192,160,96,0.35))',
            color: '#111',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '0.7rem',
            fontWeight: 700,
          }}
        >
          O
        </div>
      ) : null}
      <div style={{ maxWidth: '92%' }}>
        {isBot && msg.tools?.length ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
            {msg.tools.map((tool) => (
              <span
                key={tool}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  padding: '0.14rem 0.4rem',
                  borderRadius: 4,
                  border: '1px solid rgba(192,160,96,0.22)',
                  background: 'rgba(192,160,96,0.06)',
                  color: 'rgba(192,160,96,0.9)',
                  fontSize: '0.6rem',
                }}
              >
                {TOOL_LABELS[tool] || tool}
              </span>
            ))}
          </div>
        ) : null}
        <div
          style={{
            padding: '0.72rem 0.9rem',
            borderRadius: isBot ? '6px 12px 12px 12px' : '12px 6px 12px 12px',
            background: isBot ? 'rgba(192,160,96,0.08)' : 'rgba(255,255,255,0.08)',
            border: isBot ? '1px solid rgba(192,160,96,0.16)' : '1px solid rgba(255,255,255,0.1)',
            color: 'rgba(255,255,255,0.88)',
            fontSize: '0.78rem',
            lineHeight: 1.7,
            wordBreak: 'break-word',
            animation: 'omega-chat-slide-up 0.24s ease-out',
          }}
          dangerouslySetInnerHTML={isBot ? { __html: renderMarkdown(msg.content) } : undefined}
        >
          {isBot ? null : msg.content}
        </div>
        {isBot ? <StructuredPayload payload={msg.payload} /> : null}
      </div>
    </div>
  );
}

function ChatSurface({
  assistantName,
  messages,
  loading,
  input,
  setInput,
  sendMessage,
  handleKeyDown,
  bottomRef,
  inputRef,
  compact = false,
}) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
      }}
    >
      <div
        style={{
          padding: compact ? '0.65rem 0.8rem' : '0.8rem 0.95rem',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          borderBottom: '1px solid rgba(192,160,96,0.1)',
          background: 'rgba(192,160,96,0.04)',
        }}
      >
        <div
          style={{
            width: 24,
            height: 24,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, rgba(192,160,96,0.95), rgba(192,160,96,0.35))',
            color: '#111',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            fontSize: '0.72rem',
          }}
        >
          O
        </div>
        <div>
          <div style={{ color: 'rgba(255,255,255,0.92)', fontSize: '0.72rem', fontWeight: 700 }}>
            {assistantName}
          </div>
          <div style={{ color: '#4EAA5E', fontSize: '0.56rem' }}>Online</div>
        </div>
      </div>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          padding: compact ? '0.7rem' : '0.8rem',
        }}
      >
        {messages.map((msg, index) => (
          <MessageBubble key={`${msg.role}-${index}`} msg={msg} />
        ))}
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: '0.7rem' }}>
            <div
              style={{
                width: 24,
                height: 24,
                borderRadius: '50%',
                flexShrink: 0,
                marginRight: 8,
                alignSelf: 'flex-end',
                background: 'linear-gradient(135deg, rgba(192,160,96,0.95), rgba(192,160,96,0.35))',
                color: '#111',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '0.7rem',
                fontWeight: 700,
              }}
            >
              O
            </div>
            <div
              style={{
                borderRadius: '6px 12px 12px 12px',
                border: '1px solid rgba(192,160,96,0.16)',
                background: 'rgba(192,160,96,0.08)',
              }}
            >
              <TypingIndicator />
            </div>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <div
        style={{
          display: 'flex',
          gap: 6,
          padding: compact ? '0.6rem' : '0.7rem',
          borderTop: '1px solid rgba(192,160,96,0.1)',
          background: 'rgba(0,0,0,0.22)',
        }}
      >
        <textarea
          ref={inputRef}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={loading ? '응답 생성 중…' : '질문을 입력해 주세요'}
          rows={compact ? 2 : 3}
          disabled={loading}
          style={{
            flex: 1,
            resize: 'none',
            outline: 'none',
            borderRadius: 8,
            border: '1px solid rgba(192,160,96,0.18)',
            background: loading ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.05)',
            color: loading ? 'rgba(255,255,255,0.45)' : 'rgba(255,255,255,0.88)',
            fontSize: '0.74rem',
            lineHeight: 1.5,
            padding: '0.55rem 0.65rem',
            cursor: loading ? 'not-allowed' : 'text',
          }}
        />
        <button
          type="button"
          onClick={sendMessage}
          disabled={loading || !input.trim()}
          style={{
            width: compact ? 38 : 42,
            borderRadius: 8,
            border: '1px solid rgba(192,160,96,0.24)',
            background: loading || !input.trim() ? 'rgba(192,160,96,0.08)' : 'rgba(192,160,96,0.22)',
            color: 'rgba(192,160,96,0.95)',
            cursor: loading || !input.trim() ? 'default' : 'pointer',
            fontSize: '0.82rem',
            fontWeight: 700,
          }}
        >
          전송
        </button>
      </div>
    </div>
  );
}

export default function ChatBot({ inline = false }) {
  const [open, setOpen] = useState(inline);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [unread, setUnread] = useState(0);
  const [assistantName, setAssistantName] = useState('Omega-Cortex');
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  // ── B5-γ: 요청-응답 상관관계 추적 ──
  const pendingRequestIdRef = useRef(null);

  useEffect(() => {
    if (document.getElementById('omega-chatbot-style')) {
      return undefined;
    }

    const styleTag = document.createElement('style');
    styleTag.id = 'omega-chatbot-style';
    styleTag.textContent = BOT_STYLE;
    document.head.appendChild(styleTag);

    return () => {
      const existing = document.getElementById('omega-chatbot-style');
      if (existing) {
        existing.remove();
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    panelAPI
      .getChatConfig()
      .then((response) => {
        if (cancelled) {
          return;
        }

        const data = normalizeServerValue(response.data || {});
        const welcome = data.welcome_markdown || 'Omega-Cortex입니다.';
        setAssistantName(data.assistant_name || 'Omega-Cortex');
        setMessages([{ role: 'assistant', content: welcome, payload: null, tools: [] }]);
      })
      .catch(() => {
        if (!cancelled) {
          setMessages([
            {
              role: 'assistant',
              content: 'Omega-Cortex입니다.\n\n문서 기반으로 실적, 비교, 추세, 공시를 정리해 드립니다.',
              payload: null,
              tools: [],
            },
          ]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
      setUnread(0);
    }
  }, [open]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) {
      return;
    }

    // ── B5-γ: 고유 요청 ID 생성 + pendingRef 업데이트 ──
    const requestId = `req_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    pendingRequestIdRef.current = requestId;

    const userMessage = { role: 'user', content: text, requestId };
    const history = messages
      .filter((message) => message.role === 'user' || message.role === 'assistant')
      .map((message) => ({ role: message.role, content: message.content }));

    setMessages((previous) => [...previous, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const response = await panelAPI.chat(text, history, requestId);
      const data = normalizeServerValue(response.data || {});

      // ── B5-γ: 응답 ID가 현재 pending과 다르면 stale 응답 → 폐기 ──
      const echoedId = data.request_id || data.requestId;
      if (echoedId && echoedId !== pendingRequestIdRef.current) {
        return;
      }

      const citations = data.citations || data.payload?.citations || [];
      const payload = data.payload
        ? { ...data.payload, citations: data.payload.citations || citations }
        : citations.length
          ? { type: 'qa', criteria: { query: text }, rows: [], series: [], citations }
          : null;

      setMessages((previous) => [
        ...previous,
        {
          role: 'assistant',
          content: data.reply || '응답을 생성하지 못했습니다.',
          tools: data.tools_used || [],
          payload,
          requestId,
        },
      ]);

      if (!inline && !open) {
        setUnread((value) => value + 1);
      }
    } catch {
      // ── 에러도 stale check ──
      if (pendingRequestIdRef.current !== requestId) {
        return;
      }
      setMessages((previous) => [
        ...previous,
        {
          role: 'assistant',
          content: 'AI 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.',
          tools: [],
          payload: null,
          requestId,
        },
      ]);
    } finally {
      // 본인이 마지막 pending이었을 때만 loading 해제
      if (pendingRequestIdRef.current === requestId) {
        pendingRequestIdRef.current = null;
        setLoading(false);
      }
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  };

  if (inline) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          flex: 1,
          minHeight: 0,
          borderTop: '1px solid rgba(192,160,96,0.1)',
        }}
      >
        <ChatSurface
          assistantName={assistantName}
          messages={messages}
          loading={loading}
          input={input}
          setInput={setInput}
          sendMessage={sendMessage}
          handleKeyDown={handleKeyDown}
          bottomRef={bottomRef}
          inputRef={inputRef}
          compact
        />
      </div>
    );
  }

  return (
    <>
      {open ? (
        <div
          style={{
            position: 'fixed',
            right: 24,
            bottom: 88,
            width: 380,
            height: 620,
            zIndex: 80,
            borderRadius: 18,
            overflow: 'hidden',
            background: 'rgba(18,18,18,0.96)',
            border: '1px solid rgba(192,160,96,0.18)',
            boxShadow: '0 20px 48px rgba(0,0,0,0.4)',
            backdropFilter: 'blur(16px)',
          }}
        >
          <ChatSurface
            assistantName={assistantName}
            messages={messages}
            loading={loading}
            input={input}
            setInput={setInput}
            sendMessage={sendMessage}
            handleKeyDown={handleKeyDown}
            bottomRef={bottomRef}
            inputRef={inputRef}
          />
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        style={{
          position: 'fixed',
          right: 24,
          bottom: 24,
          zIndex: 81,
          width: 56,
          height: 56,
          borderRadius: '50%',
          border: '1px solid rgba(192,160,96,0.22)',
          background: 'linear-gradient(135deg, rgba(192,160,96,0.92), rgba(192,160,96,0.42))',
          color: '#111',
          fontWeight: 700,
          cursor: 'pointer',
          boxShadow: '0 14px 32px rgba(0,0,0,0.35)',
        }}
      >
        O
        {unread ? (
          <span
            style={{
              position: 'absolute',
              top: -4,
              right: -2,
              minWidth: 18,
              height: 18,
              borderRadius: 9,
              background: '#d14545',
              color: '#fff',
              fontSize: '0.62rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 5px',
            }}
          >
            {unread}
          </span>
        ) : null}
      </button>
    </>
  );
}
