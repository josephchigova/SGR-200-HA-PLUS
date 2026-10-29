import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import TabSearch from '../components/TabSearch'

function ReportsPage() {
  const [reports, setReports] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const filteredReports = reports.filter((report) => `${report.name} ${report.code} ${report.description}`.toLowerCase().includes(search.toLowerCase()))

  useEffect(() => {
    const loadReports = async () => {
      const token = localStorage.getItem('sgr_access_token')
      if (!token) {
        setLoading(false)
        setError('Please sign in to view reports.')
        return
      }

      try {
        const response = await apiClient.get('/report-templates/', {
          headers: { Authorization: `Bearer ${token}` },
        })

        setReports(response.data?.results || response.data || [])
        setError('')
      } catch {
        setError('Unable to load reporting templates.')
      } finally {
        setLoading(false)
      }
    }

    loadReports()
  }, [])

  return (
    <div className="page-card">
      <div className="section-head">
        <h3>Reports &amp; Templates</h3>
        <TabSearch value={search} onChange={setSearch} placeholder="Filter reports..." />
      </div>

      {error ? <div className="form-message error">{error}</div> : null}
      {loading ? <div className="form-message">Loading reports...</div> : null}

      {!loading && reports.length === 0 ? (
        <div className="form-message">No report templates are available yet.</div>
      ) : null}

      {!loading && filteredReports.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Code</th>
                <th>Status</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {filteredReports.map((report) => (
                <tr key={report.id}>
                  <td>{report.name}</td>
                  <td>{report.code}</td>
                  <td>
                    <span className={`status-pill ${report.is_active ? 'active' : 'review'}`}>
                      {report.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>{report.description || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

export default ReportsPage
