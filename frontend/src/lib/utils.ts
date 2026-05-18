import { clsx, type ClassValue } from 'clsx'
import { formatDistanceToNow, parseISO, format } from 'date-fns'
import { ptBR } from 'date-fns/locale'
import type { Platform, SessionStatus } from '../types'

export { getSessionStatus } from '../types'

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs)
}

export function formatRelativeTime(iso: string): string {
  try {
    return formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: ptBR })
  } catch {
    return iso
  }
}

export function formatDateTime(iso: string): string {
  try {
    return format(parseISO(iso), "dd/MM/yyyy 'às' HH:mm", { locale: ptBR })
  } catch {
    return iso
  }
}

export function platformLabel(platform: Platform): string {
  return platform === 'google_ads' ? 'Google Ads' : 'Meta Ads'
}

export function platformColor(platform: Platform) {
  return platform === 'google_ads'
    ? { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200', dot: 'bg-blue-500' }
    : { bg: 'bg-indigo-50', text: 'text-indigo-700', border: 'border-indigo-200', dot: 'bg-indigo-500' }
}

export function statusConfig(status: SessionStatus) {
  const configs = {
    pending: { label: 'Aguardando aprovação', bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', dot: 'bg-amber-400' },
    executed: { label: 'Executado', bg: 'bg-green-50', text: 'text-green-700', border: 'border-green-200', dot: 'bg-green-500' },
    rejected: { label: 'Rejeitado', bg: 'bg-gray-100', text: 'text-gray-500', border: 'border-gray-200', dot: 'bg-gray-400' },
  }
  return configs[status]
}
