import { useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../api'
import { useJob } from '../hooks/useJob'
import { Card, SectionTitle, Btn, Input, JobProgress } from '../components/ui'
import { Download, Clipboard, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react'

export default function DownloadPage() {
  const location = useLocation()
  const [idsText, setIdsText]     = useState('')
  const [session, setSession]     = useState('default')
  const [starting, setStarting]   = useState(false)
  const [doneInfo, setDoneInfo]   = useState(null) // holds result after completion

  const { jobState, startWatching, isRunning, isDone, isError } = useJob()

  // Pre-fill IDs if navigated here from Search page
  useEffect(() => {
    const incoming = location.state?.ids
    if (incoming?.length) setIdsText(incoming.join('\n'))
  }, [location.state])

  // Capture result when job finishes
  useEffect(() => {
    if (!jobState) return
    if (jobState.status === 'done') {
      setDoneInfo(jobState.result ?? jobState)
      setStarting(false)
    }
    if (jobState.status === 'error' || jobState.status === 'quota_exceeded') {
      setStarting(false)
    }
  }, [jobState?.status])

  const ids = idsText
    .split(/[\n,\s]+/)
    .map(s => s.trim())
    .filter(s => /^[A-Za-z0-9_-]{11}$/.test(s))

  async function handleDownload() {
    if (!ids.length) return
    setDoneInfo(null)
    setStarting(true) // ← immediate feedback before await

    try {
      const res = await api.download({ video_ids: ids, session_id: session })
      setStarting(false)
      startWatching(res.job_id)
    } catch (e) {
      console.error('Download failed:', e)
      setStarting(false)
    }
  }

  async function paste() {
    const text = await navigator.clipboard.readText().catch(() => '')
    setIdsText(prev => prev ? prev + '\n' + text : text)
  }

  const busy = starting || isRunning

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Download comments for a list of YouTube video IDs">
        Download Comments
      </SectionTitle>

      <Card>
        <div className="space-y-5">

          {/* IDs textarea */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs uppercase tracking-widest text-ink-500 font-body">
                Video IDs
                <span className="ml-2 normal-case tracking-normal text-ink-600">
                  (one per line, or comma/space separated)
                </span>
              </label>
              <button onClick={paste}
                className="flex items-center gap-1 text-xs text-ink-500 hover:text-acid-400 font-mono transition-colors">
                <Clipboard size={11} /> paste
              </button>
            </div>
            <textarea
              value={idsText}
              onChange={e => setIdsText(e.target.value)}
              rows={8}
              placeholder={"dQw4w9WgXcQ\nabc123defgh\n..."}
              className="w-full bg-ink-800 border border-ink-600 rounded-xl px-4 py-3 text-sm
                         text-ink-100 font-mono placeholder:text-ink-600
                         focus:outline-none focus:border-acid-500/60 resize-none"
            />
            <p className="text-xs text-ink-500 font-mono mt-1">
              {ids.length} valid ID{ids.length !== 1 ? 's' : ''} detected
              {ids.length > 0 &&
                <span className="text-ink-600 ml-2">· ~{ids.length * 100} quota units</span>
              }
            </p>
          </div>

          {/* Session ID */}
          <Input
            label="Session ID (used to reference this data in analysis pages)"
            value={session}
            onChange={e => setSession(e.target.value)}
            placeholder="default"
          />

          {/* Info box */}
          <div className="bg-ink-800 border border-ink-700 rounded-xl p-4 text-xs text-ink-400 font-body space-y-1">
            <p className="text-ink-300 font-medium">Before downloading:</p>
            <p>• Make sure your YouTube API key is set in Settings</p>
            <p>• Each video uses ~100 API quota units — free quota is 10,000/day (~100 videos)</p>
            <p>• Data is saved per session — use the same Session ID to append more videos later</p>
          </div>

          {/* Button */}
          <Btn onClick={handleDownload} disabled={busy || ids.length === 0} size="lg">
            {busy
              ? <Loader2 size={16} className="animate-spin" />
              : <Download size={16} />
            }
            {starting   ? 'Connecting…'
            : isRunning ? 'Downloading…'
            : `Download ${ids.length} video${ids.length !== 1 ? 's' : ''}`}
          </Btn>

          {/* Live progress */}
          <JobProgress jobState={jobState} />

          {/* Error */}
          {isError && (
            <div className="flex items-center gap-2 p-3 bg-coral-500/10 border border-coral-500/20 rounded-xl text-sm text-coral-400">
              <AlertTriangle size={14} />
              {jobState?.error ?? 'Download failed. Check your API key and quota.'}
            </div>
          )}

          {/* Quota exceeded */}
          {jobState?.status === 'quota_exceeded' && (
            <div className="flex items-start gap-2 p-3 bg-coral-500/10 border border-coral-500/20 rounded-xl text-sm text-coral-400">
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium">API quota exceeded</p>
                <p className="text-xs mt-1 text-coral-300">
                  Partial data has been saved to session <span className="font-mono">"{session}"</span>.
                  Come back tomorrow when quota resets, use the same Session ID and re-download the remaining IDs.
                </p>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Done result */}
      {isDone && doneInfo && (
        <Card>
          <div className="flex items-center gap-2 mb-5">
            <CheckCircle2 size={16} className="text-teal-500" />
            <p className="text-sm font-body text-teal-400 font-medium">Download complete</p>
          </div>

          <div className="grid grid-cols-3 gap-3 mb-5">
            <div className="bg-ink-800 rounded-xl p-3 border border-ink-700">
              <p className="text-xs text-ink-500 font-body mb-1">Videos downloaded</p>
              <p className="text-2xl font-display text-acid-400">
                {doneInfo.processed ?? doneInfo.total_videos ?? ids.length}
              </p>
            </div>
            <div className="bg-ink-800 rounded-xl p-3 border border-ink-700">
              <p className="text-xs text-ink-500 font-body mb-1">Session ID</p>
              <p className="text-sm font-mono text-ink-200 mt-1">{doneInfo.session_id ?? session}</p>
            </div>
            <div className="bg-ink-800 rounded-xl p-3 border border-ink-700">
              <p className="text-xs text-ink-500 font-body mb-1">Total in session</p>
              <p className="text-2xl font-display text-ink-200">
                {doneInfo.total_videos ?? '—'}
              </p>
            </div>
          </div>

          {/* Download JSON button */}
          <div className="p-4 bg-ink-800 border border-ink-700 rounded-xl space-y-3">
            <p className="text-xs text-ink-400 font-body">
              <span className="text-ink-200 font-medium">Important:</span> On cloud deployments,
              data lives in memory and will be lost if the server restarts.
              Download your JSON now to keep a permanent copy.
            </p>
            <a
              href={api.downloadJson(doneInfo.session_id ?? session)}
              download={`Comments_${doneInfo.session_id ?? session}.json`}
              className="inline-flex items-center gap-2 px-4 py-2 bg-acid-500 text-ink-950
                         rounded-xl text-sm font-body font-medium hover:bg-acid-400 transition-colors"
            >
              <Download size={14} />
              Download Comments_{doneInfo.session_id ?? session}.json
            </a>
          </div>

          {/* Next step */}
          <div className="mt-4 pt-4 border-t border-ink-800">
            <p className="text-xs text-ink-500 font-body">
              Next step: go to{' '}
              <a href="/enrich" className="text-acid-400 underline">Enrich</a>
              {' '}to run language detection and sentiment analysis,
              or go straight to{' '}
              <a href="/tubescope" className="text-acid-400 underline">TubeScope</a>
              {' '}to start analysing.
              Use session ID <span className="font-mono text-ink-300">"{doneInfo.session_id ?? session}"</span> on all analysis pages.
            </p>
          </div>
        </Card>
      )}
    </div>
  )
}
