import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import TabSearch from '../components/TabSearch'

function InputIssuesPage() {
  const [issues, setIssues] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const filteredIssues = issues.filter((issue) => `${issue.input_name} ${issue.batch_number} ${issue.farmer_name} ${issue.issue_status}`.toLowerCase().includes(search.toLowerCase()))

  useEffect(() => {
    const loadIssues = async () => {
      const token = localStorage.getItem('sgr_access_token')
      if (!token) {
        setLoading(false)
        setError('Please sign in to view input issues.')
        return
      }

      try {
        const response = await apiClient.get('/input-issues/', {
          headers: { Authorization: `Bearer ${token}` },
        })

        setIssues(response.data?.results || response.data || [])
        setError('')
      } catch {
        setError('Unable to load input issues.')
      } finally {
        setLoading(false)
      }
    }

    loadIssues()
  }, [])

  return (
    <div className="page-card">
      <div className="section-head">
        <h3>Input Issuance</h3>
        <TabSearch value={search} onChange={setSearch} placeholder="Filter inputs..." />
      </div>

      {error ? <div className="form-message error">{error}</div> : null}
      {loading ? <div className="form-message">Loading input records...</div> : null}

      {!loading && issues.length === 0 ? (
        <div className="form-message">No input issues have been recorded yet.</div>
      ) : null}

      {!loading && filteredIssues.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Farmer</th>
                <th>Input</th>
                <th>Batch</th>
                <th>Quantity</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredIssues.map((issue) => (
                <tr key={issue.id}>
                  <td>{issue.farmer_name || '—'}</td>
                  <td>{issue.input_name || '—'}</td>
                  <td>{issue.batch_number || '—'}</td>
                  <td>{issue.quantity} {issue.unit || ''}</td>
                  <td>
                    <span className={`status-pill ${issue.issue_status === 'ISSUED' || issue.issue_status === 'COLLECTED' ? 'active' : 'review'}`}>
                      {issue.issue_status || '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

export default InputIssuesPage
