import { useState, useCallback } from 'react'
import type { ChatMessage } from './types'
import { ChatPanel } from './components/ChatPanel'
import { DownloadPanel } from './components/DownloadPanel'
import { ServiceStatusPanel } from './components/ServiceStatusPanel'

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return

    const newMessages: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(newMessages)
    setIsStreaming(true)

    try {
      const resp = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'media-agent',
          messages: newMessages.map(m => ({ role: m.role, content: m.content })),
          stream: true,
        }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const reader = resp.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let assistantText = ''
      setMessages([...newMessages, { role: 'assistant', content: '' }])

      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data: ')) continue
          const data = trimmed.slice(6)
          if (data === '[DONE]') continue
          try {
            const parsed = JSON.parse(data)
            const delta = parsed.choices?.[0]?.delta?.content
            if (delta) {
              assistantText += delta
              setMessages(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = { role: 'assistant', content: assistantText }
                return updated
              })
            }
          } catch { /* partial */ }
        }
      }
      setRefreshKey(k => k + 1)
    } catch (err) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `❌ ${err instanceof Error ? err.message : 'Connection error'}` },
      ])
    } finally {
      setIsStreaming(false)
    }
  }, [messages, isStreaming])

  return (
    <div className="h-screen flex flex-col bg-canvas">
      {/* Header bar */}
      <header className="flex-shrink-0 border-b border-border-subtle bg-panel h-12 flex items-center justify-between px-4">
        <div className="flex items-center gap-2.5">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-ink">
            <path d="M4 4h16v16H4z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
            <path d="M4 9h16M9 4v16" stroke="currentColor" strokeWidth="1" opacity="0.3" />
          </svg>
          <span className="text-ink font-medium text-sm tracking-tight">Media Agent</span>
        </div>
        <ServiceStatusPanel refreshKey={refreshKey} />
      </header>

      {/* Two-column layout */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col min-w-0">
          <ChatPanel messages={messages} isStreaming={isStreaming} onSend={sendMessage} />
        </div>
        <aside className="w-80 border-l border-border-subtle bg-panel overflow-y-auto flex-shrink-0">
          <DownloadPanel refreshKey={refreshKey} />
        </aside>
      </div>
    </div>
  )
}
