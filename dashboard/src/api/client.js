const API = '/api/dashboard'

export async function fetchData() {
  const resp = await fetch(`${API}/data`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

export async function sendChat(message) {
  const resp = await fetch(`${API}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

/**
 * Stream chat via SSE using fetch + ReadableStream.
 * Calls onToken for each chunk, onDone when complete.
 */
export async function streamChat(message, { onToken, onDone, onError }) {
  try {
    const resp = await fetch(`${API}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const payload = JSON.parse(line.slice(6))
            if (payload.error) {
              onError?.(payload.error)
              return
            }
            if (payload.content) {
              onToken?.(payload.content)
            }
            if (payload.done) {
              onDone?.(payload.full || '')
              return
            }
          } catch (e) {
            // partial JSON, skip
          }
        }
      }
    }
  } catch (e) {
    onError?.(e.message)
  }
}
