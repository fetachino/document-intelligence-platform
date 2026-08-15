import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  documentApi,
  type DocumentRecord,
  type QaResponse,
} from '../api/client'

type QaScope = 'all' | 'selected'

interface GroundedQaProps {
  documents: DocumentRecord[]
  selectedDocument: DocumentRecord | null
}

interface QaResponseState {
  scopeKey: string
  data: QaResponse
}

export function GroundedQa({ documents, selectedDocument }: GroundedQaProps) {
  const [question, setQuestion] = useState('')
  const [retrievalLimit, setRetrievalLimit] = useState(5)
  const [scope, setScope] = useState<QaScope>('all')
  const [response, setResponse] = useState<QaResponseState | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestVersion = useRef(0)
  const previousSelectedId = useRef<string | null>(selectedDocument?.id ?? null)

  const documentNames = useMemo(
    () => new Map(documents.map((document) => [document.id, document.filename])),
    [documents],
  )
  const scopeKey = scope === 'selected' ? `document:${selectedDocument?.id ?? 'none'}` : 'all'
  const currentResponse = response?.scopeKey === scopeKey ? response.data : null

  useEffect(() => {
    const selectedId = selectedDocument?.id ?? null
    if (scope === 'selected' && previousSelectedId.current !== selectedId) {
      resetResponse()
      if (!selectedId) setScope('all')
    }
    previousSelectedId.current = selectedId
  }, [scope, selectedDocument?.id])

  function resetResponse() {
    // Versioning invalidates responses from a prior question, scope, or selected document.
    requestVersion.current += 1
    setResponse(null)
    setLoading(false)
    setError(null)
  }

  function changeScope(nextScope: QaScope) {
    if (nextScope === scope || (nextScope === 'selected' && !selectedDocument)) return
    setScope(nextScope)
    resetResponse()
  }

  async function ask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedQuestion = question.trim()
    if (!trimmedQuestion || loading) return

    const version = ++requestVersion.current
    const documentIds = scope === 'selected' && selectedDocument ? [selectedDocument.id] : undefined
    setLoading(true)
    setResponse(null)
    setError(null)
    try {
      const result = await documentApi.askQuestion({
        question: trimmedQuestion,
        retrievalLimit,
        documentIds,
      })
      if (requestVersion.current !== version) return
      setResponse({ scopeKey, data: result })
    } catch (qaError) {
      if (requestVersion.current !== version) return
      setError(errorMessage(qaError, 'Could not answer the question.'))
    } finally {
      if (requestVersion.current === version) setLoading(false)
    }
  }

  return (
    <section className="grounded-qa" aria-labelledby="grounded-qa-heading">
      <div className="search-heading">
        <div>
          <p className="eyebrow">Grounded answering</p>
          <h2 id="grounded-qa-heading">Ask the documents</h2>
        </div>
        {currentResponse && (
          <div className="qa-provider-metadata">
            <span>{currentResponse.answer_provider}</span>
            <span>{currentResponse.retrieval.embedding_model}</span>
          </div>
        )}
      </div>

      <form className="search-form qa-form" onSubmit={(event) => void ask(event)}>
        <label className="search-query-field" htmlFor="grounded-qa-question">
          <span>Question</span>
          <input
            id="grounded-qa-question"
            value={question}
            maxLength={500}
            placeholder="Ask a question grounded in document text"
            onChange={(event) => setQuestion(event.target.value)}
          />
        </label>

        <fieldset className="search-scope">
          <legend>Scope</legend>
          <div className="segmented-control">
            <label data-selected={scope === 'all'}>
              <input
                type="radio"
                name="qa-scope"
                checked={scope === 'all'}
                onChange={() => changeScope('all')}
              />
              All documents
            </label>
            <label data-selected={scope === 'selected'} data-disabled={!selectedDocument}>
              <input
                type="radio"
                name="qa-scope"
                checked={scope === 'selected'}
                disabled={!selectedDocument}
                onChange={() => changeScope('selected')}
              />
              Selected document
            </label>
          </div>
        </fieldset>

        <label className="search-limit" htmlFor="grounded-qa-limit">
          <span>Context limit</span>
          <select
            id="grounded-qa-limit"
            value={retrievalLimit}
            onChange={(event) => setRetrievalLimit(Number(event.target.value))}
          >
            {[3, 5, 10].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>

        <button
          className="button button-primary search-submit"
          type="submit"
          disabled={!question.trim() || loading}
        >
          {loading ? 'Answering...' : 'Ask'}
        </button>
      </form>

      {scope === 'selected' && selectedDocument && (
        <p className="search-scope-context">Using {selectedDocument.filename}</p>
      )}
      {loading && <p className="state-message" role="status">Retrieving grounded context...</p>}
      {error && <p className="state-message state-error" role="alert">{error}</p>}

      {!loading && !error && currentResponse && (
        <div className="qa-response">
          <section className={`qa-answer qa-answer-${currentResponse.status}`} aria-label="Answer">
            <p className="eyebrow">
              {currentResponse.status === 'answered' ? 'Grounded answer' : 'Insufficient evidence'}
            </p>
            <p>{currentResponse.answer}</p>
          </section>

          {currentResponse.citations.length > 0 && (
            <section className="qa-citations" aria-labelledby="qa-citations-heading">
              <h3 id="qa-citations-heading">Citations</h3>
              {currentResponse.citations.map((citation, index) => (
                <article
                  className="qa-citation"
                  key={`${citation.document_id}:${citation.page_number}:${citation.chunk_index}`}
                >
                  <div className="search-result-title">
                    <strong>Citation {index + 1}: {documentNames.get(citation.document_id) ?? citation.document_id}</strong>
                    <code>{citation.document_id}</code>
                  </div>
                  <p>{citation.source_snippet}</p>
                  <div className="search-result-metadata">
                    <span>Page {citation.page_number}</span>
                    <span>Chunk {citation.chunk_index}</span>
                    <span>Cosine distance {String(citation.distance)}</span>
                  </div>
                </article>
              ))}
            </section>
          )}

          <details className="qa-retrieval">
            <summary>
              Retrieved context ({currentResponse.retrieval.result_count} results)
            </summary>
            <div className="qa-retrieval-metadata">
              <span>Limit {currentResponse.retrieval.retrieval_limit}</span>
              <span>{currentResponse.retrieval.embedding_model}</span>
            </div>
            {currentResponse.retrieval.results.map((result, index) => (
              <article
                className="qa-context-row"
                key={`${result.document_id}:${result.page_number}:${result.chunk_index}`}
              >
                <strong>Rank {index + 1}: {documentNames.get(result.document_id) ?? result.document_id}</strong>
                <p>{result.text}</p>
                <div className="search-result-metadata">
                  <span>Page {result.page_number}</span>
                  <span>Chunk {result.chunk_index}</span>
                  <span>Cosine distance {String(result.distance)}</span>
                </div>
              </article>
            ))}
          </details>
        </div>
      )}
    </section>
  )
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}
