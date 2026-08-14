import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  documentApi,
  type DocumentRecord,
  type SemanticSearchResponse,
} from '../api/client'

type SearchScope = 'all' | 'selected'

interface SemanticSearchProps {
  documents: DocumentRecord[]
  selectedDocument: DocumentRecord | null
}

interface SearchResponseState {
  scopeKey: string
  data: SemanticSearchResponse
}

export function SemanticSearch({ documents, selectedDocument }: SemanticSearchProps) {
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(10)
  const [scope, setScope] = useState<SearchScope>('all')
  const [response, setResponse] = useState<SearchResponseState | null>(null)
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
      resetResults()
      if (!selectedId) setScope('all')
    }
    previousSelectedId.current = selectedId
  }, [scope, selectedDocument?.id])

  function resetResults() {
    // Versioning keeps late searches from replacing results after a newer query or scope change.
    requestVersion.current += 1
    setResponse(null)
    setLoading(false)
    setError(null)
  }

  function changeScope(nextScope: SearchScope) {
    if (nextScope === scope || (nextScope === 'selected' && !selectedDocument)) return
    setScope(nextScope)
    resetResults()
  }

  async function search(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedQuery = query.trim()
    if (!trimmedQuery) return

    const version = ++requestVersion.current
    const documentId = scope === 'selected' ? selectedDocument?.id : undefined
    setLoading(true)
    setResponse(null)
    setError(null)
    try {
      const result = await documentApi.searchDocuments({
        query: trimmedQuery,
        limit,
        documentId,
      })
      if (requestVersion.current !== version) return
      setResponse({ scopeKey, data: result })
    } catch (searchError) {
      if (requestVersion.current !== version) return
      setResponse(null)
      setError(errorMessage(searchError, 'Could not search documents.'))
    } finally {
      if (requestVersion.current === version) setLoading(false)
    }
  }

  return (
    <section className="semantic-search" aria-labelledby="semantic-search-heading">
      <div className="search-heading">
        <div>
          <p className="eyebrow">Retrieval</p>
          <h2 id="semantic-search-heading">Semantic search</h2>
        </div>
        {currentResponse && (
          <span className="search-result-count">{currentResponse.results.length} results</span>
        )}
      </div>

      <form className="search-form" onSubmit={(event) => void search(event)}>
        <label className="search-query-field" htmlFor="semantic-search-query">
          <span>Query</span>
          <input
            id="semantic-search-query"
            value={query}
            maxLength={500}
            placeholder="Search document text"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>

        <fieldset className="search-scope">
          <legend>Scope</legend>
          <div className="segmented-control">
            <label data-selected={scope === 'all'}>
              <input
                type="radio"
                name="search-scope"
                value="all"
                checked={scope === 'all'}
                onChange={() => changeScope('all')}
              />
              All documents
            </label>
            <label data-selected={scope === 'selected'} data-disabled={!selectedDocument}>
              <input
                type="radio"
                name="search-scope"
                value="selected"
                checked={scope === 'selected'}
                disabled={!selectedDocument}
                onChange={() => changeScope('selected')}
              />
              Selected document
            </label>
          </div>
        </fieldset>

        <label className="search-limit" htmlFor="semantic-search-limit">
          <span>Results</span>
          <select
            id="semantic-search-limit"
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
          >
            {[5, 10, 20, 50].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>

        <button className="button button-primary search-submit" type="submit" disabled={!query.trim()}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {scope === 'selected' && selectedDocument && (
        <p className="search-scope-context">Searching {selectedDocument.filename}</p>
      )}
      {loading && <p className="state-message" role="status">Searching document chunks...</p>}
      {error && <p className="state-message state-error" role="alert">{error}</p>}
      {!loading && !error && currentResponse?.results.length === 0 && (
        <p className="state-message">No matching document chunks found.</p>
      )}
      {!loading && !error && currentResponse && currentResponse.results.length > 0 && (
        <div className="search-results" aria-label="Semantic search results">
          {currentResponse.results.map((result, index) => (
            <article
              className="search-result-row"
              key={`${result.document_id}:${result.page_number}:${result.chunk_index}`}
            >
              <div className="search-result-rank" aria-label={`Rank ${index + 1}`}>{index + 1}</div>
              <div className="search-result-body">
                <div className="search-result-title">
                  <strong>{documentNames.get(result.document_id) ?? result.document_id}</strong>
                  <code>{result.document_id}</code>
                </div>
                <p>{result.text}</p>
                <div className="search-result-metadata">
                  <span>Page {result.page_number}</span>
                  <span>Chunk {result.chunk_index}</span>
                  <span>{result.embedding_model}</span>
                  <span>Cosine distance {String(result.distance)}</span>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}
