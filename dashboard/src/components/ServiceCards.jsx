import ServiceCard from './ServiceCard'

export default function ServiceCards({ services }) {
  if (!services || Object.keys(services).length === 0) {
    return (
      <div className="card">
        <div className="text-center text-dark-400 py-8">
          No services configured
        </div>
      </div>
    )
  }

  const serviceOrder = ['sonarr', 'radarr', 'emby', 'sabnzbd', 'download_station']
  const sortedServices = Object.entries(services).sort((a, b) => {
    const idxA = serviceOrder.indexOf(a[0].toLowerCase())
    const idxB = serviceOrder.indexOf(b[0].toLowerCase())
    if (idxA === -1 && idxB === -1) return a[0].localeCompare(b[0])
    if (idxA === -1) return 1
    if (idxB === -1) return -1
    return idxA - idxB
  })

  return (
    <>
      <h2 className="text-lg font-semibold mb-4">Services</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {sortedServices.map(([name, service]) => (
          <ServiceCard key={name} service={{ name, ...service }} />
        ))}
      </div>
    </>
  )
}