import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { formatDateTime, platformLabel, platformColor } from '../lib/utils'
import {
  FileSpreadsheet, ExternalLink, TrendingUp, BarChart2, Zap,
  Activity, ChevronDown, ChevronUp, CheckCircle, Info
} from 'lucide-react'
import type { ReportExecution, ReportAccount } from '../types'

const SHEETS_URL = import.meta.env.VITE_SHEETS_URL || ''

// ── Sub-componentes ───────────────────────────────────────────────────────────

function StatCard({
  label, value, sub, icon: Icon, color,
}: { label: string; value: string | number; sub?: string; icon: React.ElementType; color: string }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-gray-500">{label}</p>
          <p className="text-3xl font-bold text-gray-900 mt-1">{value}</p>
          {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
        </div>
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${color}`}>
          <Icon className="w-6 h-6" />
        </div>
      </div>
    </div>
  )
}

function PlatformBar({
  platform, execucoes, acoes, maxAcoes,
}: { platform: string; execucoes: number; acoes: number; maxAcoes: number }) {
  const pCfg     = platformColor(platform as 'google_ads' | 'meta_ads')
  const label    = platformLabel(platform as 'google_ads' | 'meta_ads')
  const pct      = maxAcoes > 0 ? Math.round((acoes / maxAcoes) * 100) : 0
  const barColor = platform === 'google_ads' ? 'bg-blue-500' : 'bg-violet-500'

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full border ${pCfg.bg} ${pCfg.text} ${pCfg.border}`}>
            {label}
          </span>
          <span className="text-gray-500">{execucoes} execução{execucoes !== 1 ? 'ões' : ''}</span>
        </div>
        <span className="font-semibold text-gray-900">{acoes} ações</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function AccountRow({
  name, platform, execucoes, acoes,
}: { name: string; platform: string; execucoes: number; acoes: number }) {
  const pCfg = platformColor(platform as 'google_ads' | 'meta_ads')
  return (
    <div className="flex items-center gap-3 py-3 border-b border-gray-50 last:border-0">
      <span className={`text-xs font-medium px-2 py-0.5 rounded-full border flex-shrink-0 ${pCfg.bg} ${pCfg.text} ${pCfg.border}`}>
        {platformLabel(platform as 'google_ads' | 'meta_ads')}
      </span>
      <span className="flex-1 text-sm font-medium text-gray-800 truncate">{name}</span>
      <span className="text-xs text-gray-400">{execucoes}×</span>
      <span className="text-sm font-bold text-gray-900 w-16 text-right">{acoes} ações</span>
    </div>
  )
}

function ActionBadge({ description }: { description: string }) {
  const getColor = () => {
    const d = description.toLowerCase()
    if (d.includes('pausar') || d.includes('pause'))       return 'bg-red-50 text-red-700 border-red-200'
    if (d.includes('lance') || d.includes('bid'))          return 'bg-blue-50 text-blue-700 border-blue-200'
    if (d.includes('negativ'))                             return 'bg-orange-50 text-orange-700 border-orange-200'
    if (d.includes('ativar') || d.includes('enable'))      return 'bg-green-50 text-green-700 border-green-200'
    return 'bg-gray-50 text-gray-700 border-gray-200'
  }
  return (
    <span className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-md border ${getColor()}`}>
      {description}
    </span>
  )
}

function ExecutionRow({ execution }: { execution: ReportExecution }) {
  const [expanded, setExpanded] = useState(false)
  const pCfg = platformColor(execution.platform)

  return (
    <div className="border-b border-gray-50 last:border-0">
      {/* Row header */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-4 px-6 py-4 hover:bg-gray-50 transition-colors text-left"
      >
        <div className="w-5 h-5 flex-shrink-0 text-gray-300">
          {expanded
            ? <ChevronUp className="w-5 h-5 text-indigo-500" />
            : <ChevronDown className="w-5 h-5" />
          }
        </div>

        {/* Date */}
        <div className="w-36 flex-shrink-0">
          <p className="text-sm font-medium text-gray-900">
            {formatDateTime(execution.executed_at || execution.created_at)}
          </p>
        </div>

        {/* Platform */}
        <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full border flex-shrink-0 ${pCfg.bg} ${pCfg.text} ${pCfg.border}`}>
          {platformLabel(execution.platform)}
        </span>

        {/* Accounts */}
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-700 truncate">
            {execution.accounts.map(a => a.account_name || a.account_id).join(', ')}
          </p>
        </div>

        {/* Actions count */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {execution.total_actions > 0 ? (
            <span className="flex items-center gap-1 text-sm font-semibold text-green-700 bg-green-50 border border-green-200 px-2.5 py-1 rounded-full">
              <Zap className="w-3 h-3" />
              {execution.total_actions} ações
            </span>
          ) : (
            <span className="text-xs text-gray-400">Sem ações</span>
          )}
        </div>

        {/* Session ID */}
        <span className="font-mono text-xs text-gray-400 hidden lg:block flex-shrink-0">
          #{execution.session_id}
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-6 pb-5 bg-gray-50 border-t border-gray-100">
          {execution.accounts.map((acc: ReportAccount, ai) => (
            <div key={ai} className="mt-4">
              {/* Account header */}
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
                <span className="text-sm font-semibold text-gray-800">
                  {acc.account_name || acc.account_id}
                </span>
                <span className="text-xs text-gray-400">
                  {acc.actions_count} ação{acc.actions_count !== 1 ? 'ões' : ''}
                </span>
              </div>

              {/* Actions list */}
              {acc.actions_detail.length > 0 ? (
                <div className="flex flex-wrap gap-1.5 pl-6">
                  {acc.actions_detail.map((action, idx) => (
                    <ActionBadge key={idx} description={action.description} />
                  ))}
                </div>
              ) : (
                <p className="text-xs text-gray-400 pl-6 italic">Nenhuma ação registrada</p>
              )}

              {/* Summary preview */}
              {acc.summary && (
                <details className="pl-6 mt-2">
                  <summary className="text-xs font-medium text-indigo-600 cursor-pointer flex items-center gap-1 hover:text-indigo-700">
                    <Info className="w-3 h-3" /> Ver análise completa
                  </summary>
                  <pre className="mt-2 text-xs text-gray-600 whitespace-pre-wrap bg-white rounded-lg border border-gray-100 p-3 max-h-40 overflow-y-auto">
                    {acc.summary}
                  </pre>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────────────

export function Relatorios() {
  const [platformFilter, setPlatformFilter] = useState<'all' | 'google_ads' | 'meta_ads'>('all')

  const { data, isLoading } = useQuery({
    queryKey: ['reports'],
    queryFn: api.reports.get,
    refetchInterval: 60_000,
  })

  const executions = (data?.executions ?? []).filter(
    e => platformFilter === 'all' || e.platform === platformFilter
  )

  const googleStats = data?.platform_stats?.['google_ads']
  const metaStats   = data?.platform_stats?.['meta_ads']
  const maxAcoes    = Math.max(
    googleStats?.acoes ?? 0,
    metaStats?.acoes   ?? 0,
    1
  )

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-emerald-500 rounded-xl flex items-center justify-center">
            <FileSpreadsheet className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Relatórios</h1>
            <p className="text-gray-500 text-sm mt-0.5">Histórico completo de todas as otimizações aplicadas</p>
          </div>
        </div>

        {SHEETS_URL && (
          <a
            href={SHEETS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2.5 bg-emerald-600 text-white rounded-xl text-sm font-semibold hover:bg-emerald-700 transition-colors shadow-sm"
          >
            <ExternalLink className="w-4 h-4" />
            Abrir no Google Sheets
          </a>
        )}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-24 text-gray-400">
          <Activity className="w-6 h-6 animate-spin mr-2" />
          <span className="text-sm">Carregando relatório...</span>
        </div>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="Total de Execuções"
              value={data?.total_executions ?? 0}
              icon={CheckCircle}
              color="bg-green-50 text-green-500"
            />
            <StatCard
              label="Total de Ações"
              value={data?.total_actions ?? 0}
              sub="em todas as plataformas"
              icon={Zap}
              color="bg-indigo-50 text-indigo-500"
            />
            <StatCard
              label="Google Ads"
              value={googleStats?.acoes ?? 0}
              sub={`${googleStats?.execucoes ?? 0} execução(ões)`}
              icon={BarChart2}
              color="bg-blue-50 text-blue-500"
            />
            <StatCard
              label="Meta Ads"
              value={metaStats?.acoes ?? 0}
              sub={`${metaStats?.execucoes ?? 0} execução(ões)`}
              icon={TrendingUp}
              color="bg-violet-50 text-violet-500"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Por plataforma */}
            {(googleStats || metaStats) && (
              <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 space-y-4">
                <h2 className="font-semibold text-gray-900">Ações por Plataforma</h2>
                {googleStats && (
                  <PlatformBar
                    platform="google_ads"
                    execucoes={googleStats.execucoes}
                    acoes={googleStats.acoes}
                    maxAcoes={maxAcoes}
                  />
                )}
                {metaStats && (
                  <PlatformBar
                    platform="meta_ads"
                    execucoes={metaStats.execucoes}
                    acoes={metaStats.acoes}
                    maxAcoes={maxAcoes}
                  />
                )}
              </div>
            )}

            {/* Por conta */}
            {(data?.account_stats?.length ?? 0) > 0 && (
              <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 lg:col-span-2">
                <h2 className="font-semibold text-gray-900 mb-4">Ações por Conta</h2>
                <div>
                  {data!.account_stats.map((acc, i) => (
                    <AccountRow
                      key={i}
                      name={acc.name}
                      platform={acc.platform}
                      execucoes={acc.execucoes}
                      acoes={acc.acoes}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Execution timeline */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
            {/* Table header */}
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between gap-4 flex-wrap">
              <h2 className="font-semibold text-gray-900">
                Histórico de Execuções
                <span className="ml-2 text-sm font-normal text-gray-400">
                  ({executions.length})
                </span>
              </h2>

              {/* Platform filter */}
              <div className="flex gap-1 bg-gray-100 p-1 rounded-xl">
                {([
                  { id: 'all',        label: 'Todas'      },
                  { id: 'google_ads', label: 'Google Ads' },
                  { id: 'meta_ads',   label: 'Meta Ads'   },
                ] as const).map(({ id, label }) => (
                  <button
                    key={id}
                    onClick={() => setPlatformFilter(id)}
                    className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                      platformFilter === id
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {executions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-gray-400">
                <FileSpreadsheet className="w-10 h-10 mb-4 opacity-30" />
                <p className="font-semibold text-gray-600">Nenhuma execução encontrada</p>
                <p className="text-sm mt-1">As execuções aprovadas aparecerão aqui</p>
              </div>
            ) : (
              <div>
                {/* Column headers */}
                <div className="hidden lg:flex items-center gap-4 px-6 py-2 bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  <div className="w-5 flex-shrink-0" />
                  <div className="w-36 flex-shrink-0">Data</div>
                  <div className="w-24 flex-shrink-0">Plataforma</div>
                  <div className="flex-1">Conta(s)</div>
                  <div className="w-28 flex-shrink-0 text-right pr-2">Ações</div>
                  <div className="w-20 flex-shrink-0">Sessão</div>
                </div>
                {executions.map(ex => (
                  <ExecutionRow key={ex.session_id} execution={ex} />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
