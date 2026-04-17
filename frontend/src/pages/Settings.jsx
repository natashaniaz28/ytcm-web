import { useState, useEffect } from 'react'
import { api } from '../api'
import { Card, SectionTitle, Btn, Input, Tag } from '../components/ui'
import { Key, CheckCircle2, AlertTriangle, Shield, ExternalLink, Cloud, Monitor } from 'lucide-react'

export default function SettingsPage() {
  const [apiKey, setApiKey]       = useState('')
  const [keyExists, setKeyExists] = useState(null)
  const [saving, setSaving]       = useState(false)
  const [saveResult, setSaveResult] = useState(null)
  const [health, setHealth]       = useState(null)
  const [config, setConfig]       = useState(null)

  useEffect(() => {
    api.checkApiKey().then(r => setKeyExists(r.exists)).catch(() => setKeyExists(false))
    api.health().then(setHealth).catch(() => {})
    api.getConfig().then(setConfig).catch(() => {})
  }, [])

  const isCloud = health?.cloud === true

  async function saveKey() {
    if (!apiKey.trim()) return
    setSaving(true)
    setSaveResult(null)
    try {
      await api.saveApiKey(apiKey.trim())
      setSaveResult('saved')
      setKeyExists(true)
      setApiKey('')
    } catch (e) {
      setSaveResult('error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6 animate-fade-up">
      <SectionTitle sub="Configure your API key and review system status">Settings</SectionTitle>

      {/* Deployment mode banner */}
      <Card>
        <div className="flex items-center gap-3">
          {isCloud
            ? <Cloud size={16} className="text-acid-400" />
            : <Monitor size={16} className="text-teal-400" />
          }
          <div>
            <p className="text-sm font-body font-medium text-ink-200">
              {isCloud ? 'Running on Render (cloud)' : 'Running locally'}
            </p>
            <p className="text-xs text-ink-500 mt-0.5">
              {isCloud
                ? 'Data is stored in memory per-session. Upload your Comments.json on the Dashboard to analyse existing data.'
                : 'Data is saved to disk in the backend/ folder between sessions.'}
            </p>
          </div>
        </div>
      </Card>

      {/* System status */}
      <Card>
        <h3 className="text-sm font-body font-medium text-ink-200 mb-4">System Status</h3>
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: 'API Backend',    ok: !!health,               yes: 'online',     no: 'offline'  },
            { label: 'YTCM Modules',   ok: health?.ytcm_modules,   yes: 'loaded',     no: 'missing'  },
            { label: 'YouTube API Key',ok: keyExists,              yes: 'configured', no: 'missing'  },
          ].map(({ label, ok, yes, no }) => (
            <div key={label} className="bg-ink-800 rounded-xl p-3 border border-ink-700">
              <p className="text-xs text-ink-500 font-body mb-1.5">{label}</p>
              <div className="flex items-center gap-1.5">
                {ok ? <CheckCircle2 size={13} className="text-teal-500" /> : <AlertTriangle size={13} className="text-coral-400" />}
                <span className={`text-sm font-mono ${ok ? 'text-teal-400' : 'text-coral-400'}`}>{ok ? yes : no}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* API Key */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Key size={15} className="text-acid-400" />
          <h3 className="text-sm font-body font-medium text-ink-200">YouTube Data API v3 Key</h3>
        </div>

        {/* Cloud instruction */}
        {isCloud && (
          <div className="mb-4 p-4 bg-ink-800 border border-ink-700 rounded-xl space-y-2 text-xs font-body text-ink-400">
            <p className="text-ink-200 font-medium flex items-center gap-1.5"><Cloud size={12} /> On Render (recommended)</p>
            <p>Set <code className="font-mono bg-ink-900 px-1 rounded">YOUTUBE_API_KEY</code> as an environment variable in your Render service dashboard.</p>
            <p>This persists across restarts. The form below only lasts until the next restart.</p>
            <a href="https://dashboard.render.com" target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-acid-400 underline">
              Open Render Dashboard <ExternalLink size={10} />
            </a>
          </div>
        )}

        {keyExists && (
          <div className="flex items-center gap-2 mb-4 p-3 bg-teal-500/10 border border-teal-500/20 rounded-xl">
            <CheckCircle2 size={14} className="text-teal-500" />
            <p className="text-sm text-teal-400 font-body">API key is configured. Enter a new one below to replace it.</p>
          </div>
        )}

        <div className="space-y-4">
          <Input label="API Key" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="AIza…" />

          {saveResult === 'saved' && (
            <div className="flex items-center gap-2 p-3 bg-teal-500/10 border border-teal-500/20 rounded-xl text-sm text-teal-400">
              <CheckCircle2 size={14} />
              {isCloud ? 'Saved in memory for this session.' : 'API key saved to YOUTUBE.API file.'}
            </div>
          )}
          {saveResult === 'error' && (
            <div className="flex items-center gap-2 p-3 bg-coral-500/10 border border-coral-500/20 rounded-xl text-sm text-coral-400">
              <AlertTriangle size={14} /> Failed to save. Check the backend is running.
            </div>
          )}
          <Btn onClick={saveKey} disabled={saving || !apiKey.trim()}>
            <Key size={14} /> {saving ? 'Saving…' : 'Save API Key'}
          </Btn>
        </div>

        <div className="mt-5 pt-5 border-t border-ink-800 space-y-2 text-xs text-ink-500 font-body">
          <p className="flex items-start gap-1.5">
            <Shield size={12} className="flex-shrink-0 mt-0.5 text-ink-600" />
            {isCloud
              ? 'On Render, use the environment variable for persistence. Keys set here are lost on restart.'
              : 'Your API key is saved locally to backend/YOUTUBE.API and never leaves your machine.'}
          </p>
          <p>
            Don't have a key?{' '}
            <a href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer"
              className="text-acid-400 underline inline-flex items-center gap-0.5">
              Google Cloud Console <ExternalLink size={10} />
            </a>
            {' '}→ enable YouTube Data API v3 → Create credentials. Free quota: 10,000 units/day.
          </p>
        </div>
      </Card>

      {config && (
        <Card>
          <h3 className="text-sm font-body font-medium text-ink-200 mb-4">Current Configuration</h3>
          <div className="space-y-3 text-xs font-mono">
            <Row label="Version date"  value={config.version_date} />
            <Row label="Search year"   value={config.search_year} />
            <Row label="Cloud mode"    value={String(config.cloud_mode)} />
            {config.primary_terms?.length > 0 && (
              <div className="pt-2">
                <p className="text-ink-500 mb-1.5">Primary search terms</p>
                <div className="flex flex-wrap gap-1.5">
                  {config.primary_terms.map((g, i) => <Tag key={i}>{g.join(' + ')}</Tag>)}
                </div>
              </div>
            )}
          </div>
          <p className="text-xs text-ink-600 font-body mt-4">
            To change default terms, edit <code className="font-mono bg-ink-800 px-1 rounded">backend/YTCM_config.py</code>.
          </p>
        </Card>
      )}
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-ink-800">
      <span className="text-ink-500">{label}</span>
      <span className="text-ink-300">{String(value ?? '—')}</span>
    </div>
  )
}