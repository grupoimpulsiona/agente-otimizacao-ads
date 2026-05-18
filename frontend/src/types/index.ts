export type Platform = 'google_ads' | 'meta_ads'

export interface ActionDetail {
  tool: string
  input: Record<string, unknown>
  result: Record<string, unknown>
  description: string
}

export interface AccountResult {
  customer_id?: string
  ad_account_id?: string
  account_name: string
  status: 'ok' | 'error' | 'guardrail_blocked'
  actions_count: number
  actions_detail: ActionDetail[]
  summary: string
  dry_run: boolean
  error?: string
}

export interface SessionSummary {
  session_id: string
  platform: Platform
  created_at: string
  executed: boolean
  executed_at?: string
  rejected: boolean
  rejected_at?: string
  reverted: boolean
  reverted_at?: string
  total_actions: number
  accounts_count: number
  accounts: {
    id: string
    name: string
    status: string
    actions_count: number
  }[]
}

export interface SessionDetail {
  session_id: string
  platform: Platform
  created_at: string
  executed: boolean
  executed_at?: string
  rejected: boolean
  rejected_at?: string
  reverted: boolean
  reverted_at?: string
  accounts: AccountResult[]
}

export interface SessionsResponse {
  sessions: SessionSummary[]
  total: number
}

export type SessionStatus = 'pending' | 'executed' | 'rejected'

// ── Relatórios ────────────────────────────────────────────────────────────────

export interface ReportAccount {
  account_id: string
  account_name: string
  status: string
  actions_count: number
  actions_detail: ActionDetail[]
  summary: string
}

export interface ReportExecution {
  session_id: string
  platform: Platform
  created_at: string
  executed_at: string
  total_actions: number
  accounts: ReportAccount[]
}

export interface ReportsResponse {
  executions: ReportExecution[]
  total_executions: number
  total_actions: number
  platform_stats: Record<string, { execucoes: number; acoes: number }>
  account_stats: { name: string; platform: string; execucoes: number; acoes: number }[]
}

export function getSessionStatus(session: SessionSummary | SessionDetail): SessionStatus {
  if (session.executed) return 'executed'
  if (session.rejected) return 'rejected'
  return 'pending'
}
