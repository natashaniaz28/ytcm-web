import { useState, useEffect } from 'react'
import { api } from '../api'
import { useJob } from '../hooks/useJob'
import { Card, SectionTitle, Btn, Select, JobProgress } from '../components/ui'
import { Languages, Heart, RefreshCw } from 'lucide-react'

export default function EnrichPage() {
  const [files, setFiles] = useState([])
  const [session, setSession] = useState('Comments.json')
  const [forceRebuild, setForceRebuild] = useState(false)

  const langJob = useJob()
  const sentJob = useJob()

  useEffect(() => {
    api.listFiles().then(r => setFiles(r.files)).catch(() => {})
  }, [])

  async function runLanguage() {
    const res = await api.detectLanguages({ session_id: session, force_rebuild: forceRebuild })
    langJob.startWatching(res.job_id)
  }

  async function runSentiment() {
    const res = await api.runSentiment({ session_id: session, force_rebuild: forceRebuild })
    sentJob.startWatching(res.job_id)
  }

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Add language detection and sentiment scores to your data">
        Enrich Data
      </SectionTitle>

      {/* File + rebuild */}
      <Card>
        <div className="grid grid-cols-2 gap-4">
          <Select
            label="Dataset"
            value={session}
            onChange={e => setSession(e.target.value)}
          >
            {files.map(f => <option key={f.name}>{f.name}</option>)}
            {files.length === 0 && <option>Comments.json</option>}
          </Select>
          <div className="flex flex-col gap-1.5 justify-end">
            <label className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={forceRebuild}
                onChange={e => setForceRebuild(e.target.checked)}
                className="accent-acid-500 w-4 h-4"
              />
              <span className="text-sm text-ink-300 font-body">Force rebuild (re-run on existing data)</span>
            </label>
          </div>
        </div>
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
              Detects the language of each comment and reply using <code className="font-mono text-xs bg-ink-800 px-1.5 py-0.5 rounded">langdetect</code>.
              Required before running sentiment analysis.
            </p>
            <Btn onClick={runLanguage} disabled={langJob.isRunning}>
              <Languages size={14} />
              {langJob.isRunning ? 'Detecting…' : 'Run Language Detection'}
            </Btn>
            <JobProgress jobState={langJob.jobState} />
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
              Runs <span className="text-ink-300">TextBlob</span> and <span className="text-ink-300">VADER</span> sentiment scoring on all English-language comments and replies.
              Language detection must be completed first.
            </p>
            <div className="bg-ink-800 border border-ink-700 rounded-xl p-3 text-xs text-ink-400 font-body mb-4">
              VADER scores range from <span className="text-ink-300">−1 (negative)</span> to <span className="text-ink-300">+1 (positive)</span>.
              Non-English comments receive <code className="font-mono bg-ink-900 px-1 rounded">N/A</code>.
            </div>
            <Btn onClick={runSentiment} disabled={sentJob.isRunning}>
              <Heart size={14} />
              {sentJob.isRunning ? 'Analysing…' : 'Run Sentiment Analysis'}
            </Btn>
            <JobProgress jobState={sentJob.jobState} />
          </div>
        </div>
      </Card>
    </div>
  )
}
