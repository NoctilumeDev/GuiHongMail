import type { AuthResponse, Category, Draft, Folder, FolderCount, MessageDetail, MessageSummary, Page, User } from './model'

export class StaleResponseError extends Error { constructor() { super('STALE_RESPONSE') } }
export class ApiError extends Error {
  constructor(public status: number, public code: string, public details: Record<string, unknown> = {}) { super(code) }
}

export class ApiClient {
  private generation = 0
  private csrf = sessionStorage.getItem('guihong_csrf') ?? ''
  currentUser: User | null = null

  resetSession(): void { this.generation += 1; this.csrf = ''; this.currentUser = null; sessionStorage.removeItem('guihong_csrf') }
  async login(address: string, password: string): Promise<User> {
    this.resetSession()
    const result = await this.request<AuthResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify({ address, password }) }, false)
    this.csrf = result.csrf; this.currentUser = result.user; sessionStorage.setItem('guihong_csrf', this.csrf); return result.user
  }
  async me(): Promise<User> { const user = await this.request<User>('/api/auth/me'); this.currentUser = user; return user }
  async logout(): Promise<void> { try { await this.request<void>('/api/auth/logout', { method: 'POST' }) } finally { this.resetSession() } }
  folders(): Promise<FolderCount[]> { return this.request('/api/mailbox/folders') }
  categories(): Promise<Category[]> { return this.request('/api/mailbox/categories') }
  createCategory(name: string): Promise<Category> { return this.request('/api/mailbox/categories', { method: 'POST', body: JSON.stringify({ name }) }) }
  deleteCategory(category: Category): Promise<void> { return this.request(`/api/mailbox/categories/${category.id}?version=${category.version}`, { method: 'DELETE' }) }
  messages(folder: Folder | null, categoryId: string | null, query = ''): Promise<Page<MessageSummary>> {
    const params = new URLSearchParams({ size: '30' }); if (folder) params.set('folder', folder); if (categoryId) params.set('category_id', categoryId); if (query) params.set('q', query)
    return this.request(`/api/mailbox/messages?${params}`)
  }
  message(id: string): Promise<MessageDetail> { return this.request(`/api/mailbox/messages/${id}`) }
  changeMessage(id: string, body: Record<string, unknown>): Promise<MessageDetail> { return this.request(`/api/mailbox/messages/${id}`, { method: 'PATCH', body: JSON.stringify(body) }) }
  drafts(): Promise<Page<Draft>> { return this.request('/api/mailbox/drafts?size=30') }
  draft(id: string): Promise<Draft> { return this.request(`/api/mailbox/drafts/${id}`) }
  createDraft(body: Record<string, unknown>): Promise<Draft> { return this.request('/api/mailbox/drafts', { method: 'POST', body: JSON.stringify(body) }) }
  saveDraft(draft: Draft): Promise<Draft> {
    const body = { version: draft.version, subject: draft.subject, textBody: draft.textBody, htmlBody: draft.htmlBody,
      to: draft.to, cc: draft.cc, bcc: draft.bcc, mode: draft.mode, sourceContentId: draft.sourceContentId }
    return this.request(`/api/mailbox/drafts/${draft.id}`, { method: 'PUT', body: JSON.stringify(body) })
  }
  deriveDraft(entryId: string, mode: string): Promise<Draft> { return this.request(`/api/mailbox/messages/${entryId}/drafts?mode=${encodeURIComponent(mode)}`, { method: 'POST' }) }
  async attach(draft: Draft, file: File): Promise<Draft> { const form = new FormData(); form.append('file', file); return this.request(`/api/mailbox/drafts/${draft.id}/attachments?version=${draft.version}`, { method: 'POST', body: form }, true, false) }

  private async request<T>(path: string, init: RequestInit = {}, authenticated = true, json = true): Promise<T> {
    const observed = this.generation
    const headers = new Headers(init.headers)
    if (json && init.body) headers.set('Content-Type', 'application/json')
    if (authenticated && !['GET', 'HEAD'].includes(init.method ?? 'GET')) headers.set('X-GuiHong-CSRF', this.csrf)
    const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
    if (observed !== this.generation) throw new StaleResponseError()
    if (!response.ok) { const body = await response.json().catch(() => ({})) as Record<string, unknown>; throw new ApiError(response.status, String(body.code ?? 'REQUEST_FAILED'), body) }
    if (response.status === 204) return undefined as T
    return response.json() as Promise<T>
  }
}
