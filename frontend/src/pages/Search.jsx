import { useState } from 'react'
import { api } from '../api'
import { useJob } from '../hooks/useJob'
import { Card, SectionTitle, Btn, Input, JobProgress, Tag } from '../components/ui'
import { Plus, X, Search, ChevronRight } from 'lucide-react'

export default function SearchPage() {
  const [primaryGroups, setPrimaryGroups] = useState([['']]) // array of string arrays
  const [secondary, setSecondary] = useState('')
  const [excluded, setExcluded] = useState('')
  const [year, setYear] = useState(new Date().getFullYear() - 1)
  const [foundIds, setFoundIds] = useState(null)

  const { jobState, startWatching, isRunning, isDone } = useJob()

  // Primary groups
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
    const primary = primaryGroups.map(g => g.filter(t => t.trim())).filter(g => g.length > 0)
    if (!primary.length) return
    const sec = secondary.split(',').map(s => s.trim()).filter(Boolean)
    const exc = excluded.split(',').map(s => s.trim()).filter(Boolean)
    const res = await api.search({
      primary_terms: primary,
      secondary_terms: sec,
      excluded_terms: exc,
      search_year: Number(year),
    })
    startWatching(res.job_id)
  }

  // When job finishes extract IDs
  if (isDone && jobState?.result.video_ids  && !foundIds) {
    setFoundIds(jobState.result.video_ids)
    console.log("FINAL IDS:", jobState.result.video_ids)
  }

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
                (all terms in a group must appear in the video title)
              </span>
            </label>
            <div className="space-y-3">
              {primaryGroups.map((group, gi) => (
                <div key={gi} className="bg-ink-800 border border-ink-700 rounded-xl p-3 space-y-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-ink-500 font-mono">Group {gi + 1}</span>
                    {primaryGroups.length > 1 && (
                      <button onClick={() => removePrimaryGroup(gi)} className="text-coral-500 hover:text-coral-400">
                        <X size={12} />
                      </button>
                    )}
                  </div>
                  {group.map((term, ti) => (
                    <div key={ti} className="flex gap-2">
                      <input
                        value={term}
                        onChange={e => updatePrimaryTerm(gi, ti, e.target.value)}
                        placeholder={`Term ${ti + 1}…`}
                        className="flex-1 bg-ink-900 border border-ink-600 rounded-lg px-3 py-2 text-sm text-ink-100 font-mono placeholder:text-ink-600 focus:outline-none focus:border-acid-500/60"
                      />
                      {group.length > 1 && (
                        <button onClick={() => removeTermFromGroup(gi, ti)} className="text-ink-600 hover:text-coral-400">
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                  <button
                    onClick={() => addTermToGroup(gi)}
                    className="text-xs text-ink-500 hover:text-acid-400 flex items-center gap-1 mt-1"
                  >
                    <Plus size={11} /> Add term
                  </button>
                </div>
              ))}
            </div>
            <button
              onClick={addPrimaryGroup}
              className="mt-2 text-xs text-ink-500 hover:text-acid-400 flex items-center gap-1"
            >
              <Plus size={11} /> Add group
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

          {/* Year */}
          <Input
            label="Search year"
            type="number"
            value={year}
            onChange={e => setYear(e.target.value)}
            min={2005}
            max={new Date().getFullYear()}
          />

          <Btn onClick={handleSearch} disabled={isRunning}>
            <Search size={14} />
            {isRunning ? 'Searching…' : 'Search YouTube'}
          </Btn>

          <JobProgress jobState={jobState} />
        </div>
      </Card>

      {/* Results */}
      {foundIds && foundIds.length > 0 && (
        <Card>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm font-body text-ink-300">
              Found <span className="text-acid-400 font-mono">{foundIds.length}</span> video IDs
            </p>
          </div>
          <div className="flex flex-wrap gap-2 max-h-48 overflow-y-auto">
            {foundIds.map(id => (
              <Tag key={id}>{id}</Tag>
            ))}
          </div>
          <div className="mt-4 pt-4 border-t border-ink-800">
            <p className="text-xs text-ink-500 font-body">
              These IDs are ready to download. Go to the{' '}
              <a href="/download" className="text-acid-400 underline">Download page</a> and paste them in.
            </p>
          </div>
        </Card>
      )}

      {isDone && foundIds?.length === 0 && (
        <Card>
          <p className="text-sm text-ink-400 font-body text-center py-6">
            No videos found for these search terms and year.
          </p>
        </Card>
      )}
    </div>
  )
}
