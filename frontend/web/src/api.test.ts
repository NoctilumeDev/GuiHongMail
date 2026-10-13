import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient, StaleResponseError } from './api'
import type { Draft } from './model'

describe('account response ownership', () => {
  afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear() })
  it('rejects a response that arrives after the session generation changes', async () => {
    let complete!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { complete = resolve })))
    const client = new ApiClient()
    const pending = client.me()
    client.resetSession()
    complete(new Response(JSON.stringify({ account_id: 'account-a' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await expect(pending).rejects.toBeInstanceOf(StaleResponseError)
  })
  it('sends only writable draft fields back to the bounded API', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => Promise.resolve(new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    vi.stubGlobal('fetch', fetchMock)
    const draft = { id: 'd', version: 2, subject: 's', textBody: 't', htmlBody: '', to: [], cc: [], bcc: [],
      mode: 'COMPOSE', sourceContentId: null, attachments: [{ id: 'a' }], createdAt: 'now', updatedAt: 'now' } as unknown as Draft
    await new ApiClient().saveDraft(draft)
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>
    expect(Object.keys(body).sort()).toEqual(['bcc', 'cc', 'htmlBody', 'mode', 'sourceContentId', 'subject', 'textBody', 'to', 'version'])
  })
})
