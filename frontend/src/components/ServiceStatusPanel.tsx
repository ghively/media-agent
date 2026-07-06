import { useState, useEffect } from 'react'
import type { StatusResponse, ServiceStatus } from '../types'

interface Props {
  refreshKey: number
}

export function ServiceStatusPanel({ refreshKey }: Props) {
  const [data, setData] = useState<StatusResponse | null>(null)

  useEffect(() => {
    let active = true
    const fetch_ = async () => {
      try {
        const r = await fetch('/api/status')
        if (!r.ok) return
        const j = await r.json()
        if (active) setData(j)
      } catch { /* silent */ }
    }
    fetch_()
    const iv = setInterval(fetch_, 30000)
    return () => { active = false; clearInterval(iv) }
  }, [refreshKey])

  const services = data ? Object.values(data.services) : []

  return (
    <div className="flex items-center gap-3">
      {services.map(svc => (
        <div key={svc.name} className="flex items-center gap-1.5">
          <StatusDot status={svc.status} />
          <span className="text-caption text-ink-muted" title={svc.name}>{svc.name}</span>
          {svc.shows !== undefined && (
            <span className="text-micro text-ink-subtle font-mono">{svc.shows}</span>
          )}
          {svc.movies !== undefined && (
            <span className="text-micro text-ink-subtle font-mono">{svc.movies}</span>
          )}
        </div>
      ))}
    </div>
  )
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === 'healthy' ? 'bg-success status-pulse' :
    status === 'paused' ? 'bg-warning' :
    status === 'offline' ? 'bg-danger' :
    'bg-ink-subtle'
  return <span className={`w-1.5 h-1.5 rounded-full ${color}`} />
}
