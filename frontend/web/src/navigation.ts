import type { Folder } from './model'

export type NavItem = { id: 'compose' | 'drafts' | Lowercase<Folder>; label: string; folder?: Folder; glyph: string }
export const navigation: readonly NavItem[] = [
  { id: 'compose', label: '写信', glyph: '✦' },
  { id: 'inbox', label: '收件箱', folder: 'INBOX', glyph: '收' },
  { id: 'sent', label: '已发邮件', folder: 'SENT', glyph: '发' },
  { id: 'drafts', label: '草稿箱', glyph: '稿' },
  { id: 'archive', label: '归档', folder: 'ARCHIVE', glyph: '归' },
  { id: 'spam', label: '垃圾邮件', folder: 'SPAM', glyph: '拦' },
  { id: 'trash', label: '已删除', folder: 'TRASH', glyph: '删' },
] as const
