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

  test('centralizes structured-field correction requests', async () => {
    const field = {
      field_name: 'total_amount',
      value_index: 0,
      value: '$10.00',
      effective_value: '$12.00',
      reviewed: true,
      reviewer_id: 'reviewer-a',
      reviewed_at: '2026-08-14T10:01:00',
      page_number: 1,
      extraction_method: 'local_regex',
      extractor_version: 'local_regex_v1',
    }
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(field), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      documentApi.correctStructuredField('doc/one', 'total amount', 0, '$12.00', 'reviewer-a'),
    ).resolves.toEqual(field)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/documents/doc%2Fone/extraction/fields/total%20amount/0',
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: '$12.00', reviewer_id: 'reviewer-a' }),
      },
    )
  })

  test('builds typed global and document-scoped search requests', async () => {
    const response = { query: 'invoice total', results: [] }
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(response), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      documentApi.searchDocuments({ query: 'invoice total', limit: 5 }),
    ).resolves.toEqual(response)
    await documentApi.searchDocuments({
      query: 'invoice total',
      limit: 10,
      documentId: 'doc/one',
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/search?q=invoice+total&limit=5',
      undefined,
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/search?q=invoice+total&limit=10&document_id=doc%2Fone',
      undefined,
    )
  })
})
