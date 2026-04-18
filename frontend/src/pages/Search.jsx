import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useJob } from '../hooks/useJob'
import { Card, SectionTitle, Btn, Input, JobProgress, Tag } from '../components/ui'
import { Plus, X, Search, Copy, ArrowRight, CheckCircle2, Loader2 } from 'lucide-react'

export default function SearchPage() {
  const [primaryGroups, setPrimaryGroups] = useState([['']])
  const [secondary, setSecondary]         = useState('')
  const [excluded, setExcluded]           = useState('')
  const [year, setYear]                   = useState(new Date().getFullYear() - 1)
  const [foundIds, setFoundIds]           = useState(null)
  const [copied, setCopied]               = useState(false)
  const [starting, setStarting]           = useState(false) // true from click → until job_id arrives

  const navigate = useNavigate()
  const { jobState, startWatching, isRunning, isDone, isError } = useJob()

  // Extract IDs when job completes
  useEffect(() => {
    if (!jobState) return
    if (jobState.status === 'done') {
      const ids = jobState.video_ids ?? jobState.result?.video_ids ?? []
      setFoundIds(ids)
    }
  }, [jobState?.status, jobState?.video_ids])

  function addPrimaryGroup() { setPrimaryGroups(g => [...g, ['']]) }
  function removePrimaryGroup(i) { setPrimaryGroups(g => g.filter((_, idx) => idx !== i)) }
  function updatePrimaryTerm(gi, ti, val) {
    setPrimaryGroups(g => g.map((group, i) =>
      i === gi ? group.map((t, j) => j === ti ? val : t) : group
    ))
  }
  function addTermToGroup(gi) {
    setPrimaryGroups(g => g.map((group, i) => i === gi ? [...group, ''] : group))
  }
  function removeTermFromGroup(gi, ti) {
    setPrimaryGroups(g => g.map((group, i) =>
      i === gi ? group.filter((_, j) => j !== ti) : group
    ))
  }

  async function handleSearch() {
    const primary = primaryGroups
      .map(g => g.map(t => t.trim()).filter(Boolean))
      .filter(g => g.length > 0)
    if (!primary.length) return

    setFoundIds(null)
    setCopied(false)
    setStarting(true) // ← spinner starts HERE, before any await

    const sec = secondary.split(',').map(s => s.trim()).filter(Boolean)
    const exc = excluded.split(',').map(s => s.trim()).filter(Boolean)

    try {
      const res = await api.search({  // ← this POST may take 10-15s on cold start
        primary_terms: primary,
        secondary_terms: sec,
        excluded_terms: exc,
        search_year: Number(year),
      })
      setStarting(false) // job started, hand off to useJob
      startWatching(res.job_id)
    } catch (e) {
      console.error('Search failed:', e)
      setStarting(false)
    }
  }

  async function copyIds() {
    if (!foundIds?.length) return
    await navigator.clipboard.writeText(foundIds.join('\n'))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function goToDownload() {
    navigate('/download', { state: { ids: foundIds } })
  }

  // Button is busy from the moment it's clicked until search is fully done
  const busy = starting || isRunning

  // Label changes to reflect exactly what's happening
  const buttonLabel = starting   ? 'Connecting…'
                    : isRunning  ? 'Searching YouTube…'
                    : 'Search YouTube'

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Search YouTube for videos matching your keywords">
        Search Videos
      </SectionTitle>

      <Card>
        <div className="space-y-6">

          {/* Primary terms */}
          <div>
            <label className="text-xs uppercase tracking-widest text-ink-500 font-body block mb-3">
              Primary search terms
              <span className="ml-2 text-ink-600 normal-case tracking-normal">
                — all terms in a group must appear in the video title
              </span>
            </label>
            <div className="space-y-3">
              {primaryGroups.map((group, gi) => (
                <div key={gi} className="bg-ink-800 border border-ink-700 rounded-xl p-3 space-y-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-ink-500 font-mono">Group {gi + 1}</span>
                    {primaryGroups.length > 1 && (
                      <button onClick={() => removePrimaryGroup(gi)}
                        className="text-ink-600 hover:text-coral-400 transition-colors">
                        <X size={12} />
                      </button>
                    )}
                  </div>
                  {group.map((term, ti) => (
                    <div key={ti} className="flex gap-2">
                      <input
                        value={term}
                        onChange={e => updatePrimaryTerm(gi, ti, e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && !busy && handleSearch()}
                        placeholder={`Term ${ti + 1}…`}
                        className="flex-1 bg-ink-900 border border-ink-600 rounded-lg px-3 py-2
                                   text-sm text-ink-100 font-mono placeholder:text-ink-600
                                   focus:outline-none focus:border-acid-500/60 transition-colors"
                      />
                      {group.length > 1 && (
                        <button onClick={() => removeTermFromGroup(gi, ti)}
                          className="text-ink-600 hover:text-coral-400 transition-colors">
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                  <button onClick={() => addTermToGroup(gi)}
                    className="text-xs text-ink-500 hover:text-acid-400 flex items-center gap-1 mt-1">
                    <Plus size={11} /> Add term to group
                  </button>
                </div>
              ))}
            </div>
            <button onClick={addPrimaryGroup}
              className="mt-2 text-xs text-ink-500 hover:text-acid-400 flex items-center gap-1">
              <Plus size={11} /> Add another group
            </button>
          </div>

          {/* Secondary & excluded */}
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Secondary terms (comma-separated, optional)"
              value={secondary}
              onChange={e => setSecondary(e.target.value)}
              placeholder="term1, term2…"
            />
            <Input
              label="Excluded terms (comma-separated, optional)"
              value={excluded}
              onChange={e => setExcluded(e.target.value)}
              placeholder="exclude1, exclude2…"
            />
          </div>

          <Input
            label="Search year"
            type="number"
            value={year}
            onChange={e => setYear(e.target.value)}
            min={2005}
            max={new Date().getFullYear()}
            className="w-36"
          />

          <Btn onClick={handleSearch} disabled={busy} size="lg">
            {busy
              ? <Loader2 size={15} className="animate-spin" />
              : <Search size={15} />
            }
            {buttonLabel}
          </Btn>

          <JobProgress jobState={jobState} />

          {isError && (
            <p className="text-sm text-coral-400 font-mono">
              {jobState?.error ?? 'Search failed. Check the backend is running.'}
            </p>
          )}
        </div>
      </Card>

      {/* Results */}
      {isDone && foundIds !== null && (
        foundIds.length > 0 ? (
          <Card>
            <div className="flex items-center justify-between mb-5">
              <div>
                <p className="text-sm font-body text-ink-300">
                  Found{' '}
                  <span className="text-acid-400 font-mono text-lg">{foundIds.length}</span>
                  {' '}video ID{foundIds.length !== 1 ? 's' : ''}
                </p>
                <p className="text-xs text-ink-600 font-mono mt-0.5">
                  year={year} · {primaryGroups.flat().filter(Boolean).join(', ')}
                </p>
              </div>
              <div className="flex gap-2">
                <Btn variant="ghost" size="sm" onClick={copyIds}>
                  {copied
                    ? <><CheckCircle2 size={13} className="text-teal-400" /> Copied!</>
                    : <><Copy size={13} /> Copy all IDs</>
                  }
                </Btn>
                <Btn size="sm" onClick={goToDownload}>
                  Download these <ArrowRight size={13} />
                </Btn>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 max-h-52 overflow-y-auto pr-1">
              {foundIds.map(id => (
                <a key={id}
                  href={`https://www.youtube.com/watch?v=${id}`}
                  target="_blank" rel="noopener noreferrer"
                  className="inline-block px-2 py-1 bg-ink-800 border border-ink-600
                             hover:border-acid-500/40 rounded-lg text-xs font-mono
                             text-ink-300 hover:text-acid-400 transition-colors"
                  title="Preview on YouTube">
                  {id}
                </a>
              ))}
            </div>
            <p className="text-xs text-ink-600 font-body mt-4">
              Click any ID to preview on YouTube.{' '}
              Use <span className="text-ink-400">Download these →</span> to proceed.
            </p>
          </Card>
        ) : (
          <Card>
            <div className="py-8 text-center space-y-2">
              <p className="text-ink-300 font-body">No videos found.</p>
              <p className="text-sm text-ink-500">
                Try broader terms, a different year, or remove secondary/excluded filters.
              </p>
            </div>
          </Card>
        )
      )}
    </div>
  )
}
