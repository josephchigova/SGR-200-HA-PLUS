import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import { ColumnChart, DoughnutChart, GroupedBarChart, HorizontalBarChart } from '../components/Charts'
import Icon from '../components/Icon'
import ProductionRecords, { ProductionForm } from '../components/ProductionRecords'
import { EmptyState, PageHead, Skeleton, StatCard } from '../components/ui'
import { STATUSES, downloadCsv, hectares } from '../production'
import { Meter } from './ClusterDashboard'

const quantity = (value) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })
const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)']
const STATUS_COLORS = { PENDING: 'var(--chart-3)', PLANTED: 'var(--chart-1)', HARVESTED: 'var(--chart-2)', COMPLETED: 'var(--chart-4)' }
const TABS = [
  ['overview', 'Overview', 'chart'],
  ['records', 'Production records', 'clipboard'],
  ['crops', 'Crop performance', 'sprout'],
  ['leads', 'Lead farmer performance', 'users'],
  ['analysis', 'Analysis & reports', 'layers'],
]
const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])

// "↑ 6.4% vs 2025/2026", or nothing when last season has no records to compare with.
function change(current, previous, season) {
  const before = Number(previous)
  if (!season || !Number.isFinite(before) || before === 0) return ''
  const percent = ((Number(current) - before) / before) * 100
  const arrow = percent > 0 ? '↑' : percent < 0 ? '↓' : '→'
  return `${arrow} ${Math.abs(percent).toFixed(1)}% vs ${season}`
}

function ProductionPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { can } = useAuth()
  const permissions = { create: can('production', 'create'), edit: can('production', 'edit'), delete: can('production', 'delete') }
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = TABS.some(([key]) => key === searchParams.get('tab')) ? searchParams.get('tab') : 'overview'
  const setTab = (key) => setSearchParams(key === 'overview' ? {} : { tab: key }, { replace: true })

  const [season, setSeason] = useState(cropSeason || '')
  const [seasonSource, setSeasonSource] = useState(cropSeason)
  if (seasonSource !== cropSeason) {
    // The season chosen in the header applies until it is changed here.
    setSeasonSource(cropSeason)
    setSeason(cropSeason || '')
  }
  const [crop, setCrop] = useState('')
  const [province, setProvince] = useState('')
  const [district, setDistrict] = useState('')
  const [options, setOptions] = useState({ crops: [], provinces: [], districts: [] })
  const [overview, setOverview] = useState(null)
  const [error, setError] = useState('')
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [capturing, setCapturing] = useState(false)
  const [notice, setNotice] = useState('')

  const blocked = periodStatus === 'error' || (periodStatus === 'ready' && !selectedSeason)
  const filters = useMemo(() => {
    if (periodStatus !== 'ready' || !selectedSeason) return null
    const next = { season: String(selectedSeason.id), season_name: selectedSeason.name }
    if (season) next.crop_season = season
    if (crop) next.crop = crop
    if (province) next.province = province
    if (district) next.district = district
    return next
  }, [periodStatus, selectedSeason, season, crop, province, district])
  const requestKey = `${JSON.stringify(filters)}:${token}`
  const loading = !blocked && (periodStatus === 'loading' || loadedKey !== requestKey)

  useEffect(() => {
    let active = true
    Promise.all([
      apiClient.get('/crops/', { params: { page_size: 200 } }).catch(() => ({ data: [] })),
      apiClient.get('/provinces/', { params: { official: 1, page_size: 50 } }).catch(() => ({ data: [] })),
    ]).then(([cropResponse, provinceResponse]) => {
      if (!active) return
      setOptions((current) => ({
        ...current,
        crops: listOf(cropResponse.data).sort((a, b) => a.name.localeCompare(b.name)),
        provinces: listOf(provinceResponse.data).sort((a, b) => a.name.localeCompare(b.name)),
      }))
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!province) return undefined
    let active = true
    apiClient.get('/districts/', { params: { province, page_size: 200 } })
      .then((response) => { if (active) setOptions((current) => ({ ...current, districts: listOf(response.data).sort((a, b) => a.name.localeCompare(b.name)) })) })
      .catch(() => { if (active) setOptions((current) => ({ ...current, districts: [] })) })
    return () => { active = false }
  }, [province])

  useEffect(() => {
    if (!filters) return undefined
    let active = true
    const params = new URLSearchParams(filters)
    apiClient.get(`/farmer-productions/overview/?${params.toString()}`)
      .then((response) => {
        if (!active) return
        setOverview(response.data || {})
        setError('')
      })
      .catch(() => {
        if (!active) return
        setOverview(null)
        setError('Production for this period could not be loaded.')
      })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [filters, requestKey])

  const refresh = useCallback(() => setToken((value) => value + 1), [])
  const crops = overview?.by_crop || []
  const leads = overview?.by_lead || []
  const statuses = overview?.by_status || []
  const previous = overview?.previous
  const periodLabel = selectedSeason?.name || ''
  const visibleCrops = season ? options.crops.filter((item) => !item.category || item.category === season) : options.crops

  const exportCrops = () => downloadCsv(`crop-performance-${periodLabel.replace(/\W+/g, '-')}.csv`,
    ['Crop', 'Farmers', 'Registered ha', 'Planted ha', 'Irrigated ha', 'Planting progress %', 'Estimated t', 'Actual t', 'Yield t/ha'],
    crops.map((row) => [row.crop, row.farmers, row.hectares, row.planted_hectares, row.irrigated_hectares, row.planting_progress, row.estimated_production, row.actual_production, row.yield_per_hectare]))
  const exportLeads = () => downloadCsv(`lead-farmer-production-${periodLabel.replace(/\W+/g, '-')}.csv`,
    ['Lead farmer', 'District', 'Farmers', 'Registered ha', 'Planted ha', 'Irrigated ha', 'Planting progress %', 'Estimated t', 'Actual t', 'Yield t/ha'],
    leads.map((row) => [row.lead_farmer, row.district, row.farmers, row.registered_hectares, row.planted_hectares, row.irrigated_hectares, row.planting_progress, row.estimated_production, row.actual_production, row.yield_per_hectare]))

  return (
    <div className="page-card production-page">
      <PageHead title="Production" subtitle="Crop production tracking, performance and yields for the selected agri year.">
        {permissions.create ? <button type="button" className="primary-btn" onClick={() => { setNotice(''); setCapturing(true) }}><Icon name="plus" />Capture production</button> : null}
      </PageHead>

      <div className="tabs production-tabs" role="tablist" aria-label="Production sections">
        {TABS.map(([key, label, icon]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}><Icon name={icon} />{label}</button>
        ))}
      </div>

      <div className="production-filters" role="group" aria-label="Production filters">
        <label className="form-field">
          <span><Icon name="calendar" />Agri year</span>
          <input value={selectedSeason?.name || 'Choose in the header'} readOnly title="Change the agri year in the header" />
        </label>
        <label className="form-field">
          <span><Icon name="sprout" />Season</span>
          <select value={season} onChange={(event) => { setSeason(event.target.value); setCrop('') }}>
            <option value="">All seasons</option>
            <option value="SUMMER">Summer</option>
            <option value="WINTER">Winter</option>
          </select>
        </label>
        <label className="form-field">
          <span><Icon name="wheat" />Crop</span>
          <select value={crop} onChange={(event) => setCrop(event.target.value)}>
            <option value="">All crops</option>
            {visibleCrops.map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}
          </select>
        </label>
        <label className="form-field">
          <span><Icon name="mapPin" />Province</span>
          <select value={province} onChange={(event) => { setProvince(event.target.value); setDistrict(''); setOptions((current) => ({ ...current, districts: [] })) }}>
            <option value="">All provinces</option>
            {options.provinces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="form-field">
          <span><Icon name="map" />District</span>
          <select value={district} onChange={(event) => setDistrict(event.target.value)} disabled={!province}>
            <option value="">{province ? 'All districts' : 'Choose a province first'}</option>
            {options.districts.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <button type="button" className="icon-btn production-refresh" title="Refresh" aria-label="Refresh production" onClick={refresh}><Icon name="refresh" /></button>
      </div>

      {blocked ? <div className="form-message">Choose an agricultural year to see production.</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {loading && !overview ? <Skeleton kind="block" /> : null}

      {!blocked && overview ? (
        <>
          {tab !== 'records' ? (
            <section className="stats-grid production-stats" aria-label="Production totals">
              <StatCard label="Registered hectares" value={`${hectares(overview.registered_hectares)} ha`} hint={change(overview.registered_hectares, previous?.registered_hectares, previous?.season) || `${overview.records || 0} crop records in view`} icon="mapPin" />
              <StatCard label="Irrigated hectares" value={`${hectares(overview.irrigated_hectares)} ha`} hint={change(overview.irrigated_hectares, previous?.irrigated_hectares, previous?.season) || `${hectares(overview.planted_hectares)} ha planted`} icon="layers" tone="info" />
              <StatCard label="Farmers planted" value={quantity(overview.farmers_planted)} hint={`Across ${overview.crops || 0} crop${overview.crops === 1 ? '' : 's'}`} icon="users" tone="warn" />
              <StatCard label="Crops in view" value={quantity(overview.crops)} hint="In the selected filters" icon="sprout" />
              <StatCard label="Total production (est.)" value={`${quantity(overview.estimated_production)} t`} hint={change(overview.estimated_production, previous?.estimated_production, previous?.season) || `${quantity(overview.actual_production)} t harvested`} icon="wheat" tone="good" />
            </section>
          ) : null}

          {tab === 'overview' ? (
            crops.length ? (
              <section className="production-overview-grid" aria-label="Production charts">
                <ColumnChart title="Registered hectares by crop" rows={crops.map((row) => ({ label: row.crop, hectares: Number(row.hectares) }))} labelKey="label" valueKey="hectares" unit="ha" note="Contracted hectares in the selected filters." />
                <DoughnutChart
                  title="Hectare distribution"
                  unit="ha"
                  note={`${hectares(overview.registered_hectares)} ha registered.`}
                  slices={crops.map((row, index) => ({ label: row.crop, value: Number(row.hectares), color: COLORS[index % COLORS.length] }))}
                />
                <LeadSummary leads={leads.slice(0, 6)} more={leads.length > 6 ? () => setTab('leads') : null} />
              </section>
            ) : <EmptyState icon="tractor" title="No production recorded for these filters">Capture production, or change the filters. Totals update from the records.</EmptyState>
          ) : null}

          {tab === 'crops' ? (
            <>
              <section className="card">
                <div className="card-head"><h3>Crop performance</h3><button type="button" className="ghost-btn small" disabled={!crops.length} onClick={exportCrops}><Icon name="download" />Export</button></div>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Crop</th><th className="num">Farmers</th><th className="num">Registered (ha)</th><th className="num">Planted (ha)</th><th className="num">Irrigated (ha)</th><th>Planting progress</th><th className="num">Estimated (t)</th><th className="num">Actual (t)</th><th className="num">Yield (t/ha)</th></tr></thead>
                    <tbody>
                      {crops.map((row) => (
                        <tr key={row.crop}>
                          <td><strong>{row.crop}</strong></td>
                          <td className="num">{row.farmers}</td>
                          <td className="num">{hectares(row.hectares)}</td>
                          <td className="num">{hectares(row.planted_hectares)}</td>
                          <td className="num">{hectares(row.irrigated_hectares)}</td>
                          <td><Meter value={row.planting_progress} label={`${row.crop} planted`} /></td>
                          <td className="num">{quantity(row.estimated_production)}</td>
                          <td className="num">{quantity(row.actual_production)}</td>
                          <td className="num">{quantity(row.yield_per_hectare)}</td>
                        </tr>
                      ))}
                      {!crops.length ? <tr><td colSpan="9">No crops in these filters.</td></tr> : null}
                    </tbody>
                  </table>
                </div>
              </section>
              {crops.length ? (
                <section className="analytics-grid">
                  <HorizontalBarChart title="Yield by crop" rows={crops.map((row) => ({ label: row.crop, value: Number(row.yield_per_hectare) }))} labelKey="label" valueKey="value" unit="t/ha" note="Actual production per planted hectare." />
                  <GroupedBarChart title="Estimated production by crop" unit="t" note="Tonnes expected from the crops in view." series={crops.map((row, index) => ({ label: row.crop, value: Number(row.estimated_production), color: COLORS[index % COLORS.length] }))} />
                </section>
              ) : null}
            </>
          ) : null}

          {tab === 'leads' ? (
            <section className="card">
              <div className="card-head"><h3>Lead farmer performance</h3><button type="button" className="ghost-btn small" disabled={!leads.length} onClick={exportLeads}><Icon name="download" />Export</button></div>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Lead farmer (cluster)</th><th>District</th><th className="num">Farmers</th><th className="num">Registered (ha)</th><th className="num">Planted (ha)</th><th className="num">Irrigated (ha)</th><th>Planting progress</th><th className="num">Estimated (t)</th><th className="num">Actual (t)</th><th className="num">Yield (t/ha)</th></tr></thead>
                  <tbody>
                    {leads.map((row) => (
                      <tr key={row.lead_farmer}>
                        <td><strong>{row.lead_farmer}</strong></td>
                        <td>{row.district || '—'}</td>
                        <td className="num">{row.farmers}</td>
                        <td className="num">{hectares(row.registered_hectares)}</td>
                        <td className="num">{hectares(row.planted_hectares)}</td>
                        <td className="num">{hectares(row.irrigated_hectares)}</td>
                        <td><Meter value={row.planting_progress} label={`${row.lead_farmer} planted`} /></td>
                        <td className="num">{quantity(row.estimated_production)}</td>
                        <td className="num">{quantity(row.actual_production)}</td>
                        <td className="num">{quantity(row.yield_per_hectare)}</td>
                      </tr>
                    ))}
                    {!leads.length ? <tr><td colSpan="10">No lead farmers in these filters.</td></tr> : null}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          {tab === 'analysis' ? (
            <>
              <section className="analytics-grid">
                <DoughnutChart
                  title="Records by production status"
                  unit="records"
                  note={`${overview.records || 0} crop records in view.`}
                  slices={statuses.map((row) => ({ label: STATUSES.find(([code]) => code === row.status)?.[1] || row.label, value: row.records, color: STATUS_COLORS[row.status] || 'var(--chart-5)' }))}
                />
                <GroupedBarChart
                  title="Planting progress"
                  unit="ha"
                  note="Registered, planted and irrigated land in the selected filters."
                  series={[
                    { label: 'Registered', value: Number(overview.registered_hectares), color: 'var(--chart-1)' },
                    { label: 'Planted', value: Number(overview.planted_hectares), color: 'var(--chart-2)' },
                    { label: 'Irrigated', value: Number(overview.irrigated_hectares), color: 'var(--chart-3)' },
                  ]}
                />
                <GroupedBarChart
                  title="Estimated and harvested production"
                  unit="t"
                  note={previous ? `Last season (${previous.season}): ${quantity(previous.estimated_production)} t estimated.` : 'No earlier season to compare with.'}
                  series={[
                    { label: 'Estimated', value: Number(overview.estimated_production), color: 'var(--chart-1)' },
                    { label: 'Harvested', value: Number(overview.actual_production), color: 'var(--chart-4)' },
                    ...(previous ? [{ label: `Est. ${previous.season}`, value: Number(previous.estimated_production), color: 'var(--chart-5)' }] : []),
                  ]}
                />
              </section>
              <section className="card">
                <div className="card-head"><h3>Reports</h3></div>
                <p className="card-sub">Download the figures behind this page for the selected filters as CSV files.</p>
                <div className="form-actions" style={{ justifyContent: 'flex-start' }}>
                  <button type="button" className="ghost-btn" disabled={!crops.length} onClick={exportCrops}><Icon name="download" />Crop performance</button>
                  <button type="button" className="ghost-btn" disabled={!leads.length} onClick={exportLeads}><Icon name="download" />Lead farmer performance</button>
                  <button type="button" className="ghost-btn" onClick={() => setTab('records')}><Icon name="clipboard" />All production records</button>
                </div>
              </section>
            </>
          ) : null}
        </>
      ) : null}

      {filters && (tab === 'overview' || tab === 'records') ? (
        <ProductionRecords
          filters={filters}
          compact={tab === 'overview'}
          reloadToken={token}
          onChanged={refresh}
          onCapture={() => setCapturing(true)}
          permissions={permissions}
          periodLabel={periodLabel}
        />
      ) : null}

      {capturing ? (
        <ProductionForm
          defaults={selectedSeason ? { season: String(selectedSeason.id) } : {}}
          onClose={() => setCapturing(false)}
          onSaved={(saved) => {
            setCapturing(false)
            setNotice(`Production captured: ${saved.farmer_name} · ${saved.crop}.`)
            refresh()
          }}
        />
      ) : null}
    </div>
  )
}

function LeadSummary({ leads, more }) {
  return (
    <section className="card production-lead-summary">
      <div className="card-head"><h3><Icon name="users" />Cluster / lead farmer production summary</h3>{more ? <button type="button" className="ghost-btn small" onClick={more}>See all</button> : null}</div>
      <div className="table-wrap">
        <table className="data-table compact">
          <thead><tr><th>Lead farmer (cluster)</th><th>District</th><th className="num">Farmers</th><th className="num">Registered (ha)</th><th className="num">Irrigated (ha)</th></tr></thead>
          <tbody>
            {leads.map((row) => (
              <tr key={row.lead_farmer}>
                <td><strong>{row.lead_farmer}</strong></td>
                <td>{row.district || '—'}</td>
                <td className="num">{row.farmers}</td>
                <td className="num">{hectares(row.registered_hectares)}</td>
                <td className="num">{hectares(row.irrigated_hectares)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default ProductionPage
