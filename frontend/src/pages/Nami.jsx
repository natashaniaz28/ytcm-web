import { useState } from 'react'
import { api, watchJob } from '../api'
import { Card, SectionTitle, Btn, Select, StatTile, PlotGallery, Empty, Tag } from '../components/ui'
import {
  Upload, Loader2, CheckCircle2, AlertTriangle,
  BarChart3, Network, FileText, Download,
} from 'lucide-react'

// Small table renderer for the JSON row-sets the NAMI endpoints return —
// NAMI's own report.html already handles charts; the live queries here are
// tabular, so a single generic table covers all of them.
function DataTable({ rows }) {
  if (!rows || rows.length === 0) return <Empty message="No rows returned." />
  const cols = Object.keys(rows[0]).filter(c => c !== 'hashtags')
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm font-mono">
        <thead>
          <tr className="border-b border-ink-700 text-ink-500 text-xs uppercase tracking-wider">
            {cols.map(c => <th key={c} className="text-left py-2 px-3 whitespace-nowrap">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 100).map((r, i) => (
            <tr key={i} className="border-b border-ink-800 text-ink-200">
              {cols.map(c => (
                <td key={c} className="py-1.5 px-3 whitespace-nowrap">
                  {typeof r[c] === 'number' ? r[c].toLocaleString() : String(r[c] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 100 && (
        <p className="text-xs text-ink-500 font-mono mt-2">Showing first 100 of {rows.length} rows.</p>
      )}
    </div>
  )
}

const SCOPE_QUERIES = [
  { key: 'timeline', label: 'Timeline', fn: sid => api.namiScopeTimeline(sid, 'songs', 'M') },
  { key: 'dist',     label: 'Plays distribution', fn: sid => api.namiScopeDist(sid, 'plays') },
  { key: 'topreels', label: 'Top reels', fn: sid => api.namiScopeTopreels(sid, 'plays', 20) },
  { key: 'impact',   label: 'Impact by song', fn: sid => api.namiScopeImpact(sid, 'song') },
]

const TALK_QUERIES = [
  { key: 'captionterms', label: 'Caption terms', fn: sid => api.namiTalkCaptionterms(sid, 30) },
  { key: 'hashtagterms', label: 'Hashtag terms', fn: sid => api.namiTalkHashtagterms(sid, 30) },
  { key: 'distinctive',  label: 'Distinctive hashtags by song', fn: sid => api.namiTalkDistinctiveterms(sid, 'song', 'hashtags', 20) },
]

const GRAPH_TYPES = [
  { key: 'hashtags',     label: 'Hashtag co-occurrence' },
  { key: 'creator_song', label: 'Creator ↔ Song' },
  { key: 'creator_asset',label: 'Creator ↔ Asset' },
  { key: 'song_hashtag', label: 'Song ↔ Hashtag' },
]

export default function NamiPage() {
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState(null)
  const [session, setSession] = useState(null)   // { session_id, songs, reels, tagged_pct }

  const [analyse, setAnalyse] = useState(null)         // { dimensions, classifiability, distributions, ... }
  const [analyseLoading, setAnalyseLoading] = useState(false)
  const [analyseError, setAnalyseError] = useState(null)
  const [analyseDim, setAnalyseDim] = useState(null)

  const [queryData, setQueryData] = useState({})   // key -> { loading, rows, error }
  const [activeQuery, setActiveQuery] = useState(null)

  const [graphType, setGraphType] = useState('hashtags')
  const [graphData, setGraphData] = useState(null)
  const [graphLoading, setGraphLoading] = useState(false)
  const [graphError, setGraphError] = useState(null)

  const [reportJob, setReportJob] = useState(null)
  const [reportRunning, setReportRunning] = useState(false)

  async function handleUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadMsg(null)
    try {
      const r = await api.namiUpload(file)
      setSession(r)
      setUploadMsg({ ok: true, text: r.message })
      loadAnalyse(r.session_id)
    } catch (err) {
      setUploadMsg({ ok: false, text: err.message })
    } finally {
      setUploading(false)
    }
  }

  async function loadAnalyse(sessionId) {
    setAnalyseLoading(true)
    setAnalyseError(null)
    try {
      const r = await api.namiAnalyse(sessionId)
      setAnalyse(r)
      setAnalyseDim(r.dimensions?.[0] || null)
    } catch (e) {
      setAnalyseError(e.message)
    } finally {
      setAnalyseLoading(false)
    }
  }

  async function runQuery(q) {
    if (!session) return
    setActiveQuery(q.key)
    setQueryData(p => ({ ...p, [q.key]: { loading: true, rows: null, error: null } }))
    try {
      const res = await q.fn(session.session_id)
      setQueryData(p => ({ ...p, [q.key]: { loading: false, rows: res.rows, error: null } }))
    } catch (e) {
      setQueryData(p => ({ ...p, [q.key]: { loading: false, rows: null, error: e.message } }))
    }
  }

  async function runGraph() {
    if (!session) return
    setGraphLoading(true)
    setGraphError(null)
    setGraphData(null)
    try {
      const res = await api.namiGraph(session.session_id, graphType, 1, 30)
      setGraphData(res)
    } catch (e) {
      setGraphError(e.message)
    } finally {
      setGraphLoading(false)
    }
  }

  async function buildReport() {
    if (!session || reportRunning) return
    setReportRunning(true)
    setReportJob(null)
    try {
      const { job_id } = await api.namiBuildReport(session.session_id)
      const stop = watchJob(job_id, (msg) => {
        setReportJob(msg)
        if (msg.status === 'done' || msg.status === 'error') {
          setReportRunning(false)
          stop()
        }
      }, '/api/nami/ws/report')
    } catch (e) {
      setReportJob({ status: 'error', error: e.message })
      setReportRunning(false)
    }
  }

  const activeData = activeQuery ? queryData[activeQuery] : null

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Read-only dashboards over a NAMI corpus.db snapshot — crawling and vision-tagging happen offline.">
        NAMI — Reels Analysis
      </SectionTitle>

      {/* Upload */}
      <Card>
        <p className="text-xs uppercase tracking-widest text-ink-500 font-body mb-4">Load a corpus</p>
        <label className="cursor-pointer block">
          <div className="flex items-center gap-3 px-4 py-3 bg-ink-800 border border-dashed border-ink-600 hover:border-acid-500/40 rounded-xl transition-colors">
            {uploading ? <Loader2 size={16} className="animate-spin text-acid-500" /> : <Upload size={16} className="text-ink-400" />}
            <span className="text-sm text-ink-400 font-body">
              {uploading ? 'Uploading…' : 'Click to upload corpus.db'}
            </span>
          </div>
          <input type="file" accept=".db,.sqlite,.sqlite3" onChange={handleUpload} className="hidden" disabled={uploading} />
        </label>

        {uploadMsg && (
          <p className={`text-xs font-mono mt-3 ${uploadMsg.ok ? 'text-teal-400' : 'text-coral-400'}`}>
            {uploadMsg.ok ? <CheckCircle2 size={12} className="inline mr-1" /> : <AlertTriangle size={12} className="inline mr-1" />}
            {uploadMsg.text}
          </p>
        )}

        {session && (
          <div className="grid grid-cols-3 gap-3 mt-5">
            <StatTile label="Songs" value={session.songs} accent="text-acid-400" />
            <StatTile label="Reels" value={session.reels?.toLocaleString()} />
            <StatTile label="Vision-tagged" value={`${session.tagged_pct}%`} />
          </div>
        )}
      </Card>

      {session && (
        <>
          {/* Classifiability & category distributions */}
          <Card>
            <p className="text-xs uppercase tracking-widest text-ink-500 font-body mb-4">Classifiability &amp; distributions</p>

            {analyseLoading && (
              <div className="flex items-center justify-center h-32 border border-ink-700 rounded-2xl">
                <Loader2 size={20} className="animate-spin text-acid-500" />
              </div>
            )}

            {analyseError && (
              <div className="flex items-center gap-3 p-4 bg-coral-500/10 border border-coral-500/20 rounded-2xl text-coral-400 text-sm">
                <AlertTriangle size={16} />{analyseError}
                <Btn size="sm" variant="ghost" onClick={() => loadAnalyse(session.session_id)}>Retry</Btn>
              </div>
            )}

            {analyse && !analyseLoading && (
              <div className="space-y-4">
                <div className="flex gap-3">
                  {analyse.classifiability.map(c => (
                    <StatTile
                      key={c.dimension}
                      label={`${c.dimension} classifiable`}
                      value={`${Math.round(c.rate * 100)}%`}
                      sub={`${c.n_classifiable.toLocaleString()} / ${c.n_total.toLocaleString()} reels`}
                      accent={c.rate > 0.5 ? 'text-teal-400' : 'text-acid-400'}
                    />
                  ))}
                </div>

                <div className="flex gap-2">
                  {analyse.dimensions.map(d => (
                    <button
                      key={d}
                      onClick={() => setAnalyseDim(d)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-mono border transition-all ${
                        analyseDim === d
                          ? 'bg-acid-500/20 text-acid-400 border-acid-500/40'
                          : 'bg-ink-800 text-ink-400 border-ink-600 hover:border-ink-500'
                      }`}
                    >
                      {d}
                    </button>
                  ))}
                </div>

                {analyseDim && <DataTable rows={analyse.distributions[analyseDim]} />}
              </div>
            )}
          </Card>

          {/* Scope / Talk queries */}
          <Card>
            <p className="text-xs uppercase tracking-widest text-ink-500 font-body mb-4">Scope &amp; talk</p>
            <div className="grid grid-cols-4 gap-3 mb-4">
              {[...SCOPE_QUERIES, ...TALK_QUERIES].map(q => {
                const state = queryData[q.key]
                return (
                  <button
                    key={q.key}
                    onClick={() => runQuery(q)}
                    className={`group p-4 rounded-2xl border text-left transition-all duration-200 ${
                      activeQuery === q.key
                        ? 'bg-acid-500/10 border-acid-500/30 text-acid-400'
                        : 'bg-ink-900 border-ink-700 text-ink-400 hover:border-ink-500 hover:text-ink-200'
                    }`}
                  >
                    <BarChart3 size={16} className="mb-2" />
                    <p className="text-sm font-body font-medium">{q.label}</p>
                    {state?.loading && <p className="text-xs mt-1 text-ink-500 font-mono">loading…</p>}
                    {state?.rows && !state.loading && <p className="text-xs mt-1 text-teal-500 font-mono">✓ ready</p>}
                    {state?.error && <p className="text-xs mt-1 text-coral-400 font-mono truncate">{state.error}</p>}
                  </button>
                )
              })}
            </div>

            {activeQuery && (
              activeData?.loading ? (
                <div className="flex items-center justify-center h-32 border border-ink-700 rounded-2xl">
                  <Loader2 size={20} className="animate-spin text-acid-500" />
                </div>
              ) : activeData?.error ? (
                <div className="flex items-center gap-3 p-4 bg-coral-500/10 border border-coral-500/20 rounded-2xl text-coral-400 text-sm">
                  <AlertTriangle size={16} />{activeData.error}
                </div>
              ) : (
                <DataTable rows={activeData?.rows} />
              )
            )}
          </Card>

          {/* Graphs */}
          <Card>
            <p className="text-xs uppercase tracking-widest text-ink-500 font-body mb-4">Networks</p>
            <div className="flex items-end gap-4 mb-4">
              <div className="w-64">
                <Select label="Graph type" value={graphType} onChange={e => setGraphType(e.target.value)}>
                  {GRAPH_TYPES.map(g => <option key={g.key} value={g.key}>{g.label}</option>)}
                </Select>
              </div>
              <Btn onClick={runGraph} disabled={graphLoading}>
                {graphLoading ? <><Loader2 size={16} className="animate-spin" />Building…</> : <><Network size={16} />Build graph</>}
              </Btn>
            </div>

            {graphError && (
              <div className="flex items-center gap-3 p-4 bg-coral-500/10 border border-coral-500/20 rounded-2xl text-coral-400 text-sm mb-4">
                <AlertTriangle size={16} />{graphError}
              </div>
            )}

            {graphData && (
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <Tag>{graphData.n_nodes.toLocaleString()} nodes</Tag>
                  <Tag>{graphData.n_edges.toLocaleString()} edges</Tag>
                  {!graphData.gexf_available && <Tag color="yellow">networkx unavailable — no GEXF</Tag>}
                </div>

                {graphData.chart && <PlotGallery images={[graphData.chart]} />}

                <div className="flex gap-2 flex-wrap">
                  <a href={api.namiGraphDownloadUrl(session.session_id, graphType, 'edges.csv')} download
                     className="inline-flex items-center gap-2 px-4 py-2 text-xs font-mono rounded-lg bg-ink-800 text-ink-300 border border-ink-600 hover:border-ink-500">
                    <Download size={12} />edges.csv
                  </a>
                  <a href={api.namiGraphDownloadUrl(session.session_id, graphType, 'nodes.csv')} download
                     className="inline-flex items-center gap-2 px-4 py-2 text-xs font-mono rounded-lg bg-ink-800 text-ink-300 border border-ink-600 hover:border-ink-500">
                    <Download size={12} />nodes.csv
                  </a>
                  {graphData.gexf_available && (
                    <a href={api.namiGraphDownloadUrl(session.session_id, graphType, 'gexf')} download
                       className="inline-flex items-center gap-2 px-4 py-2 text-xs font-mono rounded-lg bg-ink-800 text-ink-300 border border-ink-600 hover:border-ink-500">
                      <Download size={12} />.gexf (Gephi)
                    </a>
                  )}
                </div>
              </div>
            )}
          </Card>

          {/* Full report */}
          <Card>
            <p className="text-xs uppercase tracking-widest text-ink-500 font-body mb-4">Full report</p>
            <div className="flex items-start gap-3">
              <Btn onClick={buildReport} disabled={reportRunning} size="lg">
                {reportRunning
                  ? <><Loader2 size={16} className="animate-spin" />Building…</>
                  : <><FileText size={16} />Build full report</>}
              </Btn>
              <p className="text-xs font-mono text-ink-500 mt-3 leading-relaxed">
                Runs NAMI's full report pipeline (classifiability, distributions,<br />
                song profiles, hashtag network, robustness checks…).
              </p>
            </div>

            {reportJob?.status === 'error' && (
              <div className="mt-4 flex items-center gap-2 p-3 bg-coral-500/10 border border-coral-500/20 rounded-xl text-coral-400 text-sm font-mono">
                <AlertTriangle size={14} />{reportJob.error}
              </div>
            )}

            {reportJob?.status === 'done' && (
              <div className="mt-4 flex items-center justify-between gap-4 p-4 bg-teal-500/5 border border-teal-500/20 rounded-xl">
                <div className="flex items-center gap-3">
                  <CheckCircle2 size={18} className="text-teal-400" />
                  <p className="text-sm font-body text-ink-100">Report ready</p>
                </div>
                <a
                  href={api.namiReportFileUrl(session.session_id)}
                  target="_blank" rel="noreferrer"
                  className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-body font-medium rounded-xl bg-teal-500/20 text-teal-400 hover:bg-teal-500/30 border border-teal-500/30 transition-all"
                >
                  <Download size={16} />Open report
                </a>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
