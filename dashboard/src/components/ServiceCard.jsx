import { useState } from 'react'

// The dashboard API (`/api/dashboard/data`) returns each service as a FLAT
// object, e.g. { name, status, emoji, health, queue_count, queue_items[],
// library_count | libraries, recent[], speed }. Keep this component reading
// those fields directly — there is no nested `data` object.
export default function ServiceCard({ service }) {
  const [expanded, setExpanded] = useState(false)

  if (!service) return null

  const { name, status, emoji } = service
  const key = (name || '').toLowerCase()

  const getStatusBadge = () => {
    if (status === 'healthy') return <span className="badge badge-healthy">Healthy</span>
    if (status === 'warning') return <span className="badge badge-warning">Warning</span>
    return <span className="badge badge-error">Error</span>
  }

  const getEmoji = () => {
    if (emoji && !['✅', '⚠️', '❌'].includes(emoji)) return emoji
    switch (key) {
      case 'sonarr': return '📺'
      case 'radarr': return '🎬'
      case 'emby': return '🎭'
      case 'sabnzbd': return '⬇️'
      case 'download station': return '📥'
      default: return '📦'
    }
  }

  const queueItems = service.queue_items || []
  const recent = service.recent || []
  const visibleQueue = queueItems.slice(0, expanded ? 10 : 3)
  const visibleRecent = recent.slice(0, expanded ? 10 : 3)

  const moreButton = (count) =>
    count > 3 && !expanded ? (
      <button
        onClick={() => setExpanded(true)}
        className="text-xs text-accent-blue hover:text-accent-blue/80"
      >
        +{count - 3} more
      </button>
    ) : null

  const queueRow = (item, idx, barColor) => (
    <div key={idx} className="space-y-1">
      <div className="flex justify-between gap-2 text-xs">
        <span className="text-dark-300 truncate">{item.name}</span>
        <span className="text-dark-400 shrink-0">{item.progress ?? 0}%</span>
      </div>
      <div className="h-1.5 bg-dark-600 rounded-full overflow-hidden">
        <div
          className={`h-full ${barColor} rounded-full transition-all duration-300`}
          style={{ width: `${Math.max(0, Math.min(100, item.progress || 0))}%` }}
        />
      </div>
      {(item.size || item.status) && (
        <div className="text-[0.65rem] text-dark-500 truncate">
          {[item.size, item.status].filter(Boolean).join(' · ')}
        </div>
      )}
    </div>
  )

  const renderContent = () => {
    const isLibrary = key === 'sonarr' || key === 'radarr'
    const isEmby = key === 'emby'
    const isDownloader = key === 'sabnzbd' || key === 'download station'

    if (isLibrary) {
      return (
        <>
          {service.library_count !== undefined && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-dark-400">Library:</span>
              <span className="text-dark-200 font-medium">{service.library_count}</span>
            </div>
          )}
          {service.health && (
            <div className="text-xs text-dark-400 mt-1 break-words">{service.health}</div>
          )}
          {queueItems.length > 0 && (
            <div className="mt-3 space-y-2">
              <div className="text-xs text-dark-400 uppercase tracking-wide">
                Queue ({service.queue_count ?? queueItems.length})
              </div>
              {visibleQueue.map((item, idx) => queueRow(item, idx, 'bg-accent-blue'))}
              {moreButton(queueItems.length)}
            </div>
          )}
          {queueItems.length === 0 && service.queue_count === 0 && (
            <div className="text-xs text-dark-500 mt-2">Queue empty</div>
          )}
        </>
      )
    }

    if (isEmby) {
      const libCount = service.libraries ?? service.library_count
      return (
        <>
          {libCount !== undefined && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-dark-400">Libraries:</span>
              <span className="text-dark-200 font-medium">{libCount}</span>
            </div>
          )}
          {recent.length > 0 && (
            <div className="mt-3 space-y-1.5">
              <div className="text-xs text-dark-400 uppercase tracking-wide">Recently Added</div>
              {visibleRecent.map((item, idx) => (
                <div key={idx} className="text-xs text-dark-300 truncate">
                  {item.name}{item.type ? <span className="text-dark-500"> · {item.type}</span> : null}
                </div>
              ))}
              {moreButton(recent.length)}
            </div>
          )}
        </>
      )
    }

    if (isDownloader) {
      return (
        <>
          {service.queue_count !== undefined && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-dark-400">Queue:</span>
              <span className="text-dark-200 font-medium">{service.queue_count}</span>
            </div>
          )}
          {service.speed && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-dark-400">Speed:</span>
              <span className="text-dark-200 font-medium">{service.speed} KB/s</span>
            </div>
          )}
          {queueItems.length > 0 && (
            <div className="mt-3 space-y-2">
              <div className="text-xs text-dark-400 uppercase tracking-wide">Downloads</div>
              {visibleQueue.map((item, idx) => queueRow(item, idx, 'bg-accent-green'))}
              {moreButton(queueItems.length)}
            </div>
          )}
          {queueItems.length === 0 && service.queue_count === 0 && (
            <div className="text-xs text-dark-500 mt-2">Queue empty</div>
          )}
        </>
      )
    }

    return null
  }

  return (
    <div className="card">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-2xl shrink-0">{getEmoji()}</span>
          <div className="min-w-0">
            <h3 className="text-lg font-semibold text-dark-100 truncate">{name}</h3>
            <div className="mt-1">{getStatusBadge()}</div>
          </div>
        </div>
      </div>
      <div className="space-y-2">{renderContent()}</div>
    </div>
  )
}
