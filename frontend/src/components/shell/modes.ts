import type { Mode, Workspace } from '../../types'

export const MODES: { id: Mode; label: string; workspace: Workspace; hint: string }[] = [
  { id: 'admin', label: 'Bank Admin', workspace: 'bank_official', hint: 'Manage official policies' },
  { id: 'customer', label: 'Bank Customer', workspace: 'bank_official', hint: 'Read-only Q&A' },
  { id: 'byo', label: 'BYO Private Docs', workspace: 'byo_private', hint: 'Your own PDFs, isolated' },
]
