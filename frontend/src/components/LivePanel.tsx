import { useState, useEffect } from 'react'
import type { QueueResponse, QueueItem, SabnzbdData } from '../types'

interface Props {
  refreshKey: number
  agentState: string
}

export function LivePanel({ refreshKey, agentState }: Props) {
  const [data, setData] = useState<QueueResponse | null>(null)
  const [loading, setLoading] = useState(true)
  // Bump a local refresh when agentState changes — so the panel immediately
  // refetches when the agent says "checking downloads…"
  const [localTick, setLocalTick] = useState(0)

  useEffect(() => {
    if (agentState) setLocalTick(t => t + 1)
  }, [agentState])

  useEffect(() => {
    let active = true
    const fetch_ = async () => {
      try {
        const r = await fetch('/api/queue')
        if (!r.ok) return
        const j = await r.json()
        if (active) { setData(j); setLoading(false) }
      } catch { if (active) setLoading(false) }
    }
    fetch_()
    // Poll faster (3s) when agent is active, slower (10s) when idle
    const interval = agentState ? 3000 : 10000
    const iv = setInterval(fetch_, interval)
    return () => { active = false; clearInterval(iv) }
  }, [refreshKey, localTick, agentState])

  const sonarrActive = (data?.sonarr || []).filter(q => q.status !== 'completed')
  const radarrActive = (data?.radarr || []).filter(q => q.status !== 'completed')
  const sabActive = data?.sabnzbd?.slots?.filter(s => s.progress < 100) || []
  const totalActive = sonarrActive.length + radarrActive.length + sabActive.length

  return (
    <div className="py-3">
      {/* Agent activity indicator */}
      {agentState && (
        <div className="mx-3 mb-3 px-3 py-2 bg-accent/10 border border-accent/20 rounded-md flex items-center gap-2">
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

      {/* Summary line */}
      <div className="px-3 mb-2 flex items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full ${totalActive > 0 ? 'bg-success status-pulse' : 'bg-ink-subtle'}`} />
        <span className="text-micro text-ink-muted uppercase tracking-wider" style={{ fontWeight: 510 }}>
          {totalActive > 0 ? `${totalActive} active` : 'Downloads'}
        </span>
      </div>

      {loading ? (
        <div className="text-center py-6 text-ink-subtle text-caption">Loading…</div>
      ) : totalActive === 0 && !data?.sabnzbd?.slots?.length ? (
        <div className="px-3 py-3">
          <p className="text-caption text-ink-subtle">Nothing active right now.</p>
          <p className="text-micro text-ink-subtle mt-1">
            Downloads will appear here automatically.
          </p>
        </div>
      ) : (
        <>
          {/* Radarr (Movies) */}
          {radarrActive.length > 0 && (
            <Section title="Movies" count={radarrActive.length}>
              {radarrActive.map((item, i) => <DownloadBar key={i} item={item} />)}
            </Section>
          )}

          {/* Sonarr (TV) */}
          {sonarrActive.length > 0 && (
            <Section title="TV Shows" count={sonarrActive.length}>
              {sonarrActive.map((item, i) => <DownloadBar key={i} item={item} />)}
            </Section>
          )}

          {/* SABnzbd */}
          {sabActive.length > 0 && data?.sabnzbd && (
            <SabnzbdWidget data={data.sabnzbd} />
          )}
        </>
      )}
    </div>
  )
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="px-3 mb-1.5 text-micro text-ink-subtle uppercase tracking-wider" style={{ fontWeight: 510 }}>
        {title}
        <span className="ml-1.5 text-ink-subtle">{count}</span>
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

function DownloadBar({ item }: { item: QueueItem }) {
  const downloading = item.status === 'downloading'
  const importing = item.status === 'importing' || item.status === 'importPending'
  const queued = item.status === 'queued' || item.status === 'paused'
  const pct = Math.min(100, Math.max(0, item.progress))

  const barColor = downloading ? '#5e6ad2' : importing ? '#f59e0b' : '#62666d'
  const statusText = downloading ? `${pct}%` : importing ? 'Importing' : queued ? 'Queued' : item.status

  const cleanTitle = item.title
    .replace(/\.\d{3,4}p\..*$/, '')
    .replace(/\.\d+p\..*$/, '')
    .replace(/\.[A-Z0-9-]+$/, '')
    .replace(/\./g, ' ')

  return (
    <div className="px-3 py-2 hover:bg-surface transition-colors msg-enter">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-caption text-ink-secondary truncate flex-1" title={item.title}>
          {cleanTitle}
        </span>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {item.quality && (
            <span className="text-micro text-ink-subtle font-mono px-1 py-0.5 bg-hover rounded">
              {item.quality.replace('WEBRip-', '').replace('WEBDL-', '').replace('WEB-', '')}
            </span>
          )}
          <span className={`text-micro ${item.warning ? 'text-warning' : 'text-ink-subtle'} flex-shrink-0`}>
            {item.warning && '⚠ '}{statusText}
          </span>
        </div>
      </div>
      {/* Progress bar */}
      <div className="relative h-1 bg-white/5 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700 ease-out"
          style={{ width: `${pct}%`, background: barColor }}
        />
        {downloading && <div className="progress-shimmer" />}
      </div>
      {/* Size / ETA */}
      {item.sizeleft_mb > 0 && (
        <div className="mt-1 flex items-center justify-between text-micro text-ink-subtle">
          <span className="font-mono">{item.sizeleft_mb.toFixed(0)} MB left</span>
          {item.timeleft && item.timeleft !== '0:00:00' && (
            <span className="font-mono">~{item.timeleft}</span>
          )}
        </div>
      )}
    </div>
  )
}

function SabnzbdWidget({ data }: { data: SabnzbdData }) {
  const active = data.slots.filter(s => s.progress < 100)

  return (
    <div className="mb-3">
      <div className="px-3 mb-1.5 flex items-center justify-between">
        <span className="text-micro text-ink-subtle uppercase tracking-wider" style={{ fontWeight: 510 }}>
          SABnzbd
        </span>
        <span className={`text-micro font-mono ${data.paused ? 'text-warning' : 'text-success'}`}>
          {data.paused ? 'Paused' : data.speed}
        </span>
      </div>
      <div className="space-y-1">
        {active.slice(0, 5).map((slot, i) => {
          const cleanName = slot.filename
            .replace(/\./g, ' ')
            .replace(/\s[A-Z0-9]{6,}$/, '')
            .replace(/\s\d{4}-\d+/g, '')
            .trim()
          return (
            <div key={i} className="px-3 py-1.5 hover:bg-surface transition-colors msg-enter">
              <div className="flex justify-between mb-1">
                <span className="text-micro text-ink-muted truncate flex-1 mr-2">{cleanName}</span>
                <span className="text-micro text-ink-subtle font-mono flex-shrink-0">
                  {slot.progress.toFixed(0)}%
                </span>
              </div>
              <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${data.paused ? 'bg-ink-subtle' : 'bg-warning'}`}
                  style={{ width: `${Math.min(100, slot.progress)}%` }}
                />
              </div>
            </div>
          )
        })}
        {active.length > 5 && (
          <div className="text-micro text-ink-subtle text-center py-1">
            +{active.length - 5} more
          </div>
        )}
      </div>
    </div>
  )
}
