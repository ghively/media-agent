import { useState, useRef, useEffect } from 'react'
import { streamChat } from '../api/client'

export default function ChatPanel({ initialQuery }) {
  const [messages, setMessages] = useState([
    { role: 'system', content: 'Hello! I\'m your Media Agent. I can help you manage your media library, search for content, and monitor your services. What would you like to do?' }
  ])
  const [input, setInput] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
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
        onDone: (fullResponse) => {
          // If nothing streamed (e.g. only tool calls), fall back to the final text.
          if (!currentAssistantMessageRef.current && fullResponse) {
            setLastAssistant(fullResponse)
          }
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
    <div className="flex flex-col h-[calc(100dvh-11rem)] min-h-[24rem]">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-1 sm:pr-2">
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
      <div className="card p-3 sm:p-4">
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
        <div className="mt-2 text-xs text-dark-500">Press Enter to send, Shift+Enter for newline</div>
      </div>
    </div>
  )
}
