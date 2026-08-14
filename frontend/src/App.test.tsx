import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App from './App'
import {
  ApiError,
  documentApi,
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
})

async function flushPromises() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}
