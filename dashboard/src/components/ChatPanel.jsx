import { useState, useRef, useEffect } from 'react'
import { streamChat } from '../api/client'

export default function ChatPanel() {
  const [messages, setMessages] = useState([
    { role: 'system', content: 'Hello! I\'m your Media Agent. I can help you manage your media library, search for content, and monitor your services. What would you like to do?' }
  ])
  const [input, setInput] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const currentAssistantMessageRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!input.trim() || isGenerating) return

    const userMessage = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setIsGenerating(true)

    // Create a placeholder for the assistant's response
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])
    currentAssistantMessageRef.current = ''

    try {
      await streamChat(userMessage, {
        onToken: (token) => {
          currentAssistantMessageRef.current += token
          setMessages(prev => {
            const newMessages = [...prev]
            const lastMessage = newMessages[newMessages.length - 1]
            if (lastMessage.role === 'assistant') {
              lastMessage.content = currentAssistantMessageRef.current
            }
            return newMessages
          })
        },
        onDone: (fullResponse) => {
          setIsGenerating(false)
          currentAssistantMessageRef.current = null
        },
        onError: (error) => {
          setMessages(prev => {
            const newMessages = [...prev]
            const lastMessage = newMessages[newMessages.length - 1]
            if (lastMessage.role === 'assistant') {
              lastMessage.content = `❌ Error: ${error}`
            }
            return newMessages
          })
          setIsGenerating(false)
          currentAssistantMessageRef.current = null
        }
      })
    } catch (error) {
      setMessages(prev => {
        const newMessages = [...prev]
        const lastMessage = newMessages[newMessages.length - 1]
        if (lastMessage.role === 'assistant') {
          lastMessage.content = `❌ Error: ${error.message}`
        }
        return newMessages
      })
      setIsGenerating(false)
      currentAssistantMessageRef.current = null
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px'
    }
  }

  useEffect(() => {
    adjustTextareaHeight()
  }, [input])

  return (
    <div className="flex flex-col h-[calc(100vh-180px)]">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-2">
        {messages.map((message, idx) => (
          <div
            key={idx}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                message.role === 'user'
                  ? 'bg-accent-blue text-white rounded-br-md'
                  : message.role === 'system'
                  ? 'bg-dark-600 text-dark-300 text-center w-full max-w-full rounded-xl'
                  : 'bg-dark-700 text-dark-200 rounded-bl-md border border-dark-500/60'
              }`}
            >
              {message.role === 'system' && <div className="text-sm">{message.content}</div>}
              {message.role !== 'system' && (
                <div className="text-sm whitespace-pre-wrap break-words leading-relaxed">
                  {message.content}
                </div>
              )}
            </div>
          </div>
        ))}
        {isGenerating && (
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
      <div className="card p-4">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask me anything about your media library..."
              disabled={isGenerating}
              className="w-full bg-dark-600 text-dark-100 placeholder-dark-500 rounded-xl px-4 py-3 resize-none focus:outline-none focus:ring-2 focus:ring-accent-blue/50 border border-dark-500/60 disabled:opacity-50"
              rows={1}
              style={{ minHeight: '48px', maxHeight: '200px' }}
            />
          </div>
          <button
            type="submit"
            disabled={!input.trim() || isGenerating}
            className="btn btn-primary px-6 h-[48px] self-end"
          >
            {isGenerating ? (
              <span className="flex items-center gap-2">
                <span className="typing-dot scale-75" />
                <span className="typing-dot scale-75" />
                <span className="typing-dot scale-75" />
              </span>
            ) : (
              <span>Send</span>
            )}
          </button>
        </form>
        <div className="mt-2 text-xs text-dark-500">
          Press Enter to send, Shift+Enter for newline
        </div>
      </div>
    </div>
  )
}