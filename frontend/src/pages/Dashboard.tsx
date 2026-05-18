import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { formatRelativeTime, getSessionStatus, platformLabel, platformColor, statusConfig } from '../lib/utils'
import { CheckCircle, Clock, XCircle, Zap, TrendingUp, Activity, AlertCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { SessionSummary } from '../types'

function StatCard({ label, value, icon: Icon, color }: { label: string; value: number | string; icon: React.ElementType; color: string }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-gray-500">{label}</p>
          <p className="text-3xl font-bold text-gray-900 mt-1">{value}</p>
        </div>
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${color}`}>
          <Icon className="w-6 h-6" />
        </div>
      </div>
    </div>
  )
}

function SessionRow({ session }: { session: SessionSummary }) {
  const status = getSessionStatus(session)
  const statusCfg = statusConfig(status)
  const platformCfg = platformColor(session.platform)

  return (
    <Link
      to={status === 'pending' ? `/approvals/${session.session_id}` : '#'}
      className="flex items-center gap-4 p-4 rounded-xl hover:bg-gray-50 transition-colors group"
    >
      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${statusCfg.dot}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${platformCfg.bg} ${platformCfg.text} ${platformCfg.border}`}>
            {platformLabel(session.platform)}
          </span>
          <span className="text-xs text-gray-400">#{session.session_id}</span>
        </div>
        <p className="text-sm font-medium text-gray-900 truncate">
          {session.accounts.map(a => a.name || a.id).join(', ')}
        </p>
      </div>
      <div className="text-right flex-shrink-0">
        <p className="text-sm font-semibold text-gray-900">{session.total_actions} ações</p>
        <p className="text-xs text-gray-400">{formatRelativeTime(session.created_at)}</p>
      </div>
      <span className={`text-xs font-medium px-2.5 py-1 rounded-full border flex-shrink-0 ${statusCfg.bg} ${statusCfg.text} ${statusCfg.border}`}>
        {statusCfg.label}
      </span>
    </Link>
  )
}

export function Dashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['sessions'],
    queryFn: api.sessions.list,
    refetchInterval: 30_000,
  })

  const sessions = data?.sessions ?? []
  const pending = sessions.filter(s => getSessionStatus(s) === 'pending')
  const executed = sessions.filter(s => getSessionStatus(s) === 'executed')
  const totalActions = executed.reduce((sum, s) => sum + s.total_actions, 0)

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 mt-1">Visão geral das otimizações de anúncios</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Aguardando Aprovação"
          value={pending.length}
          icon={Clock}
          color="bg-amber-50 text-amber-500"
        />
        <StatCard
          label="Sessões Executadas"
          value={executed.length}
          icon={CheckCircle}
          color="bg-green-50 text-green-500"
        />
        <StatCard
          label="Total de Ações"
          value={totalActions}
          icon={TrendingUp}
          color="bg-indigo-50 text-indigo-500"
        />
        <StatCard
          label="Total de Sessões"
          value={sessions.length}
          icon={Activity}
          color="bg-slate-100 text-slate-500"
        />
      </div>

      {/* Pending alert */}
      {pending.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 flex items-center gap-4">
          <AlertCircle className="w-5 h-5 text-amber-500 flex-shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-amber-800">
              {pending.length} análise{pending.length > 1 ? 's' : ''} aguardando sua aprovação
            </p>
            <p className="text-xs text-amber-600 mt-0.5">
              {pending.reduce((s, p) => s + p.total_actions, 0)} otimizações propostas no total
            </p>
          </div>
          <Link
            to="/approvals"
            className="flex-shrink-0 bg-amber-500 text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-amber-600 transition-colors"
          >
            Revisar
          </Link>
        </div>
      )}

      {/* Recent sessions */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Sessões Recentes</h2>
          <Link to="/history" className="text-sm text-indigo-600 hover:text-indigo-700 font-medium">
            Ver tudo →
          </Link>
        </div>
        <div className="p-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-12 text-gray-400">
              <Activity className="w-5 h-5 animate-spin mr-2" />
              <span className="text-sm">Carregando...</span>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-12 text-red-400 gap-2">
              <XCircle className="w-5 h-5" />
              <span className="text-sm">Erro ao carregar sessões. Verifique a conexão com a API.</span>
            </div>
          ) : sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400">
              <Zap className="w-8 h-8 mb-3 opacity-30" />
              <p className="text-sm font-medium">Nenhuma sessão ainda</p>
              <p className="text-xs mt-1">Execute uma análise para começar</p>
            </div>
          ) : (
            sessions.slice(0, 8).map(s => <SessionRow key={s.session_id} session={s} />)
          )}
        </div>
      </div>
    </div>
  )
}
