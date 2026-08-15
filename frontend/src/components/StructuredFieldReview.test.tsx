import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import {
  ApiError,
  documentApi,
  type StructuredExtraction,
  type StructuredField,
  type StructuredFieldCorrection,
  type StructuredFieldReviewHistory,
} from '../api/client'
import { StructuredFieldReview } from './StructuredFieldReview'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    documentApi: {
      ...actual.documentApi,
      getExtraction: vi.fn(),
      getExtractionReviews: vi.fn(),
      correctStructuredField: vi.fn(),
    },
  }
})

const automaticField: StructuredField = {
  field_name: 'total_amount',
  value_index: 0,
  value: '$10.00',
  effective_value: '$10.00',
  reviewed: false,
  reviewer_id: null,
  reviewed_at: null,
  page_number: 2,
  extraction_method: 'local_regex',
  extractor_version: 'local_regex_v1',
}

const reviewedField: StructuredField = {
  ...automaticField,
  effective_value: '$12.00',
  reviewed: true,
  reviewer_id: 'reviewer-a',
  reviewed_at: '2026-08-14T10:03:00',
}

const automaticExtraction: StructuredExtraction = {
  document_id: 'doc-1',
  document_type: 'invoice',
  status: 'completed',
  extractor_version: 'local_regex_v1',
  started_at: '2026-08-14T10:01:00',
  completed_at: '2026-08-14T10:02:00',
  fields: [automaticField],
}

const emptyHistory: StructuredFieldReviewHistory = {
  document_id: 'doc-1',
  corrections: [],
}

const activeCorrection: StructuredFieldCorrection = {
  id: 'correction-active',
  document_id: 'doc-1',
  field_name: 'total_amount',
  value_index: 0,
  automatic_value: '$10.00',
  previous_effective_value: '$10.00',
  corrected_value: '$12.00',
  effective_value: '$12.00',
  reviewer_id: 'reviewer-a',
  created_at: '2026-08-14T10:03:00',
  status: 'active',
}

