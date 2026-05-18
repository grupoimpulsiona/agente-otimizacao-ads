import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LayoutDashboard, CheckSquare, History, Settings, Zap,
  ChevronRight, BarChart2, TrendingUp
} from 'lucide-react'
import { cn } from '../../lib/utils'
import { getSessionStatus } from '../../types'
import { api } from '../../lib/api'

function NavItem({
  to,
  icon: Icon,
  label,
  end,
  badge,
}: {
  to: string
  icon: React.ElementType
  label: string
  end?: boolean
  badge?: number
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all group',
          isActive
            ? 'bg-indigo-600 text-white'
            : 'text-slate-400 hover:text-white hover:bg-slate-800'
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon className="w-4 h-4 flex-shrink-0" />
          <span className="flex-1">{label}</span>
          {badge != null && badge > 0 && (
            <span className={cn(
              'text-xs font-bold px-1.5 py-0.5 rounded-full min-w-[20px] text-center',
              isActive ? 'bg-white/20 text-white' : 'bg-amber-500 text-white'
            )}>
              {badge}
            </span>
          )}
          {!badge && isActive && <ChevronRight className="w-3 h-3 opacity-60" />}
        </>
      )}
    </NavLink>
  )
}

function SectionLabel({ label }: { label: string }) {
  return (
    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 pt-5 pb-1">
      {label}
    </p>
  )
}

export function Sidebar() {
  const { data } = useQuery({
    queryKey: ['sessions'],
    queryFn: api.sessions.list,
    refetchInterval: 30_000,
  })

  const pending = (data?.sessions ?? []).filter(s => getSessionStatus(s) === 'pending').length
  const googlePending = (data?.sessions ?? []).filter(
    s => s.platform === 'google_ads' && getSessionStatus(s) === 'pending'
  ).length
  const metaPending = (data?.sessions ?? []).filter(
    s => s.platform === 'meta_ads' && getSessionStatus(s) === 'pending'
  ).length

  return (
    <aside className="fixed inset-y-0 left-0 z-50 w-64 bg-slate-900 flex flex-col">
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-slate-800">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center flex-shrink-0">
          <Zap className="w-4 h-4 text-white" />
        </div>
        <div>
          <p className="text-white font-semibold text-sm leading-tight">Ads Agent</p>
          <p className="text-slate-400 text-xs">Otimização com IA</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
        <SectionLabel label="Geral" />
        <NavItem to="/" icon={LayoutDashboard} label="Dashboard" end />
        <NavItem to="/approvals" icon={CheckSquare} label="Aprovações" badge={pending} />

        <SectionLabel label="Plataformas" />
        <NavItem to="/google-ads" icon={BarChart2} label="Google Ads" badge={googlePending} />
        <NavItem to="/meta-ads" icon={TrendingUp} label="Meta Ads" badge={metaPending} />

        <SectionLabel label="Mais" />
        <NavItem to="/history" icon={History} label="Histórico" />
        <NavItem to="/settings" icon={Settings} label="Configurações" />
      </nav>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-slate-800">
        <p className="text-slate-500 text-xs text-center">v2.0 · Impulsiona</p>
      </div>
    </aside>
  )
}
