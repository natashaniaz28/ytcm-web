import { NavLink } from 'react-router-dom'
import { clsx } from 'clsx'
import {
  Home, Search, Download, Languages, BarChart3,
  Network, Settings, FileText, Filter, Cpu
} from 'lucide-react'

const NAV = [
  { to: '/',            icon: Home,       label: 'Dashboard' },
  { to: '/search',      icon: Search,     label: 'Search' },
  { to: '/download',    icon: Download,   label: 'Download' },
  { to: '/enrich',      icon: Cpu,        label: 'Enrich' },
  { to: '/filter',      icon: Filter,     label: 'Filter' },
  { to: '/tubescope',   icon: BarChart3,  label: 'TubeScope' },
  { to: '/tubetalk',    icon: Languages,  label: 'TubeTalk' },
  { to: '/tubegraph',   icon: Network,    label: 'TubeGraph' },
  { to: '/export',      icon: FileText,   label: 'Export' },
  { to: '/settings',    icon: Settings,   label: 'Settings' },
]

export default function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-ink-950 border-r border-ink-800 flex flex-col z-50">
      {/* Logo */}
      <div className="px-5 pt-7 pb-6 border-b border-ink-800">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-acid-500 rounded-lg flex items-center justify-center flex-shrink-0">
            <span className="text-ink-950 font-display text-sm font-bold">Y</span>
          </div>
          <div>
            <p className="font-display text-ink-50 text-base leading-none">YTCM</p>
            <p className="text-ink-500 text-xs font-mono mt-0.5">Comment Miner</p>
          </div>
        </div>
      </div>

      {/* Nav links */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-body transition-all duration-150',
                isActive
                  ? 'bg-acid-500/15 text-acid-400 border border-acid-500/25'
                  : 'text-ink-400 hover:text-ink-200 hover:bg-ink-800'
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Bottom version badge */}
      <div className="px-5 py-4 border-t border-ink-800">
        <p className="text-ink-600 text-xs font-mono">v1.0.0 · local</p>
      </div>
    </aside>
  )
}