beforeEach(() => {
  vi.mocked(documentApi.getExtraction).mockResolvedValue(automaticExtraction)
  vi.mocked(documentApi.getExtractionReviews).mockResolvedValue(emptyHistory)
  vi.mocked(documentApi.correctStructuredField).mockResolvedValue(reviewedField)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('StructuredFieldReview', () => {
  test('renders automatic values and extraction provenance', async () => {
    render(<StructuredFieldReview documentId="doc-1" canReview />)

    expect(await screen.findByRole('heading', { name: 'Total Amount' })).toBeInTheDocument()
    expect(screen.getByText('Automatic').parentElement).toHaveTextContent('$10.00')
    expect(screen.getByText('Effective').parentElement).toHaveTextContent('$10.00')
    expect(screen.getByText('Page 2 | local_regex | local_regex_v1')).toBeInTheDocument()
    expect(screen.getByText('Invoice')).toBeInTheDocument()
  })

  test('renders effective reviewed values as human overrides', async () => {
    vi.mocked(documentApi.getExtraction).mockResolvedValue({
      ...automaticExtraction,
      fields: [reviewedField],
    })
    render(<StructuredFieldReview documentId="doc-1" canReview />)

    expect(await screen.findByText('Human override')).toBeInTheDocument()
    expect(screen.getByText('Automatic').parentElement).toHaveTextContent('$10.00')
    expect(screen.getByText('Effective').parentElement).toHaveTextContent('$12.00')
  })

  test('groups multiple indexed values under one field name', async () => {
    vi.mocked(documentApi.getExtraction).mockResolvedValue({
      ...automaticExtraction,
      document_type: 'contract',
      fields: [
        { ...automaticField, field_name: 'party', value: 'Acme', effective_value: 'Acme' },
        {
          ...automaticField,
          field_name: 'party',
          value_index: 1,
          value: 'Example LLC',
          effective_value: 'Example LLC',
        },
      ],
    })
    render(<StructuredFieldReview documentId="doc-1" canReview />)

    expect(await screen.findByRole('heading', { name: 'Party' })).toBeInTheDocument()
    expect(screen.getByText('Value 1')).toBeInTheDocument()
    expect(screen.getByText('Value 2')).toBeInTheDocument()
    expect(screen.getAllByText('Acme')).toHaveLength(2)
    expect(screen.getAllByText('Example LLC')).toHaveLength(2)
  })

  test('submits a correction and refreshes extraction and history', async () => {
    vi.mocked(documentApi.getExtraction)
      .mockResolvedValueOnce(automaticExtraction)
      .mockResolvedValueOnce({ ...automaticExtraction, fields: [reviewedField] })
    vi.mocked(documentApi.getExtractionReviews)
      .mockResolvedValueOnce(emptyHistory)
      .mockResolvedValueOnce({ document_id: 'doc-1', corrections: [activeCorrection] })
    render(<StructuredFieldReview documentId="doc-1" canReview />)
    const input = await screen.findByLabelText('Correct value')

    fireEvent.change(input, { target: { value: '$12.00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))

    expect(await screen.findByText('Field correction saved.')).toBeInTheDocument()
    expect(documentApi.correctStructuredField).toHaveBeenCalledWith(
      'doc-1',
      'total_amount',
      0,
      '$12.00',
    )
    expect(documentApi.getExtraction).toHaveBeenCalledTimes(2)
    expect(documentApi.getExtractionReviews).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Human override')).toBeInTheDocument()
    expect(screen.getByText('reviewer-a')).toBeInTheDocument()
  })

  test('guards duplicate and no-op corrections', async () => {
    render(<StructuredFieldReview documentId="doc-1" canReview />)

    expect(await screen.findByRole('button', { name: 'Save field' })).toBeDisabled()
    expect(documentApi.correctStructuredField).not.toHaveBeenCalled()
  })

  test('surfaces correction errors without changing the effective value', async () => {
    vi.mocked(documentApi.correctStructuredField).mockRejectedValue(
      new ApiError('invalid_field_value', 422, 'invalid_field_value'),
    )
    render(<StructuredFieldReview documentId="doc-1" canReview />)
    const input = await screen.findByLabelText('Correct value')

    fireEvent.change(input, { target: { value: 'approximately ten' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('invalid_field_value')
    expect(screen.getByText('Effective').parentElement).toHaveTextContent('$10.00')
  })

  test('renders append-only active, superseded, and orphaned history states', async () => {
    const corrections: StructuredFieldCorrection[] = [
      { ...activeCorrection, id: 'old', status: 'superseded', effective_value: null },
      activeCorrection,
      {
        ...activeCorrection,
        id: 'missing',
        field_name: 'invoice_number',
        corrected_value: 'INV-2',
        status: 'orphaned',
        effective_value: null,
      },
    ]
    vi.mocked(documentApi.getExtractionReviews).mockResolvedValue({
      document_id: 'doc-1',
      corrections,
    })
    render(<StructuredFieldReview documentId="doc-1" canReview />)

    expect(await screen.findByText('Superseded')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Orphaned')).toBeInTheDocument()
    expect(screen.getAllByText('reviewer-a')).toHaveLength(3)
    expect(screen.getAllByText('Automatic $10.00')).toHaveLength(3)
  })

  test('surfaces extraction API errors', async () => {
    vi.mocked(documentApi.getExtraction).mockRejectedValue(
      new ApiError('extraction_service_unavailable', 503),
    )
    render(<StructuredFieldReview documentId="doc-1" canReview />)

    expect(await screen.findByRole('alert')).toHaveTextContent('extraction_service_unavailable')
  })

  test('handles missing extraction state without an error alert', async () => {
    vi.mocked(documentApi.getExtraction).mockRejectedValue(
      new ApiError('structured_extraction_not_found', 404, 'structured_extraction_not_found'),
    )
    render(<StructuredFieldReview documentId="doc-1" canReview />)

    expect(await screen.findByText('Structured extraction is not available yet.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  test('clears stale fields when document selection changes', async () => {
    let resolveSecondExtraction: (value: StructuredExtraction) => void = () => undefined
    vi.mocked(documentApi.getExtraction)
      .mockResolvedValueOnce(automaticExtraction)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveSecondExtraction = resolve
        }),
      )
    vi.mocked(documentApi.getExtractionReviews)
      .mockResolvedValueOnce(emptyHistory)
      .mockResolvedValueOnce({ document_id: 'doc-2', corrections: [] })
    const { rerender } = render(<StructuredFieldReview documentId="doc-1" canReview />)
    await screen.findByRole('heading', { name: 'Total Amount' })

    rerender(<StructuredFieldReview documentId="doc-2" canReview />)

    expect(await screen.findByText('Loading structured fields...')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Total Amount' })).not.toBeInTheDocument()
    await act(async () => {
      resolveSecondExtraction({
        ...automaticExtraction,
        document_id: 'doc-2',
        document_type: 'resume',
        fields: [],
      })
    })
  })
})
