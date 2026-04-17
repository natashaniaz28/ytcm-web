import { clsx } from 'clsx'
import { Loader2, AlertTriangle, CheckCircle2, ChevronRight } from 'lucide-react'

// ── Card ─────────────────────────────────────────────────────────────────────
export function Card({ children, className, ...props }) {
  return (
    <div
      className={clsx(
        'bg-ink-900 border border-ink-700 rounded-2xl p-6',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

// ── Section heading ───────────────────────────────────────────────────────────
export function SectionTitle({ children, sub }) {
  return (
    <div className="mb-6">
      <h2 className="font-display text-2xl text-ink-50">{children}</h2>
      {sub && <p className="text-ink-400 text-sm mt-1 font-body">{sub}</p>}
    </div>
  )
}

// ── Button ────────────────────────────────────────────────────────────────────
export function Btn({ children, onClick, disabled, variant = 'primary', size = 'md', className, ...props }) {
  const base = 'inline-flex items-center gap-2 font-body font-medium rounded-xl transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-acid-500/40'
  const sizes = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-5 py-2.5 text-sm',
    lg: 'px-7 py-3.5 text-base',
  }
  const variants = {
    primary: 'bg-acid-500 text-ink-950 hover:bg-acid-400 disabled:opacity-40 disabled:cursor-not-allowed',
    ghost:   'bg-ink-800 text-ink-200 hover:bg-ink-700 border border-ink-600 disabled:opacity-40 disabled:cursor-not-allowed',
    danger:  'bg-coral-500/20 text-coral-400 hover:bg-coral-500/30 border border-coral-500/30 disabled:opacity-40',
    success: 'bg-teal-500/20 text-teal-400 hover:bg-teal-500/30 border border-teal-500/30 disabled:opacity-40',
  }
  return (
    <button
      className={clsx(base, sizes[size], variants[variant], className)}
      onClick={onClick}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  )
}

// ── Input ─────────────────────────────────────────────────────────────────────
export function Input({ label, className, ...props }) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <label className="text-xs text-ink-400 font-body uppercase tracking-wider">{label}</label>}
      <input
        className={clsx(
          'bg-ink-800 border border-ink-600 rounded-xl px-4 py-2.5 text-sm text-ink-100',
          'font-mono placeholder:text-ink-500 focus:outline-none focus:border-acid-500/60',
          'transition-colors duration-200',
          className
        )}
        {...props}
      />
    </div>
  )
}

// ── Select ────────────────────────────────────────────────────────────────────
export function Select({ label, className, children, ...props }) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <label className="text-xs text-ink-400 font-body uppercase tracking-wider">{label}</label>}
      <select
        className={clsx(
          'bg-ink-800 border border-ink-600 rounded-xl px-4 py-2.5 text-sm text-ink-100',
          'font-body focus:outline-none focus:border-acid-500/60 transition-colors duration-200',
          className
        )}
        {...props}
      >
        {children}
      </select>
    </div>
  )
}

// ── Job progress bar ──────────────────────────────────────────────────────────
export function JobProgress({ jobState }) {
  if (!jobState) return null
  const { status, progress = 0, total = 0, message, error } = jobState
  const pct = total > 0 ? Math.round((progress / total) * 100) : null

  return (
    <div className="mt-4 space-y-2">
      {/* Status row */}
      <div className="flex items-center gap-2 text-sm">
        {status === 'pending' || status === 'running' ? (
          <Loader2 size={14} className="animate-spin text-acid-500" />
        ) : status === 'done' ? (
          <CheckCircle2 size={14} className="text-teal-500" />
        ) : (
          <AlertTriangle size={14} className="text-coral-500" />
        )}
        <span className={clsx(
          'font-mono text-xs',
          status === 'done' ? 'text-teal-400' :
          status === 'error' ? 'text-coral-400' : 'text-ink-300'
        )}>
          {error || message || status}
        </span>
      </div>

      {/* Progress bar */}
      {total > 0 && (
        <div className="h-1.5 bg-ink-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-acid-500 rounded-full transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
      {pct !== null && (
        <p className="text-xs text-ink-500 font-mono">{progress}/{total} — {pct}%</p>
      )}
    </div>
  )
}

// ── Plot image gallery ────────────────────────────────────────────────────────
export function PlotGallery({ images, loading, error }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 border border-ink-700 rounded-2xl">
        <div className="flex flex-col items-center gap-3 text-ink-400">
          <Loader2 size={24} className="animate-spin text-acid-500" />
          <span className="text-sm font-body">Generating plots…</span>
        </div>
      </div>
    )
  }
  if (error) {
    return (
      <div className="flex items-center gap-3 p-4 bg-coral-500/10 border border-coral-500/20 rounded-2xl text-coral-400 text-sm">
        <AlertTriangle size={16} />
        {error}
      </div>
    )
  }
  if (!images || images.length === 0) return null
  return (
    <div className="space-y-4">
      {images.map((src, i) => (
        <div key={i} className="border border-ink-700 rounded-2xl overflow-hidden bg-ink-800/40">
          <img src={src} alt={`Plot ${i + 1}`} className="w-full" />
        </div>
      ))}
    </div>
  )
}

// ── Stat tile ─────────────────────────────────────────────────────────────────
export function StatTile({ label, value, sub, accent }) {
  return (
    <div className="bg-ink-900 border border-ink-700 rounded-2xl p-5 flex flex-col gap-1">
      <span className="text-xs uppercase tracking-widest text-ink-500 font-body">{label}</span>
      <span className={clsx('text-3xl font-display', accent || 'text-ink-50')}>{value ?? '—'}</span>
      {sub && <span className="text-xs text-ink-500 font-mono">{sub}</span>}
    </div>
  )
}

// ── File badge ────────────────────────────────────────────────────────────────
export function FileBadge({ name, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono transition-all',
        active
          ? 'bg-acid-500/20 text-acid-400 border border-acid-500/40'
          : 'bg-ink-800 text-ink-400 border border-ink-600 hover:border-ink-500'
      )}
    >
      <ChevronRight size={10} />
      {name}
    </button>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────
export function Empty({ message = 'No data available.', icon }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-ink-500 gap-3">
      {icon && <div className="text-ink-600">{icon}</div>}
      <p className="text-sm font-body">{message}</p>
    </div>
  )
}

// ── Tag ───────────────────────────────────────────────────────────────────────
export function Tag({ children, color = 'default' }) {
  const colors = {
    default: 'bg-ink-800 text-ink-300 border-ink-600',
    green:   'bg-teal-500/10 text-teal-400 border-teal-500/20',
    red:     'bg-coral-500/10 text-coral-400 border-coral-500/20',
    yellow:  'bg-acid-500/10 text-acid-400 border-acid-500/20',
  }
  return (
    <span className={clsx('inline-block px-2 py-0.5 text-xs rounded-md border font-mono', colors[color])}>
      {children}
    </span>
  )
}
