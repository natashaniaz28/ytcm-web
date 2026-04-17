import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Card, SectionTitle, StatTile, Tag, Btn } from '../components/ui'
import { Search, BarChart3, Languages, Network, ArrowRight, AlertTriangle, Upload, CheckCircle2, Loader2 } from 'lucide-react'

const QUICK_LINKS = [
  { to: '/search',    icon: Search,    label: 'Search Videos',   desc: 'Find YouTube videos by keyword' },
  { to: '/tubescope', icon: BarChart3, label: 'TubeScope',       desc: 'Statistical analysis & charts' },
  { to: '/tubetalk',  icon: Languages, label: 'TubeTalk',        desc: 'NLP, word clouds, topics' },
  { to: '/tubegraph', icon: Network,   label: 'TubeGraph',       desc: 'Network & channel analysis' },
]

export default function Dashboard() {
  const [sessions, setSessions]   = useState([])
  const [selected, setSelected]   = useState(null)
  const [stats, setStats]         = useState(null)
  const [preview, setPreview]     = useState(null)
  const [loading, setLoading]     = useState(false)
  const [apiOk, setApiOk]         = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState(null)

  useEffect(() => {
    api.checkApiKey().then(r => setApiOk(r.exists)).catch(() => setApiOk(false))
    loadSessions()
  }, [])

  async function loadSessions() {
    try {
      const r = await api.listSessions()
      setSessions(r.sessions || [])
      if (r.sessions?.length > 0 && !selected) {
        selectSession(r.sessions[0].session_id)
      }
    } catch (_) {}
  }

  async function selectSession(sid) {
    setSelected(sid)
    setLoading(true)
    try {
      const [s, p] = await Promise.all([
        api.getStats(sid).catch(() => null),
        api.previewData(sid, 5).catch(() => null),
      ])
      setStats(s)
      setPreview(p)
    } finally {
      setLoading(false)
    }
  }

  async function handleUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadMsg(null)
    try {
      const r = await api.uploadFile(file)
      setUploadMsg({ ok: true, text: `Loaded ${r.total_videos} videos (session: ${r.session_id})` })
      await loadSessions()
      selectSession(r.session_id)
    } catch (err) {
      setUploadMsg({ ok: false, text: err.message })
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="space-y-8 animate-fade-up">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-3xl bg-ink-900 border border-ink-700 p-8">
        <div className="orb w-64 h-64 bg-acid-500/8 top-[-4rem] right-[-4rem]" />
        <div className="relative z-10">
          <p className="text-xs font-mono text-acid-500 uppercase tracking-widest mb-2">Research Tool</p>
          <h1 className="font-display text-4xl text-ink-50 leading-tight">
            YouTube Comment<br /><span className="italic text-acid-400">Miner</span>
          </h1>
          <p className="text-ink-400 text-sm font-body mt-3 max-w-md">
            Search, download, enrich and analyse YouTube comment sections for academic research.
          </p>
        </div>
      </div>

      {/* API key warning */}
      {apiOk === false && (
        <div className="flex items-center gap-3 p-4 bg-coral-500/10 border border-coral-500/20 rounded-2xl">
          <AlertTriangle size={16} className="text-coral-400 flex-shrink-0" />
          <p className="text-sm text-coral-300 font-body">
            No YouTube API key found. <Link to="/settings" className="underline text-coral-400">Configure it in Settings →</Link>
          </p>
        </div>
      )}

      {/* Upload existing JSON */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Upload size={16} className="text-acid-400" />
          <h3 className="text-sm font-body font-medium text-ink-200">Load a Comments.json file</h3>
        </div>
        <p className="text-xs text-ink-500 font-body mb-4">
          Already have a dataset from YTCM? Upload it here to analyse it without re-downloading.
        </p>
        <label className="cursor-pointer">
          <div className="flex items-center gap-3 px-4 py-3 bg-ink-800 border border-dashed border-ink-600 hover:border-acid-500/40 rounded-xl transition-colors">
            {uploading
              ? <Loader2 size={16} className="animate-spin text-acid-400" />
              : <Upload size={16} className="text-ink-500" />
            }
            <span className="text-sm text-ink-400 font-body">
              {uploading ? 'Uploading…' : 'Click to upload Comments.json'}
            </span>
          </div>
          <input type="file" accept=".json" onChange={handleUpload} className="hidden" />
        </label>
        {uploadMsg && (
          <div className={`mt-3 flex items-center gap-2 text-sm font-body ${uploadMsg.ok ? 'text-teal-400' : 'text-coral-400'}`}>
            {uploadMsg.ok ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            {uploadMsg.text}
          </div>
        )}
      </Card>

      {/* Quick links */}
      <div>
        <SectionTitle sub="Jump straight to a tool">Quick Access</SectionTitle>
        <div className="grid grid-cols-2 gap-3">
          {QUICK_LINKS.map(({ to, icon: Icon, label, desc }) => (
            <Link key={to} to={to}
              className="group bg-ink-900 border border-ink-700 hover:border-ink-500 rounded-2xl p-4 transition-all duration-200 flex items-start gap-3">
              <div className="w-9 h-9 bg-ink-800 group-hover:bg-acid-500/15 rounded-xl flex items-center justify-center flex-shrink-0 transition-colors">
                <Icon size={16} className="text-ink-400 group-hover:text-acid-400 transition-colors" />
              </div>
              <div>
                <p className="text-sm font-body font-medium text-ink-200 group-hover:text-ink-50">{label}</p>
                <p className="text-xs text-ink-500 mt-0.5">{desc}</p>
              </div>
              <ArrowRight size={14} className="ml-auto text-ink-600 group-hover:text-ink-400 mt-1 transition-colors" />
            </Link>
          ))}
        </div>
      </div>

      {/* Sessions + stats */}
      {sessions.length > 0 && (
        <div>
          <SectionTitle sub="Active data sessions">Loaded Datasets</SectionTitle>
          <div className="flex gap-2 flex-wrap mb-5">
            {sessions.map(s => (
              <button key={s.session_id} onClick={() => selectSession(s.session_id)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono transition-all border ${
                  selected === s.session_id
                    ? 'bg-acid-500/20 text-acid-400 border-acid-500/40'
                    : 'bg-ink-800 text-ink-400 border-ink-600 hover:border-ink-500'
                }`}>
                {s.session_id}
                {s.videos && <span className="text-ink-500">· {s.videos} videos</span>}
              </button>
            ))}
          </div>

          {selected && !loading && stats && (
            <div className="space-y-4">
              <div className="grid grid-cols-4 gap-3">
                <StatTile label="Videos"   value={stats.counts?.total_videos?.toLocaleString()} />
                <StatTile label="Comments" value={stats.counts?.total_comments?.toLocaleString()} accent="text-acid-400" />
                <StatTile label="Replies"  value={stats.counts?.total_replies?.toLocaleString()} />
                <StatTile label="Avg comments/video"
                  value={stats.counts?.comments_per_video_mean?.toFixed(1)}
                  sub={`median ${stats.counts?.comments_per_video_median?.toFixed(0)}`} />
              </div>

              {stats.languages?.comment && (
                <Card>
                  <p className="text-xs uppercase tracking-widest text-ink-500 mb-3 font-body">Top comment languages</p>
                  <div className="flex gap-2 flex-wrap">
                    {Object.entries(stats.languages.comment).slice(0, 10).map(([lang, count]) => (
                      <Tag key={lang}>{lang} · {count.toLocaleString()}</Tag>
                    ))}
                  </div>
                </Card>
              )}

              {preview?.videos?.length > 0 && (
                <Card>
                  <p className="text-xs uppercase tracking-widest text-ink-500 mb-3 font-body">Recent videos</p>
                  <div className="space-y-2">
                    {preview.videos.map(v => (
                      <div key={v.video_id} className="flex items-center gap-3 py-2 border-b border-ink-800 last:border-0">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-ink-200 truncate font-body">{v.title || v.video_id}</p>
                          <p className="text-xs text-ink-500 font-mono mt-0.5">{v.channel} · {v.published_at?.slice(0,10)}</p>
                        </div>
                        <div className="text-right flex-shrink-0">
                          <p className="text-xs font-mono text-acid-400">{v.comment_count} comments</p>
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* Download enriched data */}
                  <div className="mt-4 pt-4 border-t border-ink-800">
                    <a href={api.downloadJson(selected)} download={`Comments_${selected}.json`}
                      className="text-xs text-acid-400 underline font-mono">
                      ↓ Download this dataset as JSON
                    </a>
                  </div>
                </Card>
              )}
            </div>
          )}
          {loading && <div className="h-32 flex items-center justify-center text-ink-500 text-sm font-body">Loading…</div>}
        </div>
      )}

      {sessions.length === 0 && (
        <Card>
          <div className="flex flex-col items-center py-8 gap-4 text-center">
            <Search size={32} className="text-ink-600" />
            <div>
              <p className="text-ink-300 font-body">No data loaded yet.</p>
              <p className="text-ink-500 text-sm mt-1">Upload a Comments.json above, or use Search → Download to collect data.</p>
            </div>
            <Link to="/search"><Btn>Start searching →</Btn></Link>
          </div>
        </Card>
      )}
    </div>
  )
}