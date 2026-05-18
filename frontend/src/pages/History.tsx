import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { getSessionStatus, platformLabel, platformColor, statusConfig, formatDateTime, formatRelativeTime } from '../lib/utils'
import {
  History as HistoryIcon, CheckCircle, XCircle, Clock,
  BarChart2, TrendingUp
} from 'lucide-react'
import type { Platform, SessionStatus } from '../types'

type PlatformTab = 'all' | Platform
type StatusTab   = 'all' | SessionStatus

const platformTabs: { id: PlatformTab; label: string; icon: React.ElementType }[] = [
  { id: 'all',        label: 'Todas',      icon: HistoryIcon },
  { id: 'google_ads', label: 'Google Ads', icon: BarChart2   },
  { id: 'meta_ads',   label: 'Meta Ads',   icon: TrendingUp  },
]

const statusTabs: { id: StatusTab; label: string }[] = [
  { id: 'all',      label: 'Todos'      },
  { id: 'pending',  label: 'Pendentes'  },
  { id: 'executed', label: 'Executados' },
  { id: 'rejected', label: 'Rejeitados' },
]

export function History() {
  const [platformTab, setPlatformTab] = useState<PlatformTab>('all')
  const [statusTab,   setStatusTab]   = useState<StatusTab>('all')

  const { data, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: api.sessions.list,
    refetchInterval: 30_000,
  })

  const sessions = (data?.sessions ?? [])
    .filter(s => platformTab === 'all' || s.platform === platformTab)
    .filter(s => statusTab   === 'all' || getSessionStatus(s) === statusTab)

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Histórico</h1>
        <p className="text-gray-500 mt-1">Registro completo de todas as análises e execuções</p>
      </div>

      {/* Platform tabs */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex gap-1 bg-gray-100 p-1 rounded-xl">
          {platformTabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setPlatformTab(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                platformTab === id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>

        <div className="flex gap-1 bg-gray-100 p-1 rounded-xl">
          {statusTabs.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setStatusTab(id)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                statusTab === id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-gray-400">
            <HistoryIcon className="w-6 h-6 animate-pulse mr-2" />
            <span className="text-sm">Carregando...</span>
          </div>
        ) : sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <HistoryIcon className="w-10 h-10 mb-4 opacity-30" />
            <p className="font-semibold text-gray-600">Nenhum resultado encontrado</p>
            <p className="text-sm mt-1">Tente ajustar os filtros</p>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">Sessão</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Plataforma</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Contas</th>
                <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Ações</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Status</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Data</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {sessions.map(s => {
                const status      = getSessionStatus(s)
                const statusCfg   = statusConfig(status)
                const platformCfg = platformColor(s.platform)
                const StatusIcon  = status === 'executed' ? CheckCircle : status === 'rejected' ? XCircle : Clock

                return (
                  <tr key={s.session_id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4">
                      <span className="font-mono text-xs font-semibold text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
                        #{s.session_id}
                      </span>
                    </td>
                    <td className="px-4 py-4">
                      <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full border ${platformCfg.bg} ${platformCfg.text} ${platformCfg.border}`}>
                        {platformLabel(s.platform)}
                      </span>
                    </td>
                    <td className="px-4 py-4">
                      <p className="text-sm text-gray-700 truncate max-w-[200px]">
                        {s.accounts.map(a => a.name || a.id).join(', ')}
                      </p>
                    </td>
                    <td className="px-4 py-4 text-right">
                      <span className={`text-sm font-semibold ${s.total_actions > 0 ? 'text-gray-900' : 'text-gray-400'}`}>
                        {s.total_actions}
                      </span>
                    </td>
                    <td className="px-4 py-4">
                      <div className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border ${statusCfg.bg} ${statusCfg.text} ${statusCfg.border}`}>
                        <StatusIcon className="w-3 h-3" />
                        {statusCfg.label}
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <p className="text-sm text-gray-600">{formatDateTime(s.created_at)}</p>
                      <p className="text-xs text-gray-400">{formatRelativeTime(s.created_at)}</p>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
