import { useState } from 'react'
import { api } from '../api'
import { useJob } from '../hooks/useJob'
import { Card, SectionTitle, Btn, Input, JobProgress } from '../components/ui'
import { Download, Clipboard } from 'lucide-react'

export default function DownloadPage() {
  const [idsText, setIdsText] = useState('')
  const [outputFile, setOutputFile] = useState('Comments.json')
  const { jobState, startWatching, isRunning } = useJob()

  const ids = idsText.split(/[\n,\s]+/).map(s => s.trim()).filter(s => s.length === 11)

  async function handleDownload() {
    if (!ids.length) return
    const res = await api.download({ video_ids: ids, comments_file: outputFile })
    startWatching(res.job_id)
  }

  async function paste() {
    const text = await navigator.clipboard.readText().catch(() => '')
    setIdsText(prev => (prev ? prev + '\n' + text : text))
  }

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Download comments for a list of YouTube video IDs">
        Download Comments
      </SectionTitle>

      <Card>
        <div className="space-y-5">
          {/* IDs input */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs uppercase tracking-widest text-ink-500 font-body">
                Video IDs
                <span className="ml-2 normal-case tracking-normal text-ink-600">
                  (one per line, or comma/space separated)
                </span>
              </label>
              <button
                onClick={paste}
                className="flex items-center gap-1 text-xs text-ink-500 hover:text-acid-400 font-mono"
              >
                <Clipboard size={11} /> paste
              </button>
            </div>
            <textarea
              value={idsText}
              onChange={e => setIdsText(e.target.value)}
              rows={8}
              placeholder={"dQw4w9WgXcQ\nabc123defgh\n..."}
              className="w-full bg-ink-800 border border-ink-600 rounded-xl px-4 py-3 text-sm text-ink-100 font-mono placeholder:text-ink-600 focus:outline-none focus:border-acid-500/60 resize-none"
            />
            <p className="text-xs text-ink-500 font-mono mt-1">
              {ids.length} valid ID{ids.length !== 1 ? 's' : ''} detected
            </p>
          </div>

          <Input
            label="Output file"
            value={outputFile}
            onChange={e => setOutputFile(e.target.value)}
            placeholder="Comments.json"
          />

          <div className="bg-ink-800 border border-ink-700 rounded-xl p-4 text-xs text-ink-400 font-body space-y-1">
            <p className="text-ink-300 font-medium">Before downloading:</p>
            <p>• Make sure your YouTube API key is set in Settings</p>
            <p>• Each video uses ~100 API quota units. Free quota is 10,000/day</p>
            <p>• Downloads auto-save to disk — safe to stop and resume</p>
          </div>

          <Btn onClick={handleDownload} disabled={isRunning || ids.length === 0} size="lg">
            <Download size={16} />
            {isRunning ? 'Downloading…' : `Download ${ids.length} video${ids.length !== 1 ? 's' : ''}`}
          </Btn>

          <JobProgress jobState={jobState} />
        </div>
      </Card>
    </div>
  )
}
