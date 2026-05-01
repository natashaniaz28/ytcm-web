import { useState, useEffect } from 'react'
import { api } from '../api'
import { Card, SectionTitle, Btn, Select, Tag } from '../components/ui'
import { FileText, Download, CheckCircle2, Loader2, AlertTriangle } from 'lucide-react'

const FORMATS = [
  {
    key: 'csv',
    label: 'CSV',
    desc: 'Flat table with one row per comment/reply. Ideal for Excel, MAXQDA, SPSS.',
    ext: '.csv',
    color: 'text-teal-400',
  },
  {
    key: 'html',
    label: 'HTML Report',
    desc: 'Readable HTML page with collapsible video sections. Share with collaborators.',
    ext: '.html',
    color: 'text-acid-400',
  },
  {
    key: 'gephi',
    label: 'Gephi (GEXF)',
    desc: 'Network graph files for Gephi — one with replies, one without.',
    ext: '.gexf',
    color: 'text-coral-400',
  },
  {
    key: 'all',
    label: 'All formats',
    desc: 'Export CSV + HTML + both GEXF files at once.',
    ext: 'all',
    color: 'text-ink-300',
  },
]

export default function ExportPage() {
  const [sessions, setSessions] = useState([])
  const [session, setSession] = useState('')
  const [format, setFormat] = useState('all')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  // ✅ Load sessions
  useEffect(() => {
    api.listSessions()
      .then(r => {
        setSessions(r.sessions || [])
        if (r.sessions?.length > 0) {
          setSession(r.sessions[0].session_id)
        }
      })
      .catch(() => {})
  }, [])

  async function runExport() {
    if (!session) return

    // ✅ immediate feedback
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const r = await api.exportData({
        format,
        session_id: session
      })
      setResult(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Export your dataset to CSV, HTML, or Gephi network formats">
        Export Data
      </SectionTitle>

      <Card>
        <div className="space-y-5">

          {/* ✅ Session dropdown */}
          <Select
            label="Dataset"
            value={session}
            onChange={e => setSession(e.target.value)}
          >
            {sessions.map(s => (
              <option key={s.session_id} value={s.session_id}>
                {s.session_id} ({s.video_count} videos)
              </option>
            ))}
            {sessions.length === 0 && (
              <option value="">No sessions available</option>
            )}
          </Select>

          {/* Format cards */}
          <div>
            <label className="text-xs uppercase tracking-widest text-ink-500 font-body block mb-3">
              Export format
            </label>

            <div className="grid grid-cols-2 gap-3">
              {FORMATS.map(f => (
                <button
                  key={f.key}
                  onClick={() => setFormat(f.key)}
                  className={`text-left p-4 rounded-2xl border transition-all duration-200 ${
                    format === f.key
                      ? 'bg-acid-500/10 border-acid-500/30'
                      : 'bg-ink-800 border-ink-700 hover:border-ink-500'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <FileText size={14} className={format === f.key ? 'text-acid-400' : 'text-ink-500'} />
                    <span className={`text-sm font-body font-medium ${
                      format === f.key ? 'text-ink-100' : 'text-ink-300'
                    }`}>
                      {f.label}
                    </span>
                    <Tag color={format === f.key ? 'yellow' : 'default'}>
                      {f.ext}
                    </Tag>
                  </div>

                  <p className="text-xs text-ink-500 font-body leading-relaxed">
                    {f.desc}
                  </p>
                </button>
              ))}
            </div>
          </div>

          <Btn onClick={runExport} disabled={loading || !session} size="lg">
            {loading
              ? <Loader2 size={16} className="animate-spin" />
              : <Download size={16} />
            }
            {loading ? 'Exporting…' : 'Export'}
          </Btn>

          {error && (
            <div className="flex items-center gap-2 p-3 bg-coral-500/10 border border-coral-500/20 rounded-xl text-sm text-coral-400">
              <AlertTriangle size={14} />
              {error}
            </div>
          )}
        </div>
      </Card>

      {/* Results */}
      {result && result.files && (
        <Card>
          <div className="flex items-center gap-2 mb-5">
            <CheckCircle2 size={16} className="text-teal-500" />
            <p className="text-sm font-body text-teal-400">
              Export complete
            </p>
          </div>

          <div className="space-y-2">
            {Object.entries(result.files).map(([key, filename]) => (
              <div
                key={key}
                className="flex items-center justify-between py-3 px-4 bg-ink-800 rounded-xl border border-ink-700"
              >
                <div>
                  <p className="text-sm text-ink-200">{filename}</p>
                  <p className="text-xs text-ink-500 font-mono mt-0.5">
                    {key.replace(/_/g, ' ')}
                  </p>
                </div>

                <a
                   href={api.exportDownloadUrl(filename)}  // ← was: `/api/export/download/${encodeURIComponent(filename)}`
  download={filename}
  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-ink-700 hover:bg-ink-600 border border-ink-600 rounded-lg text-xs text-ink-200 font-mono"
>
  <Download size={11} />
  download
</a>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
