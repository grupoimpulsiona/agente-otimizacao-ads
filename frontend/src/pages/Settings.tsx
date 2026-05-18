import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Settings, Server, Shield, Clock } from 'lucide-react'

function SettingRow({ label, value, description }: { label: string; value: string | boolean; description?: string }) {
  return (
    <div className="flex items-center justify-between py-4 border-b border-gray-100 last:border-0">
      <div>
        <p className="text-sm font-medium text-gray-900">{label}</p>
        {description && <p className="text-xs text-gray-400 mt-0.5">{description}</p>}
      </div>
      <span className={`text-sm font-semibold px-3 py-1 rounded-full ${
        typeof value === 'boolean'
          ? value ? 'bg-amber-50 text-amber-700 border border-amber-200' : 'bg-green-50 text-green-700 border border-green-200'
          : 'bg-gray-100 text-gray-700'
      }`}>
        {typeof value === 'boolean' ? (value ? 'Ativo' : 'Desativado') : value}
      </span>
    </div>
  )
}

export function SettingsPage() {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 60_000,
  })

  const apiUrl = import.meta.env.VITE_API_URL || 'http://31.97.170.137:8000'

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Configurações</h1>
        <p className="text-gray-500 mt-1">Status e configurações do agente</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* API Status */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center gap-2 mb-5">
            <Server className="w-4 h-4 text-gray-500" />
            <h2 className="font-semibold text-gray-900">Status da API</h2>
            <div className={`ml-auto w-2 h-2 rounded-full ${health?.status === 'ok' ? 'bg-green-500' : 'bg-red-400'}`} />
          </div>
          <SettingRow label="Status" value={health?.status === 'ok' ? 'Online' : 'Offline'} />
          <SettingRow label="Versão" value={health?.version ?? '—'} />
          <SettingRow
            label="Modo Dry-Run"
            value={health?.dry_run ?? true}
            description="Quando ativo, nenhuma ação real é executada"
          />
          <SettingRow label="URL da API" value={apiUrl} />
        </div>

        {/* Execution Schedule */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center gap-2 mb-5">
            <Clock className="w-4 h-4 text-gray-500" />
            <h2 className="font-semibold text-gray-900">Agendamento</h2>
          </div>
          <SettingRow label="Google Ads" value="7h00 — Seg a Sex" description="Cron: 0 7 * * 1-5" />
          <SettingRow label="Meta Ads" value="7h30 — Seg a Sex" description="Cron: 30 7 * * 1-5" />
          <SettingRow label="Fuso horário" value="America/Sao_Paulo" />
        </div>

        {/* Guardrails */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center gap-2 mb-5">
            <Shield className="w-4 h-4 text-gray-500" />
            <h2 className="font-semibold text-gray-900">Guardrails de Segurança</h2>
          </div>
          <SettingRow label="Variação máx. de lance" value="±20%" description="Limite por execução" />
          <SettingRow label="Mín. impressões para agir" value="200" />
          <SettingRow label="Mín. cliques para agir" value="10" />
          <SettingRow label="Máx. ações por execução" value="20" />
          <SettingRow label="Aumento de orçamento" value="Bloqueado" />
        </div>

        {/* Info */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center gap-2 mb-5">
            <Settings className="w-4 h-4 text-gray-500" />
            <h2 className="font-semibold text-gray-900">Como alterar configurações</h2>
          </div>
          <p className="text-sm text-gray-600 leading-relaxed">
            As configurações são gerenciadas pelo arquivo <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs font-mono">.env</code> no servidor.
          </p>
          <p className="text-sm text-gray-600 leading-relaxed mt-3">
            Para adicionar ou remover clientes, edite <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs font-mono">GOOGLE_ADS_CUSTOMER_IDS</code> e reinicie o container.
          </p>
          <div className="mt-4 bg-slate-900 rounded-xl p-4">
            <code className="text-xs text-green-400 leading-relaxed block">
              {`# No VPS:\nnano /opt/agente-otimizacao-ads/.env\ndocker compose up -d --force-recreate`}
            </code>
          </div>
        </div>
      </div>
    </div>
  )
}
