import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  documentApi,
  type DocumentClassification,
  type DocumentRecord,
  type DocumentType,
  type ProcessingJob,
} from './api/client'
import { DocumentLibrary } from './components/DocumentLibrary'
import { GroundedQa } from './components/GroundedQa'
import { SemanticSearch } from './components/SemanticSearch'
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
  const [classification, setClassification] = useState<DocumentClassification | null>(null)
  const [classificationLoading, setClassificationLoading] = useState(false)
  const [classificationError, setClassificationError] = useState<string | null>(null)
  const [classificationCorrecting, setClassificationCorrecting] = useState(false)
  const [classificationFeedback, setClassificationFeedback] =
    useState<WorkspaceFeedback | null>(null)
  const classificationRequestVersion = useRef(0)

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
    const requestVersion = ++classificationRequestVersion.current
    setClassification(null)
    setClassificationError(null)
    setClassificationFeedback(null)
    setClassificationCorrecting(false)
    setClassificationLoading(Boolean(selectedDocumentId))
    if (!selectedDocumentId) return

    void documentApi.getClassification(selectedDocumentId).then(
      (loadedClassification) => {
        if (classificationRequestVersion.current !== requestVersion) return
        setClassification(loadedClassification)
        setClassificationLoading(false)
      },
      (error: unknown) => {
        if (classificationRequestVersion.current !== requestVersion) return
        setClassificationError(
          error instanceof ApiError && error.detail === 'classification_not_found'
            ? null
            : errorMessage(error, 'Could not load classification.'),
        )
        setClassificationLoading(false)
      },
    )

    return () => {
      // Invalidating the request prevents a late response from a prior selection being rendered.
      if (classificationRequestVersion.current === requestVersion) {
        classificationRequestVersion.current += 1
      }
    }
  }, [selectedDocumentId])

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

  async function correctClassification(documentType: DocumentType) {
    if (
      !selectedDocumentId ||
      !classification ||
      classification.document_id !== selectedDocumentId ||
      classification.effective_type === documentType ||
      classificationCorrecting
    ) return

    const documentId = selectedDocumentId
    const requestVersion = classificationRequestVersion.current
    setClassificationCorrecting(true)
    setClassificationFeedback(null)

    try {
      const updated = await documentApi.updateClassification(documentId, documentType)
      if (classificationRequestVersion.current !== requestVersion) return
      setClassification(updated)

      try {
        const refreshed = await documentApi.getClassification(documentId)
        if (classificationRequestVersion.current !== requestVersion) return
        setClassification(refreshed)
        setClassificationError(null)
        setClassificationFeedback({ message: 'Classification correction saved.', kind: 'success' })
      } catch (error) {
        if (classificationRequestVersion.current !== requestVersion) return
        setClassificationFeedback({
          message: errorMessage(error, 'Correction saved, but classification could not be refreshed.'),
          kind: 'error',
        })
      }
    } catch (error) {
      if (classificationRequestVersion.current !== requestVersion) return
      setClassificationFeedback({
        message: errorMessage(error, 'Could not save classification correction.'),
        kind: 'error',
      })
    } finally {
      if (classificationRequestVersion.current === requestVersion) {
        setClassificationCorrecting(false)
      }
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

      <SemanticSearch documents={documents} selectedDocument={selectedDocument} />

      <GroundedQa documents={documents} selectedDocument={selectedDocument} />

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
          classification={
            classification?.document_id === selectedDocumentId ? classification : null
          }
          classificationLoading={classificationLoading}
          classificationError={classificationError}
          classificationCorrecting={classificationCorrecting}
          classificationFeedback={classificationFeedback}
          onReprocess={() => void reprocess()}
          onCorrectClassification={(documentType) => void correctClassification(documentType)}
        />
      </div>
    </div>
  )
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  return fallback
}
