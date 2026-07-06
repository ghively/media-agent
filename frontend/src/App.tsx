import { useState, useCallback, useRef, useEffect } from 'react'
import type { ChatMessage, QueueResponse, StatusResponse } from './types'
import { ChatView } from './components/ChatView'
import { LivePanel } from './components/LivePanel'

type View = 'chat' | 'live'

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [mobileView, setMobileView] = useState<View>('chat')

  // Track what the agent is currently doing (parsed from streaming text)
  const [agentState, setAgentState] = useState<string>('')

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return

    const newMessages: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(newMessages)
    setIsStreaming(true)
    setAgentState('Working…')

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
              // Parse agent activity from streaming text
              setAgentState(parseAgentState(assistantText))
            }
          } catch { /* partial */ }
        }
      }
      setRefreshKey(k => k + 1)
      setAgentState('')
    } catch (err) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `❌ ${err instanceof Error ? err.message : 'Connection error'}` },
      ])
    } finally {
      setIsStreaming(false)
      setAgentState('')
    }
  }, [messages, isStreaming])

  return (
    <div className="h-[100dvh] flex flex-col bg-canvas overflow-hidden">
      {/* Top bar — status dots + view switcher (mobile) */}
      <header className="flex-shrink-0 border-b border-border-subtle bg-panel h-11 flex items-center justify-between px-3 z-10">
        <div className="flex items-center gap-2">
          <span className="text-ink font-medium text-sm" style={{ fontWeight: 510, letterSpacing: '-0.24px' }}>
            Media Agent
          </span>
        </div>

        {/* Desktop: status dots inline */}
        <StatusDots refreshKey={refreshKey} className="hidden sm:flex" />

        {/* Mobile: tab switcher */}
        <div className="flex sm:hidden rounded-md bg-surface border border-border-subtle overflow-hidden">
          <button
            onClick={() => setMobileView('chat')}
            className={`px-3 py-1 text-xs transition-colors ${
              mobileView === 'chat' ? 'bg-accent text-white' : 'text-ink-muted'
            }`}
          >
            Chat
          </button>
          <button
            onClick={() => setMobileView('live')}
            className={`px-3 py-1 text-xs transition-colors ${
              mobileView === 'live' ? 'bg-accent text-white' : 'text-ink-muted'
            }`}
          >
            Live
          </button>
        </div>
      </header>

      {/* Content area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat — full width on mobile when chat tab active, flex-1 on desktop */}
        <div className={`flex-1 flex flex-col min-w-0 ${mobileView === 'live' ? 'hidden sm:flex' : 'flex'}`}>
          <ChatView
            messages={messages}
            isStreaming={isStreaming}
            agentState={agentState}
            onSend={sendMessage}
          />
        </div>

        {/* Live panel — sidebar on desktop, full width on mobile when live tab active */}
        <aside className={`w-80 border-l border-border-subtle bg-panel overflow-y-auto flex-shrink-0 ${
          mobileView === 'chat' ? 'hidden sm:block' : 'block'
        }`}>
          <LivePanel refreshKey={refreshKey} agentState={agentState} />
        </aside>
      </div>
    </div>
  )
}

function StatusDots({ refreshKey, className }: { refreshKey: number; className?: string }) {
  const [data, setData] = useState<StatusResponse | null>(null)

  useEffect(() => {
    let active = true
    const fetch_ = async () => {
      try {
        const r = await fetch('/api/status')
        if (!r.ok) return
        const j = await r.json()
        if (active) setData(j)
      } catch { /* silent */ }
    }
    fetch_()
    const iv = setInterval(fetch_, 15000)
    return () => { active = false; clearInterval(iv) }
  }, [refreshKey])

  const services = data ? Object.values(data.services) : []

  return (
    <div className={`items-center gap-3 ${className}`}>
      {services.map(svc => {
        const color =
          svc.status === 'healthy' ? 'bg-success status-pulse' :
          svc.status === 'paused' ? 'bg-warning' :
          svc.status === 'offline' ? 'bg-danger' :
          'bg-ink-subtle'
        const count = svc.shows ?? svc.movies ?? svc.queue_count
        return (
          <div key={svc.name} className="flex items-center gap-1" title={`${svc.name}: ${svc.status}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${color}`} />
            <span className="text-caption text-ink-muted">{svc.name}</span>
            {count !== undefined && (
              <span className="text-micro text-ink-subtle font-mono">{count}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

// Parse agent activity from streaming text to drive the live panel
function parseAgentState(text: string): string {
  const lower = text.toLowerCase()
  if (lower.includes('checking your library') || lower.includes('checking library')) return 'Checking library…'
  if (lower.includes('searching')) return 'Searching…'
  if (lower.includes('adding') || lower.includes('added')) return 'Adding to library…'
  if (lower.includes('checking download') || lower.includes('verifying') || lower.includes('queue')) return 'Checking downloads…'
  if (lower.includes('already') || lower.includes('exists')) return 'Already in library'
  return ''
}
