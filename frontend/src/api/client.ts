export type ProcessingStatus = 'uploaded' | 'processing' | 'processed' | 'failed'
export type ProcessingJobStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export type DocumentType = 'invoice' | 'resume' | 'contract' | 'other' | 'unknown'
export type ClassificationSource = 'classifier' | 'human'

export interface DocumentRecord {
  id: string
  filename: string
  content_type: string
  size: number
  storage_path: string
  status: ProcessingStatus
  created_at: string
  updated_at: string
}

export interface ProcessingJob {
  id: string
  document_id: string
  status: ProcessingJobStatus
  attempt_count: number
  max_attempts: number
  last_error_code: string | null
  queued_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
}

export interface UploadResponse {
  id: string
  filename: string
  status: ProcessingStatus
  job_id: string
}

export interface DocumentClassification {
  document_id: string
  predicted_type: DocumentType
  effective_type: DocumentType
  source: ClassificationSource
  classifier_version: string
  classified_at: string
  updated_at: string
  reviewed_at: string | null
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly detail: string | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError('Unable to reach the document service.', 0)
  }

  if (!response.ok) {
    let detail: string | null = null
    try {
      const body = (await response.json()) as { detail?: unknown }
      detail = typeof body.detail === 'string' ? body.detail : null
    } catch {
      // Error responses are not guaranteed to contain JSON.
    }
    throw new ApiError(detail ?? `Request failed with status ${response.status}.`, response.status, detail)
  }

  return (await response.json()) as T
}

export const documentApi = {
  listDocuments: () => request<DocumentRecord[]>('/api/v1/documents/'),
  listJobs: (documentId: string) =>
    request<ProcessingJob[]>(`/api/v1/documents/${encodeURIComponent(documentId)}/jobs`),
  getClassification: (documentId: string) =>
    request<DocumentClassification>(
      `/api/v1/documents/${encodeURIComponent(documentId)}/classification`,
    ),
  updateClassification: (documentId: string, documentType: DocumentType) =>
    request<DocumentClassification>(
      `/api/v1/documents/${encodeURIComponent(documentId)}/classification`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_type: documentType }),
      },
    ),
  reprocessDocument: (documentId: string) =>
    request<ProcessingJob>(`/api/v1/documents/${encodeURIComponent(documentId)}/process`, {
      method: 'POST',
    }),
  uploadDocument: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<UploadResponse>('/api/v1/documents/upload', { method: 'POST', body })
  },
}
