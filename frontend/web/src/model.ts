export type Folder = 'INBOX' | 'SENT' | 'ARCHIVE' | 'SPAM' | 'TRASH'
export type DraftMode = 'COMPOSE' | 'REPLY' | 'REPLY_ALL' | 'FORWARD'

export interface User { account_id: string; address: string; display_name: string; role: string }
export interface AuthResponse { user: User; csrf: string }
export interface FolderCount { folder: Folder; total: number; unread: number }
export interface Category { id: string; name: string; version: number; total: number; unread: number }
export interface MessageSummary {
  entryId: string; contentId: string; folder: Folder; read: boolean; categoryId: string | null; version: number
  fromAddress: string; fromName: string | null; subject: string; preview: string; sentAt: string | null
  receivedAt: string; attachmentCount: number
}
export interface Recipient { kind: 'TO' | 'CC' | 'BCC'; ordinal: number; address: string; name: string | null }
export interface Attachment { id: string; objectId: string; fileName: string; mediaType: string; sha256: string; size: number }
export interface MessageDetail {
  summary: MessageSummary; textBody: string; safeHtml: string; recipients: Recipient[]
  attachments: Attachment[]; rawSha256: string; rawSize: number
}
export interface Draft {
  id: string; version: number; subject: string; textBody: string; htmlBody: string; to: string[]; cc: string[]; bcc: string[]
  mode: DraftMode; sourceContentId: string | null; attachments: Attachment[]; createdAt: string; updatedAt: string
}
export interface Page<T> { items: T[]; nextCursor: string | null }

export interface SendIntent {
  id: string; draftId: string; draftVersion: number; requestKey: string; payloadSha256: string
  dispatchScopeId: string; contentId: string; rawSha256: string; rawSize: number; senderAddress: string
  envelope: Array<{ kind: 'TO' | 'CC' | 'BCC'; address: string }>; state: 'SUBMITTED_LOCAL'; createdAt: string
}
export interface DeliveryAttempt {
  id: string; epoch: number; lastStage: string; dataSubmitted: boolean; smtpCode: number | null
  outcome: string | null; evidenceSha256: string | null; duplicateRiskAcknowledged: boolean
  priorAttemptId: string | null; startedAt: string; completedAt: string | null
}
export interface RecipientDelivery {
  id: string; recipient: string; state: 'QUEUED' | 'STARTED' | 'RETRY_WAIT' | 'NEXT_HOP_ACCEPTED' | 'PERMANENT_FAILURE' | 'UNKNOWN' | 'CANCELLED'
  attemptCount: number; attempts: DeliveryAttempt[]
}
export interface DeliveryStatus {
  id: string; intentId: string; state: 'QUEUED' | 'STARTED' | 'COMPLETED' | 'CANCELLED'; everStarted: boolean; version: number
  recipients: RecipientDelivery[]
}
export interface SendStatus { intent: SendIntent; delivery?: DeliveryStatus }

export const folderLabels: Record<Folder, string> = {
  INBOX: '收件箱', SENT: '已发邮件', ARCHIVE: '归档', SPAM: '垃圾邮件', TRASH: '已删除',
}
