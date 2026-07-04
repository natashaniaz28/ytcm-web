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
  graphChannelStats: (sid, topN) =>
  req('GET', `/tubegraph/channelstats?session_id=${encodeURIComponent(sid)}&top_n=${topN}`),
  graphNetwork: (sid, topN) =>
  req(
    'GET',
    `/tubegraph/network?session_id=${encodeURIComponent(sid)}&top_n=${topN}`
  ),

  graphReplyGraph: (sid) => req('GET', `/tubegraph/replygraph?session_id=${encodeURIComponent(sid)}`),

  // Quick Report
  quickReport:            (config)   => req('POST', '/quickreport', config),
  quickReportDownloadUrl: (filename) => `${BASE}/quickreport/download/${encodeURIComponent(filename)}`,

  // NAMI (Instagram Reels analysis) — read-only dashboards over an uploaded corpus.db
  namiUpload: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return fetch(BASE + '/nami/upload', { method: 'POST', body: fd }).then(r => {
      if (!r.ok) return r.json().then(e => { throw new Error(e.detail) })
      return r.json()
    })
  },
  namiStatus:  (sid) => req('GET', `/nami/status?session_id=${encodeURIComponent(sid)}`),
  namiAnalyse: (sid) => req('GET', `/nami/analyse?session_id=${encodeURIComponent(sid)}`),

  namiScopeTimeline: (sid, entity = 'songs', freq = 'M') =>
    req('GET', `/nami/scope/timeline?session_id=${encodeURIComponent(sid)}&entity=${entity}&freq=${freq}`),
  namiScopeDist: (sid, field = 'plays') =>
    req('GET', `/nami/scope/dist?session_id=${encodeURIComponent(sid)}&field=${field}`),
  namiScopeTopreels: (sid, field = 'plays', n = 20) =>
    req('GET', `/nami/scope/topreels?session_id=${encodeURIComponent(sid)}&field=${field}&n=${n}`),
  namiScopeImpact: (sid, by = 'song') =>
    req('GET', `/nami/scope/impact?session_id=${encodeURIComponent(sid)}&by=${by}`),

  namiTalkCaptionterms: (sid, top = 50) =>
    req('GET', `/nami/talk/captionterms?session_id=${encodeURIComponent(sid)}&top=${top}`),
  namiTalkHashtagterms: (sid, top = 50) =>
    req('GET', `/nami/talk/hashtagterms?session_id=${encodeURIComponent(sid)}&top=${top}`),
  namiTalkDistinctiveterms: (sid, by = 'song', source = 'hashtags', top = 30) =>
    req('GET', `/nami/talk/distinctiveterms?session_id=${encodeURIComponent(sid)}&by=${by}&source=${source}&top=${top}`),

  namiGraph: (sid, type, minWeight = 1, top = 40) =>
    req('GET', `/nami/graphs/${type}?session_id=${encodeURIComponent(sid)}&min_weight=${minWeight}&top=${top}`),
  namiGraphDownloadUrl: (sid, type, fmt) =>
    `${BASE}/nami/graphs/${type}/download/${fmt}?session_id=${encodeURIComponent(sid)}`,

  namiBuildReport: (sid) => req('POST', `/nami/report?session_id=${encodeURIComponent(sid)}`),
  namiReportFileUrl: (sid) => `${BASE}/nami/report/file?session_id=${encodeURIComponent(sid)}`,
}

// WebSocket helper — works for both local and cloud.
// `base` lets callers point at a different job namespace (e.g. NAMI's report jobs).
export function watchJob(jobId, onMessage, base = '/ws/jobs') {
  const ws = new WebSocket(`${WS_BASE}${base}/${jobId}`)
  ws.onmessage = (e) => onMessage(JSON.parse(e.data))
  ws.onerror   = ()  => onMessage({ status: 'error', error: 'WebSocket connection failed' })
  return () => ws.close()
}
