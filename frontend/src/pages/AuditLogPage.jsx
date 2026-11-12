import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import Icon from '../components/Icon'
import { EmptyState, PageHead, Pill, Skeleton, errorMessage } from '../components/ui'

const TONES = { CREATE: 'good', UPDATE: 'info', DELETE: 'bad', LOGIN: '', LOGIN_FAILED: 'bad', PASSWORD: 'warn', EXPORT: 'info' }

function AuditLogPage() {
  const [filters, setFilters] = useState({ search: '', action: '', module: '', start_date: '', end_date: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ results: [], count: 0 })
  const [meta, setMeta] = useState({ modules: [], actions: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState(false)

  const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value))

  useEffect(() => {
    apiClient.get('/audit-logs/modules/').then((response) => setMeta(response.data)).catch(() => {})
  }, [])

  const key = JSON.stringify([params, page])
  useEffect(() => {
    let active = true
    const timer = window.setTimeout(async () => {
      setLoading(true)
      try {
        const response = await apiClient.get('/audit-logs/', { params: { ...params, page, page_size: 50 } })
        if (!active) return
        setData(response.data)
        setError('')
      } catch (requestError) {
        if (active) setError(errorMessage(requestError, 'The audit log could not be loaded.'))
      } finally {
        if (active) setLoading(false)
      }
    }, 250)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const change = (name, value) => {
    setPage(1)
    setFilters((current) => ({ ...current, [name]: value }))
  }

  const download = async () => {
    setDownloading(true)
    try {
      const response = await apiClient.get('/audit-logs/export/', { params, responseType: 'blob' })
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = 'SGR_Audit_Log.csv'
      link.click()
      URL.revokeObjectURL(url)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The audit log could not be exported.'))
    } finally {
      setDownloading(false)
    }
  }

  const rows = data.results || []
  const pages = Math.max(Math.ceil((data.count || 0) / 50), 1)

  return (
    <div className="page-card">
      <PageHead title="Audit log" subtitle="Every change, sign-in and export, with who did it and when. Entries cannot be edited or removed.">
        <button type="button" className="ghost-btn" disabled={downloading} onClick={download}><Icon name="download" />{downloading ? 'Preparing…' : 'Export CSV'}</button>
      </PageHead>

      <div className="card">
        <div className="form-grid">
          <label>Search<input type="search" placeholder="User, summary or path" value={filters.search} onChange={(event) => change('search', event.target.value)} /></label>
          <label>Action
            <select value={filters.action} onChange={(event) => change('action', event.target.value)}>
              <option value="">All actions</option>
              {meta.actions.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
            </select>
          </label>
          <label>Module
            <select value={filters.module} onChange={(event) => change('module', event.target.value)}>
              <option value="">All modules</option>
              {meta.modules.map((module) => <option key={module} value={module}>{module}</option>)}
            </select>
          </label>
          <label>From<input type="date" value={filters.start_date} onChange={(event) => change('start_date', event.target.value)} /></label>
          <label>To<input type="date" value={filters.end_date} onChange={(event) => change('end_date', event.target.value)} /></label>
        </div>
      </div>

      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      <div className="table-wrap">
        {loading && !rows.length ? <div style={{ padding: 16, display: 'grid', gap: 8 }}><Skeleton kind="row" count={8} /></div> : null}
        {!loading && !rows.length ? <EmptyState icon="history" title="No activity matches">Change the filters to see more entries.</EmptyState> : null}
        {rows.length ? (
          <table className="data-table">
            <thead><tr><th>When</th><th>User</th><th>Action</th><th>Module</th><th>Summary</th><th>Fields sent</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td style={{ whiteSpace: 'nowrap' }}>{new Date(row.created_at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}</td>
                  <td>{row.user_email || 'Unknown'}<small>{row.user_role}</small></td>
                  <td><Pill tone={TONES[row.action] || ''}>{row.action_label}</Pill></td>
                  <td>{row.module || '—'}</td>
                  <td>{row.summary}<small>{row.ip_address || ''}</small></td>
                  <td>{(row.changed_fields || []).join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {rows.length ? (
          <div className="table-foot">
            <span>{data.count} entr{data.count === 1 ? 'y' : 'ies'}</span>
            <span className="table-actions">
              <button type="button" className="ghost-btn small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span style={{ alignSelf: 'center' }}>Page {page} of {pages}</span>
              <button type="button" className="ghost-btn small" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
            </span>
          </div>
        ) : null}
      </div>
    </div>
  )
}

export default AuditLogPage
