import { useState, useEffect, useRef } from 'react'
import { fetchData, streamChat } from './api/client'
import ServiceCards from './components/ServiceCards'
import ContentProviders from './components/ContentProviders'
import ActivityFeed from './components/ActivityFeed'
import QuickActions from './components/QuickActions'
import ChatPanel from './components/ChatPanel'

export default function App() {
  const [activeTab, setActiveTab] = useState('overview')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const abortControllerRef = useRef(null)

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

    let interval
    if (autoRefresh) {
      interval = setInterval(fetchDashboardData, 30000)
    }

    return () => {
      if (interval) clearInterval(interval)
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [autoRefresh])

  const handleQuickAction = (query) => {
    setActiveTab('chat')
  }

  const getStatusColor = () => {
    if (!data) return 'bg-gray-500'
    const services = Object.values(data.services || {})
    const hasError = services.some(s => s.status === 'error')
    const hasWarning = services.some(s => s.status === 'warning')
    if (hasError) return 'bg-accent-red'
    if (hasWarning) return 'bg-accent-yellow'
    return 'bg-accent-green'
  }

  const formatLastUpdated = () => {
    if (!lastUpdated) return 'Never'
    const now = new Date()
    const diff = Math.floor((now - lastUpdated) / 1000)
    if (diff < 60) return `${diff}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    return lastUpdated.toLocaleTimeString()
  }

  return (
    <div className="min-h-screen bg-dark-800 text-dark-100 font-sans">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-dark-800/80 backdrop-blur-md border-b border-dark-500/60">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <span className="text-2xl">🎬</span>
              <h1 className="text-xl font-semibold text-dark-100">Media Agent</h1>
              <div className="flex items-center gap-2 ml-4">
                <div className={`w-2 h-2 rounded-full ${getStatusColor()} animate-pulse-slow`} />
                <span className="text-xs text-dark-400">{formatLastUpdated()}</span>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
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
                <span className="text-sm text-dark-300">Auto-refresh</span>
              </label>
            </div>
          </div>
        </div>
      </header>

      {/* Tab Navigation */}
      <div className="border-b border-dark-500/60">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <nav className="flex gap-8">
            <button
              onClick={() => setActiveTab('overview')}
              className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'overview'
                  ? 'border-accent-blue text-accent-blue'
                  : 'border-transparent text-dark-400 hover:text-dark-300 hover:border-dark-500'
              }`}
            >
              Overview
            </button>
            <button
              onClick={() => setActiveTab('chat')}
              className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'chat'
                  ? 'border-accent-blue text-accent-blue'
                  : 'border-transparent text-dark-400 hover:text-dark-300 hover:border-dark-500'
              }`}
            >
              Chat
            </button>
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
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
            {/* Service Cards */}
            <section>
              <ServiceCards services={data?.services || {}} />
            </section>

            {/* Content Providers */}
            <section>
              <ContentProviders providers={data?.local_tools || {}} />
            </section>

            {/* Quick Actions */}
            <section>
              <QuickActions onAction={handleQuickAction} />
            </section>

            {/* Activity Feed */}
            <section>
              <ActivityFeed activities={data?.activity || []} />
            </section>

            {/* Disk Space */}
            {data?.disk_space && (
              <section>
                <h2 className="text-lg font-semibold mb-4">Disk Space</h2>
                <div className="card">
                  <div className="space-y-3">
                    {Object.entries(data.disk_space).map(([name, info]) => (
                      <div key={name}>
                        <div className="flex justify-between text-sm mb-1">
                          <span className="text-dark-300">{name}</span>
                          <span className="text-dark-400">{info.used} / {info.total} ({info.percent}%)</span>
                        </div>
                        <div className="h-2 bg-dark-600 rounded-full overflow-hidden">
                          <div
                            className={`h-full transition-all duration-500 ${
                              info.percent > 90 ? 'bg-accent-red' :
                              info.percent > 75 ? 'bg-accent-yellow' :
                              'bg-accent-green'
                            }`}
                            style={{ width: `${info.percent}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            )}
          </div>
        ) : (
          <ChatPanel />
        )}
      </main>
    </div>
  )
}