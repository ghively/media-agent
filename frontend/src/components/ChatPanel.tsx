import { useState, useRef, useEffect } from 'react'
import type { ChatMessage } from '../types'

interface Props {
  messages: ChatMessage[]
  isStreaming: boolean
  onSend: (text: string) => void
}

export function ChatPanel({ messages, isStreaming, onSend }: Props) {
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

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-500 animate-slide-up">
            <span className="text-5xl mb-4">🎬</span>
            <h2 className="text-xl font-semibold text-gray-400 mb-2">Media Agent</h2>
            <p className="max-w-md">
              Ask me to add movies or shows, check what's downloading, or manage your library.
            </p>
            <div className="mt-6 flex flex-wrap gap-2 justify-center">
              {["What's downloading?", 'Add the movie Dune', "What's new on TV this week?"].map(s => (
                <button
                  key={s}
                  onClick={() => onSend(s)}
                  className="px-3 py-1.5 text-sm bg-dark-surface border border-dark-border rounded-lg hover:border-dark-accent hover:text-dark-accent transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-slide-up`}
          >
            <div
              className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white rounded-br-md'
                  : 'bg-dark-surface border border-dark-border rounded-bl-md'
              }`}
            >
              {msg.content || (isStreaming && i === messages.length - 1 ? (
                <span className="inline-flex items-center gap-1">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </span>
              ) : '')}
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="flex-shrink-0 px-6 py-4 border-t border-dark-border">
        <div className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask me anything about your media..."
            disabled={isStreaming}
            className="flex-1 bg-dark-surface border border-dark-border rounded-xl px-4 py-3 text-sm outline-none focus:border-dark-accent transition-colors disabled:opacity-50"
            autoFocus
          />
          <button
            type="submit"
            disabled={isStreaming || !input.trim()}
            className="px-6 py-3 bg-dark-green text-white rounded-xl text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isStreaming ? '...' : 'Send'}
          </button>
        </div>
      </form>
    </div>
  )
}
