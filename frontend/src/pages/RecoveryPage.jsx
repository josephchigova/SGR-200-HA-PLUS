import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import TabSearch from '../components/TabSearch'

function RecoveryPage() {
  const [records, setRecords] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const filteredRecords = records.filter((record) => `${record.farmer_name} ${record.farm_name} ${record.crop} ${record.status}`.toLowerCase().includes(search.toLowerCase()))

  useEffect(() => {
    const loadRecords = async () => {
      const token = localStorage.getItem('sgr_access_token')
      if (!token) {
        setLoading(false)
        setError('Please sign in to review recovery records.')
        return
      }

      try {
        const response = await apiClient.get('/recovery-records/', {
          headers: { Authorization: `Bearer ${token}` },
        })

        setRecords(response.data?.results || response.data || [])
        setError('')
      } catch {
        setError('Unable to load recovery records.')
      } finally {
        setLoading(false)
      }
    }

    loadRecords()
  }, [])

  return (
    <div className="page-card">
      <div className="section-head">
        <h3>Recovery &amp; Follow-up</h3>
        <TabSearch value={search} onChange={setSearch} placeholder="Filter recovery..." />
      </div>

      {error ? <div className="form-message error">{error}</div> : null}
      {loading ? <div className="form-message">Loading recovery records...</div> : null}

      {!loading && records.length === 0 ? (
        <div className="form-message">No recovery records have been created yet.</div>
      ) : null}

      {!loading && filteredRecords.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Farmer</th>
                <th>Debt</th>
                <th>Currency</th>
                <th>Status</th>
                <th>Due Date</th>
              </tr>
            </thead>
            <tbody>
              {filteredRecords.map((record) => (
                <tr key={record.id}>
                  <td>{record.farmer_name || '—'}</td>
                  <td>{record.debt_amount || 0}</td>
                  <td>{record.currency || 'USD'}</td>
                  <td>
                    <span className={`status-pill ${record.status === 'PAID' ? 'active' : 'review'}`}>
                      {record.status || '—'}
                    </span>
                  </td>
                  <td>{record.due_date || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

export default RecoveryPage
