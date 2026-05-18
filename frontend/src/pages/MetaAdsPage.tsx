import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { getSessionStatus, formatRelativeTime, formatDateTime, statusConfig } from '../lib/utils'
import {
  TrendingUp, CheckCircle, Clock, Zap, Activity,
  AlertCircle, ChevronRight, Play, XCircle
} from 'lucide-react'
import type { SessionSummary } from '../types'

function StatCard({
  label, value, icon: Icon, color,
}: { label: string; value: number; icon: React.ElementType; color: string }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
          <p className="text-3xl font-bold text-gray-900 mt-1">{value}</p>
        </div>
        <div className={`w-11 h-11 rounded-xl flex items-center justify-center ${color}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
    </div>
  )
}

function PendingCard({ session }: { session: SessionSummary }) {
  return (
    <Link
      to={`/approvals/${session.session_id}`}
      className="block bg-white rounded-2xl border-2 border-amber-200 shadow-sm hover:shadow-md hover:border-amber-300 transition-all group"
    >
      <div className="p-5">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <span className="text-xs font-bold text-amber-600 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
              Aguardando Aprovação
            </span>
            <p className="text-sm font-semibold text-gray-900 mt-2">
              {session.accounts.map(a => a.name || a.id).join(', ')}
            </p>
          </div>
          <ChevronRight className="w-5 h-5 text-gray-300 group-hover:text-amber-500 flex-shrink-0 mt-1 transition-colors" />
        </div>
        <div className="space-y-1.5 mb-3">
          {session.accounts.map(acc => (
            <div key={acc.id} className="flex items-center justify-between text-xs">
              <span className="text-gray-500 truncate">{acc.name || acc.id}</span>
              <span className={`font-semibold ${acc.actions_count > 0 ? 'text-amber-600' : 'text-gray-400'}`}>
                {acc.actions_count > 0 ? `${acc.actions_count} ação(ões)` : 'Sem ações'}
              </span>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between pt-3 border-t border-gray-100">
          <div className="flex items-center gap-1 text-xs text-gray-400">
            <Clock className="w-3 h-3" />
            {formatRelativeTime(session.created_at)}
          </div>
          <span className="text-xs font-bold text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-full">
            {session.total_actions} otimizações
          </span>
        </div>
      </div>
    </Link>
  )
}

function HistoryRow({ session }: { session: SessionSummary }) {
  const status     = getSessionStatus(session)
  const statusCfg  = statusConfig(status)
  const StatusIcon = status === 'executed' ? CheckCircle : status === 'rejected' ? XCircle : Clock

  return (
    <div className="flex items-center gap-4 px-6 py-4 hover:bg-gray-50 transition-colors">
      <div className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border flex-shrink-0 ${statusCfg.bg} ${statusCfg.text} ${statusCfg.border}`}>
        <StatusIcon className="w-3 h-3" />
        {statusCfg.label}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">
          {session.accounts.map(a => a.name || a.id).join(', ')}
        </p>
        <p className="text-xs text-gray-400">{formatDateTime(session.created_at)}</p>
      </div>
      <div className="text-right flex-shrink-0">
        <p className="text-sm font-semibold text-gray-900">{session.total_actions}</p>
        <p className="text-xs text-gray-400">ações</p>
      </div>
      <span className="font-mono text-xs text-gray-400 hidden sm:block">#{session.session_id}</span>
    </div>
  )
}

export function MetaAdsPage() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: api.sessions.list,
    refetchInterval: 30_000,
  })

  const triggerMutation = useMutation({
    mutationFn: api.analyze.trigger,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sessions'] }),
  })

  const all       = (data?.sessions ?? []).filter(s => s.platform === 'meta_ads')
  const pending   = all.filter(s => getSessionStatus(s) === 'pending')
  const executed  = all.filter(s => getSessionStatus(s) === 'executed')
  const totalActs = executed.reduce((sum, s) => sum + s.total_actions, 0)
  const history   = all.filter(s => getSessionStatus(s) !== 'pending').slice(0, 10)

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-violet-500 rounded-xl flex items-center justify-center">
            <TrendingUp className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Meta Ads</h1>
            <p className="text-gray-500 text-sm mt-0.5">Facebook, Instagram e Audience Network</p>
          </div>
        </div>
        <button
          onClick={() => triggerMutation.mutate()}
          disabled={triggerMutation.isPending}
          className="flex items-center gap-2 px-4 py-2.5 bg-violet-600 text-white rounded-xl text-sm font-semibold hover:bg-violet-700 disabled:opacity-60 transition-colors shadow-sm"
        >
          {triggerMutation.isPending
            ? <Activity className="w-4 h-4 animate-spin" />
            : <Play className="w-4 h-4" />}
          Analisar agora
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Sessões"         value={all.length}      icon={Activity}    color="bg-violet-50 text-violet-500" />
        <StatCard label="Executadas"      value={executed.length} icon={CheckCircle} color="bg-green-50 text-green-500" />
        <StatCard label="Ações aplicadas" value={totalActs}       icon={TrendingUp}  color="bg-indigo-50 text-indigo-500" />
        <StatCard label="Pendentes"       value={pending.length}  icon={Clock}       color="bg-amber-50 text-amber-500" />
      </div>

      {/* Pending approvals */}
      {pending.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-amber-500" />
            <h2 className="font-semibold text-gray-900">
              {pending.length} análise{pending.length > 1 ? 's' : ''} aguardando aprovação
            </h2>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {pending.map(s => <PendingCard key={s.session_id} session={s} />)}
          </div>
        </div>
      )}

      {/* History */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Histórico Meta Ads</h2>
          <Link to="/history" className="text-sm text-violet-600 hover:text-violet-700 font-medium">
            Ver tudo →
          </Link>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-gray-400">
            <Activity className="w-5 h-5 animate-spin mr-2" />
            <span className="text-sm">Carregando...</span>
          </div>
        ) : history.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-gray-400">
            <Zap className="w-8 h-8 mb-3 opacity-30" />
            <p className="text-sm font-medium">Nenhuma execução ainda</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {history.map(s => <HistoryRow key={s.session_id} session={s} />)}
          </div>
        )}
      </div>
    </div>
  )
}
