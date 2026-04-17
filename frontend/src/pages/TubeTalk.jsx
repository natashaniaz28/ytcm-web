import { useState, useEffect } from 'react'
import { api } from '../api'
import { useJob } from '../hooks/useJob'
import { Card, SectionTitle, Btn, Select, Input, PlotGallery, JobProgress } from '../components/ui'
import { Languages, Cloud, Tag as TagIcon, Loader2 } from 'lucide-react'

export default function TubeTalkPage() {
  const [files, setFiles] = useState([])
  const [session, setSession] = useState('Comments.json')

  // Language analysis state
  const [langLevel, setLangLevel] = useState('comment')
  const [langImages, setLangImages] = useState(null)
  const [langLoading, setLangLoading] = useState(false)
  const [confImages, setConfImages] = useState(null)
  const [confLoading, setConfLoading] = useState(false)

  // Wordcloud
  const [wcNgramMin, setWcNgramMin] = useState(1)
  const [wcNgramMax, setWcNgramMax] = useState(2)
  const [wcStopwords, setWcStopwords] = useState('youtube, http, www')
  const wcJob = useJob()

  // Topics
  const [nTopics, setNTopics] = useState(6)
  const [nWords, setNWords] = useState(10)
  const topicsJob = useJob()

  useEffect(() => {
    api.listFiles().then(r => setFiles(r.files)).catch(() => {})
  }, [])

  async function runLangDist() {
    setLangLoading(true)
    setLangImages(null)
    try {
      const r = await api.talkLanguages(session, langLevel, 20)
      setLangImages(r.images)
    } catch (e) {
      setLangImages([])
    } finally {
      setLangLoading(false)
    }
  }

  async function runLangConflicts() {
    setConfLoading(true)
    setConfImages(null)
    try {
      const r = await api.talkLangConflicts(session)
      setConfImages(r.images)
    } catch (e) {
      setConfImages([])
    } finally {
      setConfLoading(false)
    }
  }

  async function runWordcloud() {
    const sw = wcStopwords.split(',').map(s => s.trim()).filter(Boolean)
    const res = await api.talkWordcloud({
      session_id: session,
      ngram_min: Number(wcNgramMin),
      ngram_max: Number(wcNgramMax),
      extra_stopwords: sw,
      min_df: 2,
      max_df: 0.95,
    })
    wcJob.startWatching(res.job_id)
  }

  async function runTopics() {
    const res = await api.talkTopics({
      session_id: session,
      n_topics: Number(nTopics),
      n_words: Number(nWords),
      min_df: 5,
      max_df: 0.6,
      ngram_min: 1,
      ngram_max: 2,
    })
    topicsJob.startWatching(res.job_id)
  }

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Linguistic analysis: language detection, word clouds, topic modeling">
        TubeTalk
      </SectionTitle>

      <div className="w-64">
        <Select label="Dataset" value={session} onChange={e => setSession(e.target.value)}>
          {files.map(f => <option key={f.name}>{f.name}</option>)}
          {files.length === 0 && <option>Comments.json</option>}
        </Select>
      </div>

      {/* Language distribution */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Languages size={18} className="text-acid-400" />
          <h3 className="font-body font-medium text-ink-100">Language Distribution</h3>
        </div>
        <div className="flex items-end gap-4 mb-4">
          <Select label="Level" value={langLevel} onChange={e => setLangLevel(e.target.value)} className="w-36">
            <option value="video">Video</option>
            <option value="comment">Comment</option>
            <option value="reply">Reply</option>
          </Select>
          <Btn onClick={runLangDist} disabled={langLoading}>
            {langLoading ? <Loader2 size={14} className="animate-spin" /> : <Languages size={14} />}
            {langLoading ? 'Running…' : 'Plot Distribution'}
          </Btn>
          <Btn onClick={runLangConflicts} disabled={confLoading} variant="ghost">
            {confLoading ? 'Running…' : 'Plot Conflicts'}
          </Btn>
        </div>
        <PlotGallery images={langImages} loading={langLoading} />
        <PlotGallery images={confImages} loading={confLoading} />
      </Card>

      {/* Word cloud */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Cloud size={18} className="text-teal-400" />
          <h3 className="font-body font-medium text-ink-100">Word Cloud</h3>
        </div>
        <div className="grid grid-cols-3 gap-4 mb-4">
          <Input label="Min n-gram" type="number" min={1} max={3} value={wcNgramMin} onChange={e => setWcNgramMin(e.target.value)} />
          <Input label="Max n-gram" type="number" min={1} max={3} value={wcNgramMax} onChange={e => setWcNgramMax(e.target.value)} />
          <Input label="Extra stopwords (comma-separated)" value={wcStopwords} onChange={e => setWcStopwords(e.target.value)} />
        </div>
        <Btn onClick={runWordcloud} disabled={wcJob.isRunning}>
          <Cloud size={14} />
          {wcJob.isRunning ? 'Generating…' : 'Generate Word Cloud'}
        </Btn>
        {wcJob.isDone && (wcJob.jobState?.images || wcJob.jobState?.result?.images) && (
  <div className="mt-4">
    <PlotGallery images={wcJob.jobState.images || wcJob.jobState.result.images} />
  </div>
)}
      </Card>

      {/* Topic modeling */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <TagIcon size={18} className="text-coral-400" />
          <h3 className="font-body font-medium text-ink-100">LDA Topic Modeling</h3>
        </div>
        <p className="text-sm text-ink-500 font-body mb-4">
          Latent Dirichlet Allocation — discovers latent topics across the comment corpus.
          May take several minutes on large datasets.
        </p>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <Input label="Number of topics" type="number" min={2} max={20} value={nTopics} onChange={e => setNTopics(e.target.value)} />
          <Input label="Top words per topic" type="number" min={5} max={30} value={nWords} onChange={e => setNWords(e.target.value)} />
        </div>
        <Btn onClick={runTopics} disabled={topicsJob.isRunning}>
          <TagIcon size={14} />
          {topicsJob.isRunning ? 'Running LDA…' : 'Run Topic Modeling'}
        </Btn>
        <JobProgress jobState={topicsJob.jobState} />
        {topicsJob.isDone && (topicsJob.jobState?.images || topicsJob.jobState?.result?.images) && (
          <div className="mt-4">
            <PlotGallery images={(topicsJob.jobState?.images || topicsJob.jobState?.result?.images)} />
          </div>
        )}
      </Card>
    </div>
  )
}
