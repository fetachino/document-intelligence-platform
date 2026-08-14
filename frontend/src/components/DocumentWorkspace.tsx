import React from 'react'
import type {
  DocumentClassification,
  DocumentRecord,
  DocumentType,
  ProcessingJob,
} from '../api/client'
import { ClassificationReview } from './ClassificationReview'
import { StatusBadge } from './StatusBadge'

interface DocumentWorkspaceProps {
  document: DocumentRecord | null
  jobs: ProcessingJob[]
  jobsLoading: boolean
  jobsError: string | null
  reprocessing: boolean
  feedback: WorkspaceFeedback | null
  classification: DocumentClassification | null
  classificationLoading: boolean
  classificationError: string | null
  classificationCorrecting: boolean
  classificationFeedback: WorkspaceFeedback | null
  onReprocess: () => void
  onCorrectClassification: (documentType: DocumentType) => void
}

export interface WorkspaceFeedback {
  message: string
  kind: 'success' | 'error'
}

export function DocumentWorkspace({
  document,
  jobs,
  jobsLoading,
  jobsError,
  reprocessing,
  feedback,
  classification,
  classificationLoading,
  classificationError,
  classificationCorrecting,
  classificationFeedback,
  onReprocess,
  onCorrectClassification,
}: DocumentWorkspaceProps) {
  if (!document) {
    return (
      <main className="document-workspace workspace-empty">
        <p>Select a document to inspect its processing lifecycle.</p>
      </main>
    )
  }

  const hasActiveJob = jobs.some((job) => job.status === 'queued' || job.status === 'running')

  return (
    <main className="document-workspace">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">Document detail</p>
          <h2>{document.filename}</h2>
          <p className="document-id">ID {document.id}</p>
        </div>
        <button
          className="button button-primary"
          type="button"
          disabled={hasActiveJob || reprocessing}
          onClick={onReprocess}
        >
          {reprocessing ? 'Queueing...' : 'Reprocess'}
        </button>
      </header>

      {feedback && (
        <p
          className={`feedback feedback-${feedback.kind}`}
          role={feedback.kind === 'error' ? 'alert' : 'status'}
        >
          {feedback.message}
        </p>
      )}

      <section className="metadata-band" aria-label="Document metadata">
        <Metadata label="Status"><StatusBadge status={document.status} /></Metadata>
        <Metadata label="Type">{document.content_type}</Metadata>
        <Metadata label="Size">{formatBytes(document.size)}</Metadata>
        <Metadata label="Uploaded">{formatDate(document.created_at)}</Metadata>
        <Metadata label="Updated">{formatDate(document.updated_at)}</Metadata>
      </section>

      <ClassificationReview
        classification={classification}
        loading={classificationLoading}
        error={classificationError}
        correcting={classificationCorrecting}
        feedback={classificationFeedback}
        onCorrect={onCorrectClassification}
      />

      <section className="job-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Processing</p>
            <h3>Job history</h3>
          </div>
          {hasActiveJob && <span className="polling-indicator">Live</span>}
        </div>

        {jobsLoading && <p className="state-message">Loading job history...</p>}
        {!jobsLoading && jobsError && <p className="state-message state-error" role="alert">{jobsError}</p>}
        {!jobsLoading && !jobsError && jobs.length === 0 && (
          <p className="state-message">No processing jobs recorded.</p>
        )}
        {!jobsLoading && !jobsError && jobs.length > 0 && (
          <div className="job-list">
            {jobs.map((job) => (
              <article className="job-row" key={job.id}>
                <div className="job-status">
                  <StatusBadge status={job.status} />
                  <span>Attempt {job.attempt_count} of {job.max_attempts}</span>
                </div>
                <div className="job-timing">
                  <span>Queued {formatDate(job.queued_at)}</span>
                  {job.finished_at && <span>Finished {formatDate(job.finished_at)}</span>}
                </div>
                {job.last_error_code && (
                  <code className="error-code" aria-label="Error code">{job.last_error_code}</code>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  )
}

function Metadata({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="metadata-item"><span>{label}</span><strong>{children}</strong></div>
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
