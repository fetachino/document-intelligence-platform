import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import {
  ApiError,
  documentApi,
  type DocumentRecord,
  type QaResponse,
} from '../api/client'
import { GroundedQa } from './GroundedQa'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    documentApi: { ...actual.documentApi, askQuestion: vi.fn() },
  }
})

const invoiceDocument: DocumentRecord = {
  id: 'invoice-1',
  filename: 'invoice.pdf',
  content_type: 'application/pdf',
  size: 1024,
  storage_path: '/uploads/invoice.pdf',
  status: 'processed',
  created_at: '2026-08-14T10:00:00',
  updated_at: '2026-08-14T10:01:00',
}

const contractDocument: DocumentRecord = {
  ...invoiceDocument,
  id: 'contract-1',
  filename: 'contract.pdf',
}

const answeredResponse: QaResponse = {
  answer: 'Invoice 42 has a total of $19.00. Payment is due September 1.',
  status: 'answered',
  citations: [
    {
      document_id: 'invoice-1',
      page_number: 1,
      chunk_index: 0,
      source_snippet: 'Invoice 42 has a total of $19.00.',
      distance: 0.125,
    },
    {
      document_id: 'invoice-1',
      page_number: 2,
      chunk_index: 1,
      source_snippet: 'Payment is due September 1.',
      distance: 0.25,
    },
  ],
  retrieval: {
    result_count: 2,
    retrieval_limit: 5,
    document_ids: null,
    embedding_model: 'local_hash_v1',
    results: [
      {
        document_id: 'invoice-1',
        page_number: 1,
        chunk_index: 0,
        text: 'Invoice 42 has a total of $19.00.',
        embedding_model: 'local_hash_v1',
        distance: 0.125,
      },
      {
        document_id: 'invoice-1',
        page_number: 2,
        chunk_index: 1,
        text: 'Payment is due September 1.',
        embedding_model: 'local_hash_v1',
        distance: 0.25,
      },
    ],
  },
  answer_provider: 'local_extractive_v1',
}

beforeEach(() => {
  vi.mocked(documentApi.askQuestion).mockReset()
  vi.mocked(documentApi.askQuestion).mockResolvedValue(answeredResponse)
})

function submitQuestion(question = 'What is the invoice total?') {
  fireEvent.change(screen.getByLabelText('Question'), { target: { value: question } })
  fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
}

describe('GroundedQa', () => {
  test('renders an answered response, multiple citations, and retrieval metadata', async () => {
    render(<GroundedQa documents={[invoiceDocument]} selectedDocument={invoiceDocument} />)

    submitQuestion()

    expect(await screen.findByText(answeredResponse.answer)).toBeInTheDocument()
    expect(screen.getByText('Grounded answer')).toBeInTheDocument()
    expect(screen.getByText('Citation 1: invoice.pdf')).toBeInTheDocument()
    expect(screen.getByText('Citation 2: invoice.pdf')).toBeInTheDocument()
    expect(screen.getAllByText('Page 1')).toHaveLength(2)
    expect(screen.getAllByText('Chunk 1')).toHaveLength(2)
    expect(screen.getAllByText('Cosine distance 0.125')).toHaveLength(2)
    expect(screen.getByText('Retrieved context (2 results)')).toBeInTheDocument()
    expect(screen.getByText('local_extractive_v1')).toBeInTheDocument()
    expect(screen.getAllByText('local_hash_v1').length).toBeGreaterThan(0)
    expect(documentApi.askQuestion).toHaveBeenCalledWith({
      question: 'What is the invoice total?',
      retrievalLimit: 5,
      documentIds: undefined,
    })
  })

  test('renders deterministic insufficient-evidence behavior without citations', async () => {
    vi.mocked(documentApi.askQuestion).mockResolvedValue({
      ...answeredResponse,
      answer: 'Insufficient evidence in the retrieved documents.',
      status: 'insufficient_evidence',
      citations: [],
    })
    render(<GroundedQa documents={[invoiceDocument]} selectedDocument={invoiceDocument} />)

    submitQuestion('Who approved this invoice?')

    expect(await screen.findByText('Insufficient evidence')).toBeInTheDocument()
    expect(screen.getByText('Insufficient evidence in the retrieved documents.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Citations' })).not.toBeInTheDocument()
  })

  test('supports selected-document scope', async () => {
    render(<GroundedQa documents={[invoiceDocument]} selectedDocument={invoiceDocument} />)
    fireEvent.click(screen.getByLabelText('Selected document'))

    submitQuestion()

    await waitFor(() => expect(documentApi.askQuestion).toHaveBeenCalledWith({
      question: 'What is the invoice total?',
      retrievalLimit: 5,
      documentIds: ['invoice-1'],
    }))
    expect(screen.getByText('Using invoice.pdf')).toBeInTheDocument()
  })

  test('guards empty questions and duplicate active submissions', async () => {
    let resolveRequest: (response: QaResponse) => void = () => undefined
    vi.mocked(documentApi.askQuestion).mockReturnValue(
      new Promise((resolve) => { resolveRequest = resolve }),
    )
    render(<GroundedQa documents={[]} selectedDocument={null} />)

    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Question'), { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    submitQuestion()
    expect(screen.getByRole('button', { name: 'Answering...' })).toBeDisabled()
    fireEvent.submit(screen.getByRole('button', { name: 'Answering...' }).closest('form')!)
    expect(documentApi.askQuestion).toHaveBeenCalledTimes(1)

    resolveRequest(answeredResponse)
    expect(await screen.findByText(answeredResponse.answer)).toBeInTheDocument()
  })

  test('renders centralized API errors', async () => {
    vi.mocked(documentApi.askQuestion).mockRejectedValue(
      new ApiError('document_not_found', 404, 'document_not_found'),
    )
    render(<GroundedQa documents={[]} selectedDocument={null} />)

    submitQuestion()

    expect(await screen.findByRole('alert')).toHaveTextContent('document_not_found')
  })

  test('prevents a stale response from replacing a newer scoped response', async () => {
    let resolveFirst: (response: QaResponse) => void = () => undefined
    vi.mocked(documentApi.askQuestion)
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce({ ...answeredResponse, answer: 'Scoped current answer.' })
    render(<GroundedQa documents={[invoiceDocument]} selectedDocument={invoiceDocument} />)

    submitQuestion('First question')
    fireEvent.click(screen.getByLabelText('Selected document'))
    fireEvent.change(screen.getByLabelText('Question'), { target: { value: 'Second question' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText('Scoped current answer.')).toBeInTheDocument()

    resolveFirst({ ...answeredResponse, answer: 'Stale global answer.' })
    await waitFor(() => expect(screen.queryByText('Stale global answer.')).not.toBeInTheDocument())
    expect(screen.getByText('Scoped current answer.')).toBeInTheDocument()
  })

  test('clears selected-document results when the selected document changes', async () => {
    const { rerender } = render(
      <GroundedQa documents={[invoiceDocument, contractDocument]} selectedDocument={invoiceDocument} />,
    )
    fireEvent.click(screen.getByLabelText('Selected document'))
    submitQuestion()
    expect(await screen.findByText(answeredResponse.answer)).toBeInTheDocument()

    rerender(
      <GroundedQa documents={[invoiceDocument, contractDocument]} selectedDocument={contractDocument} />,
    )

    await waitFor(() => expect(screen.queryByText(answeredResponse.answer)).not.toBeInTheDocument())
    expect(screen.getByText('Using contract.pdf')).toBeInTheDocument()
  })
})
