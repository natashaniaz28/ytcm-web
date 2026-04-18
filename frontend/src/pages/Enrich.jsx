import { useState, useEffect } from 'react'
import { api } from '../api'
import { useJob } from '../hooks/useJob'
import { Card, SectionTitle, Btn, Select, JobProgress } from '../components/ui'
import { Languages, Heart, Loader2, CheckCircle2 } from 'lucide-react'

export default function EnrichPage() {
  const [sessions, setSessions] = useState([])
  const [session, setSession]   = useState('default')
  const [forceRebuild, setForceRebuild] = useState(false)
  const [langStarting, setLangStarting] = useState(false)
  const [sentStarting, setSentStarting] = useState(false)

  const langJob = useJob()
  const sentJob = useJob()

  useEffect(() => {
    api.listSessions()
      .then(r => {
        const s = r.sessions || []
        setSessions(s)
        if (s.length > 0) setSession(s[0].session_id)
      })
      .catch(() => {})
  }, [])

  async function runLanguage() {
    setLangStarting(true)
    try {
      const res = await api.detectLanguages({ session_id: session, force_rebuild: forceRebuild })
      setLangStarting(false)
      langJob.startWatching(res.job_id)
    } catch (e) {
      console.error(e)
      setLangStarting(false)
    }
  }

  async function runSentiment() {
    setSentStarting(true)
    try {
      const res = await api.runSentiment({ session_id: session, force_rebuild: forceRebuild })
      setSentStarting(false)
      sentJob.startWatching(res.job_id)
    } catch (e) {
      console.error(e)
      setSentStarting(false)
    }
  }

  const langBusy = langStarting || langJob.isRunning
  const sentBusy = sentStarting || sentJob.isRunning

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Add language detection and sentiment scores to your data">
        Enrich Data
      </SectionTitle>

      {/* Session selector */}
      <Card>
        <div className="grid grid-cols-2 gap-4">
          <Select
            label="Session"
            value={session}
            onChange={e => setSession(e.target.value)}
          >
            {sessions.length > 0
              ? sessions.map(s => (
                  <option key={s.session_id} value={s.session_id}>
                    {s.session_id}{s.videos ? ` (${s.videos} videos)` : ''}
                  </option>
                ))
              : <option value="default">default</option>
            }
          </Select>
          <div className="flex flex-col gap-1.5 justify-end">
            <label className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={forceRebuild}
                onChange={e => setForceRebuild(e.target.checked)}
                className="accent-acid-500 w-4 h-4"
              />
              <span className="text-sm text-ink-300 font-body">
                Force rebuild (re-run on already-processed data)
              </span>
            </label>
          </div>
        </div>

        {sessions.length === 0 && (
          <p className="text-xs text-ink-500 font-body mt-3">
            No sessions found. Upload a Comments.json on the{' '}
            <a href="/" className="text-acid-400 underline">Dashboard</a>
            {' '}or complete a Download first.
          </p>
        )}
      </Card>

      {/* Language detection */}
      <Card>
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 bg-ink-800 rounded-xl flex items-center justify-center flex-shrink-0">
            <Languages size={18} className="text-acid-400" />
          </div>
          <div className="flex-1">
            <h3 className="font-body font-medium text-ink-100 mb-1">Language Detection</h3>
            <p className="text-sm text-ink-500 mb-4">
              Detects the language of each comment and reply using{' '}
              <code className="font-mono text-xs bg-ink-800 px-1.5 py-0.5 rounded">langdetect</code>.
              Required before running sentiment analysis.
            </p>
            <Btn onClick={runLanguage} disabled={langBusy}>
              {langBusy
                ? <Loader2 size={14} className="animate-spin" />
                : <Languages size={14} />
              }
              {langStarting   ? 'Connecting…'
               : langJob.isRunning ? 'Detecting…'
               : 'Run Language Detection'}
            </Btn>
            <JobProgress jobState={langJob.jobState} />
            {langJob.isDone && (
              <div className="flex items-center gap-2 mt-3 text-sm text-teal-400">
                <CheckCircle2 size={14} />
                Language detection complete — you can now run sentiment analysis.
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* Sentiment */}
      <Card>
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 bg-ink-800 rounded-xl flex items-center justify-center flex-shrink-0">
            <Heart size={18} className="text-coral-400" />
          </div>
          <div className="flex-1">
            <h3 className="font-body font-medium text-ink-100 mb-1">Sentiment Analysis</h3>
            <p className="text-sm text-ink-500 mb-2">
              Runs <span className="text-ink-300">TextBlob</span> and{' '}
              <span className="text-ink-300">VADER</span> on all English-language comments and replies.
              Language detection must be completed first.
            </p>
            <div className="bg-ink-800 border border-ink-700 rounded-xl p-3 text-xs text-ink-400 font-body mb-4">
              VADER scores range from{' '}
              <span className="text-ink-300">−1 (negative)</span> to{' '}
              <span className="text-ink-300">+1 (positive)</span>.
              Non-English comments receive{' '}
              <code className="font-mono bg-ink-900 px-1 rounded">N/A</code>.
            </div>
            <Btn onClick={runSentiment} disabled={sentBusy}>
              {sentBusy
                ? <Loader2 size={14} className="animate-spin" />
                : <Heart size={14} />
              }
              {sentStarting    ? 'Connecting…'
               : sentJob.isRunning ? 'Analysing…'
               : 'Run Sentiment Analysis'}
            </Btn>
            <JobProgress jobState={sentJob.jobState} />
            {sentJob.isDone && (
              <div className="flex items-center gap-2 mt-3 text-sm text-teal-400">
                <CheckCircle2 size={14} />
                Sentiment analysis complete. Head to{' '}
                <a href="/tubescope" className="underline">TubeScope</a>
                {' '}to visualise results.
              </div>
            )}
          </div>
        </div>
      </Card>
    </div>
  )
}
