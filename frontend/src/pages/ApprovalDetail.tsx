import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { platformLabel, platformColor, formatDateTime, getSessionStatus } from '../lib/utils'
import {
  ArrowLeft, CheckCircle, XCircle, ChevronDown, ChevronUp,
  Zap, AlertTriangle, Info, CheckSquare, Square, Loader2, RotateCcw
} from 'lucide-react'
import type { AccountResult, ActionDetail } from '../types'

function priorityConfig(description: string) {
  if (description.includes('P0') || description.toLowerCase().includes('crítico')) {
    return { label: 'P0 — Crítico', bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200', icon: '🔴' }
  }
  if (description.includes('P1') || description.toLowerCase().includes('alto')) {
    return { label: 'P1 — Alto', bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200', icon: '🟠' }
  }
  if (description.includes('P2') || description.toLowerCase().includes('médio')) {
    return { label: 'P2 — Médio', bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', icon: '🟡' }
  }
  return { label: 'P3 — Baixo', bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200', icon: '🔵' }
}

function toolLabel(tool: string) {
  const map: Record<string, string> = {
    pause_keyword: '⏸ Pausar Keyword',
    update_keyword_bid: '💰 Ajustar Lance',
    add_negative_keyword: '🚫 Negativa',
    pause_ad_set: '⏸ Pausar Ad Set',
    pause_ad: '⏸ Pausar Anúncio',
    update_ad_set_bid: '💰 Ajustar Lance Ad Set',
  }
  return map[tool] || tool
}

/** Extrai contexto da ação: campanha, grupo, correspondência */
function getActionContext(action: ActionDetail) {
  const inp = action.input as Record<string, string>
  return {
    campaignName: inp?.campaign_name || '',
    adGroupName:  inp?.ad_group_name || '',
    matchType:    inp?.match_type    || '',
    keywordText:  inp?.keyword_text  || '',
  }
}

function MatchTypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    EXACT:  'bg-purple-50 text-purple-700 border-purple-200',
    PHRASE: 'bg-blue-50   text-blue-700   border-blue-200',
    BROAD:  'bg-orange-50 text-orange-700 border-orange-200',
  }
  if (!type) return null
  return (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wide ${colors[type] || 'bg-gray-50 text-gray-600 border-gray-200'}`}>
      {type}
    </span>
  )
}

function ActionCard({
  action,
  checked,
  onToggle,
  disabled,
}: {
  action: ActionDetail
  checked: boolean
  onToggle: () => void
  disabled: boolean
}) {
  const { adGroupName, matchType } = getActionContext(action)

  return (
    <div
      className={`flex items-start gap-3 p-4 rounded-xl border transition-all cursor-pointer ${
        checked ? 'bg-indigo-50 border-indigo-200' : 'bg-white border-gray-200 hover:border-gray-300'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      onClick={disabled ? undefined : onToggle}
    >
      <div className="flex-shrink-0 mt-0.5">
        {checked ? (
          <CheckSquare className="w-5 h-5 text-indigo-600" />
        ) : (
          <Square className="w-5 h-5 text-gray-300" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        {/* Tool label + match type + ad group */}
        <div className="flex items-center gap-1.5 flex-wrap mb-1.5">
          <span className="text-xs font-semibold text-gray-700 bg-gray-100 px-2 py-0.5 rounded-md">
            {toolLabel(action.tool)}
          </span>
          {matchType && <MatchTypeBadge type={matchType} />}
          {adGroupName && (
            <span className="text-[10px] text-gray-400 font-medium truncate max-w-[160px]" title={adGroupName}>
              {adGroupName}
            </span>
          )}
        </div>
        <p className="text-sm text-gray-800 leading-relaxed">{action.description}</p>
      </div>
    </div>
  )
}

function SummarySection({ summary }: { summary: string }) {
  const [expanded, setExpanded] = useState(false)
  const lines = summary.split('\n').filter(l => l.trim())
  const preview = lines.slice(0, 5)
  const hasMore = lines.length > 5

  const formatLine = (line: string, i: number) => {
    if (line.startsWith('═') || line.startsWith('─')) {
      return <hr key={i} className="border-gray-200 my-2" />
    }
    if (line.startsWith('AÇÕES EXECUTADAS') || line.startsWith('ATENÇÃO MANUAL') || line.startsWith('NÃO ALTERAR') ||
        line.startsWith('PRÓXIMOS') || line.startsWith('SITUAÇÃO') || line.startsWith('ALERTAS') || line.startsWith('DADOS QUE')) {
      return <p key={i} className="text-xs font-bold text-gray-500 uppercase tracking-wider mt-4 mb-1">{line}</p>
    }
    if (line.startsWith('OTIMIZAÇÃO') || line.match(/^P[0-3] —/)) {
      return <p key={i} className="text-sm font-semibold text-indigo-700 mt-3">{line}</p>
    }
    if (line.startsWith('- ') || line.startsWith('• ')) {
      return <p key={i} className="text-sm text-gray-700 pl-4">• {line.replace(/^[-•]\s*/, '')}</p>
    }
    return <p key={i} className="text-sm text-gray-700 leading-relaxed">{line}</p>
  }

  const displayLines = expanded ? lines : preview

  return (
    <div className="bg-slate-50 rounded-xl border border-slate-200 p-5">
      <div className="space-y-1">
        {displayLines.map(formatLine)}
      </div>
      {hasMore && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-3 flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700"
        >
          {expanded ? (
            <><ChevronUp className="w-3.5 h-3.5" /> Mostrar menos</>
          ) : (
            <><ChevronDown className="w-3.5 h-3.5" /> Ver análise completa</>
          )}
        </button>
      )}
    </div>
  )
}

/** Agrupa actions_detail por campaign_name (ou "Geral" se ausente) */
function groupByCampaign(actions: ActionDetail[]): Map<string, { action: ActionDetail; idx: number }[]> {
  const map = new Map<string, { action: ActionDetail; idx: number }[]>()
  actions.forEach((action, idx) => {
    const campaign = (action.input as Record<string, string>)?.campaign_name || 'Geral'
    if (!map.has(campaign)) map.set(campaign, [])
    map.get(campaign)!.push({ action, idx })
  })
  return map
}

function AccountSection({ account, checkedActions, onToggle, onSelectAll, onDeselectAll, disabled }: {
  account: AccountResult
  checkedActions: Set<number>
  onToggle: (idx: number) => void
  onSelectAll: () => void
  onDeselectAll: () => void
  disabled: boolean
}) {
  const total = account.actions_detail.length
  const allChecked = checkedActions.size === total
  const noneChecked = checkedActions.size === 0

  const campaignGroups = groupByCampaign(account.actions_detail)

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-900">{account.account_name || account.customer_id || account.ad_account_id}</h3>
          <p className="text-xs text-gray-400 mt-0.5">{account.actions_count} otimizações identificadas</p>
        </div>
        {total > 0 && !disabled && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200 px-2.5 py-1 rounded-full">
              {checkedActions.size} de {total} selecionadas
            </span>
            <button
              onClick={allChecked ? onDeselectAll : onSelectAll}
              className="text-xs font-medium text-indigo-600 hover:text-indigo-800 underline underline-offset-2 whitespace-nowrap"
            >
              {allChecked ? 'Desmarcar todas' : noneChecked ? 'Marcar todas' : 'Marcar todas'}
            </button>
          </div>
        )}
        {total > 0 && disabled && (
          <span className="text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200 px-2.5 py-1 rounded-full">
            {checkedActions.size} de {total} selecionadas
          </span>
        )}
      </div>

      <div className="p-6 space-y-6">
        {/* Analysis summary */}
        {account.summary && (
          <div>
            <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Info className="w-3.5 h-3.5" /> Análise da IA
            </h4>
            <SummarySection summary={account.summary} />
          </div>
        )}

        {/* Actions grouped by campaign */}
        {account.actions_detail.length > 0 && (
          <div>
            <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5" /> Ações Propostas
            </h4>
            <div className="space-y-5">
              {Array.from(campaignGroups.entries()).map(([campaignName, items]) => (
                <div key={campaignName}>
                  {/* Campaign header */}
                  <div className="flex items-center gap-2 mb-2">
                    <div className="h-px flex-1 bg-gray-100" />
                    <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider px-2 whitespace-nowrap">
                      📢 {campaignName}
                    </span>
                    <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded-full">
                      {items.length}
                    </span>
                    <div className="h-px flex-1 bg-gray-100" />
                  </div>
                  {/* Actions for this campaign */}
                  <div className="space-y-2">
                    {items.map(({ action, idx }) => (
                      <ActionCard
                        key={idx}
                        action={action}
                        checked={checkedActions.has(idx)}
                        onToggle={() => onToggle(idx)}
                        disabled={disabled}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {account.status === 'error' && (
          <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 rounded-lg p-3">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span>{account.error || 'Erro ao analisar esta conta.'}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export function ApprovalDetail() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: session, isLoading } = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => api.sessions.get(sessionId!),
    enabled: !!sessionId,
  })

  // Per-account, per-action selection (all checked by default)
  const [checkedMap, setCheckedMap] = useState<Record<number, Set<number>>>({})

  const initChecked = (accounts: AccountResult[]) => {
    const map: Record<number, Set<number>> = {}
    accounts.forEach((acc, ai) => {
      map[ai] = new Set(acc.actions_detail.map((_, i) => i))
    })
    return map
  }

  const getChecked = (accountIdx: number, total: number): Set<number> => {
    if (checkedMap[accountIdx]) return checkedMap[accountIdx]
    return new Set(Array.from({ length: total }, (_, i) => i))
  }

  const toggleAction = (accountIdx: number, actionIdx: number, total: number) => {
    const current = getChecked(accountIdx, total)
    const next = new Set(current)
    if (next.has(actionIdx)) next.delete(actionIdx)
    else next.add(actionIdx)
    setCheckedMap(prev => ({ ...prev, [accountIdx]: next }))
  }

  const selectAllAccount = (accountIdx: number, total: number) => {
    setCheckedMap(prev => ({ ...prev, [accountIdx]: new Set(Array.from({ length: total }, (_, i) => i)) }))
  }

  const deselectAllAccount = (accountIdx: number) => {
    setCheckedMap(prev => ({ ...prev, [accountIdx]: new Set() }))
  }

  const selectAllGlobal = (accs: AccountResult[]) => {
    const map: Record<number, Set<number>> = {}
    accs.forEach((acc, ai) => { map[ai] = new Set(acc.actions_detail.map((_, i) => i)) })
    setCheckedMap(map)
  }

  const deselectAllGlobal = (accs: AccountResult[]) => {
    const map: Record<number, Set<number>> = {}
    accs.forEach((_, ai) => { map[ai] = new Set() })
    setCheckedMap(map)
  }

  // Constrói o mapa account_id → índices selecionados para execução seletiva
  const buildAccountActions = (accounts: AccountResult[]): Record<string, number[]> => {
    const result: Record<string, number[]> = {}
    accounts.forEach((acc, ai) => {
      const accountId = acc.customer_id || acc.ad_account_id || ''
      if (!accountId) return
      const checked = getChecked(ai, acc.actions_detail.length)
      result[accountId] = Array.from(checked).sort((a, b) => a - b)
    })
    return result
  }

  const executeMutation = useMutation({
    mutationFn: (accountActions?: Record<string, number[]>) =>
      api.sessions.execute(sessionId!, session?.execute_token, accountActions),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
      navigate('/approvals')
    },
  })

  const rejectMutation = useMutation({
    mutationFn: () => api.sessions.reject(sessionId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      navigate('/approvals')
    },
  })

  const revertMutation = useMutation({
    mutationFn: () => api.sessions.revert(sessionId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    },
  })

  if (isLoading || !session) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
      </div>
    )
  }

  const status = getSessionStatus(session)
  const isAlreadyDone = status !== 'pending'
  const platformCfg = platformColor(session.platform)
  const isMutating = executeMutation.isPending || rejectMutation.isPending || revertMutation.isPending

  const accounts = session.accounts ?? []
  const initialChecked = initChecked(accounts)

  return (
    <div className="space-y-6">
      {/* Back + header */}
      <div>
        <button
          onClick={() => navigate('/approvals')}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-4 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> Voltar
        </button>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full border ${platformCfg.bg} ${platformCfg.text} ${platformCfg.border}`}>
                {platformLabel(session.platform)}
              </span>
              <span className="text-xs text-gray-400 font-mono">#{session.session_id}</span>
            </div>
            <h1 className="text-2xl font-bold text-gray-900">
              {accounts.map(a => a.account_name || a.customer_id || a.ad_account_id).join(', ')}
            </h1>
            <p className="text-gray-500 text-sm mt-1">Análise gerada {formatDateTime(session.created_at)}</p>
          </div>

          {/* Action buttons — pending */}
          {!isAlreadyDone && (
            <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
              <button
                onClick={() => rejectMutation.mutate()}
                disabled={isMutating}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-gray-200 text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors"
              >
                {rejectMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <XCircle className="w-4 h-4" />}
                Rejeitar
              </button>
              <button
                onClick={() => executeMutation.mutate(buildAccountActions(accounts))}
                disabled={isMutating}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-500 text-white text-sm font-semibold hover:bg-amber-600 disabled:opacity-50 transition-colors shadow-sm"
                title="Executa apenas as ações selecionadas (checkboxes)"
              >
                {executeMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckSquare className="w-4 h-4" />}
                Aplicar Selecionadas
              </button>
              <button
                onClick={() => executeMutation.mutate(undefined)}
                disabled={isMutating}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-colors shadow-sm"
                title="Executa todas as ações propostas pela IA"
              >
                {executeMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                Aplicar Tudo
              </button>
            </div>
          )}

          {/* Status badge + revert — executed/rejected */}
          {isAlreadyDone && (
            <div className="flex items-center gap-2 flex-shrink-0">
              {status === 'executed' && !session.reverted && (
                <button
                  onClick={() => {
                    if (window.confirm('Tem certeza que deseja REVERTER todas as otimizações desta sessão? Esta ação ativará/restaurará os itens que foram pausados/ajustados.')) {
                      revertMutation.mutate()
                    }
                  }}
                  disabled={isMutating}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl border border-orange-200 text-sm font-medium text-orange-600 hover:bg-orange-50 disabled:opacity-50 transition-colors"
                >
                  {revertMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
                  Reverter
                </button>
              )}
              <span className={`text-sm font-medium px-4 py-2 rounded-xl border ${
                session.reverted
                  ? 'bg-orange-50 text-orange-700 border-orange-200'
                  : status === 'executed'
                  ? 'bg-green-50 text-green-700 border-green-200'
                  : 'bg-gray-100 text-gray-500 border-gray-200'
              }`}>
                {session.reverted ? '↩ Revertido' : status === 'executed' ? '✓ Executado' : '✗ Rejeitado'}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Error feedback */}
      {(executeMutation.isError || rejectMutation.isError || revertMutation.isError) && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-center gap-2 text-sm text-red-700">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {(executeMutation.error || rejectMutation.error || revertMutation.error)?.message}
        </div>
      )}
      {revertMutation.isSuccess && (
        <div className="bg-orange-50 border border-orange-200 rounded-xl p-4 flex items-center gap-2 text-sm text-orange-700">
          <RotateCcw className="w-4 h-4 flex-shrink-0" />
          Otimizações revertidas com sucesso.
        </div>
      )}

      {/* Account sections */}
      {accounts.map((account, ai) => (
        <AccountSection
          key={ai}
          account={account}
          checkedActions={getChecked(ai, account.actions_detail.length)}
          onToggle={(idx) => toggleAction(ai, idx, account.actions_detail.length)}
          onSelectAll={() => selectAllAccount(ai, account.actions_detail.length)}
          onDeselectAll={() => deselectAllAccount(ai)}
          disabled={isAlreadyDone || isMutating}
        />
      ))}

      {/* Bottom approve bar */}
      {!isAlreadyDone && (
        <div className="sticky bottom-6 bg-white border border-gray-200 rounded-2xl shadow-lg p-4 flex items-center justify-between gap-4 flex-wrap">
          {/* Contagem + atalhos globais */}
          <div className="flex items-center gap-3">
            <p className="text-sm text-gray-600">
              <span className="font-semibold text-gray-900">
                {accounts.reduce((sum, acc, ai) => sum + getChecked(ai, acc.actions_detail.length).size, 0)}
              </span>
              {' '}de{' '}
              <span className="font-semibold text-gray-900">
                {accounts.reduce((sum, acc) => sum + acc.actions_detail.length, 0)}
              </span>
              {' '}selecionadas
            </p>
            <div className="flex gap-2 text-xs font-medium">
              <button
                onClick={() => selectAllGlobal(accounts)}
                disabled={isMutating}
                className="text-indigo-600 hover:text-indigo-800 underline underline-offset-2 disabled:opacity-40"
              >
                Marcar todas
              </button>
              <span className="text-gray-300">|</span>
              <button
                onClick={() => deselectAllGlobal(accounts)}
                disabled={isMutating}
                className="text-gray-500 hover:text-gray-700 underline underline-offset-2 disabled:opacity-40"
              >
                Desmarcar todas
              </button>
            </div>
          </div>

          {/* Botões de ação */}
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => rejectMutation.mutate()}
              disabled={isMutating}
              className="px-4 py-2 rounded-xl border border-gray-200 text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              Rejeitar tudo
            </button>
            <button
              onClick={() => executeMutation.mutate(buildAccountActions(accounts))}
              disabled={isMutating}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-500 text-white text-sm font-semibold hover:bg-amber-600 disabled:opacity-50 transition-colors"
              title="Executa apenas as ações com checkbox marcado"
            >
              {executeMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckSquare className="w-4 h-4" />}
              Aplicar Selecionadas
            </button>
            <button
              onClick={() => executeMutation.mutate(undefined)}
              disabled={isMutating}
              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              title="Executa todas as ações propostas pela IA"
            >
              {executeMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
              Aplicar Tudo
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
