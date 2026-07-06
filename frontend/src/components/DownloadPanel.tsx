import { useState, useEffect } from 'react'
import type { QueueResponse, QueueItem, SabnzbdData } from '../types'

interface Props {
  refreshKey: number
}

export function DownloadPanel({ refreshKey }: Props) {
  const [data, setData] = useState<QueueResponse | null>(null)
  const [loading, setLoading] = useState(true)

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
    const iv = setInterval(fetch_, 5000)
    return () => { active = false; clearInterval(iv) }
  }, [refreshKey])

  const active = [
    ...(data?.sonarr || []).filter(q => q.status !== 'completed'),
    ...(data?.radarr || []).filter(q => q.status !== 'completed'),
  ]
  const done = [
    ...(data?.sonarr || []).filter(q => q.status === 'completed'),
    ...(data?.radarr || []).filter(q => q.status === 'completed'),
  ]

  return (
    <div className="px-3 py-4">
      {/* Section label */}
      <div className="flex items-center gap-2 mb-3 px-1">
        <span className={`w-1.5 h-1.5 rounded-full ${active.length > 0 ? 'bg-success status-pulse' : 'bg-ink-subtle'}`} />
        <span className="text-micro text-ink-muted uppercase tracking-wider" style={{ fontWeight: 510 }}>
          Downloads
        </span>
      </div>

      {loading && <div className="text-center py-6 text-ink-subtle text-caption">Loading…</div>}

      {/* Active downloads */}
      {active.length > 0 && (
        <div className="space-y-2 mb-4">
          {active.map((item, i) => <DownloadBar key={i} item={item} />)}
        </div>
      )}

      {/* SABnzbd */}
      {data?.sabnzbd && data.sabnzbd.slots.length > 0 && (
        <SabnzbdWidget data={data.sabnzbd} />
      )}

      {/* Completed */}
      {done.length > 0 && (
        <details className="mt-4 group">
          <summary className="cursor-pointer text-caption text-ink-muted hover:text-ink-secondary transition-colors px-1">
            <span className="text-success">●</span> {done.length} completed
          </summary>
          <div className="mt-2 space-y-1 px-1">
            {done.slice(0, 8).map((item, i) => (
              <div key={i} className="flex items-center gap-2 text-micro text-ink-subtle py-0.5">
                <span className="truncate flex-1">{item.title}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Empty state */}
      {!loading && active.length === 0 && !data?.sabnzbd?.slots.length && (
        <div className="px-1 py-2">
          <p className="text-caption text-ink-subtle">Nothing downloading.</p>
        </div>
      )}
    </div>
  )
}

function DownloadBar({ item }: { item: QueueItem }) {
  const downloading = item.status === 'downloading'
  const importing = item.status === 'importing' || item.status === 'importPending'
  const pct = Math.min(100, Math.max(0, item.progress))

  const barColor = downloading ? '#5e6ad2' : importing ? '#f59e0b' : '#62666d'
  const statusText = downloading ? `${pct}%` : importing ? 'Importing…' : item.status

  // Clean up title: strip release-group noise
  const cleanTitle = item.title
    .replace(/\.\d{3,4}p\..*$/, '')  // .1080p.WEB-DL...
    .replace(/\.\d+p\..*$/, '')
    .replace(/\.[A-Z0-9-]+$/, '')
    .replace(/\./g, ' ')

  return (
    <div className="px-2 py-2 rounded-md hover:bg-surface transition-colors msg-enter">
      {/* Title row */}
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span className="text-caption text-ink-secondary truncate flex-1" title={item.title}>
          {cleanTitle}
        </span>
        {item.quality && (
          <span className="text-micro text-ink-subtle font-mono px-1 py-0.5 bg-hover rounded">
            {item.quality.replace('WEBDL-', '').replace('WEB-', '')}
          </span>
        )}
      </div>
      {/* Progress bar */}
      <div className="relative h-1.5 bg-white/5 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500 ease-out"
          style={{ width: `${pct}%`, background: barColor }}
        />
        {downloading && <div className="progress-shimmer" />}
      </div>
      {/* Status row */}
      <div className="flex items-center justify-between mt-1 text-micro">
        <span className={item.warning ? 'text-warning' : 'text-ink-subtle'}>
          {item.warning && '⚠ '}{statusText}
        </span>
        {item.sizeleft_mb > 0 && (
          <span className="text-ink-subtle font-mono">
            {item.sizeleft_mb.toFixed(0)} MB
            {item.timeleft && item.timeleft !== '0:00:00' && ` · ${item.timeleft}`}
          </span>
        )}
      </div>
    </div>
  )
}

function SabnzbdWidget({ data }: { data: SabnzbdData }) {
  return (
    <div className="px-2 py-2 rounded-md hover:bg-surface transition-colors">
      <div className="flex items-center justify-between mb-2">
        <span className="text-caption text-ink-secondary" style={{ fontWeight: 510 }}>
          SABnzbd
        </span>
        <div className="flex items-center gap-1.5">
          {data.paused ? (
            <span className="text-micro text-warning">Paused</span>
          ) : (
            <span className="text-micro text-success font-mono">{data.speed}</span>
          )}
        </div>
      </div>
      <div className="space-y-2">
        {data.slots.slice(0, 4).map((slot, i) => (
          <div key={i}>
            <div className="flex justify-between mb-0.5">
              <span className="text-micro text-ink-muted truncate flex-1">
                {slot.filename.replace(/\./g, ' ').replace(/[A-Z0-9-]+$/, '').trim()}
              </span>
              <span className="text-micro text-ink-subtle font-mono">
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
        ))}
        {data.total_count > 4 && (
          <div className="text-micro text-ink-subtle text-center pt-0.5">
            +{data.total_count - 4} more
          </div>
        )}
      </div>
    </div>
  )
}
