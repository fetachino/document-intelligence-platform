import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, documentApi, type DocumentRecord, type ProcessingJob } from './api/client'
import { DocumentLibrary } from './components/DocumentLibrary'
import {
  DocumentWorkspace,
  type WorkspaceFeedback,
} from './components/DocumentWorkspace'
import './styles.css'

const DEFAULT_POLL_INTERVAL_MS = 2_000

export interface AppProps {
  pollIntervalMs?: number
}

export default function App({ pollIntervalMs = DEFAULT_POLL_INTERVAL_MS }: AppProps) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [documentsLoading, setDocumentsLoading] = useState(true)
  const [documentsError, setDocumentsError] = useState<string | null>(null)
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null)
  const [jobs, setJobs] = useState<ProcessingJob[]>([])
  const [jobsLoading, setJobsLoading] = useState(false)
  const [jobsError, setJobsError] = useState<string | null>(null)
  const [reprocessing, setReprocessing] = useState(false)
  const [feedback, setFeedback] = useState<WorkspaceFeedback | null>(null)
  const [uploadFeedback, setUploadFeedback] = useState<WorkspaceFeedback | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)

  const selectedDocument = useMemo(
    () => documents.find((document) => document.id === selectedDocumentId) ?? null,
    [documents, selectedDocumentId],
  )
  const hasActiveJob = jobs.some((job) => job.status === 'queued' || job.status === 'running')

  const loadDocuments = useCallback(async () => {
    setDocumentsLoading(true)
    setDocumentsError(null)
    try {
      setDocuments(await documentApi.listDocuments())
    } catch (error) {
      setDocumentsError(errorMessage(error, 'Could not load documents.'))
    } finally {
      setDocumentsLoading(false)
    }
  }, [])

  const loadJobs = useCallback(async (documentId: string, showLoading = false) => {
    if (showLoading) setJobsLoading(true)
    setJobsError(null)
    try {
      setJobs(await documentApi.listJobs(documentId))
    } catch (error) {
      setJobsError(errorMessage(error, 'Could not load job history.'))
    } finally {
      if (showLoading) setJobsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadDocuments()
  }, [loadDocuments])

  useEffect(() => {
    setJobs([])
    setFeedback(null)
    if (selectedDocumentId) void loadJobs(selectedDocumentId, true)
  }, [selectedDocumentId, loadJobs])

  useEffect(() => {
    if (!selectedDocumentId || !hasActiveJob) return
    let disposed = false
    let requestInFlight = false
    const timer = window.setInterval(async () => {
      if (requestInFlight) return
      requestInFlight = true
      try {
        const [loadedDocuments, loadedJobs] = await Promise.all([
          documentApi.listDocuments(),
          documentApi.listJobs(selectedDocumentId),
        ])
        if (!disposed) {
          setDocuments(loadedDocuments)
          setJobs(loadedJobs)
          setJobsError(null)
        }
      } catch (error) {
        if (!disposed) setJobsError(errorMessage(error, 'Could not refresh processing state.'))
      } finally {
        requestInFlight = false
      }
    }, pollIntervalMs)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [hasActiveJob, pollIntervalMs, selectedDocumentId])

  async function reprocess() {
    if (!selectedDocumentId || hasActiveJob || reprocessing) return
    setReprocessing(true)
    setFeedback(null)
    try {
      const job = await documentApi.reprocessDocument(selectedDocumentId)
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)])
      setFeedback({ message: 'Reprocessing job queued.', kind: 'success' })
    } catch (error) {
      setFeedback({
        message: errorMessage(error, 'Could not queue reprocessing.'),
        kind: 'error',
      })
    } finally {
      setReprocessing(false)
    }
  }

  async function upload() {
    if (!file || uploading) return
    setUploading(true)
    setUploadFeedback(null)
    try {
      const uploaded = await documentApi.uploadDocument(file)
      setDocuments(await documentApi.listDocuments())
      setSelectedDocumentId(uploaded.id)
      setFile(null)
      setUploadFeedback({
        message: 'Document uploaded and queued for processing.',
        kind: 'success',
      })
    } catch (error) {
      setUploadFeedback({
        message: errorMessage(error, 'Could not upload document.'),
        kind: 'error',
      })
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Document intelligence</p>
          <h1>Processing workspace</h1>
        </div>
        <div className="upload-control">
          <label className="file-picker">
            <span>{file ? file.name : 'Choose document'}</span>
            <input
              aria-label="Choose document"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button className="button button-primary" type="button" disabled={!file || uploading} onClick={upload}>
            {uploading ? 'Uploading...' : 'Upload'}
          </button>
        </div>
      </header>

      {uploadFeedback && (
        <p
          className={`global-feedback feedback-${uploadFeedback.kind}`}
          role={uploadFeedback.kind === 'error' ? 'alert' : 'status'}
        >
          {uploadFeedback.message}
        </p>
      )}

      <div className="workspace-layout">
        <DocumentLibrary
          documents={documents}
          selectedDocumentId={selectedDocumentId}
          loading={documentsLoading}
          error={documentsError}
          onSelect={setSelectedDocumentId}
          onRetry={() => void loadDocuments()}
        />
        <DocumentWorkspace
          document={selectedDocument}
          jobs={jobs}
          jobsLoading={jobsLoading}
          jobsError={jobsError}
          reprocessing={reprocessing}
          feedback={feedback}
          onReprocess={() => void reprocess()}
        />
      </div>
    </div>
  )
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  return fallback
}
