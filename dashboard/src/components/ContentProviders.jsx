export default function ContentProviders({ providers }) {
  // Icons for known providers; anything else the API reports still renders
  // (new integrations show up without a frontend change).
  const ICONS = {
    youtube: '▶️', audible: '🎧', roms: '🕹️', bandcamp: '🎵',
    lidarr: '🎼', prowlarr: '🔍', komga: '📚', calibre: '📖',
    qbittorrent: '🧲', podcasts: '🎙️', twitch: '📡',
  }
  const providerConfig = Object.keys(providers || {}).map((key) => ({
    key,
    icon: ICONS[key] || '🔌',
    label: providers[key]?.name || key,
  }))

  // API (`local_tools`) reports status as available | warning | error.
  const getStatusBadge = (status) => {
    if (status === 'available') return <span className="badge badge-available">Available</span>
    if (status === 'warning') return <span className="badge badge-warning">Auth needed</span>
    if (status === 'error') return <span className="badge badge-error">Unavailable</span>
    return <span className="badge badge-warning">Unknown</span>
  }

  if (!providers || Object.keys(providers).length === 0) {
    return (
      <>
        <h2 className="text-lg font-semibold mb-4">Content Providers</h2>
        <div className="card">
          <div className="text-center text-dark-400 py-8">No content providers configured</div>
        </div>
      </>
    )
  }

  return (
    <>
      <h2 className="text-lg font-semibold mb-4">Content Providers</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {providerConfig.map(({ key, icon, label }) => {
          const provider = providers[key]
          const status = provider?.status || 'unknown'
          return (
            <div key={key} className="card py-3 px-4">
              <div className="flex items-center gap-3">
                <span className="text-xl shrink-0">{provider?.emoji || icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-medium text-dark-200 truncate">{label}</div>
                    {getStatusBadge(status)}
                  </div>
                  {provider?.info && (
                    <div className="mt-1 text-xs text-dark-500 truncate" title={provider.info}>
                      {provider.info}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}
