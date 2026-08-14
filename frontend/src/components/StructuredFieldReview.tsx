import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  documentApi,
  type StructuredExtraction,
  type StructuredField,
  type StructuredFieldCorrection,
  type StructuredFieldReviewHistory,
} from '../api/client'

interface StructuredFieldReviewProps {
  documentId: string
}

interface ReviewState {
  documentId: string
  extraction: StructuredExtraction | null
  history: StructuredFieldReviewHistory | null
  loading: boolean
  missing: boolean
  error: string | null
}

interface ReviewFeedback {
  message: string
  kind: 'success' | 'error'
}

export function StructuredFieldReview({ documentId }: StructuredFieldReviewProps) {
  const [state, setState] = useState<ReviewState>({
    documentId,
    extraction: null,
    history: null,
    loading: true,
    missing: false,
    error: null,
  })
  const [reviewerId, setReviewerId] = useState('local-reviewer')
  const [correctingKey, setCorrectingKey] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<ReviewFeedback | null>(null)
  const requestVersion = useRef(0)

  useEffect(() => {
    const version = ++requestVersion.current
    setState({
      documentId,
      extraction: null,
      history: null,
      loading: true,
      missing: false,
      error: null,
    })
    setCorrectingKey(null)
    setFeedback(null)

    void loadReviewData(documentId).then(
      ({ extraction, history }) => {
        if (requestVersion.current !== version) return
        setState({ documentId, extraction, history, loading: false, missing: false, error: null })
      },
      (error: unknown) => {
        if (requestVersion.current !== version) return
        const missing = error instanceof ApiError && error.detail === 'structured_extraction_not_found'
        setState({
          documentId,
          extraction: null,
          history: null,
          loading: false,
          missing,
          error: missing ? null : errorMessage(error, 'Could not load structured extraction.'),
        })
      },
    )

    return () => {
      // Ignore extraction and history responses that complete after the selection changes.
      if (requestVersion.current === version) requestVersion.current += 1
    }
  }, [documentId])

  const currentState = state.documentId === documentId ? state : null
  const groupedFields = useMemo(
    () => groupFields(currentState?.extraction?.fields ?? []),
    [currentState?.extraction?.fields],
  )

  async function correctField(field: StructuredField, value: string) {
    const key = fieldKey(field)
    const trimmedReviewerId = reviewerId.trim()
    if (
      correctingKey ||
      !trimmedReviewerId ||
      value.trim() === field.effective_value
    ) return

    const version = requestVersion.current
    setCorrectingKey(key)
    setFeedback(null)
    try {
      const updatedField = await documentApi.correctStructuredField(
        documentId,
        field.field_name,
        field.value_index,
        value,
        trimmedReviewerId,
      )
      if (requestVersion.current !== version) return
      setState((current) => ({
        ...current,
        extraction: current.extraction
          ? {
              ...current.extraction,
              fields: current.extraction.fields.map((item) =>
                fieldKey(item) === key ? updatedField : item,
              ),
            }
          : null,
      }))

      try {
        const refreshed = await loadReviewData(documentId)
        if (requestVersion.current !== version) return
        setState({
          documentId,
          extraction: refreshed.extraction,
          history: refreshed.history,
          loading: false,
          missing: false,
          error: null,
        })
        setFeedback({ message: 'Field correction saved.', kind: 'success' })
      } catch (error) {
        if (requestVersion.current !== version) return
        setFeedback({
          message: errorMessage(error, 'Correction saved, but review data could not be refreshed.'),
          kind: 'error',
        })
      }
    } catch (error) {
      if (requestVersion.current !== version) return
      setFeedback({
        message: errorMessage(error, 'Could not save field correction.'),
        kind: 'error',
      })
    } finally {
      if (requestVersion.current === version) setCorrectingKey(null)
    }
  }

  return (
    <section className="structured-review-section" aria-labelledby="structured-review-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Structured extraction</p>
          <h3 id="structured-review-heading">Field review</h3>
        </div>
        {currentState?.extraction && (
          <span className={`extraction-status extraction-status-${currentState.extraction.status}`}>
            {formatLabel(currentState.extraction.status)}
          </span>
        )}
      </div>

      {(!currentState || currentState.loading) && (
        <p className="state-message">Loading structured fields...</p>
      )}
      {currentState?.error && (
        <p className="state-message state-error" role="alert">{currentState.error}</p>
      )}
      {currentState?.missing && (
        <p className="state-message">Structured extraction is not available yet.</p>
      )}
      {currentState?.extraction && currentState.history && (
        <>
          <div className="extraction-metadata">
            <span>Schema <strong>{formatLabel(currentState.extraction.document_type)}</strong></span>
            <span>Extractor <strong>{currentState.extraction.extractor_version}</strong></span>
          </div>

          <label className="reviewer-field" htmlFor="structured-reviewer-id">
            <span>Reviewer ID</span>
            <input
              id="structured-reviewer-id"
              value={reviewerId}
              maxLength={100}
              disabled={correctingKey !== null}
              onChange={(event) => setReviewerId(event.target.value)}
            />
          </label>

          {groupedFields.length === 0 && (
            <p className="state-message">No structured fields were extracted.</p>
          )}
          {groupedFields.length > 0 && (
            <div className="structured-field-groups">
              {groupedFields.map(([fieldName, fields]) => (
                <div className="structured-field-group" key={fieldName}>
                  <h4>{formatLabel(fieldName)}</h4>
                  {fields.map((field) => (
                    <StructuredFieldRow
                      key={fieldKey(field)}
                      field={field}
                      valueCount={fields.length}
                      reviewerAvailable={Boolean(reviewerId.trim())}
                      correcting={correctingKey === fieldKey(field)}
                      correctionLocked={correctingKey !== null}
                      onCorrect={(value) => void correctField(field, value)}
                    />
                  ))}
                </div>
              ))}
            </div>
          )}

          <ReviewHistory corrections={currentState.history.corrections} />
        </>
      )}

      {feedback && (
        <p
          className={`feedback feedback-${feedback.kind}`}
          role={feedback.kind === 'error' ? 'alert' : 'status'}
        >
          {feedback.message}
        </p>
      )}
    </section>
  )
}

