import { useState } from 'react'
import { api, watchJob } from '../api'
import { Card, SectionTitle, Btn, Input, Select } from '../components/ui'
import { FileText, Download, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react'
import { clsx } from 'clsx'

const STEPS = [
  'Searching YouTube',
  'Downloading comments',
  'Enriching data (language + sentiment)',
  'Generating charts',
  'Building PDF',
]

function StepList({ currentStep, isDone, isError }) {
  return (
    <div className="space-y-2">
      {STEPS.map((label, i) => {
        const stepNum = i + 1
        const done   = isDone || stepNum < currentStep
        const active = !isDone && stepNum === currentStep

        return (
          <div key={i} className="flex items-center gap-3">
            <div className={clsx(
              'w-6 h-6 rounded-full flex items-center justify-center text-xs font-mono flex-shrink-0 border',
              done   ? 'bg-teal-500/20  text-teal-400  border-teal-500/30'  :
              active ? 'bg-acid-500/20  text-acid-400  border-acid-500/30'  :
                       'bg-ink-800     text-ink-600   border-ink-700',
            )}>
              {done   ? <CheckCircle2 size={12} /> :
               active ? <Loader2 size={12} className="animate-spin" /> :
                        stepNum}
            </div>
            <span className={clsx(
              'text-sm font-body',
              done   ? 'text-teal-400' :
              active ? 'text-ink-200'  :
                       'text-ink-600',
            )}>
              {label}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default function QuickReportPage() {
  const [keyword,   setKeyword]   = useState('')
  const [numVideos, setNumVideos] = useState(3)
  const [jobState,  setJobState]  = useState(null)
  const [pdfFile,   setPdfFile]   = useState(null)
  const [running,   setRunning]   = useState(false)

  async function startReport() {
    if (!keyword.trim() || running) return
    setRunning(true)
    setJobState(null)
    setPdfFile(null)

    try {
      const { job_id } = await api.quickReport({
        keyword:    keyword.trim(),
        num_videos: numVideos,
      })

      const stop = watchJob(job_id, (msg) => {
        setJobState(msg)
        if (msg.status === 'done') {
          // pdf_file can be top-level (live WS push) or inside result (WS reconnect)
          const file = msg.pdf_file || msg.result?.pdf_file
          setPdfFile(file)
          setRunning(false)
          stop()
        } else if (msg.status === 'error') {
          setRunning(false)
          stop()
        }
      })
    } catch (e) {
      setJobState({ status: 'error', error: e.message })
      setRunning(false)
    }
  }

  const isDone    = jobState?.status === 'done'
  const isError   = jobState?.status === 'error'
  const step      = jobState?.step ?? 0
  const showProgress = running || jobState

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Enter a keyword — we search YouTube, download comments, run all analyses, and hand you a PDF.">
        Quick Report
      </SectionTitle>

      {/* ── Input form ─────────────────────────────────────────────────────── */}
      <Card>
        <div className="space-y-4">
          <Input
            label="Search Keyword"
            placeholder="e.g. climate change, AI art, Gaza protests…"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && startReport()}
            disabled={running}
          />

          <Select
            label="Number of Videos (max 5)"
            value={numVideos}
            onChange={e => setNumVideos(Number(e.target.value))}
            disabled={running}
          >
            {[1, 2, 3, 4, 5].map(n => (
              <option key={n} value={n}>
                {n} video{n !== 1 ? 's' : ''}
              </option>
            ))}
          </Select>

          <div className="flex items-start gap-3">
            <Btn
              onClick={startReport}
              disabled={running || !keyword.trim()}
              size="lg"
            >
              {running
                ? <><Loader2 size={16} className="animate-spin" />Running…</>
                : <><FileText size={16} />Generate Report</>}
            </Btn>

            <p className="text-xs font-mono text-ink-500 mt-3 leading-relaxed">
              This runs the full pipeline automatically.<br />
              Allow 2–5 min depending on comment volume.
            </p>
          </div>
        </div>
      </Card>

      {/* ── Progress ───────────────────────────────────────────────────────── */}
      {showProgress && (
        <Card>
          <p className="text-xs uppercase tracking-widest text-ink-500 font-body mb-4">
            Pipeline Progress
          </p>

          <StepList currentStep={step} isDone={isDone} isError={isError} />

          {jobState?.message && (
            <p className="mt-4 text-xs font-mono text-ink-400 border-t border-ink-700 pt-3">
              {jobState.message}
            </p>
          )}

          {isError && (
            <div className="mt-4 flex items-start gap-2 p-3 bg-coral-500/10 border border-coral-500/20 rounded-xl text-coral-400 text-sm font-mono">
              <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
              {jobState.error}
            </div>
          )}
        </Card>
      )}

      {/* ── Download card ──────────────────────────────────────────────────── */}
      {isDone && pdfFile && (
        <Card className="border-teal-500/20 bg-teal-500/5">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <CheckCircle2 size={20} className="text-teal-400 flex-shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-body text-ink-100 font-medium">Report ready</p>
                <p className="text-xs font-mono text-ink-500 truncate">{pdfFile}</p>
              </div>
            </div>
            <a
              href={api.quickReportDownloadUrl(pdfFile)}
              download
              className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-body font-medium rounded-xl bg-teal-500/20 text-teal-400 hover:bg-teal-500/30 border border-teal-500/30 transition-all flex-shrink-0"
            >
              <Download size={16} />
              Download PDF
            </a>
          </div>

          {jobState?.summary && (
            <div className="mt-4 pt-4 border-t border-ink-700 grid grid-cols-3 gap-4">
              <div>
                <p className="text-xs text-ink-500 uppercase tracking-wider font-body">Keyword</p>
                <p className="text-sm font-mono text-ink-200 mt-1 truncate">
                  {jobState.summary.keyword}
                </p>
              </div>
              <div>
                <p className="text-xs text-ink-500 uppercase tracking-wider font-body">Videos</p>
                <p className="text-2xl font-display text-ink-50 mt-0.5">
                  {jobState.summary.num_videos}
                </p>
              </div>
              <div>
                <p className="text-xs text-ink-500 uppercase tracking-wider font-body">Comments</p>
                <p className="text-2xl font-display text-ink-50 mt-0.5">
                  {jobState.summary.total_comments?.toLocaleString()}
                </p>
              </div>
            </div>
          )}

          {jobState?.summary?.video_titles?.length > 0 && (
            <div className="mt-4 pt-4 border-t border-ink-700">
              <p className="text-xs text-ink-500 uppercase tracking-wider font-body mb-2">
                Videos included
              </p>
              <ol className="space-y-1">
                {jobState.summary.video_titles.map((title, i) => (
                  <li key={i} className="text-xs font-mono text-ink-400">
                    {i + 1}. {title}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
