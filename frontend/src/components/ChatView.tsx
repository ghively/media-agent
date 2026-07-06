import { useState, useRef, useEffect } from 'react'
import type { ChatMessage } from '../types'

interface Props {
  messages: ChatMessage[]
  isStreaming: boolean
  agentState: string
  onSend: (text: string) => void
}

const SUGGESTIONS = [
  "What's downloading?",
  'Add the movie Dune',
  "What's on TV this week?",
]

export function ChatView({ messages, isStreaming, agentState, onSend }: Props) {
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isStreaming) return
    onSend(input)
    setInput('')
  }

  const isEmpty = messages.length === 0

  return (
    <div className="flex-1 flex flex-col min-h-0 h-full">
      {/* Agent activity banner — shows what the agent is doing right now */}
      {agentState && (
        <div className="flex-shrink-0 px-4 py-1.5 bg-accent/10 border-b border-accent/20 flex items-center gap-2">
          <span className="inline-flex items-center gap-0.5">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
          </span>
          <span className="text-caption text-accent-hover" style={{ fontWeight: 510 }}>
            {agentState}
          </span>
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 sm:px-6 py-4">
        {isEmpty ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-sm mx-auto">
            <div className="w-10 h-10 rounded-lg bg-surface border border-border flex items-center justify-center mb-4">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="text-ink-muted">
                <path d="M4 4h16v16H4z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                <path d="M4 9h16M9 4v16" stroke="currentColor" strokeWidth="1" opacity="0.3" />
              </svg>
            </div>
            <h2 className="text-lg text-ink mb-1.5" style={{ fontWeight: 510, letterSpacing: '-0.24px' }}>
              Media Agent
            </h2>
            <p className="text-sm text-ink-muted mb-6 leading-relaxed">
              Add movies and shows, check downloads, or manage your library.
            </p>
            <div className="flex flex-col gap-1.5 w-full">
              {SUGGESTIONS.map(s => (
                <button
                  key={s}
                  onClick={() => onSend(s)}
                  className="text-left px-3 py-2 text-sm text-ink-secondary bg-surface border border-border-subtle rounded-md hover:border-border hover:text-ink transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-2xl mx-auto space-y-3">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} msg-enter`}
              >
                <div
                  className={`max-w-[85%] px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap rounded-lg ${
                    msg.role === 'user'
                      ? 'bg-accent text-white rounded-br-sm'
                      : 'bg-surface border border-border-subtle text-ink rounded-bl-sm'
                  }`}
                >
                  {msg.content || (isStreaming && i === messages.length - 1 ? (
                    <span className="inline-flex items-center gap-0.5 py-1">
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                    </span>
                  ) : '')}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Input — sticky at bottom, mobile-friendly */}
      <form onSubmit={handleSubmit} className="flex-shrink-0 px-4 sm:px-6 py-3 border-t border-border-subtle bg-panel">
        <div className="flex gap-2 max-w-2xl mx-auto">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask about your media…"
            disabled={isStreaming}
            className="flex-1 bg-surface border border-border rounded-md px-3 py-2 text-base text-ink placeholder:text-ink-subtle outline-none focus:border-accent transition-colors disabled:opacity-40"
            // text-base prevents iOS zoom on focus
            autoFocus
          />
          <button
            type="submit"
            disabled={isStreaming || !input.trim()}
            className="px-4 py-2 bg-accent text-white rounded-md text-sm hover:bg-accent-hover transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ fontWeight: 510, minWidth: '44px', minHeight: '44px' }}
          >
            Send
          </button>
        </div>
      </form>
    </div>
  )
}
