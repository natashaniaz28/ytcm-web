import { useState, useEffect } from 'react'
import { api } from '../api'
import {
  Card,
  SectionTitle,
  Btn,
  Select,
  Input,
  PlotGallery,
  StatTile
} from '../components/ui'
import { Network, GitBranch, Users, Loader2 } from 'lucide-react'

export default function TubeGraphPage() {
  const [netResult, setNetResult] = useState(null)
  const [netLoading, setNetLoading] = useState(false)

  const [replyResult, setReplyResult] = useState(null)
  const [replyLoading, setReplyLoading] = useState(false)

  const [sessions, setSessions] = useState([])
  const [session, setSession] = useState('')

  // Channel stats
  const [topN, setTopN] = useState(15)
  const [chanImages, setChanImages] = useState(null)
  const [chanLoading, setChanLoading] = useState(false)
  const [chanData, setChanData] = useState(null)

  // Interaction network
  const [netTopN, setNetTopN] = useState(50)

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

  async function runChannelStats() {
    if (!session) return
    setChanLoading(true)
    setChanImages(null)
    setChanData(null)
    try {
      const r = await api.graphChannelStats(session, topN)
      setChanImages(r.images || [])
      setChanData(r.top_channels || [])
    } catch {
      setChanImages([])
    } finally {
      setChanLoading(false)
    }
  }

  async function runNetwork() {
    if (!session) return
    setNetLoading(true)
    setNetResult(null)
    try {
      const res = await api.graphNetwork(session, netTopN)
      console.log("GRAPH RESULT:", res)
      setNetResult(res)
    } catch (err) {
      console.error("Network error:", err)
      setNetResult(null)
    } finally {
      setNetLoading(false)
    }
  }

  async function runReplyGraph() {
    if (!session) return
    setReplyLoading(true)
    setReplyResult(null)
    try {
      const res = await api.graphReplyGraph(session)
      console.log("REPLY GRAPH RESPONSE:", res)
      setReplyResult(res)
    } catch (err) {
      console.error("Reply graph error:", err)
    } finally {
      setReplyLoading(false)
    }
  }

  return (
    <div className="space-y-6 animate-fade-up">

      <SectionTitle sub="Network analysis: channel interactions, reply graphs, co-occurrence">
        TubeGraph
      </SectionTitle>

      {/* Session */}
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
          </Select>
        </div>
      </div>

      {/* Channel Stats */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Users size={18} className="text-acid-400" />
          <h3 className="font-medium">Channel Activity Stats</h3>
        </div>

        <div className="flex items-end gap-4 mb-4">
          <Input
            label="Top N"
            type="number"
            value={topN}
            onChange={e => setTopN(Number(e.target.value))}
            className="w-28"
          />
          <Btn onClick={runChannelStats} disabled={chanLoading || !session}>
            {chanLoading ? <Loader2 size={14} className="animate-spin" /> : 'Run'}
          </Btn>
        </div>

        {chanData?.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  <th>Channel</th>
                  <th>Uploader</th>
                  <th>Commenter</th>
                  <th>Replier</th>
                  <th>Total</th>
                  <th>Videos</th>
                </tr>
              </thead>
              <tbody>
                {chanData.slice(0, 10).map((row, i) => (
                  <tr key={i}>
                    <td>{row.channel_id}</td>
                    <td>{row.as_uploader}</td>
                    <td>{row.as_commenter}</td>
                    <td>{row.as_replier}</td>
                    <td>{row.total_activity}</td>
                    <td>{row.videos_active_in}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <PlotGallery images={chanImages || []} loading={chanLoading} />
      </Card>

      {/* Network */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <Network size={18} />
          <h3>Channel Interaction Network</h3>
        </div>

        <div className="flex items-end gap-4 mb-4">
          <Input
            label="Top Nodes"
            type="number"
            value={netTopN}
            onChange={e => setNetTopN(Number(e.target.value))}
            className="w-32"
          />
          <Btn onClick={runNetwork} disabled={netLoading || !session}>
            {netLoading ? (
              <><Loader2 size={14} className="animate-spin" /> Building...</>
            ) : (
              'Build Network'
            )}
          </Btn>
        </div>

        {netLoading && (
          <div className="text-sm text-gray-400">Building graph...</div>
        )}

        {netResult?.nodes != null && (
          <div className="flex gap-3 mb-4">
            <StatTile label="Nodes" value={netResult.nodes.toLocaleString()} />
            <StatTile label="Edges" value={netResult.edges.toLocaleString()} />
          </div>
        )}

        {netResult?.images?.length > 0 && (
          <PlotGallery images={netResult.images} />
        )}
      </Card>

      {/* Reply Graph */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <GitBranch size={18} />
          <h3>Reply Graph</h3>
        </div>

        <Btn onClick={runReplyGraph} disabled={replyLoading || !session}>
          {replyLoading ? (
            <><Loader2 size={14} className="animate-spin" /> Building...</>
          ) : (
            'Build Reply Graph'
          )}
        </Btn>

        {replyLoading && (
          <div className="text-sm text-gray-400 mt-2">Building graph...</div>
        )}

        {replyResult?.images?.length > 0 && (
          <PlotGallery images={replyResult.images} />
        )}
      </Card>

    </div>
  )
}
