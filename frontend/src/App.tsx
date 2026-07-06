import { useState, useEffect, useRef } from 'react'
import type { ChatMessage } from './types'
import { ChatPanel } from './components/ChatPanel'
import { DownloadPanel } from './components/DownloadPanel'
import { ServiceStatusPanel } from './components/ServiceStatusPanel'

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)

  // Refresh trigger for download/status panels — bumped after each chat reply
  const [refreshKey, setRefreshKey] = useState(0)

  const sendMessage = async (text: string) => {
    if (!text.trim() || isStreaming) return

    const newMessages = [...messages, { role: 'user' as const, content: text }]
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
      const assistantMsg: ChatMessage = { role: 'assistant', content: '' }
      setMessages([...newMessages, assistantMsg])

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
          } catch {
            // partial JSON, skip
          }
        }
      }
      setRefreshKey(k => k + 1)
    } catch (err) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `❌ ${err instanceof Error ? err.message : 'Unknown error'}` },
      ])
    } finally {
      setIsStreaming(false)
    }
  }

  return (
    <div className="h-screen flex flex-col bg-dark-bg">
      {/* Header */}
      <header className="flex-shrink-0 border-b border-dark-border bg-dark-surface px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🎬</span>
          <div>
            <h1 className="text-lg font-semibold text-white">Media Agent</h1>
            <p className="text-xs text-gray-500">Your media library, automated</p>
          </div>
        </div>
        <ServiceStatusPanel refreshKey={refreshKey} />
      </header>

      {/* Main content: chat + sidebar */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat — left, takes more space */}
        <div className="flex-1 flex flex-col min-w-0">
          <ChatPanel
            messages={messages}
            isStreaming={isStreaming}
            onSend={sendMessage}
          />
        </div>

        {/* Download sidebar — right */}
        <div className="w-96 border-l border-dark-border bg-dark-surface overflow-y-auto flex-shrink-0">
          <DownloadPanel refreshKey={refreshKey} />
        </div>
      </div>
    </div>
  )
}
