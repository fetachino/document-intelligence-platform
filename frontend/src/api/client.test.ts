import { afterEach, describe, expect, test, vi } from 'vitest'
import { ApiError, documentApi } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('documentApi', () => {
  test('centralizes document requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(documentApi.listDocuments()).resolves.toEqual([])
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/documents/', undefined)
  })

  test('returns a typed API error using the backend detail code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'document_not_found' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    const request = documentApi.listJobs('missing/id')

    await expect(request).rejects.toEqual(
      expect.objectContaining<ApiError>({
        name: 'ApiError',
        message: 'document_not_found',
        status: 404,
        detail: 'document_not_found',
      }),
    )
  })
})
