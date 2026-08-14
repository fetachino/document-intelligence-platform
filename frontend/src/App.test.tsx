import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App from './App'
import {
  ApiError,
  documentApi,
  type DocumentClassification,
  type DocumentRecord,
  type ProcessingJob,
  type ProcessingJobStatus,
} from './api/client'

vi.mock('./api/client', async () => {
  const actual = await vi.importActual<typeof import('./api/client')>('./api/client')
  return {
    ...actual,
    documentApi: {
      listDocuments: vi.fn(),
      listJobs: vi.fn(),
      getClassification: vi.fn(),
      updateClassification: vi.fn(),
      getExtraction: vi.fn(),
      getExtractionReviews: vi.fn(),
      correctStructuredField: vi.fn(),
      searchDocuments: vi.fn(),
      reprocessDocument: vi.fn(),
      uploadDocument: vi.fn(),
    },
  }
})

const documentOne: DocumentRecord = {
  id: 'doc-1',
  filename: 'invoice-august.pdf',
  content_type: 'application/pdf',
  size: 2_048,
  storage_path: '/not-rendered/invoice.pdf',
  status: 'processed',
  created_at: '2026-08-14T10:00:00',
  updated_at: '2026-08-14T10:02:00',
}

const documentTwo: DocumentRecord = {
  ...documentOne,
  id: 'doc-2',
  filename: 'resume.docx',
  content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  size: 900,
  status: 'uploaded',
}

const automaticClassification: DocumentClassification = {
  document_id: 'doc-1',
  predicted_type: 'invoice',
  effective_type: 'invoice',
  source: 'classifier',
  classifier_version: 'local_keyword_v1',
  classified_at: '2026-08-14T10:01:00',
  updated_at: '2026-08-14T10:01:00',
  reviewed_at: null,
}

const reviewedClassification: DocumentClassification = {
  ...automaticClassification,
  effective_type: 'contract',
  source: 'human',
  updated_at: '2026-08-14T10:03:00',
  reviewed_at: '2026-08-14T10:03:00',
}

function job(status: ProcessingJobStatus, id = `job-${status}`): ProcessingJob {
  return {
    id,
    document_id: 'doc-1',
    status,
    attempt_count: status === 'queued' ? 0 : 1,
    max_attempts: 2,
    last_error_code: status === 'failed' ? 'processor_exception' : null,
    queued_at: '2026-08-14T10:00:00',
    started_at: status === 'queued' ? null : '2026-08-14T10:00:01',
    finished_at: status === 'succeeded' || status === 'failed' ? '2026-08-14T10:00:02' : null,
    updated_at: '2026-08-14T10:00:02',
  }
}

beforeEach(() => {
  vi.mocked(documentApi.listDocuments).mockResolvedValue([documentOne, documentTwo])
  vi.mocked(documentApi.listJobs).mockResolvedValue([])
  vi.mocked(documentApi.getClassification).mockResolvedValue(automaticClassification)
  vi.mocked(documentApi.updateClassification).mockResolvedValue(reviewedClassification)
  vi.mocked(documentApi.getExtraction).mockRejectedValue(
    new ApiError('structured_extraction_not_found', 404, 'structured_extraction_not_found'),
  )
  vi.mocked(documentApi.getExtractionReviews).mockResolvedValue({
    document_id: 'doc-1',
    corrections: [],
  })
  vi.mocked(documentApi.reprocessDocument).mockResolvedValue(job('queued', 'job-new'))
})

afterEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe('document workspace', () => {
  test('shows the document library loading state', async () => {
    let resolveDocuments: (documents: DocumentRecord[]) => void = () => undefined
    vi.mocked(documentApi.listDocuments).mockReturnValue(
      new Promise((resolve) => {
        resolveDocuments = resolve
      }),
    )

    render(<App />)

    expect(screen.getByText('Loading documents...')).toBeInTheDocument()
    await act(async () => resolveDocuments([]))
  })

  test('shows a useful empty state', async () => {
    vi.mocked(documentApi.listDocuments).mockResolvedValue([])

    render(<App />)

    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument()
  })

  test('selects a document and renders its metadata and job history', async () => {
    vi.mocked(documentApi.listJobs).mockResolvedValue([job('succeeded')])
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))

    expect(await screen.findByRole('heading', { name: 'invoice-august.pdf' })).toBeInTheDocument()
    expect(screen.getByText('application/pdf')).toBeInTheDocument()
    expect(screen.getByText('Succeeded')).toBeInTheDocument()
    expect(documentApi.listJobs).toHaveBeenCalledWith('doc-1')
  })

  test('renders queued, running, succeeded, and failed jobs with stable error codes', async () => {
    vi.mocked(documentApi.listJobs).mockResolvedValue([
      job('queued'),
      job('running'),
      job('succeeded'),
      job('failed'),
    ])
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))

    expect(await screen.findByText('Queued')).toBeInTheDocument()
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getByText('Succeeded')).toBeInTheDocument()
    expect(screen.getAllByText('Failed').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Error code')).toHaveTextContent('processor_exception')
    expect(screen.getByRole('button', { name: 'Reprocess' })).toBeDisabled()
  })

  test('polls active processing and stops after a terminal state', async () => {
    vi.useFakeTimers()
    vi.mocked(documentApi.listJobs)
      .mockResolvedValueOnce([job('running')])
      .mockResolvedValueOnce([job('succeeded')])
    render(<App pollIntervalMs={100} />)
    await flushPromises()

    fireEvent.click(screen.getByRole('button', { name: /invoice-august\.pdf/i }))
    await flushPromises()
    expect(screen.getByText('Running')).toBeInTheDocument()

    await act(async () => vi.advanceTimersByTimeAsync(100))
    expect(screen.getByText('Succeeded')).toBeInTheDocument()
    const callsAfterCompletion = vi.mocked(documentApi.listJobs).mock.calls.length

    await act(async () => vi.advanceTimersByTimeAsync(400))
    expect(documentApi.listJobs).toHaveBeenCalledTimes(callsAfterCompletion)
  })

  test('queues reprocessing and guards the action while the new job is active', async () => {
    vi.mocked(documentApi.listJobs).mockResolvedValue([job('succeeded')])
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))

    const reprocessButton = await screen.findByRole('button', { name: 'Reprocess' })
    fireEvent.click(reprocessButton)

    expect(await screen.findByText('Reprocessing job queued.')).toBeInTheDocument()
    expect(documentApi.reprocessDocument).toHaveBeenCalledWith('doc-1')
    expect(screen.getByText('Queued')).toBeInTheDocument()
    expect(reprocessButton).toBeDisabled()
  })

  test('surfaces API errors and supports retrying the library request', async () => {
    vi.mocked(documentApi.listDocuments)
      .mockRejectedValueOnce(new ApiError('Document service unavailable.', 503))
      .mockResolvedValueOnce([documentOne])
    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Document service unavailable.')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('invoice-august.pdf')).toBeInTheDocument()
    expect(documentApi.listDocuments).toHaveBeenCalledTimes(2)
  })

  test('renders the automatic and effective classification', async () => {
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))

    expect(await screen.findByText('Automatic prediction')).toBeInTheDocument()
    expect(screen.getByText('Automatic prediction').parentElement).toHaveTextContent('Invoice')
    expect(screen.getByText('Effective classification').parentElement).toHaveTextContent('Invoice')
    expect(screen.getByText('Source').parentElement).toHaveTextContent('Classifier')
    expect(screen.getByText('local_keyword_v1')).toBeInTheDocument()
  })

  test('identifies a reviewed classification override', async () => {
    vi.mocked(documentApi.getClassification).mockResolvedValue(reviewedClassification)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))

    expect(await screen.findByText('Human override')).toBeInTheDocument()
    expect(screen.getByText('Automatic prediction').parentElement).toHaveTextContent('Invoice')
    expect(screen.getByText('Effective classification').parentElement).toHaveTextContent('Contract')
    expect(screen.getByText('Source').parentElement).toHaveTextContent('Human')
  })

  test('submits and refreshes a classification correction', async () => {
    vi.mocked(documentApi.getClassification)
      .mockResolvedValueOnce(automaticClassification)
      .mockResolvedValueOnce(reviewedClassification)
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))
    await screen.findByText('Automatic prediction')

    fireEvent.change(screen.getByLabelText('Correct classification'), {
      target: { value: 'contract' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    expect(await screen.findByText('Classification correction saved.')).toBeInTheDocument()
    expect(documentApi.updateClassification).toHaveBeenCalledWith('doc-1', 'contract')
    expect(documentApi.getClassification).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Effective classification').parentElement).toHaveTextContent('Contract')
  })

  test('guards a duplicate classification correction', async () => {
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))

    expect(await screen.findByRole('button', { name: 'Save correction' })).toBeDisabled()
    expect(documentApi.updateClassification).not.toHaveBeenCalled()
  })

  test('surfaces correction API errors without changing the effective type', async () => {
    vi.mocked(documentApi.updateClassification).mockRejectedValue(
      new ApiError('classification correction rejected', 422),
    )
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))
    await screen.findByText('Automatic prediction')

    fireEvent.change(screen.getByLabelText('Correct classification'), {
      target: { value: 'contract' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('classification correction rejected')
    expect(screen.getByText('Effective classification').parentElement).toHaveTextContent('Invoice')
  })

  test('shows classification loading state', async () => {
    let resolveClassification: (value: DocumentClassification) => void = () => undefined
    vi.mocked(documentApi.getClassification).mockReturnValue(
      new Promise((resolve) => {
        resolveClassification = resolve
      }),
    )
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))

    expect(await screen.findByText('Loading classification...')).toBeInTheDocument()
    await act(async () => resolveClassification(automaticClassification))
  })

  test('handles missing classification state without treating it as a failure', async () => {
    vi.mocked(documentApi.getClassification).mockRejectedValue(
      new ApiError('classification_not_found', 404, 'classification_not_found'),
    )
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))

    expect(await screen.findByText('Classification is not available yet.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  test('clears stale classification state when the selected document changes', async () => {
    let resolveSecondClassification: (value: DocumentClassification) => void = () => undefined
    vi.mocked(documentApi.getClassification)
      .mockResolvedValueOnce(automaticClassification)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveSecondClassification = resolve
        }),
      )
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /invoice-august\.pdf/i }))
    await screen.findByText('Automatic prediction')

    fireEvent.click(screen.getByRole('button', { name: /resume\.docx/i }))

    expect(await screen.findByText('Loading classification...')).toBeInTheDocument()
    expect(screen.queryByText('Automatic prediction')).not.toBeInTheDocument()
    await act(async () => {
      resolveSecondClassification({
        ...automaticClassification,
        document_id: 'doc-2',
        predicted_type: 'resume',
        effective_type: 'resume',
      })
    })
  })
})

async function flushPromises() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}
