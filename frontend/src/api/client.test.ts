import { afterEach, describe, expect, test, vi } from 'vitest'
import { ApiError, authApi, documentApi, setAccessToken } from './client'

afterEach(() => {
  setAccessToken(null)
  vi.unstubAllGlobals()
})

describe('documentApi', () => {
  test('authenticates locally and attaches the access token centrally', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: 'signed-token', token_type: 'bearer', expires_in: 1800,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: 'user-1', email: 'viewer@example.test', role: 'viewer',
        tenant_id: 'tenant-1', tenant_name: 'Workspace', tenant_slug: 'workspace',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    const token = await authApi.login({
      tenantSlug: 'workspace', email: 'viewer@example.test', password: 'password',
    })
    setAccessToken(token.access_token)
    await authApi.getCurrentUser()

    const authenticatedHeaders = fetchMock.mock.calls[1][1]?.headers as Headers
    expect(authenticatedHeaders.get('Authorization')).toBe('Bearer signed-token')
    expect(fetchMock.mock.calls[0][1]?.body).toBe(JSON.stringify({
      tenant_slug: 'workspace', email: 'viewer@example.test', password: 'password',
    }))
  })

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
      documentApi.correctStructuredField('doc/one', 'total amount', 0, '$12.00'),
    ).resolves.toEqual(field)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/documents/doc%2Fone/extraction/fields/total%20amount/0',
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: '$12.00' }),
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

  test('sends typed global and document-scoped Q&A requests', async () => {
    const response = {
      answer: 'Invoice 42 totals $19.00.',
      status: 'answered',
      citations: [],
      retrieval: {
        result_count: 0,
        retrieval_limit: 5,
        document_ids: null,
        embedding_model: 'local_hash_v1',
        results: [],
      },
      answer_provider: 'local_extractive_v1',
    }
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      documentApi.askQuestion({ question: 'What is the total?', retrievalLimit: 5 }),
    ).resolves.toEqual(response)
    await documentApi.askQuestion({
      question: 'What is the total?',
      retrievalLimit: 10,
      documentIds: ['doc/one'],
    })

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/qa', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'What is the total?', retrieval_limit: 5 }),
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/qa', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: 'What is the total?',
        retrieval_limit: 10,
        document_ids: ['doc/one'],
      }),
    })
  })
})
