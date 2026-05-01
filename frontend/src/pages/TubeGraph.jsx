import { useState, useEffect } from 'react'
import { api } from '../api'
import { useJob } from '../hooks/useJob'
import {
  Card,
  SectionTitle,
  Btn,
  Select,
  Input,
  PlotGallery,
  JobProgress,
  StatTile
} from '../components/ui'

import { Network, GitBranch, Users, Loader2 } from 'lucide-react'

export default function TubeGraphPage() {
  const [netResult, setNetResult] = useState(null)
  const [netLoading, setNetLoading] = useState(false)

  const [sessions, setSessions] = useState([])
  const [session, setSession] = useState('')

  // Channel stats
  const [topN, setTopN] = useState(15)
  const [chanImages, setChanImages] = useState(null)
  const [chanLoading, setChanLoading] = useState(false)
  const [chanData, setChanData] = useState(null)

  // Interaction network
  const [netTopN, setNetTopN] = useState(50)

  // Reply graph (still async job system)
  const replyJob = useJob()

  // ---------------- Load sessions ----------------
  useEffect(() => {
    api.listSessions()
      .then(r => {
        setSessions(r.sessions || [])
        if (r.sessions?.length > 0) {
          setSession(r.sessions[0].session_id)
        }
      })
      .catch(() => {})
  }, [])

  // ---------------- Channel stats ----------------
  async function runChannelStats() {
    if (!session) return

    setChanLoading(true)
    setChanImages(null)
    setChanData(null)

    try {
      const r = await api.graphChannelStats(session, topN)
      setChanImages(r.images)
      setChanData(r.top_channels)
    } catch {
      setChanImages([])
      setChanData([])
    } finally {
      setChanLoading(false)
    }
  }

  // ---------------- Network graph (FIXED) ----------------
  async function runNetwork() {
    if (!session) return

    setNetLoading(true)
    setNetResult(null)

    try {
      const res = await api.graphNetwork(session, netTopN)
      console.log("GRAPH RESULT:", res)
      setNetResult(res)
    } catch (err) {
      console.error("Network graph error:", err)
      setNetResult(null)
    } finally {
      setNetLoading(false)
    }
  }

  // ---------------- Reply graph ----------------
  async function runReplyGraph() {
    if (!session) return

    try {
      const res = await api.graphReplyGraph(session)
      console.log("REPLY GRAPH RESPONSE:", res)
      replyJob.startWatching(res.job_id)
    } catch (err) {
      console.error("Reply graph error:", err)
    }
  }

  return (
    <div className="space-y-6 animate-fade-up">

      <SectionTitle sub="Network analysis: channel interactions, reply graphs, co-occurrence">
        TubeGraph
      </SectionTitle>

      {/* ---------------- Session dropdown ---------------- */}
      <div className="flex items-end gap-4">
        <div className="w-64">
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
        </div>
      </div>

      {/* ---------------- Warning ---------------- */}
      <div className="bg-ink-800 border border-ink-700 rounded-2xl p-4 text-xs text-ink-400 font-body">
        <p className="text-ink-300 font-medium mb-1">Performance note</p>
        <p>
          Network analysis can take <span className="text-ink-200">several minutes</span>.
          All jobs run in background.
        </p>
      </div>

      {/* ---------------- Channel stats ---------------- */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Users size={18} className="text-acid-400" />
          <h3 className="font-body font-medium text-ink-100">
            Channel Activity Stats
          </h3>
        </div>

        <div className="flex items-end gap-4 mb-4">
          <Input
            label="Top N channels"
            type="number"
            min={5}
            max={50}
            value={topN}
            onChange={e => setTopN(e.target.value)}
            className="w-28"
          />

          <Btn onClick={runChannelStats} disabled={chanLoading || !session}>
            {chanLoading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Users size={14} />
            )}
            {chanLoading ? 'Running…' : 'Analyse Channels'}
          </Btn>
        </div>

        {chanData?.length > 0 && (
          <div className="mb-4 overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-ink-700">
                  {[
                    'channel_id',
                    'as_uploader',
                    'as_commenter',
                    'as_replier',
                    'total_activity',
                    'videos_active_in'
                  ].map(h => (
                    <th key={h} className="py-2 px-2 text-left text-ink-500 font-normal">
                      {h.replace(/_/g, ' ')}
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody>
                {chanData.slice(0, 10).map((row, i) => (
                  <tr key={i} className="border-b border-ink-800 hover:bg-ink-800/50">
                    <td className="py-2 px-2 text-ink-300 truncate">{row.channel_id}</td>
                    <td className="py-2 px-2 text-ink-400">{row.as_uploader}</td>
                    <td className="py-2 px-2 text-acid-400">{row.as_commenter}</td>
                    <td className="py-2 px-2 text-teal-400">{row.as_replier}</td>
                    <td className="py-2 px-2 text-ink-200 font-medium">{row.total_activity}</td>
                    <td className="py-2 px-2 text-ink-400">{row.videos_active_in}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <PlotGallery images={chanImages} loading={chanLoading} />
      </Card>

      {/* ---------------- Network graph ---------------- */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Network size={18} className="text-teal-400" />
          <h3 className="font-body font-medium text-ink-100">
            Channel Interaction Network
          </h3>
        </div>

        <div className="flex items-end gap-4 mb-4">
          <Input
            label="Top N nodes"
            type="number"
            min={10}
            max={200}
            value={netTopN}
            onChange={e => setNetTopN(e.target.value)}
            className="w-32"
          />

          <Btn onClick={runNetwork} disabled={netLoading || !session}>
            <Network size={14} />
            {netLoading ? 'Building graph…' : 'Build Network'}
          </Btn>
        </div>

        {netLoading && (
          <div className="text-ink-400 text-sm">Building graph...</div>
        )}

        {netResult?.nodes != null && (
          <div className="flex gap-3 mt-3 mb-4">
            <StatTile label="Nodes" value={netResult.nodes.toLocaleString()} />
            <StatTile label="Edges" value={netResult.edges.toLocaleString()} />
          </div>
        )}

        {netResult?.images && (
          <PlotGallery images={netResult.images} />
        )}
      </Card>

      {/* ---------------- Reply graph ---------------- */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <GitBranch size={18} className="text-coral-400" />
          <h3 className="font-body font-medium text-ink-100">
            Directed Reply Graph
          </h3>
        </div>

        <Btn onClick={runReplyGraph} disabled={replyJob.isRunning || !session}>
          <GitBranch size={14} />
          {replyJob.isRunning ? 'Building…' : 'Build Reply Graph'}
        </Btn>

        <JobProgress jobState={replyJob.jobState} />

        {replyJob.isDone && (
          <PlotGallery
            images={
              replyJob.jobState?.images ||
              replyJob.jobState?.result?.images
            }
          />
        )}
      </Card>
    </div>
  )
}
