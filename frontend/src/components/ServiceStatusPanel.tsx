import { useState, useEffect } from 'react'
import type { StatusResponse } from '../types'

interface Props {
  refreshKey: number
}

export function ServiceStatusPanel({ refreshKey }: Props) {
  const [data, setData] = useState<StatusResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      try {
        const resp = await fetch('/api/status')
        if (!resp.ok) return
        const json = await resp.json()
        if (!cancelled) setData(json)
      } catch { /* silent */ }
    }
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [refreshKey])

  const services = data ? Object.values(data.services) : []

  return (
    <div className="flex items-center gap-3">
      {services.map(svc => (
        <div
          key={svc.name}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-dark-bg border border-dark-border"
          title={`${svc.name}: ${svc.status}`}
        >
          <span className={`w-2 h-2 rounded-full ${statusColor(svc.status)}`} />
          <span className="text-xs text-gray-400">{svc.name}</span>
          {svc.shows !== undefined && (
            <span className="text-xs text-gray-600">{svc.shows}</span>
          )}
          {svc.movies !== undefined && (
            <span className="text-xs text-gray-600">{svc.movies}</span>
          )}
          {svc.speed && !svc.paused && svc.status !== 'paused' && (
            <span className="text-xs text-gray-600">⬇{svc.speed}</span>
          )}
        </div>
      ))}
    </div>
  )
}

function statusColor(status: string): string {
  switch (status) {
    case 'healthy': return 'bg-green-500'
    case 'paused': return 'bg-yellow-500'
    case 'warning': return 'bg-yellow-500'
    case 'offline': return 'bg-red-500'
    default: return 'bg-gray-600'
  }
}
