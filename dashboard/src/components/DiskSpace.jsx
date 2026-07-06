// The API returns disk info from SABnzbd as flat strings:
//   { download_dir, disk_free_1, disk_total_1 }  (values are GB, as strings)
export default function DiskSpace({ disk }) {
  if (!disk) return null

  const free = parseFloat(disk.disk_free_1)
  const total = parseFloat(disk.disk_total_1)
  const hasNumbers = Number.isFinite(free) && Number.isFinite(total) && total > 0
  const used = hasNumbers ? total - free : null
  const percent = hasNumbers ? Math.round((used / total) * 100) : null

  // Nothing useful to show.
  if (!hasNumbers && !disk.download_dir) return null

  const fmt = (gb) => (gb >= 1024 ? `${(gb / 1024).toFixed(1)} TB` : `${gb.toFixed(0)} GB`)

  const barColor =
    percent > 90 ? 'bg-accent-red' : percent > 75 ? 'bg-accent-yellow' : 'bg-accent-green'

  return (
    <section>
      <h2 className="text-lg font-semibold mb-4">Disk Space</h2>
      <div className="card space-y-3">
        {disk.download_dir && (
          <div className="text-xs text-dark-500 truncate" title={disk.download_dir}>
            {disk.download_dir}
          </div>
        )}
        {hasNumbers ? (
          <>
            <div className="flex justify-between gap-2 text-sm">
              <span className="text-dark-300">Used</span>
              <span className="text-dark-400">
                {fmt(used)} / {fmt(total)} ({percent}%)
              </span>
            </div>
            <div className="h-2 bg-dark-600 rounded-full overflow-hidden">
              <div className={`h-full ${barColor} transition-all duration-500`} style={{ width: `${percent}%` }} />
            </div>
            <div className="text-xs text-dark-500">{fmt(free)} free</div>
          </>
        ) : (
          <div className="text-sm text-dark-500">Disk usage unavailable</div>
        )}
      </div>
    </section>
  )
}
