import React, { useEffect, useState } from 'react'
import type { DocumentClassification, DocumentType } from '../api/client'
import type { WorkspaceFeedback } from './DocumentWorkspace'

const DOCUMENT_TYPES: DocumentType[] = ['invoice', 'resume', 'contract', 'other', 'unknown']

interface ClassificationReviewProps {
  classification: DocumentClassification | null
  loading: boolean
  error: string | null
  correcting: boolean
  feedback: WorkspaceFeedback | null
  onCorrect: (documentType: DocumentType) => void
  canReview: boolean
}

export function ClassificationReview({
  classification,
  loading,
  error,
  correcting,
  feedback,
  onCorrect,
  canReview,
}: ClassificationReviewProps) {
  const [selectedType, setSelectedType] = useState<DocumentType>('unknown')

  useEffect(() => {
    if (classification) setSelectedType(classification.effective_type)
  }, [classification])

  const isHumanOverride =
    classification?.source === 'human' &&
    classification.effective_type !== classification.predicted_type

  return (
    <section className="classification-section" aria-labelledby="classification-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Classification</p>
          <h3 id="classification-heading">Document type review</h3>
        </div>
        {isHumanOverride && <span className="review-indicator">Human override</span>}
      </div>

      {loading && <p className="state-message">Loading classification...</p>}
      {!loading && error && <p className="state-message state-error" role="alert">{error}</p>}
      {!loading && !error && !classification && (
        <p className="state-message">Classification is not available yet.</p>
      )}
      {!loading && !error && classification && (
        <>
          <div className="classification-summary">
            <ClassificationValue
              label="Automatic prediction"
              value={formatType(classification.predicted_type)}
            />
            <ClassificationValue
              label="Effective classification"
              value={formatType(classification.effective_type)}
            />
            <ClassificationValue label="Source" value={formatType(classification.source)} />
            <ClassificationValue label="Classifier" value={classification.classifier_version} />
          </div>

          <div className="classification-review-form">
            <label htmlFor="classification-type">Correct classification</label>
            <div className="classification-review-controls">
              <select
                id="classification-type"
                value={selectedType}
                disabled={!canReview || correcting}
                onChange={(event) => setSelectedType(event.target.value as DocumentType)}
              >
                {DOCUMENT_TYPES.map((documentType) => (
                  <option key={documentType} value={documentType}>{formatType(documentType)}</option>
                ))}
              </select>
              <button
                className="button button-secondary"
                type="button"
                disabled={!canReview || correcting || selectedType === classification.effective_type}
                onClick={() => onCorrect(selectedType)}
              >
                {correcting ? 'Saving...' : 'Save correction'}
              </button>
            </div>
          </div>

          <div className="classification-timestamps">
            <span>Classified {formatDate(classification.classified_at)}</span>
            {classification.reviewed_at && (
              <span>Reviewed {formatDate(classification.reviewed_at)}</span>
            )}
          </div>
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

function ClassificationValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="classification-value">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function formatType(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
