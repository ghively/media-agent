import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App'

// If the dashboard is opened as /dashboard?key=SECRET, persist the key into a
// same-origin cookie so every /api/dashboard/* fetch authenticates without a
// login UI, then strip it from the visible URL. Must run before App mounts and
// fires its first fetch.
;(() => {
  const key = new URLSearchParams(window.location.search).get('key')
  if (key) {
    document.cookie = `md_key=${key}; path=/; max-age=31536000; SameSite=Strict`
    window.history.replaceState({}, '', window.location.pathname)
  }
})()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
