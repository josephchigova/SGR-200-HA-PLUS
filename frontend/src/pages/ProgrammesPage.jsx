import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import TabSearch from '../components/TabSearch'

function ProgrammesPage() {
  const [programmes, setProgrammes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const filteredProgrammes = programmes.filter((programme) => `${programme.name} ${programme.code} ${programme.description}`.toLowerCase().includes(search.toLowerCase()))

  useEffect(() => {
    const loadProgrammes = async () => {
      const token = localStorage.getItem('sgr_access_token')
      if (!token) {
        setLoading(false)
        setError('Please sign in to view the programme portfolio.')
        return
      }

      try {
        const response = await apiClient.get('/programmes/', {
          headers: { Authorization: `Bearer ${token}` },
        })

        setProgrammes(response.data?.results || response.data || [])
        setError('')
      } catch {
        setError('Unable to load programme data.')
      } finally {
        setLoading(false)
      }
    }

    loadProgrammes()
  }, [])

  return (
    <div className="page-card">
      <div className="section-head">
        <h3>Programme Portfolio</h3>
        <TabSearch value={search} onChange={setSearch} placeholder="Filter programmes..." />
      </div>

      {error ? <div className="form-message error">{error}</div> : null}
      {loading ? <div className="form-message">Loading programmes...</div> : null}

      {!loading && programmes.length === 0 ? (
        <div className="form-message">No active programmes found.</div>
      ) : null}

      {!loading && filteredProgrammes.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Status</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {filteredProgrammes.map((programme) => (
                <tr key={programme.id}>
                  <td>{programme.code}</td>
                  <td>{programme.name}</td>
                  <td>
                    <span className={`status-pill ${programme.is_active ? 'active' : 'review'}`}>
                      {programme.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>{programme.description || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

export default ProgrammesPage
