const API = '/api/dashboard'
const KEY_STORAGE = 'media-agent-api-key'

// One conversation per page load: a fresh session id means the visible chat
// and the agent's memory always agree (a reload starts clean on both sides).
let sessionId = newSessionId()

function newSessionId() {
  try {
    return crypto.randomUUID().replace(/-/g, '')
  } catch {
    return `s${Date.now()}${Math.floor(Math.random() * 1e9)}`
  }
}

export function getApiKey() {
  try {
    return localStorage.getItem(KEY_STORAGE) || ''
  } catch {
    return ''
  }
}

export function setApiKey(key) {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key)
    else localStorage.removeItem(KEY_STORAGE)
  } catch {
    // Private-mode browsers without localStorage: key lives for this page only.
  }
}

function authHeaders(extra = {}) {
  const key = getApiKey()
  return key ? { ...extra, Authorization: `Bearer ${key}` } : extra
}

// Thrown on 401 so the UI can prompt for the API key instead of showing a
// generic error.
export class AuthRequiredError extends Error {
  constructor() {
    super('API key required')
    this.name = 'AuthRequiredError'
  }
}

function checkResp(resp) {
  if (resp.status === 401) throw new AuthRequiredError()
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp
}

export async function fetchData() {
  const resp = await fetch(`${API}/data`, { headers: authHeaders() })
  checkResp(resp)
  return resp.json()
}

export async function sendChat(message) {
  const resp = await fetch(`${API}/chat`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ message, session_id: sessionId }),
  })
  checkResp(resp)
  return resp.json()
}

/**
 * Start a new conversation: tell the server to drop the old thread's memory
 * and pending confirmations, then switch to a fresh session id.
 */
export async function resetConversation() {
  const old = sessionId
  sessionId = newSessionId()
  try {
    await fetch(`${API}/reset`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ session_id: old }),
    })
  } catch {
    // Best-effort: the abandoned thread just ages out server-side.
  }
}

/**
 * Stream chat via SSE using fetch + ReadableStream.
 * Calls onToken for each chunk, onDone when complete, onAuthRequired on 401.
 */
export async function streamChat(message, { onToken, onDone, onError, onAuthRequired }) {
  try {
    const resp = await fetch(`${API}/chat`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ message, session_id: sessionId }),
    })
    if (resp.status === 401) {
      onAuthRequired?.()
      return
    }
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
        // SSE comment lines (keepalive pings) are ignored by falling through.
      }
    }
  } catch (e) {
    onError?.(e.message)
  }
}
