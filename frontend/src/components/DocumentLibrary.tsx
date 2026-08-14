import React from 'react'
import type { DocumentRecord } from '../api/client'
import { StatusBadge } from './StatusBadge'

interface DocumentLibraryProps {
  documents: DocumentRecord[]
  selectedDocumentId: string | null
  loading: boolean
  error: string | null
  onSelect: (documentId: string) => void
  onRetry: () => void
}

export function DocumentLibrary({
  documents,
  selectedDocumentId,
  loading,
  error,
  onSelect,
  onRetry,
}: DocumentLibraryProps) {
  return (
    <aside className="document-library" aria-label="Document library">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Workspace</p>
          <h2>Documents</h2>
        </div>
        <span className="document-count" aria-label={`${documents.length} documents`}>
          {documents.length}
        </span>
      </div>

      {loading && <p className="state-message">Loading documents...</p>}
      {!loading && error && (
        <div className="state-message state-error" role="alert">
          <p>{error}</p>
          <button className="button button-secondary" type="button" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}
      {!loading && !error && documents.length === 0 && (
        <p className="state-message">No documents yet. Upload one to begin processing.</p>
      )}
      {!loading && !error && documents.length > 0 && (
        <div className="document-list">
          {documents.map((document) => (
            <button
              className="document-row"
              data-selected={selectedDocumentId === document.id}
              aria-pressed={selectedDocumentId === document.id}
              type="button"
              key={document.id}
              onClick={() => onSelect(document.id)}
            >
              <span className="document-row-main">
                <strong>{document.filename}</strong>
                <span>{formatBytes(document.size)}</span>
              </span>
              <StatusBadge status={document.status} />
            </button>
          ))}
        </div>
      )}
    </aside>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
