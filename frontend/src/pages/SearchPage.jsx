import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import apiClient from '../api/client'

function SearchPage() {
  const [searchParams] = useSearchParams()
  const query = searchParams.get('q') || ''
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const loadResults = async () => {
      if (!query.trim()) {
        setResults([])
        setLoading(false)
        return
      }

      try {
        const response = await apiClient.get('/search/', { params: { q: query } })
        setResults(response.data?.results || [])
        setError('')
      } catch (requestError) {
        setError(requestError.response?.status === 401 ? 'Please sign in to search the system.' : 'Unable to complete the search.')
      } finally {
        setLoading(false)
      }
    }

    loadResults()
  }, [query])

  return (
    <div className="page-card">
      <div className="section-head">
        <h3>Search Results</h3>
        <span>{query ? `Matching “${query}”` : 'Enter a search term above'}</span>
      </div>
      {error ? <div className="form-message error">{error}</div> : null}
      {loading ? <div className="form-message">Searching...</div> : null}
      {!loading && !error && results.length === 0 ? <div className="form-message">No matching records found.</div> : null}
      {!loading && results.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Type</th><th>Record</th><th>Details</th><th>Open</th></tr></thead>
            <tbody>
              {results.map((result) => (
                <tr key={`${result.type}-${result.id}`}>
                  <td>{result.type}</td>
                  <td>{result.title}</td>
                  <td>{result.subtitle || '—'}</td>
                  <td><Link to={result.url}>View</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

export default SearchPage
