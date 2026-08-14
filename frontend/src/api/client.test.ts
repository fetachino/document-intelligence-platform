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

  test('sends classification corrections through the typed endpoint', async () => {
    const classification = {
      document_id: 'doc/one',
      predicted_type: 'invoice',
      effective_type: 'contract',
      source: 'human',
      classifier_version: 'local_keyword_v1',
      classified_at: '2026-08-14T10:00:00',
      updated_at: '2026-08-14T10:01:00',
      reviewed_at: '2026-08-14T10:01:00',
    }
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(classification), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(documentApi.updateClassification('doc/one', 'contract')).resolves.toEqual(
      classification,
    )
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/documents/doc%2Fone/classification', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document_type: 'contract' }),
    })
  })
})
