import { useState, useEffect } from 'react'
import type { QueueResponse, QueueItem } from '../types'

interface Props {
  refreshKey: number
}

export function DownloadPanel({ refreshKey }: Props) {
  const [data, setData] = useState<QueueResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    const fetchData = async () => {
      try {
        const resp = await fetch('/api/queue')
        if (!resp.ok) return
        const json = await resp.json()
        if (!cancelled) {
          setData(json)
          setLoading(false)
        }
      } catch {
        if (!cancelled) setLoading(false)
      }
    }

    fetchData()
    // Auto-refresh every 5 seconds when there are active downloads
    const interval = setInterval(fetchData, 5000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [refreshKey])

  const activeDownloads = [
    ...(data?.sonarr || []).filter(q => q.status !== 'completed'),
    ...(data?.radarr || []).filter(q => q.status !== 'completed'),
  ]

  const completedItems = [
    ...(data?.sonarr || []).filter(q => q.status === 'completed'),
    ...(data?.radarr || []).filter(q => q.status === 'completed'),
  ]

  return (
    <div className="p-4 space-y-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${activeDownloads.length > 0 ? 'bg-green-500 animate-pulse' : 'bg-gray-600'}`} />
        Downloads
      </h2>

      {loading && (
        <div className="text-center py-8 text-gray-600 text-sm">Loading...</div>
      )}

      {/* Active Downloads */}
      {activeDownloads.length > 0 && (
        <div className="space-y-3">
          {activeDownloads.map((item, i) => (
            <DownloadBar key={`active-${i}`} item={item} />
          ))}
        </div>
      )}

      {/* SABnzbd */}
      {data?.sabnzbd && (
        <SabnzbdWidget data={data.sabnzbd} />
      )}

      {/* Completed (collapsed) */}
      {completedItems.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-gray-500 hover:text-gray-400">
            ✅ {completedItems.length} completed
          </summary>
          <div className="mt-2 space-y-1">
            {completedItems.slice(0, 10).map((item, i) => (
              <div key={`done-${i}`} className="flex items-center gap-2 text-xs text-gray-500 py-1">
                <span className="truncate">{item.title}</span>
                {item.quality && <span className="text-gray-600">[{item.quality}]</span>}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Empty state */}
      {!loading && activeDownloads.length === 0 && !data?.sabnzbd && (
        <div className="text-center py-8 text-gray-600 text-sm">
          No active downloads
        </div>
      )}
    </div>
  )
}

function DownloadBar({ item }: { item: QueueItem }) {
  const isDownloading = item.status === 'downloading'
  const isImporting = item.status === 'importing' || item.status === 'importPending'
  const pct = Math.min(100, Math.max(0, item.progress))

  const barColor = isDownloading
    ? 'bg-gradient-to-r from-blue-500 to-blue-400'
    : isImporting
    ? 'bg-gradient-to-r from-yellow-500 to-yellow-400'
    : 'bg-gray-600'

  const statusLabel = isDownloading
    ? `${pct}%`
    : isImporting
    ? 'Importing...'
    : item.status

  return (
    <div className="bg-dark-bg rounded-lg p-3 border border-dark-border animate-slide-up">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-medium text-gray-300 truncate flex-1">{item.title}</span>
        {item.quality && (
          <span className="text-xs text-gray-500 ml-2 px-1.5 py-0.5 bg-dark-border rounded">
            {item.quality}
          </span>
        )}
      </div>
      {/* Progress bar */}
      <div className="relative h-2 bg-dark-border rounded-full overflow-hidden">
        <div
          className={`h-full ${barColor} rounded-full transition-all duration-500 ease-out`}
          style={{ width: `${pct}%` }}
        />
        {isDownloading && (
          <div
            className="absolute top-0 h-full opacity-30 rounded-full"
            style={{
              width: `${pct}%`,
              background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent)',
              backgroundSize: '200% 100%',
              animation: 'progressShimmer 2s linear infinite',
            }}
          />
        )}
      </div>
      {/* Status line */}
      <div className="flex items-center justify-between mt-1.5 text-xs">
        <span className={item.warning ? 'text-yellow-500' : 'text-gray-500'}>
          {item.warning && '⚠️ '}{statusLabel}
        </span>
        <span className="text-gray-600">
          {item.sizeleft_mb > 0 && `${item.sizeleft_mb.toFixed(0)} MB left`}
          {item.timeleft && item.timeleft !== '0:00:00' && ` · ~${item.timeleft}`}
        </span>
      </div>
    </div>
  )
}

function SabnzbdWidget({ data }: { data: NonNullable<QueueResponse['sabnzbd']> }) {
  if (!data.slots?.length) return null

  return (
    <div className="bg-dark-bg rounded-lg p-3 border border-dark-border">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-300">📦 SABnzbd</span>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          {data.paused ? (
            <span className="text-yellow-500">⏸ Paused</span>
          ) : (
            <span className="text-green-500">⬇ {data.speed}</span>
          )}
        </div>
      </div>
      <div className="space-y-2">
        {data.slots.slice(0, 5).map((slot, i) => (
          <div key={i} className="text-xs">
            <div className="flex justify-between mb-1">
              <span className="text-gray-400 truncate flex-1">{slot.filename}</span>
              <span className="text-gray-600 ml-2">{slot.progress.toFixed(0)}%</span>
            </div>
            <div className="h-1.5 bg-dark-border rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  data.paused ? 'bg-gray-600' : 'bg-gradient-to-r from-orange-500 to-orange-400'
                }`}
                style={{ width: `${Math.min(100, slot.progress)}%` }}
              />
            </div>
          </div>
        ))}
        {data.total_count > 5 && (
          <div className="text-xs text-gray-600 text-center pt-1">
            +{data.total_count - 5} more in queue
          </div>
        )}
      </div>
    </div>
  )
}
