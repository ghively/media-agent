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
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-8 gap-2">
        {actions.map((action, idx) => (
          <button
            key={idx}
            onClick={() => onAction(action.query)}
            className="card py-3 px-2 text-center hover:border-accent-blue/60 hover:bg-dark-600/40 transition-all cursor-pointer active:scale-95"
            title={action.label}
          >
            <div className="text-2xl mb-1">{action.icon}</div>
            <div className="text-xs text-dark-300 truncate">{action.label}</div>
          </button>
        ))}
      </div>
    </>
  )
}