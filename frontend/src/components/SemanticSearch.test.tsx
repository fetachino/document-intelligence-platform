import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import {
  ApiError,
  documentApi,
  type DocumentRecord,
  type SemanticSearchResponse,
} from '../api/client'
import { SemanticSearch } from './SemanticSearch'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    documentApi: {
      ...actual.documentApi,
      searchDocuments: vi.fn(),
    },
  }
})

const invoiceDocument: DocumentRecord = {
  id: 'doc-1',
  filename: 'invoice.pdf',
  content_type: 'application/pdf',
  size: 2_048,
  storage_path: '/not-rendered/invoice.pdf',
  status: 'processed',
  created_at: '2026-08-14T10:00:00',
  updated_at: '2026-08-14T10:02:00',
}

const contractDocument: DocumentRecord = {
  ...invoiceDocument,
  id: 'doc-2',
  filename: 'contract.pdf',
}

const rankedResponse: SemanticSearchResponse = {
  query: 'payment terms',
  results: [
    {
      document_id: 'doc-1',
      page_number: 2,
      chunk_index: 0,
      text: 'Payment is due within thirty days.',
      embedding_model: 'local_hash_v1',
      distance: 0.123456789,
    },
    {
      document_id: 'doc-2',
      page_number: 4,
      chunk_index: 1,
      text: 'The payment schedule appears in exhibit A.',
      embedding_model: 'local_hash_v1',
      distance: 0.234567891,
    },
  ],
}

beforeEach(() => {
  vi.mocked(documentApi.searchDocuments).mockResolvedValue(rankedResponse)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('SemanticSearch', () => {
  test('submits an all-document search with the selected limit', async () => {
    render(
      <SemanticSearch
        documents={[invoiceDocument, contractDocument]}
        selectedDocument={invoiceDocument}
      />,
    )

    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'payment terms' } })
    fireEvent.change(screen.getByLabelText('Results'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(documentApi.searchDocuments).toHaveBeenCalledWith({
      query: 'payment terms',
      limit: 5,
      documentId: undefined,
    })
    expect(await screen.findByText('2 results')).toBeInTheDocument()
  })

  test('submits a selected-document search', async () => {
    render(<SemanticSearch documents={[invoiceDocument]} selectedDocument={invoiceDocument} />)

    fireEvent.click(screen.getByLabelText('Selected document'))
    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'invoice number' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(documentApi.searchDocuments).toHaveBeenCalledWith({
      query: 'invoice number',
      limit: 10,
      documentId: 'doc-1',
    })
    expect(await screen.findByText('Searching invoice.pdf')).toBeInTheDocument()
  })

  test('renders ranked source text, provenance, model, and genuine distance', async () => {
    render(
      <SemanticSearch
        documents={[invoiceDocument, contractDocument]}
        selectedDocument={null}
      />,
    )
    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'payment terms' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('Payment is due within thirty days.')).toBeInTheDocument()
    expect(screen.getByLabelText('Rank 1')).toHaveTextContent('1')
    expect(screen.getByLabelText('Rank 2')).toHaveTextContent('2')
    expect(screen.getByText('invoice.pdf')).toBeInTheDocument()
    expect(screen.getByText('Page 2')).toBeInTheDocument()
    expect(screen.getByText('Chunk 0')).toBeInTheDocument()
    expect(screen.getAllByText('local_hash_v1')).toHaveLength(2)
    expect(screen.getByText('Cosine distance 0.123456789')).toBeInTheDocument()
  })

  test('shows a loading state while retrieval is pending', async () => {
    let resolveSearch: (value: SemanticSearchResponse) => void = () => undefined
    vi.mocked(documentApi.searchDocuments).mockReturnValue(
      new Promise((resolve) => {
        resolveSearch = resolve
      }),
    )
    render(<SemanticSearch documents={[]} selectedDocument={null} />)
    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'pending' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('Searching document chunks...')).toBeInTheDocument()
    await act(async () => resolveSearch({ query: 'pending', results: [] }))
  })

  test('guards empty queries without calling the API', () => {
    render(<SemanticSearch documents={[]} selectedDocument={null} />)

    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Query'), { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled()
    expect(documentApi.searchDocuments).not.toHaveBeenCalled()
  })

  test('renders a no-results state', async () => {
    vi.mocked(documentApi.searchDocuments).mockResolvedValue({ query: 'missing', results: [] })
    render(<SemanticSearch documents={[]} selectedDocument={null} />)
    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'missing' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('No matching document chunks found.')).toBeInTheDocument()
  })

  test('surfaces search API errors', async () => {
    vi.mocked(documentApi.searchDocuments).mockRejectedValue(
      new ApiError('search_service_unavailable', 503),
    )
    render(<SemanticSearch documents={[]} selectedDocument={null} />)
    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'failure' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('search_service_unavailable')
  })

  test('prevents an older response from replacing a newer query', async () => {
    let resolveFirst: (value: SemanticSearchResponse) => void = () => undefined
    vi.mocked(documentApi.searchDocuments)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveFirst = resolve
        }),
      )
      .mockResolvedValueOnce({
        query: 'new query',
        results: [{ ...rankedResponse.results[0], text: 'Newest retrieval result.' }],
      })
    render(<SemanticSearch documents={[invoiceDocument]} selectedDocument={null} />)
    const query = screen.getByLabelText('Query')

    fireEvent.change(query, { target: { value: 'old query' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    fireEvent.change(query, { target: { value: 'new query' } })
    fireEvent.click(screen.getByRole('button', { name: 'Searching...' }))

    expect(await screen.findByText('Newest retrieval result.')).toBeInTheDocument()
    await act(async () => resolveFirst({
      query: 'old query',
      results: [{ ...rankedResponse.results[0], text: 'Stale retrieval result.' }],
    }))
    expect(screen.queryByText('Stale retrieval result.')).not.toBeInTheDocument()
    expect(screen.getByText('Newest retrieval result.')).toBeInTheDocument()
  })

  test('clears selected-scope results when the selected document changes', async () => {
    const { rerender } = render(
      <SemanticSearch documents={[invoiceDocument, contractDocument]} selectedDocument={invoiceDocument} />,
    )
    fireEvent.click(screen.getByLabelText('Selected document'))
    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'payment terms' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('Payment is due within thirty days.')

    rerender(
      <SemanticSearch documents={[invoiceDocument, contractDocument]} selectedDocument={contractDocument} />,
    )

    expect(await screen.findByText('Searching contract.pdf')).toBeInTheDocument()
    expect(screen.queryByText('Payment is due within thirty days.')).not.toBeInTheDocument()
  })
})
