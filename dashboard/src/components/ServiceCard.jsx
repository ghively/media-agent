import { useState } from 'react'

export default function ServiceCard({ service }) {
  const [expanded, setExpanded] = useState(false)

  if (!service) return null

  const { name, status, data } = service

  const getStatusBadge = () => {
    if (status === 'healthy') return <span className="badge badge-healthy">Healthy</span>
    if (status === 'warning') return <span className="badge badge-warning">Warning</span>
    return <span className="badge badge-error">Error</span>
  }

  const getEmoji = () => {
    switch (name.toLowerCase()) {
      case 'sonarr': return '📺'
      case 'radarr': return '🎬'
      case 'emby': return '🎭'
      case 'sabnzbd': return '⬇️'
      case 'download station': return '📥'
      default: return '📦'
    }
  }

  const renderContent = () => {
    if (!data) return null

    const isLibraryService = name.toLowerCase() === 'sonarr' || name.toLowerCase() === 'radarr'
    const isEmby = name.toLowerCase() === 'emby'
    const isDownloader = name.toLowerCase() === 'sabnzbd' || name.toLowerCase() === 'download station'

    if (isLibraryService) {
      return (
        <>
          {data.library_count !== undefined && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-dark-400">Library:</span>
              <span className="text-dark-200 font-medium">{data.library_count}</span>
            </div>
          )}
          {data.health_message && (
            <div className="text-sm text-dark-400 mt-1">{data.health_message}</div>
          )}
          {data.queue_items && data.queue_items.length > 0 && (
            <div className="mt-3 space-y-2">
              <div className="text-xs text-dark-400 uppercase tracking-wide">Queue</div>
              {data.queue_items.slice(0, expanded ? 10 : 3).map((item, idx) => (
                <div key={idx} className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-dark-300 truncate">{item.title}</span>
                    <span className="text-dark-400">{item.progress}%</span>
                  </div>
                  <div className="h-1.5 bg-dark-600 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent-blue rounded-full transition-all duration-300"
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                </div>
              ))}
              {data.queue_items.length > 3 && !expanded && (
                <button
                  onClick={() => setExpanded(true)}
                  className="text-xs text-accent-blue hover:text-accent-blue/80"
                >
                  +{data.queue_items.length - 3} more
                </button>
              )}
            </div>
          )}
        </>
      )
    }

    if (isEmby) {
      return (
        <>
          {data.library_count !== undefined && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-dark-400">Libraries:</span>
              <span className="text-dark-200 font-medium">{data.library_count}</span>
            </div>
          )}
          {data.recently_added && data.recently_added.length > 0 && (
            <div className="mt-3 space-y-2">
              <div className="text-xs text-dark-400 uppercase tracking-wide">Recently Added</div>
              {data.recently_added.slice(0, expanded ? 10 : 3).map((item, idx) => (
                <div key={idx} className="text-xs text-dark-300 truncate">
                  {item.title || item.name}
                </div>
              ))}
              {data.recently_added.length > 3 && !expanded && (
                <button
                  onClick={() => setExpanded(true)}
                  className="text-xs text-accent-blue hover:text-accent-blue/80"
                >
                  +{data.recently_added.length - 3} more
                </button>
              )}
            </div>
          )}
        </>
      )
    }

    if (isDownloader) {
      return (
        <>
          {data.queue_count !== undefined && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-dark-400">Queue:</span>
              <span className="text-dark-200 font-medium">{data.queue_count}</span>
            </div>
          )}
          {data.speed && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-dark-400">Speed:</span>
              <span className="text-dark-200 font-medium">{data.speed}</span>
            </div>
          )}
          {data.queue_items && data.queue_items.length > 0 && (
            <div className="mt-3 space-y-2">
              <div className="text-xs text-dark-400 uppercase tracking-wide">Downloads</div>
              {data.queue_items.slice(0, expanded ? 10 : 3).map((item, idx) => (
                <div key={idx} className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-dark-300 truncate">{item.title}</span>
                    <span className="text-dark-400">{item.progress}%</span>
                  </div>
                  <div className="h-1.5 bg-dark-600 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent-green rounded-full transition-all duration-300"
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                </div>
              ))}
              {data.queue_items.length > 3 && !expanded && (
                <button
                  onClick={() => setExpanded(true)}
                  className="text-xs text-accent-blue hover:text-accent-blue/80"
                >
                  +{data.queue_items.length - 3} more
                </button>
              )}
            </div>
          )}
        </>
      )
    }

    return null
  }

  return (
    <div className="card group">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{getEmoji()}</span>
          <div>
            <h3 className="text-lg font-semibold text-dark-100">{name}</h3>
            <div className="mt-1">{getStatusBadge()}</div>
          </div>
        </div>
      </div>
      <div className="space-y-2">
        {renderContent()}
      </div>
    </div>
  )
}