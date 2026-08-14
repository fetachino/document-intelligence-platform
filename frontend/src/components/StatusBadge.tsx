import React from 'react'
import type { ProcessingJobStatus, ProcessingStatus } from '../api/client'

type Status = ProcessingStatus | ProcessingJobStatus

const labels: Record<Status, string> = {
  uploaded: 'Uploaded',
  processing: 'Processing',
  processed: 'Processed',
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
}

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`status-badge status-${status}`}>{labels[status]}</span>
}
