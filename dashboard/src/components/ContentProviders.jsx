export default function ContentProviders({ providers }) {
  const providerConfig = [
    { key: 'youtube', icon: '▶️', label: 'YouTube' },
    { key: 'audible', icon: '🎧', label: 'Audible' },
    { key: 'roms', icon: '🕹️', label: 'ROMs' },
    { key: 'bandcamp', icon: '🎵', label: 'Bandcamp' },
  ]

  const getStatusBadge = (status) => {
    if (status === 'available') return <span className="badge badge-available">Available</span>
    if (status === 'unavailable') return <span className="badge badge-error">Unavailable</span>
    return <span className="badge badge-warning">Unknown</span>
  }

  if (!providers || Object.keys(providers).length === 0) {
    return (
      <div className="card">
        <div className="text-center text-dark-400 py-8">
          No content providers configured
        </div>
      </div>
    )
  }

  return (
    <>
      <h2 className="text-lg font-semibold mb-4">Content Providers</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
        {providerConfig.map(({ key, icon, label }) => {
          const provider = providers[key]
          const status = provider?.status || 'unknown'
          return (
            <div key={key} className="card py-3 px-4">
              <div className="flex items-center gap-3">
                <span className="text-xl">{icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-dark-200 truncate">{label}</div>
                  <div className="mt-1">{getStatusBadge(status)}</div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}