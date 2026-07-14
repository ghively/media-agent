import { useState, useRef, useEffect } from 'react'
import { streamChat, resetConversation } from '../api/client'

const GREETING = { role: 'system', content: 'Hello! I\'m your Media Agent. I can help you manage your media library, search for content, and monitor your services. What would you like to do?' }

export default function ChatPanel({ initialQuery }) {
  const [messages, setMessages] = useState([GREETING])
  const [input, setInput] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  // Quick replies (yes/no/pick buttons) offered when a confirmation is
  // pending after the last agent message.
  const [suggestions, setSuggestions] = useState([])
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const currentAssistantMessageRef = useRef(null)
  const isGeneratingRef = useRef(false)
  const lastQueryIdRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const send = async (rawMessage) => {
    const userMessage = (rawMessage ?? '').trim()
    if (!userMessage || isGeneratingRef.current) return

    isGeneratingRef.current = true
    setIsGenerating(true)
    setSuggestions([])
    setMessages(prev => [...prev, { role: 'user', content: userMessage }, { role: 'assistant', content: '' }])
    currentAssistantMessageRef.current = ''

    const setLastAssistant = (content) => {
      setMessages(prev => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (last && last.role === 'assistant') last.content = content
        return next
      })
    }

    const finish = () => {
      isGeneratingRef.current = false
      setIsGenerating(false)
      currentAssistantMessageRef.current = null
    }

    try {
      await streamChat(userMessage, {
        onToken: (token) => {
          currentAssistantMessageRef.current += token
          setLastAssistant(currentAssistantMessageRef.current)
        },
        onDone: (fullResponse, suggested) => {
          // If nothing streamed (e.g. only tool calls), fall back to the final text.
          if (!currentAssistantMessageRef.current && fullResponse) {
            setLastAssistant(fullResponse)
          }
          if (suggested && suggested.length) setSuggestions(suggested.slice(0, 7))
          finish()
        },
        onError: (error) => {
          setLastAssistant(`❌ Error: ${error}`)
          finish()
        },
      })
    } catch (error) {
      setLastAssistant(`❌ Error: ${error.message}`)
      finish()
    }
  }

  const handleSubmit = (e) => {
    e?.preventDefault?.()
    if (!input.trim() || isGenerating) return
    const msg = input.trim()
    setInput('')
    send(msg)
  }

  // A quick-action from the Overview tab arrives as { text, id }. Fire once per id.
  useEffect(() => {
    if (initialQuery && initialQuery.id !== lastQueryIdRef.current) {
      lastQueryIdRef.current = initialQuery.id
      send(initialQuery.text)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px'
    }
  }, [input])

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Messages */}
      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain space-y-4 mb-4 pr-1 sm:pr-2">
        {messages.map((message, idx) => (
          <div key={idx} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] sm:max-w-[80%] rounded-2xl px-4 py-3 ${
                message.role === 'user'
                  ? 'bg-accent-blue text-white rounded-br-md'
                  : message.role === 'system'
                  ? 'bg-dark-600 text-dark-300 text-center w-full max-w-full rounded-xl'
                  : 'bg-dark-700 text-dark-200 rounded-bl-md border border-dark-500/60'
              }`}
            >
              {message.role === 'system' ? (
                <div className="text-sm">{message.content}</div>
              ) : (
                <div className="text-sm whitespace-pre-wrap break-words leading-relaxed">{message.content}</div>
              )}
            </div>
          </div>
        ))}
        {!isGenerating && suggestions.length > 0 && (
          <div className="flex flex-wrap gap-2 justify-start pl-1">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => { setSuggestions([]); send(s) }}
                className="px-3 py-1.5 rounded-full text-sm border border-accent-blue/50 text-accent-blue hover:bg-accent-blue/10 active:scale-95 transition-all touch-manipulation"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {isGenerating && !currentAssistantMessageRef.current && (
          <div className="flex justify-start">
            <div className="bg-dark-700 rounded-2xl rounded-bl-md px-4 py-3 border border-dark-500/60">
              <div className="flex gap-1">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="card shrink-0 p-3 sm:p-4">
        <form onSubmit={handleSubmit} className="flex gap-2 sm:gap-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask me anything about your media library..."
            disabled={isGenerating}
            className="flex-1 bg-dark-600 text-dark-100 placeholder-dark-500 rounded-xl px-4 py-3 resize-none focus:outline-none focus:ring-2 focus:ring-accent-blue/50 border border-dark-500/60 disabled:opacity-50"
            rows={1}
            style={{ minHeight: '48px', maxHeight: '200px' }}
          />
          <button
            type="submit"
            disabled={!input.trim() || isGenerating}
            className="btn btn-primary px-5 sm:px-6 h-[48px] self-end"
          >
            {isGenerating ? (
              <span className="flex items-center gap-1">
                <span className="typing-dot scale-75" />
                <span className="typing-dot scale-75" />
                <span className="typing-dot scale-75" />
              </span>
            ) : (
              <span>Send</span>
            )}
          </button>
        </form>
        <div className="mt-2 flex items-center justify-between gap-2">
          <div className="text-xs text-dark-500">Press Enter to send, Shift+Enter for newline</div>
          <button
            type="button"
            disabled={isGenerating}
            onClick={async () => {
              await resetConversation()
              setMessages([GREETING])
            }}
            className="text-xs text-dark-400 hover:text-accent-blue transition-colors disabled:opacity-50"
            title="Forget this conversation and start fresh"
          >
            ↺ New conversation
          </button>
        </div>
      </div>
    </div>
  )
}
