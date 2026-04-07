/**
 * Chat.jsx — AI chat interface for Tally.
 *
 * Streaming is handled via fetch + ReadableStream (not EventSource) so we
 * can include the Authorization header, which EventSource does not support.
 *
 * TODO: Chat history is ephemeral — each page load starts a fresh conversation.
 *       Revisit for persistent SQLite storage in a future phase so conversation
 *       history is retained across reloads and scoped per user/persona.
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'

// Dracula purple
const PURPLE = '#BD93F9'

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PersonaBadge({ persona }) {
  if (!persona) return null
  return (
    <span style={styles.personaBadge}>
      {persona.name}
    </span>
  )
}

function WriteAccessBadge({ canModify }) {
  if (!canModify) return null
  return (
    <span style={styles.writeAccessBadge}>
      write access
    </span>
  )
}

function ToolCallIndicator({ toolName }) {
  return (
    <div style={styles.toolIndicator}>
      <span style={styles.toolDot} />
      Running tool: <strong>{toolName}</strong>
    </div>
  )
}

// Renders a small subset of markdown inline: **bold**, *italic*, line breaks.
// No external dependency — keeps the bundle lean.
function renderMarkdown(text) {
  const lines = text.split('\n')
  return lines.map((line, li) => {
    // Split on **bold** and *italic* markers
    const parts = line.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g)
    const rendered = parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**'))
        return <strong key={i}>{part.slice(2, -2)}</strong>
      if (part.startsWith('*') && part.endsWith('*'))
        return <em key={i}>{part.slice(1, -1)}</em>
      return part
    })
    return (
      <span key={li}>
        {rendered}
        {li < lines.length - 1 && <br />}
      </span>
    )
  })
}

function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  return (
    <div style={{
      ...styles.messageRow,
      justifyContent: isUser ? 'flex-end' : 'flex-start',
    }}>
      <div style={isUser ? styles.userBubble : styles.aiBubble}>
        {isUser ? message.content : renderMarkdown(message.content)}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function Chat() {
  const { user } = useAuth()
  // user.persona is the full PersonaResponse object embedded in the login response
  const persona = user?.persona ?? null

  const [messages, setMessages]       = useState([])   // {role, content}
  const [input, setInput]             = useState('')
  const [streaming, setStreaming]     = useState(false)
  const [activeTools, setActiveTools] = useState([])   // tool names currently executing
  const [error, setError]             = useState(null)

  const bottomRef  = useRef(null)
  const abortRef   = useRef(null)   // AbortController for the active fetch

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, activeTools])

  // ---------------------------------------------------------------------------
  // Send a message
  // ---------------------------------------------------------------------------
  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || streaming || !persona) return

    setError(null)
    setInput('')

    const userMessage = { role: 'user', content: text }
    const nextMessages = [...messages, userMessage]
    setMessages(nextMessages)
    setStreaming(true)
    setActiveTools([])

    // Optimistically add a blank assistant message that we'll fill in via streaming
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    const token  = localStorage.getItem('tally_token')
    const ctrl   = new AbortController()
    abortRef.current = ctrl

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          // Send full history (minus the blank placeholder we just added)
          messages: nextMessages,
        }),
        signal: ctrl.signal,
      })

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(errBody.detail || `HTTP ${response.status}`)
      }

      const reader  = response.body.getReader()
      const decoder = new TextDecoder()
      let   buffer  = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE chunks from the buffer
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''   // incomplete last chunk back to buffer

        for (const part of parts) {
          if (!part.trim()) continue

          // Extract event type and data from SSE format:
          //   event: <type>\ndata: <payload>
          const lines      = part.split('\n')
          let   eventType  = 'delta'
          const dataLines  = []

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
              dataLines.push(line.slice(6))
            }
          }

          const dataLine = dataLines.join('\n')
          if (!dataLine) continue

          switch (eventType) {
            case 'delta':
              // Append text to the last assistant message
              setMessages(prev => {
                const updated = [...prev]
                const last    = updated[updated.length - 1]
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + dataLine,
                  }
                }
                return updated
              })
              break

            case 'tool_call': {
              try {
                const tc = JSON.parse(dataLine)
                setActiveTools(prev => [...prev, tc.name])
              } catch { /* ignore parse errors */ }
              break
            }

            case 'tool_result': {
              // Tool finished — remove it from the active list
              try {
                const tr = JSON.parse(dataLine)
                setActiveTools(prev => prev.filter(n => n !== tr.name))
              } catch { /* ignore */ }
              break
            }

            case 'done':
              // Stream complete — nothing to do; streaming state cleared below
              break

            case 'error':
              setError(dataLine)
              break

            default:
              break
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'An error occurred while streaming the response.')
        // Remove the blank placeholder if we failed before getting any content
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant' && last.content === '') {
            return prev.slice(0, -1)
          }
          return prev
        })
      }
    } finally {
      setStreaming(false)
      setActiveTools([])
      abortRef.current = null
    }
  }, [input, messages, streaming, persona])

  // Allow Ctrl+Enter or Enter (without Shift) to send
  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  function handleStop() {
    abortRef.current?.abort()
  }

  function handleClear() {
    if (streaming) handleStop()
    setMessages([])
    setError(null)
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const noPersona = !persona

  return (
    <div style={styles.page}>
      {/* ── Header ── */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <h1 style={styles.title}>Chat</h1>
          <div style={styles.badges}>
            {noPersona
              ? <span style={styles.noBadge}>No persona assigned</span>
              : (
                <>
                  <PersonaBadge persona={persona} />
                  <WriteAccessBadge canModify={persona?.can_modify_data} />
                </>
              )
            }
          </div>
        </div>
        <button
          style={styles.clearBtn}
          onClick={handleClear}
          title="Clear conversation"
        >
          Clear
        </button>
      </div>

      {/* ── Disabled notice ── */}
      {noPersona && (
        <div style={styles.disabledNotice}>
          No persona has been assigned to your account. Ask an owner to assign one in Settings before using the AI chat.
        </div>
      )}

      {/* ── Message list ── */}
      <div style={styles.messageList}>
        {messages.length === 0 && !noPersona && (
          <p style={styles.emptyHint}>
            Ask anything about your finances — transactions, budgets, accounts, or debt.
          </p>
        )}

        {messages.map((msg, idx) => (
          <MessageBubble key={idx} message={msg} />
        ))}

        {/* Active tool call indicators */}
        {activeTools.map((name, idx) => (
          <ToolCallIndicator key={`tool-${idx}`} toolName={name} />
        ))}

        {/* Error banner */}
        {error && (
          <div style={styles.errorBanner}>
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input area ── */}
      <div style={styles.inputArea}>
        <textarea
          style={{
            ...styles.textarea,
            opacity: noPersona ? 0.45 : 1,
          }}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            noPersona
              ? 'Assign a persona first…'
              : 'Ask about your finances… (Enter to send, Shift+Enter for new line)'
          }
          disabled={noPersona || streaming}
          rows={3}
        />
        <div style={styles.inputRow}>
          <span style={styles.hint}>Enter to send · Shift+Enter for new line</span>
          {streaming
            ? (
              <button style={styles.stopBtn} onClick={handleStop}>
                Stop
              </button>
            )
            : (
              <button
                style={{
                  ...styles.sendBtn,
                  opacity: noPersona || !input.trim() ? 0.45 : 1,
                  cursor: noPersona || !input.trim() ? 'not-allowed' : 'pointer',
                }}
                onClick={sendMessage}
                disabled={noPersona || !input.trim()}
              >
                Send
              </button>
            )
          }
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  page: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    maxWidth: 820,
    margin: '0 auto',
    gap: 0,
  },

  // ── Header ────────────────────────────────────────────────────────────────
  header: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 16,
    flexShrink: 0,
  },
  headerLeft: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  title: {
    fontSize: 24,
    fontWeight: 700,
    color: 'var(--white)',
    margin: 0,
  },
  badges: {
    display: 'flex',
    gap: 6,
    flexWrap: 'wrap',
  },
  personaBadge: {
    display: 'inline-block',
    background: `${PURPLE}22`,
    color: PURPLE,
    border: `1px solid ${PURPLE}55`,
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.04em',
    padding: '2px 8px',
    textTransform: 'uppercase',
  },
  writeAccessBadge: {
    display: 'inline-block',
    background: 'rgba(0, 247, 105, 0.1)',
    color: 'var(--green)',
    border: '1px solid rgba(0, 247, 105, 0.3)',
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.04em',
    padding: '2px 8px',
    textTransform: 'uppercase',
  },
  noBadge: {
    display: 'inline-block',
    background: 'rgba(255,255,255,0.05)',
    color: 'var(--muted)',
    border: '1px solid var(--border)',
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
    padding: '2px 8px',
  },
  clearBtn: {
    background: 'none',
    border: '1px solid var(--border)',
    color: 'var(--muted)',
    fontSize: 13,
    padding: '5px 12px',
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
    flexShrink: 0,
  },

  // ── Disabled notice ───────────────────────────────────────────────────────
  disabledNotice: {
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '12px 16px',
    color: 'var(--muted)',
    fontSize: 14,
    marginBottom: 12,
    flexShrink: 0,
  },

  // ── Message list ──────────────────────────────────────────────────────────
  messageList: {
    flex: 1,
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    paddingBottom: 8,
  },
  emptyHint: {
    color: 'var(--muted)',
    fontSize: 14,
    textAlign: 'center',
    marginTop: 48,
  },

  // ── Message bubbles ───────────────────────────────────────────────────────
  messageRow: {
    display: 'flex',
    width: '100%',
  },
  userBubble: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 12,
    padding: '10px 14px',
    maxWidth: '72%',
    fontSize: 14,
    lineHeight: 1.6,
    color: 'var(--white)',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  aiBubble: {
    background: 'var(--bg)',
    borderLeft: `3px solid ${PURPLE}`,
    borderRadius: '0 12px 12px 0',
    padding: '10px 14px',
    maxWidth: '85%',
    fontSize: 14,
    lineHeight: 1.6,
    color: 'var(--white)',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },

  // ── Tool call indicator ───────────────────────────────────────────────────
  toolIndicator: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    color: PURPLE,
    fontSize: 13,
    padding: '6px 0',
  },
  toolDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: PURPLE,
    animation: 'pulse 1.2s ease-in-out infinite',
    flexShrink: 0,
  },

  // ── Error banner ──────────────────────────────────────────────────────────
  errorBanner: {
    background: 'rgba(234, 81, 178, 0.1)',
    border: '1px solid rgba(234, 81, 178, 0.4)',
    borderRadius: 'var(--radius)',
    color: '#ea51b2',
    fontSize: 13,
    padding: '8px 12px',
  },

  // ── Input area ────────────────────────────────────────────────────────────
  inputArea: {
    flexShrink: 0,
    marginTop: 12,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  textarea: {
    background: 'var(--bg-card)',
    border: `1px solid ${PURPLE}55`,
    borderRadius: 'var(--radius)',
    color: 'var(--white)',
    fontSize: 14,
    lineHeight: 1.6,
    padding: '10px 14px',
    resize: 'vertical',
    width: '100%',
    boxSizing: 'border-box',
    outline: 'none',
    fontFamily: 'inherit',
    transition: 'border-color 0.15s',
  },
  inputRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  hint: {
    fontSize: 12,
    color: 'var(--muted)',
  },
  sendBtn: {
    background: PURPLE,
    border: 'none',
    borderRadius: 'var(--radius)',
    color: '#1e1e2e',
    fontWeight: 700,
    fontSize: 14,
    padding: '8px 20px',
    transition: 'opacity 0.15s',
  },
  stopBtn: {
    background: 'none',
    border: '1px solid #ea51b2',
    borderRadius: 'var(--radius)',
    color: '#ea51b2',
    fontWeight: 600,
    fontSize: 14,
    padding: '7px 20px',
    cursor: 'pointer',
  },
}
