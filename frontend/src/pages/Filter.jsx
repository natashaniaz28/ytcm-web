import { useState, useEffect } from 'react'
import { api } from '../api'
import { Card, SectionTitle, Btn, Select, Input, Tag } from '../components/ui'
import { Filter, Search } from 'lucide-react'

export default function FilterPage() {
  const [sessions, setSessions] = useState([])
  const [session, setSession] = useState('')
  const [terms, setTerms] = useState('')
  const [mode, setMode] = useState('and')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.listSessions()
      .then(r => {
        setSessions(r.sessions || [])
        if (r.sessions?.length > 0) {
          setSession(r.sessions[0].session_id) // set default
        }
      })
      .catch(() => {})
  }, [])

  async function runFilter() {
    const termList = terms.split(',').map(t => t.trim()).filter(Boolean)
    if (!termList.length || !session) return

    // ✅ immediate feedback
    setLoading(true)
    setError(null)
    setResults(null)

    try {
      const r = await api.filter({ terms: termList, mode, session_id: session })
      setResults(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Search within your downloaded dataset by keyword">
        Filter Comments
      </SectionTitle>

      <Card>
        <div className="space-y-5">

          {/* ✅ Updated Session Dropdown */}
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

          <Input
            label="Search terms (comma-separated)"
            value={terms}
            onChange={e => setTerms(e.target.value)}
            placeholder="eternity, paradise, soundtrack…"
          />

          <div className="flex gap-3 items-center">
            <label className="text-xs uppercase tracking-widest text-ink-500 font-body">
              Match mode:
            </label>

            {['and', 'or'].map(m => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-4 py-1.5 rounded-lg text-sm font-mono transition-all ${
                  mode === m
                    ? 'bg-acid-500/20 text-acid-400 border border-acid-500/30'
                    : 'bg-ink-800 text-ink-400 border border-ink-600 hover:border-ink-500'
                }`}
              >
                {m.toUpperCase()}
              </button>
            ))}

            <span className="text-xs text-ink-600 font-body">
              {mode === 'and'
                ? 'All terms must appear'
                : 'Any term must appear'}
            </span>
          </div>

          <Btn onClick={runFilter} disabled={loading || !terms.trim() || !session}>
            <Search size={14} />
            {loading ? 'Filtering…' : 'Run Filter'}
          </Btn>

          {error && (
            <p className="text-sm text-coral-400 font-mono">{error}</p>
          )}
        </div>
      </Card>

      {/* Results */}
      {results && (
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <Filter size={16} className="text-acid-400" />
            <p className="text-sm font-body text-ink-300">
              <span className="text-acid-400 font-mono text-base">
                {results.matched_videos}
              </span>{' '}
              video{results.matched_videos !== 1 ? 's' : ''} matched
            </p>
          </div>

          {results.videos.length > 0 ? (
            <div className="space-y-2">
              {results.videos.map(v => (
                <div
                  key={v.video_id}
                  className="flex items-center justify-between py-2.5 px-3 bg-ink-800 rounded-xl border border-ink-700"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink-200 font-body truncate">
                      {v.title || v.video_id}
                    </p>
                    <p className="text-xs text-ink-500 font-mono mt-0.5">
                      {v.video_id}
                    </p>
                  </div>
                  <Tag color="yellow">{v.comment_count} comments</Tag>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-ink-500 font-body text-center py-6">
              No matches found.
            </p>
          )}
        </Card>
      )}
    </div>
  )
}
