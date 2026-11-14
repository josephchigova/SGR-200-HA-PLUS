import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import { ColumnChart } from '../components/Charts'
import { errorMessage } from '../components/ui'

const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])

function ClusterPerformance({ seasonName = '' }) {
  const [data, setData] = useState(null)
  const [filters, setFilters] = useState({ province: '', district: '', ward: '', lead_member: '', cluster: '', verification_status: '' })
  const [places, setPlaces] = useState({ provinces: [], districts: [], wards: [] })
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    Promise.all([
      apiClient.get('/provinces/?official=1&page_size=50').catch(() => ({ data: [] })),
      apiClient.get('/districts/?page_size=200').catch(() => ({ data: [] })),
      apiClient.get('/wards/?page_size=200').catch(() => ({ data: [] })),
    ]).then(([provinces, districts, wards]) => {
      if (active) setPlaces({ provinces: listOf(provinces.data), districts: listOf(districts.data), wards: listOf(wards.data) })
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    const params = {}
    if (seasonName) params.season_name = seasonName
    Object.entries(filters).forEach(([key, value]) => { if (value) params[key] = value })
    apiClient.get('/farmers/cluster-performance/', { params }).then((response) => {
      if (!active) return
      setData(response.data)
      setError('')
    }).catch((requestError) => {
      if (active) setError(errorMessage(requestError, 'Cluster performance could not be loaded.'))
    })
    return () => { active = false }
  }, [filters, seasonName])

  const overview = data?.overview || {}
  const change = (name, value) => setFilters((current) => ({
    ...current,
    [name]: value,
    ...(name === 'province' ? { district: '', ward: '' } : {}),
    ...(name === 'district' ? { ward: '' } : {}),
  }))
  const districts = places.districts.filter((item) => !filters.province || String(item.province) === filters.province)
  const wards = places.wards.filter((item) => !filters.district || String(item.district) === filters.district)

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>Lead farmer performance</h3>
          <p className="card-sub">Each cluster is the lead farmer. Figures come from the register{seasonName ? ` for ${seasonName}` : ''}.</p>
        </div>
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      <div className="farmers-filters">
        <label className="form-field">Province
          <select aria-label="Province" value={filters.province} onChange={(event) => change('province', event.target.value)}>
            <option value="">All provinces</option>
            {places.provinces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="form-field">District
          <select aria-label="District" value={filters.district} onChange={(event) => change('district', event.target.value)}>
            <option value="">All districts</option>
            {districts.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="form-field">Ward
          <select aria-label="Ward" value={filters.ward} onChange={(event) => change('ward', event.target.value)}>
            <option value="">All wards</option>
            {wards.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="form-field">Registration
          <select aria-label="Registration status" value={filters.verification_status} onChange={(event) => change('verification_status', event.target.value)}>
            <option value="">All statuses</option>
            <option value="VERIFIED,APPROVED">Approved</option>
            <option value="SUBMITTED,UNDER_REVIEW,PENDING">Awaiting approval</option>
            <option value="DRAFT">Incomplete</option>
          </select>
        </label>
      </div>
      <section className="kpi-grid" aria-label="Cluster overview">
        <article className="stat-card"><span>Clusters</span><strong>{overview.clusters || 0}</strong></article>
        <article className="stat-card"><span>Lead farmers</span><strong>{overview.lead_farmers || 0}</strong></article>
        <article className="stat-card"><span>Farmers</span><strong>{overview.farmers || 0}</strong></article>
        <article className="stat-card"><span>Average cluster size</span><strong>{overview.average_cluster_size || 0}</strong></article>
        <article className="stat-card"><span>Largest cluster</span><strong>{overview.largest_cluster || 0}</strong></article>
        <article className="stat-card"><span>Smallest cluster</span><strong>{overview.smallest_cluster || 0}</strong></article>
        <article className="stat-card"><span>Awaiting approval</span><strong>{overview.awaiting_approval || 0}</strong></article>
        <article className="stat-card"><span>Approved</span><strong>{overview.approved || 0}</strong></article>
        <article className="stat-card"><span>Incomplete</span><strong>{overview.incomplete || 0}</strong></article>
      </section>
      <div className="table-wrap" style={{ marginTop: 16 }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Lead farmer</th><th>Province</th><th>District</th><th>Ward</th><th>Cluster</th>
              <th>Farmers</th><th>Approved</th><th>Pending</th><th>Subscription</th><th>Participation</th><th>Performance</th>
            </tr>
          </thead>
          <tbody>
            {(data?.clusters || []).map((row) => (
              <tr key={row.cluster_id || row.cluster}>
                <td>{row.lead_farmer || '—'}</td>
                <td>{row.province || '—'}</td>
                <td>{row.district || '—'}</td>
                <td>{row.ward || '—'}</td>
                <td>{row.cluster}</td>
                <td>{row.farmers}</td>
                <td>{row.approved}</td>
                <td>{row.pending}</td>
                <td>{row.subscription_compliance}%</td>
                <td>{row.agricultural_participation}%</td>
                <td>{row.performance}%</td>
              </tr>
            ))}
            {!data?.clusters?.length ? <tr><td colSpan={11}>No clusters match these filters.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <div className="analytics-grid" style={{ marginTop: 16 }}>
        <ColumnChart title="Farmers by province" rows={data?.by_province || []} labelKey="label" valueKey="farmers" unit="farmers" note="Farmers in each province, excluding the lead farmer’s own record." />
        <ColumnChart title="Cluster size" rows={(data?.clusters || []).map((row) => ({ label: row.cluster, farmers: row.farmers }))} labelKey="label" valueKey="farmers" unit="farmers" note="Farmers managed by each lead farmer." />
      </div>
    </section>
  )
}

export default ClusterPerformance
