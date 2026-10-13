import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient, StaleResponseError } from './api'

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
})
