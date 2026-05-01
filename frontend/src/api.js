// Base URL:
//   - In dev (local): Vite proxy rewrites /api → http://localhost:8000
//   - In production (Vercel): VITE_API_URL must be set to the Render backend URL
const BASE = import.meta.env.VITE_API_URL
  ? import.meta.env.VITE_API_URL.replace(/\/$/, '') + '/api'
  : '/api'

const WS_BASE = import.meta.env.VITE_API_URL
  ? import.meta.env.VITE_API_URL.replace(/^http/, 'ws').replace(/\/$/, '')
  : (typeof window !== 'undefined'
      ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
      : 'ws://localhost:8000')

async function req(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res = await fetch(BASE + path, opts)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export const api = {
  // Health & config
  health:       ()      => req('GET',  '/health'),
  getConfig:    ()      => req('GET',  '/config'),
  checkApiKey:  ()      => req('GET',  '/config/apikey'),
  saveApiKey:   (key)   => req('POST', '/config/apikey', { api_key: key }),

  // Data / sessions
  uploadFile:   (file)  => {
    const fd = new FormData()
    fd.append('file', file)
    return fetch(BASE + '/data/upload', { method: 'POST', body: fd }).then(r => {
      if (!r.ok) return r.json().then(e => { throw new Error(e.detail) })
      return r.json()
    })
  },
  listSessions: ()                        => req('GET', '/data/sessions'),
  getStats:     (sid)                     => req('GET', `/data/stats?session_id=${sid}`),
  previewData:  (sid, limit = 5)          => req('GET', `/data/preview?session_id=${sid}&limit=${limit}`),
  downloadJson: (sid)                     => `${BASE}/data/download?session_id=${sid}`,
  validate:     (sid)                     => req('GET', `/validate?session_id=${sid}`),

  // Search & download
  search:   (config)  => req('POST', '/search',   config),
  download: (config)  => req('POST', '/download', config),
  getJob:   (jobId)   => req('GET',  `/jobs/${jobId}`),

  // Enrichment
  detectLanguages: (config) => req('POST', '/enrich/language',  config),
  runSentiment:    (config) => req('POST', '/enrich/sentiment', config),

  // Export
  exportData:          (config)   => req('POST', '/export', config),
  exportDownloadUrl:   (filename) => `${BASE}/export/download/${encodeURIComponent(filename)}`,

  // Filter
  filter: (config) => req('POST', '/filter', config),

  // TubeScope
  scopeSummary:  (sid) => req('GET', `/tubescope/summary?session_id=${sid}`),
  scopeActivity: (sid) => req('GET', `/tubescope/activity?session_id=${sid}`),
  scopeSentiment:(sid) => req('GET', `/tubescope/sentiment?session_id=${sid}`),
  scopeLikes:    (sid) => req('GET', `/tubescope/likes?session_id=${sid}`),
  scopeWeekdays: (sid) => req('GET', `/tubescope/weekdays?session_id=${sid}`),
  scopeViews:    (sid) => req('GET', `/tubescope/views?session_id=${sid}`),
  scopeUploads:  (sid) => req('GET', `/tubescope/uploads?session_id=${sid}`),
  scopeChannels: (sid) => req('GET', `/tubescope/channels?session_id=${sid}`),

  // TubeTalk
  talkLanguages:     (sid, level, topN) => req('GET', `/tubetalk/languages?session_id=${sid}&level=${level}&top_n=${topN}`),
  talkLangConflicts: (sid)              => req('GET', `/tubetalk/langconflicts?session_id=${sid}`),
  talkWordcloud:     (config)           => req('POST', '/tubetalk/wordcloud', config),
  talkTopics:        (config)           => req('POST', '/tubetalk/topics',    config),

  // TubeGraph
  graphNetwork: (sid, topN) =>
  req(
    'GET',
    `/tubegraph/network?session_id=${encodeURIComponent(sid)}&top_n=${topN}`
  ),

  graphReplyGraph: (sid) => req('GET', `/tubegraph/replygraph?session_id=${sid}`),
}

// WebSocket helper — works for both local and cloud
export function watchJob(jobId, onMessage) {
  const ws = new WebSocket(`${WS_BASE}/ws/jobs/${jobId}`)
  ws.onmessage = (e) => onMessage(JSON.parse(e.data))
  ws.onerror   = ()  => onMessage({ status: 'error', error: 'WebSocket connection failed' })
  return () => ws.close()
}
