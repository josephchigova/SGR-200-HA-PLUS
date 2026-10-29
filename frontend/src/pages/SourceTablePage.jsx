import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import TabSearch from '../components/TabSearch'

function SourceTablePage({ title, endpoint, columns, placeholder }) {
  const [rows, setRows] = useState([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const loadRows = async () => {
      try {
        const response = await apiClient.get(endpoint)
        setRows(response.data?.results || response.data || [])
      } catch (requestError) {
        setError(requestError.response?.status === 401 ? 'Please sign in to view this tab.' : 'Unable to load this tab.')
      } finally {
        setLoading(false)
      }
    }
    loadRows()
  }, [endpoint])

  const filteredRows = rows.filter((row) => Object.values(row).join(' ').toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="page-card">
      <div className="section-head">
        <h3>{title}</h3>
        <TabSearch value={search} onChange={setSearch} placeholder={placeholder || `Filter ${title.toLowerCase()}...`} />
      </div>
      {error ? <div className="form-message error">{error}</div> : null}
      {loading ? <div className="form-message">Loading {title.toLowerCase()}...</div> : null}
      {!loading && !error && filteredRows.length === 0 ? <div className="form-message">No matching records found.</div> : null}
      {!loading && filteredRows.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
            <tbody>
              {filteredRows.map((row) => (
                <tr key={row.id}>
                  {columns.map((column) => <td key={column.key}>{row[column.key] ?? '—'}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

export default SourceTablePage
