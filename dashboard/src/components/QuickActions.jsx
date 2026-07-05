export default function QuickActions({ onAction }) {
  const actions = [
    { icon: '❤️', label: 'Health Check', query: 'Run a health check on all services' },
    { icon: '⬇️', label: 'Downloads', query: 'What is currently downloading?' },
    { icon: '📺', label: 'TV Shows', query: 'Show me the latest TV show activity' },
    { icon: '🎬', label: 'Movies', query: 'Show me the latest movie activity' },
    { icon: '🆕', label: 'Recent', query: 'What was recently added to the library?' },
    { icon: '📅', label: 'Calendar', query: 'Show me the upcoming releases calendar' },
    { icon: '🔍', label: 'Find Missing', query: 'Find all missing episodes and movies' },
    { icon: '💾', label: 'Disk Space', query: 'Check disk space usage across all drives' },
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