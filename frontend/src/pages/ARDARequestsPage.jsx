import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import TabSearch from '../components/TabSearch'

function ARDARequestsPage() {
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const filteredRequests = requests.filter((request) => `${request.farmer_name} ${request.request_type} ${request.status} ${request.reason}`.toLowerCase().includes(search.toLowerCase()))

  useEffect(() => {
    const loadRequests = async () => {
      const token = localStorage.getItem('sgr_access_token')
      if (!token) {
        setLoading(false)
        setError('Please sign in to review ARDA requests.')
        return
      }

      try {
        const response = await apiClient.get('/arda-requests/', {
          headers: { Authorization: `Bearer ${token}` },
        })

        setRequests(response.data?.results || response.data || [])
        setError('')
      } catch {
        setError('Unable to load ARDA requests.')
      } finally {
        setLoading(false)
      }
    }

    loadRequests()
  }, [])

  return (
    <div className="page-card">
      <div className="section-head">
        <h3>ARDA Requests</h3>
        <TabSearch value={search} onChange={setSearch} placeholder="Filter requests..." />
      </div>

      {error ? <div className="form-message error">{error}</div> : null}
      {loading ? <div className="form-message">Loading ARDA requests...</div> : null}

      {!loading && requests.length === 0 ? (
        <div className="form-message">No ARDA requests have been raised yet.</div>
      ) : null}

      {!loading && filteredRequests.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Farmer</th>
                <th>Request</th>
                <th>Quantity</th>
                <th>Status</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {filteredRequests.map((request) => (
                <tr key={request.id}>
                  <td>{request.farmer_name || '—'}</td>
                  <td>{request.request_type || '—'}</td>
                  <td>{request.quantity || 0} {request.unit || ''}</td>
                  <td>
                    <span className={`status-pill ${request.status === 'APPROVED' ? 'active' : 'review'}`}>
                      {request.status || '—'}
                    </span>
                  </td>
                  <td>{request.reason || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

export default ARDARequestsPage
