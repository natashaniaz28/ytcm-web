import { useState, useEffect } from 'react'
import { api } from '../api'
import { Card, SectionTitle, Btn, Select, StatTile, PlotGallery } from '../components/ui'
import { BarChart3, TrendingUp, Heart, Calendar, Eye, Upload, Users } from 'lucide-react'

const ANALYSES = [
  { key: 'activity',  label: 'Comment Activity',     icon: TrendingUp, fn: f => api.scopeActivity(f)  },
  { key: 'sentiment', label: 'Sentiment',             icon: Heart,      fn: f => api.scopeSentiment(f) },
  { key: 'likes',     label: 'Likes Distribution',   icon: BarChart3,  fn: f => api.scopeLikes(f)     },
  { key: 'weekdays',  label: 'Weekday Patterns',     icon: Calendar,   fn: f => api.scopeWeekdays(f)  },
  { key: 'views',     label: 'Views vs Comments',    icon: Eye,        fn: f => api.scopeViews(f)     },
  { key: 'uploads',   label: 'Uploads Over Time',    icon: Upload,     fn: f => api.scopeUploads(f)   },
  { key: 'channels',  label: 'Channel Participation',icon: Users,      fn: f => api.scopeChannels(f)  },
]

export default function TubeScopePage() {
  const [files, setFiles] = useState([])
  const [session, setSession] = useState('Comments.json')
  const [summary, setSummary] = useState(null)
  const [active, setActive] = useState(null)
  const [plotData, setPlotData] = useState({}) // key → { images, loading, error }

  useEffect(() => {
    api.listFiles().then(r => setFiles(r.files)).catch(() => {})
  }, [])

  useEffect(() => {
    if (file) {
      api.scopeSummary(session).then(setSummary).catch(() => setSummary(null))
    }
  }, [file])

  async function runAnalysis(a) {
    setActive(a.key)
    setPlotData(p => ({ ...p, [a.key]: { loading: true, images: null, error: null } }))
    try {
      const res = await a.fn(file)
      setPlotData(p => ({
        ...p,
        [a.key]: { loading: false, images: res.images, error: null, extra: res }
      }))
    } catch (e) {
      setPlotData(p => ({ ...p, [a.key]: { loading: false, images: null, error: e.message } }))
    }
  }

  const current = active ? plotData[active] : null

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Statistical charts and distributions across your dataset">
        TubeScope
      </SectionTitle>

      {/* Controls */}
      <div className="flex items-end gap-4">
        <div className="w-64">
          <Select label="Dataset" value={session} onChange={e => setSession(e.target.value)}>
            {files.map(f => <option key={f.name}>{f.name}</option>)}
            {files.length === 0 && <option>Comments.json</option>}
          </Select>
        </div>
      </div>

      {/* Summary stats */}
      {summary && (
        <div className="grid grid-cols-4 gap-3">
          <StatTile label="Videos" value={summary.total_videos?.toLocaleString()} />
          <StatTile label="Comments" value={summary.total_comments?.toLocaleString()} accent="text-acid-400" />
          <StatTile
            label="Avg Sentiment"
            value={summary.average_sentiment != null ? summary.average_sentiment.toFixed(3) : '—'}
            sub="VADER score"
            accent={summary.average_sentiment > 0 ? 'text-teal-400' : 'text-coral-400'}
          />
          <StatTile
            label="With Replies"
            value={summary.reply_percentage != null ? `${summary.reply_percentage.toFixed(1)}%` : '—'}
            sub="of comments"
          />
        </div>
      )}

      {/* Analysis buttons */}
      <div className="grid grid-cols-4 gap-3">
        {ANALYSES.map(a => {
          const state = plotData[a.key]
          return (
            <button
              key={a.key}
              onClick={() => runAnalysis(a)}
              className={`group p-4 rounded-2xl border text-left transition-all duration-200 ${
                active === a.key
                  ? 'bg-acid-500/10 border-acid-500/30 text-acid-400'
                  : 'bg-ink-900 border-ink-700 text-ink-400 hover:border-ink-500 hover:text-ink-200'
              }`}
            >
              <a.icon size={18} className="mb-2" />
              <p className="text-sm font-body font-medium">{a.label}</p>
              {state?.loading && <p className="text-xs mt-1 text-ink-500 font-mono">generating…</p>}
              {state?.images && !state.loading && <p className="text-xs mt-1 text-teal-500 font-mono">✓ ready</p>}
              {state?.error && <p className="text-xs mt-1 text-coral-400 font-mono truncate">{state.error}</p>}
            </button>
          )
        })}
      </div>

      {/* Plot output */}
      {active && (
        <Card>
          <p className="text-xs uppercase tracking-widest text-ink-500 font-body mb-4">
            {ANALYSES.find(a => a.key === active)?.label}
          </p>

          {/* Extra numeric data */}
          {current?.extra?.average_sentiment != null && (
            <div className="mb-4 flex gap-3">
              <StatTile label="Average Sentiment" value={current.extra.average_sentiment?.toFixed(3)} />
            </div>
          )}

          <PlotGallery
            images={current?.images}
            loading={current?.loading}
            error={current?.error}
          />
        </Card>
      )}
    </div>
  )
}
