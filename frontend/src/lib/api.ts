import type { SessionsResponse, SessionDetail } from '../types'

const API_URL = import.meta.env.VITE_API_URL || 'http://31.97.170.137:8000'
const API_KEY = import.meta.env.VITE_API_KEY || ''

const headers = () => ({
  'Content-Type': 'application/json',
  'x-api-key': API_KEY,
})

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { ...headers(), ...options?.headers },
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(error.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  health: () => request<{ status: string; dry_run: boolean; version: string }>('/health'),

  sessions: {
    list: () => request<SessionsResponse>('/sessions'),
    get: (id: string) => request<SessionDetail>(`/sessions/${id}`),
    execute: (id: string) => request<{ status: string }>(`/execute/${id}`, { method: 'POST' }),
    reject: (id: string) => request<{ status: string }>(`/sessions/${id}/reject`, { method: 'POST' }),
  },

  analyze: {
    googleAds: (customerId?: string) =>
      request('/analyze/google-ads', {
        method: 'POST',
        body: JSON.stringify({ customer_id: customerId, date_range: 'LAST_7_DAYS' }),
      }),
    metaAds: (adAccountId?: string) =>
      request('/analyze/meta-ads', {
        method: 'POST',
        body: JSON.stringify({ ad_account_id: adAccountId, date_preset: 'last_7d' }),
      }),
    trigger: () => request('/analyze/trigger', { method: 'POST' }),
  },
}
