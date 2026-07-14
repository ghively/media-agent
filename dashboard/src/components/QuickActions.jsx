export default function QuickActions({ onAction }) {
  // Phrasings deliberately match the deterministic router's patterns so
  // every button answers instantly, without an LLM round trip.
  const actions = [
    { icon: '❤️', label: 'Health Check', query: 'health check' },
    { icon: '⬇️', label: 'Downloads', query: "what's downloading?" },
    { icon: '📺', label: 'TV Shows', query: 'list my tv shows' },
    { icon: '🎬', label: 'Movies', query: 'list my movies' },
    { icon: '🆕', label: 'Recent', query: 'what was recently added to emby?' },
    { icon: '📅', label: 'Calendar', query: 'what is airing this week?' },
    { icon: '🔍', label: 'Find Missing', query: 'find all missing episodes and movies' },
    { icon: '💾', label: 'Disk Space', query: 'check disk space' },
    { icon: '🧲', label: 'Torrents', query: 'torrents' },
    { icon: '🕹️', label: 'Games', query: 'list my rom collection' },
    { icon: '▶️', label: 'YouTube Subs', query: 'list my youtube subscriptions' },
    { icon: '🎧', label: 'Audiobooks', query: 'list my audiobooks' },
    { icon: '🎙️', label: 'Podcasts', query: 'list my podcasts' },
    { icon: '🎼', label: 'Artists', query: 'list my artists' },
    { icon: '📚', label: 'Comics', query: 'recent comics' },
    { icon: '❓', label: 'Help', query: 'help' },
  ]

  return (
    <>
      <h2 className="text-lg font-semibold mb-4">Quick Actions</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-8 gap-2.5 sm:gap-2">
        {actions.map((action, idx) => (
          <button
            key={idx}
            onClick={() => onAction(action.query)}
            className="card flex flex-col items-center justify-center gap-1 min-h-[76px] sm:min-h-[64px] py-4 px-2 text-center hover:border-accent-blue/60 hover:bg-dark-600/40 active:scale-95 active:bg-dark-600/60 transition-all cursor-pointer touch-manipulation select-none"
            title={action.label}
          >
            <div className="text-3xl sm:text-2xl leading-none">{action.icon}</div>
            <div className="text-xs text-dark-300 truncate w-full">{action.label}</div>
          </button>
        ))}
      </div>
    </>
  )
}