function StructuredFieldRow({
  field,
  valueCount,
  reviewerAvailable,
  correcting,
  correctionLocked,
  onCorrect,
}: {
  field: StructuredField
  valueCount: number
  reviewerAvailable: boolean
  correcting: boolean
  correctionLocked: boolean
  onCorrect: (value: string) => void
}) {
  const [value, setValue] = useState(field.effective_value)
  const inputId = `field-${field.field_name}-${field.value_index}`

  useEffect(() => setValue(field.effective_value), [field.effective_value])

  return (
    <div className="structured-field-row">
      <div className="field-values">
        {valueCount > 1 && <span className="value-index">Value {field.value_index + 1}</span>}
        <div><span>Automatic</span><strong>{field.value}</strong></div>
        <div><span>Effective</span><strong>{field.effective_value}</strong></div>
        {field.reviewed && field.effective_value !== field.value && (
          <span className="review-indicator">Human override</span>
        )}
      </div>
      <p className="field-provenance">
        Page {field.page_number} | {field.extraction_method} | {field.extractor_version}
      </p>
      <div className="field-correction-controls">
        <label htmlFor={inputId}>Correct value</label>
        <input
          id={inputId}
          value={value}
          disabled={correctionLocked}
          onChange={(event) => setValue(event.target.value)}
        />
        <button
          className="button button-secondary"
          type="button"
          disabled={
            correctionLocked ||
            !reviewerAvailable ||
            !value.trim() ||
            value.trim() === field.effective_value
          }
          onClick={() => onCorrect(value)}
        >
          {correcting ? 'Saving...' : 'Save field'}
        </button>
      </div>
    </div>
  )
}

function ReviewHistory({ corrections }: { corrections: StructuredFieldCorrection[] }) {
  return (
    <div className="review-history">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Audit history</p>
          <h4>Field corrections</h4>
        </div>
        <span className="document-count" aria-label={`${corrections.length} corrections`}>
          {corrections.length}
        </span>
      </div>
      {corrections.length === 0 && <p className="state-message">No field corrections recorded.</p>}
      {corrections.length > 0 && (
        <div className="review-history-list">
          {corrections.map((correction) => (
            <article className="review-history-row" key={correction.id}>
              <div>
                <strong>{formatLabel(correction.field_name)}</strong>
                <span>Value {correction.value_index + 1}</span>
              </div>
              <div className="history-change">
                <span>Automatic {correction.automatic_value}</span>
                <span>Previous {correction.previous_effective_value}</span>
                <strong>Corrected {correction.corrected_value}</strong>
              </div>
              <div className="history-reviewer">
                <span>{correction.reviewer_id}</span>
                <span>{formatDate(correction.created_at)}</span>
              </div>
              <span className={`review-status review-status-${correction.status}`}>
                {formatLabel(correction.status)}
              </span>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

async function loadReviewData(documentId: string) {
  const [extraction, history] = await Promise.all([
    documentApi.getExtraction(documentId),
    documentApi.getExtractionReviews(documentId),
  ])
  return { extraction, history }
}

function groupFields(fields: StructuredField[]): Array<[string, StructuredField[]]> {
  const groups = new Map<string, StructuredField[]>()
  for (const field of fields) {
    const group = groups.get(field.field_name) ?? []
    group.push(field)
    groups.set(field.field_name, group)
  }
  return Array.from(groups.entries())
}

function fieldKey(field: Pick<StructuredField, 'field_name' | 'value_index'>): string {
  return `${field.field_name}:${field.value_index}`
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function formatLabel(value: string): string {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
