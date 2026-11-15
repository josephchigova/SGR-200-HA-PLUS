import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import { ColumnChart } from '../components/Charts'
import { StatCard, errorMessage } from '../components/ui'

const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])
const number = (value) => Number(value || 0).toLocaleString('en-US')
const hectares = (value) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 1 })
const tonnes = (value) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })

function ClusterPerformance({ seasonName = '' }) {
  const season = seasonName
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
      <section className="kpi-grid lead-metrics" aria-label="Lead farmer performance totals">
        <StatCard label="Total active lead farmers" value={number(overview.lead_farmers)} hint={`${number(overview.clusters)} cluster${overview.clusters === 1 ? '' : 's'}, one per lead farmer`} icon="userCheck" />
        <StatCard label="Total farmers registered across all lead farmers" value={number(overview.farmers)} hint="Lead farmers' own records not counted" icon="users" />
        <StatCard label="Total approved farmers" value={number(overview.approved)} tone="good" icon="shield" />
        <StatCard label="Total pending farmer registrations" value={number(overview.awaiting_approval)} hint="Waiting for administrator approval" icon="history" />
        <StatCard label="Total incomplete farmer registrations" value={number(overview.incomplete)} hint="Drafts not yet submitted" icon="clipboard" />
        <StatCard label="Largest cluster (farmers)" value={number(overview.largest_cluster)} hint="Farmers under the busiest lead farmer" icon="layers" />
        <StatCard label="Smallest cluster (farmers)" value={number(overview.smallest_cluster)} hint="Farmers under the quietest lead farmer" icon="layers" />
        <StatCard label="Total registered crop hectares" value={`${hectares(overview.crop_hectares)} ha`} hint={`Crops allocated for ${season || 'the agri year'}`} icon="mapPin" />
        <StatCard label="Total irrigated hectares" value={`${hectares(overview.irrigated_hectares)} ha`} hint="Irrigated land on active farms" icon="layers" />
        <StatCard label="Total production (MT)" value={`${tonnes(overview.production_tonnes)} MT`} hint={`${tonnes(overview.estimated_production_tonnes)} MT estimated`} icon="wheat" />
        <StatCard label="Average yield (MT per ha)" value={`${tonnes(overview.average_yield_tonnes_per_hectare)} MT/ha`} hint="Harvested tonnes over harvested hectares" icon="chart" />
      </section>
      <div className="table-wrap" style={{ marginTop: 16 }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Lead farmer</th><th>Province</th><th>District</th><th>Ward</th><th>Cluster</th>
              <th>Farmers registered</th><th>Approved farmers</th><th>Pending registrations</th>
              <th title="Subscription money paid as a percentage of the subscription money due from approved farmers">Subscription paid (% of amount due)</th>
              <th title="Approved farmers with planting or production recorded this agri year">Farmers planting (% of approved)</th>
              <th title="Average of subscription paid %, farmers planting % and farmers approved %">Overall performance score (%)</th>
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
