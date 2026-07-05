import { useState, useEffect } from 'react'
import { fetchData } from './api/client'
import ServiceCards from './components/ServiceCards'
import ContentProviders from './components/ContentProviders'
import ActivityFeed from './components/ActivityFeed'
import QuickActions from './components/QuickActions'
import ChatPanel from './components/ChatPanel'
import DiskSpace from './components/DiskSpace'

export default function App() {
  const [activeTab, setActiveTab] = useState('overview')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  // A quick-action sends a query into the chat: {text, id}. The id changes
  // on every click so ChatPanel re-fires even when the text repeats.
  const [pendingQuery, setPendingQuery] = useState(null)

  const fetchDashboardData = async () => {
    try {
      const result = await fetchData()
      setData(result)
      setLastUpdated(new Date())
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err)
    }
  }

  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      await fetchDashboardData()
      setLoading(false)
    }
    loadData()

    if (!autoRefresh) return
    const interval = setInterval(fetchDashboardData, 30000)
    return () => clearInterval(interval)
  }, [autoRefresh])

  const handleQuickAction = (query) => {
    setPendingQuery({ text: query, id: Date.now() })
    setActiveTab('chat')
  }

  const getStatusColor = () => {
    if (!data) return 'bg-dark-400'
    const services = Object.values(data.services || {})
    if (services.some(s => s.status === 'error')) return 'bg-accent-red'
    if (services.some(s => s.status === 'warning')) return 'bg-accent-yellow'
    return 'bg-accent-green'
  }

  const formatLastUpdated = () => {
    if (!lastUpdated) return 'Never'
    const diff = Math.floor((new Date() - lastUpdated) / 1000)
    if (diff < 60) return `${diff}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    return lastUpdated.toLocaleTimeString()
  }

  const tabClass = (tab) =>
    `flex-1 sm:flex-none text-center py-4 sm:py-3 px-1 border-b-2 font-semibold sm:font-medium text-sm transition-colors touch-manipulation select-none ${
      activeTab === tab
        ? 'border-accent-blue text-accent-blue'
        : 'border-transparent text-dark-400 hover:text-dark-300 hover:border-dark-500'
    }`

  return (
    <div className="min-h-screen bg-dark-800 text-dark-100 font-sans">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-dark-800/80 backdrop-blur-md border-b border-dark-500/60">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between gap-2 h-14 sm:h-16">
            <div className="flex items-center gap-2 sm:gap-3 min-w-0">
              <span className="text-xl sm:text-2xl shrink-0">🎬</span>
              <h1 className="text-base sm:text-xl font-semibold text-dark-100 truncate">Media Agent</h1>
              <div className="flex items-center gap-1.5 shrink-0">
                <div className={`w-2 h-2 rounded-full ${getStatusColor()} animate-pulse-slow`} />
                <span className="text-xs text-dark-400 whitespace-nowrap">{formatLastUpdated()}</span>
              </div>
            </div>
            <label className="flex items-center gap-2 cursor-pointer shrink-0">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.target.checked)}
                  className="sr-only"
                />
                <div className={`w-11 h-6 rounded-full transition-colors ${autoRefresh ? 'bg-accent-blue' : 'bg-dark-500'}`}>
                  <div className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${autoRefresh ? 'translate-x-5' : ''}`} />
                </div>
              </div>
              <span className="hidden sm:inline text-sm text-dark-300">Auto-refresh</span>
            </label>
          </div>
        </div>
      </header>

      {/* Tab Navigation */}
      <div className="border-b border-dark-500/60">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <nav className="flex gap-2 sm:gap-8">
            <button onClick={() => setActiveTab('overview')} className={tabClass('overview')}>Overview</button>
            <button onClick={() => setActiveTab('chat')} className={tabClass('chat')}>Chat</button>
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5 sm:py-6">
        {loading && !data ? (
          <div className="flex items-center justify-center h-64">
            <div className="flex gap-1">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </div>
          </div>
        ) : activeTab === 'overview' ? (
          <div className="space-y-6">
            <section><ServiceCards services={data?.services || {}} /></section>
            <section><ContentProviders providers={data?.local_tools || {}} /></section>
            <section><QuickActions onAction={handleQuickAction} /></section>
            <section><ActivityFeed activities={data?.activity || []} /></section>
            <DiskSpace disk={data?.disk_space} />
          </div>
        ) : (
          <ChatPanel initialQuery={pendingQuery} />
        )}
      </main>
    </div>
  )
}
