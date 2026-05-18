import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { getSessionStatus, platformLabel, platformColor, formatRelativeTime } from '../lib/utils'
import { CheckSquare, Clock, ChevronRight, Zap, AlertCircle, BarChart2, TrendingUp } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { SessionSummary, Platform } from '../types'

type Tab = 'all' | Platform

function ApprovalCard({ session }: { session: SessionSummary }) {
  const platformCfg = platformColor(session.platform)

  return (
    <Link
      to={`/approvals/${session.session_id}`}
      className="block bg-white rounded-2xl border border-gray-100 shadow-sm hover:shadow-md hover:border-indigo-200 transition-all group"
    >
      <div className="p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full border ${platformCfg.bg} ${platformCfg.text} ${platformCfg.border}`}>
                {platformLabel(session.platform)}
              </span>
              <span className="text-xs text-gray-400 font-mono">#{session.session_id}</span>
            </div>
            <h3 className="font-semibold text-gray-900 text-lg">
              {session.accounts.map(a => a.name || a.id).join(', ')}
            </h3>
          </div>
          <ChevronRight className="w-5 h-5 text-gray-300 group-hover:text-indigo-500 transition-colors flex-shrink-0 mt-1" />
        </div>

        <div className="space-y-2 mb-4">
          {session.accounts.map(acc => (
            <div key={acc.id} className="flex items-center justify-between text-sm">
              <span className="text-gray-600 truncate">{acc.name || acc.id}</span>
              <span className={`font-semibold ${acc.actions_count > 0 ? 'text-amber-600' : 'text-gray-400'}`}>
                {acc.actions_count > 0 ? `${acc.actions_count} ação(ões)` : 'Sem ações'}
              </span>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between pt-4 border-t border-gray-100">
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <Clock className="w-3.5 h-3.5" />
            <span>{formatRelativeTime(session.created_at)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold bg-amber-50 text-amber-700 px-2.5 py-1 rounded-full border border-amber-200">
              {session.total_actions} otimizações
            </span>
            <span className="text-xs font-medium text-indigo-600 group-hover:underline">
              Revisar →
            </span>
          </div>
        </div>
      </div>
    </Link>
  )
}

const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'all',        label: 'Todas',      icon: CheckSquare },
  { id: 'google_ads', label: 'Google Ads', icon: BarChart2   },
  { id: 'meta_ads',   label: 'Meta Ads',   icon: TrendingUp  },
]

export function Approvals() {
  const [activeTab, setActiveTab] = useState<Tab>('all')

  const { data, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: api.sessions.list,
    refetchInterval: 15_000,
  })

  const allPending = (data?.sessions ?? []).filter(s => getSessionStatus(s) === 'pending')
  const filtered   = activeTab === 'all' ? allPending : allPending.filter(s => s.platform === activeTab)

  const countByPlatform = (platform: Platform) =>
    allPending.filter(s => s.platform === platform).length

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Aprovações Pendentes</h1>
          <p className="text-gray-500 mt-1">Revise e aprove as otimizações propostas pela IA</p>
        </div>
        {allPending.length > 0 && (
          <span className="bg-amber-500 text-white text-sm font-bold px-3 py-1 rounded-full">
            {allPending.length}
          </span>
        )}
      </div>

      {/* Platform tabs */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-xl w-fit">
        {tabs.map(({ id, label, icon: Icon }) => {
          const count = id === 'all' ? allPending.length : countByPlatform(id as Platform)
          return (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                activeTab === id
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
              {count > 0 && (
                <span className={`text-xs font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center ${
                  activeTab === id ? 'bg-amber-500 text-white' : 'bg-gray-300 text-gray-600'
                }`}>
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <div className="text-center">
            <Zap className="w-8 h-8 animate-pulse mx-auto mb-3 opacity-40" />
            <p className="text-sm">Carregando...</p>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm">
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <CheckSquare className="w-10 h-10 mb-4 opacity-30" />
            <p className="font-semibold text-gray-600">Tudo em dia</p>
            <p className="text-sm mt-1">
              {activeTab === 'all'
                ? 'Nenhuma análise aguardando aprovação'
                : `Nenhuma análise de ${platformLabel(activeTab as Platform)} pendente`}
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-amber-500 flex-shrink-0" />
            <p className="text-sm text-amber-800">
              <span className="font-semibold">
                {filtered.reduce((s, p) => s + p.total_actions, 0)} otimizações
              </span>{' '}
              aguardam sua revisão. Clique em uma análise para ver os detalhes e aprovar.
            </p>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {filtered.map(s => <ApprovalCard key={s.session_id} session={s} />)}
          </div>
        </>
      )}
    </div>
  )
}
