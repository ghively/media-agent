export default function ActivityFeed({ activities }) {
  if (!activities || activities.length === 0) {
    return (
      <div className="card">
        <div className="text-center text-dark-400 py-8">
          No recent activity
        </div>
      </div>
    )
  }

  const getEventBadge = (eventType) => {
    const normalized = eventType?.toLowerCase() || ''
    if (normalized.includes('grab') || normalized.includes('download')) {
      return <span className="badge badge-available">Grabbed</span>
    }
    if (normalized.includes('import') || normalized.includes('complete')) {
      return <span className="badge badge-healthy">Imported</span>
    }
    if (normalized.includes('fail') || normalized.includes('error')) {
      return <span className="badge badge-error">Failed</span>
    }
    return <span className="badge badge-warning">{eventType}</span>
  }

  const getServiceColor = (service) => {
    const normalized = service?.toLowerCase() || ''
    if (normalized.includes('sonarr')) return 'text-accent-blue'
    if (normalized.includes('radarr')) return 'text-accent-purple'
    if (normalized.includes('emby')) return 'text-accent-green'
    return 'text-dark-400'
  }

  const formatTime = (timestamp) => {
    if (!timestamp) return 'Unknown'
    const date = new Date(timestamp)
    const now = new Date()
    const diff = Math.floor((now - date) / 1000)

    if (diff < 60) return 'Just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return date.toLocaleDateString()
  }

  return (
    <>
      <h2 className="text-lg font-semibold mb-4">Recent Activity</h2>
      <div className="card p-0 overflow-hidden">
        <div className="divide-y divide-dark-500/40">
          {activities.slice(0, 20).map((activity, idx) => (
            <div key={idx} className="p-4 hover:bg-dark-600/30 transition-colors">
              <div className="flex items-start gap-3">
                <span className={`text-xs font-semibold uppercase ${getServiceColor(activity.service)} mt-0.5`}>
                  {activity.service}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    {getEventBadge(activity.event)}
                  </div>
                  <div className="mt-1 text-sm text-dark-200 truncate">
                    {activity.title}
                  </div>
                </div>
                <span className="text-xs text-dark-500 whitespace-nowrap ml-2">
                  {formatTime(activity.time)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}