import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { getSessionStatus, platformLabel, platformColor, formatRelativeTime } from '../lib/utils'
import { CheckSquare, Clock, ChevronRight, Zap, AlertCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { SessionSummary } from '../types'

function ApprovalCard({ session }: { session: SessionSummary }) {
  const platformCfg = platformColor(session.platform)
  const googleAccounts = session.accounts.filter(a => a.id && !a.id.startsWith('act_'))
  const metaAccounts = session.accounts.filter(a => a.id && a.id.startsWith('act_'))
  const accounts = session.platform === 'google_ads' ? googleAccounts : metaAccounts

  return (
    <Link
      to={`/approvals/${session.session_id}`}
      className="block bg-white rounded-2xl border border-gray-100 shadow-sm hover:shadow-md hover:border-indigo-200 transition-all group"
    >
      <div className="p-6">
        {/* Header */}
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

        {/* Accounts breakdown */}
        <div className="space-y-2 mb-4">
          {session.accounts.map(acc => (
            <div key={acc.id} className="flex items-center justify-between text-sm">
              <span className="text-gray-600 truncate">{acc.name || acc.id}</span>
              <span className={`font-semibold ${acc.actions_count > 0 ? 'text-amber-600' : 'text-gray-400'}`}>
                {acc.actions_count > 0 ? `${acc.actions_count} ação${acc.actions_count > 1 ? 'ões' : ''}` : 'Sem ações'}
              </span>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-4 border-t border-gray-100">
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <Clock className="w-3.5 h-3.5" />
            <span>{formatRelativeTime(session.created_at)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-gray-900 bg-amber-50 text-amber-700 px-2.5 py-1 rounded-full border border-amber-200">
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

export function Approvals() {
  const { data, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: api.sessions.list,
    refetchInterval: 15_000,
  })

  const pending = (data?.sessions ?? []).filter(s => getSessionStatus(s) === 'pending')

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Aprovações Pendentes</h1>
          <p className="text-gray-500 mt-1">Revise e aprove as otimizações propostas pela IA</p>
        </div>
        {pending.length > 0 && (
          <span className="bg-amber-500 text-white text-sm font-bold px-3 py-1 rounded-full">
            {pending.length}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <div className="text-center">
            <Zap className="w-8 h-8 animate-pulse mx-auto mb-3 opacity-40" />
            <p className="text-sm">Carregando...</p>
          </div>
        </div>
      ) : pending.length === 0 ? (
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm">
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <CheckSquare className="w-10 h-10 mb-4 opacity-30" />
            <p className="font-semibold text-gray-600">Tudo em dia</p>
            <p className="text-sm mt-1">Nenhuma análise aguardando aprovação</p>
          </div>
        </div>
      ) : (
        <>
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-amber-500 flex-shrink-0" />
            <p className="text-sm text-amber-800">
              <span className="font-semibold">{pending.reduce((s, p) => s + p.total_actions, 0)} otimizações</span> aguardam sua revisão.
              Clique em uma análise para ver os detalhes e aprovar.
            </p>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {pending.map(s => (
              <ApprovalCard key={s.session_id} session={s} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
