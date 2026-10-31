import { useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import TabSearch from '../components/TabSearch'

const toList = (data) => (Array.isArray(data) ? data : data?.results || [])

async function loadAll(path) {
  const rows = []
  let response = await apiClient.get(path)
  rows.push(...toList(response.data))
  let guard = 0
  while (response.data?.next && guard < 20) {
    response = await apiClient.get(response.data.next)
    rows.push(...toList(response.data))
    guard += 1
  }
  return rows
}

function ReportsPage({ selectedSeason = null, cropSeason = '' }) {
  const [catalogue, setCatalogue] = useState(null)
  const [analytics, setAnalytics] = useState(null)
  const [category, setCategory] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)
  const [filters, setFilters] = useState({})
  const [page, setPage] = useState(1)
  const [preview, setPreview] = useState(null)
  const [options, setOptions] = useState({ provinces: [], districts: [], wards: [], clusters: [], crops: [], programmes: [], seasons: [] })
  const [loading, setLoading] = useState(true)
  const [previewing, setPreviewing] = useState(false)
  const [downloading, setDownloading] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let mounted = true
    const load = async () => {
      setLoading(true)
      try {
        const [catalogueResponse, analyticsResponse, provinces, districts, wards, clusters, crops, programmes, seasons] = await Promise.all([
          apiClient.get('/reports/catalogue/'),
          apiClient.get('/reports/analytics/'),
          loadAll('/provinces/?page_size=200'),
          loadAll('/districts/?page_size=300'),
          loadAll('/wards/?page_size=300'),
          loadAll('/clusters/?page_size=200'),
          loadAll('/crops/?page_size=100'),
          loadAll('/programmes/?page_size=200'),
          loadAll('/seasons/?page_size=50'),
        ])
        if (!mounted) return
        setCatalogue(catalogueResponse.data)
        setAnalytics(analyticsResponse.data)
        setOptions({ provinces, districts, wards, clusters, crops, programmes, seasons })
        setError('')
      } catch {
        if (mounted) setError('Unable to load the reporting centre.')
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    return () => { mounted = false }
  }, [selectedSeason?.id, cropSeason])

  const reports = useMemo(() => {
    const rows = catalogue?.reports || []
    const term = search.trim().toLowerCase()
    return rows.filter((report) => {
      if (category && report.category !== category) return false
      if (!term) return true
      return `${report.title} ${report.description} ${report.code}`.toLowerCase().includes(term)
    })
  }, [catalogue, category, search])

  useEffect(() => {
    if (!selected) return undefined
    let mounted = true
    const loadPreview = async () => {
      setPreviewing(true)
      try {
        const response = await apiClient.get(`/reports/${selected.code}/preview/`, {
          params: { ...cleanFilters(filters), page, page_size: 25 },
        })
        if (mounted) {
          setPreview(response.data)
          setError('')
        }
      } catch (requestError) {
        if (!mounted) return
        const detail = requestError.response?.data?.detail
        setError(typeof detail === 'string' ? detail : 'Unable to preview this report.')
        setPreview(null)
      } finally {
        if (mounted) setPreviewing(false)
      }
    }
    loadPreview()
    return () => { mounted = false }
  }, [selected, filters, page])

  const chooseReport = (report) => {
    const next = {}
    if (report.filters.includes('agricultural_year') && selectedSeason?.id) next.agricultural_year = String(selectedSeason.id)
    if (report.filters.includes('season') && cropSeason) next.season = cropSeason
    setFilters(next)
    setPage(1)
    setSelected(report)
    setPreview(null)
  }

  const download = async (format) => {
    if (!selected) return
    setDownloading(format)
    try {
      const response = await apiClient.get(`/reports/${selected.code}/export/`, {
        params: { ...cleanFilters(filters), file_format: format },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(response.data)
      const disposition = response.headers?.['content-disposition'] || ''
      const named = /filename="([^"]+)"/.exec(disposition)
      const link = document.createElement('a')
      link.href = url
      link.download = named?.[1] || `${selected.code}.${format}`
      link.click()
      URL.revokeObjectURL(url)
      setError('')
    } catch {
      setError(`Unable to download the ${format.toUpperCase()} report.`)
    } finally {
      setDownloading('')
    }
  }

  const districts = options.districts.filter((district) => !filters.province || String(district.province) === String(filters.province))
  const wards = options.wards.filter((ward) => !filters.district || String(ward.district) === String(filters.district))

  return (
    <div className="page-card">
      <div className="section-head">
        <div>
          <h3>Reports</h3>
          <p>Generate filtered reports from the live records and download PDF or Excel-compatible CSV.</p>
        </div>
        <TabSearch value={search} onChange={setSearch} placeholder="Search reports" />
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {loading ? <div className="form-message">Loading reports...</div> : null}
      {!loading && analytics?.cards?.length ? (
        <div className="stats-grid">
          {analytics.cards.map((card) => (
            <article className="stat-card" key={card.label}><span>{card.label}</span><strong>{card.value}</strong></article>
          ))}
        </div>
      ) : null}
      {!loading && analytics?.charts?.length ? (
        <div className="report-bars">
          {analytics.charts.filter((chart) => chart.rows?.length).map((chart) => <Bars key={chart.title} chart={chart} />)}
        </div>
      ) : null}
      {!loading && catalogue ? (
        <div className="report-layout">
          <div className="report-categories">
            <button type="button" className={category ? 'report-category' : 'report-category active'} onClick={() => setCategory('')}>All reports</button>
            {(catalogue.categories || []).map((item) => (
              <button type="button" key={item.code} className={category === item.code ? 'report-category active' : 'report-category'} onClick={() => setCategory(item.code)}>
                {item.label} ({item.count})
              </button>
            ))}
          </div>
          <div className="report-main">
            {reports.map((report) => (
              <button type="button" key={report.code} className={selected?.code === report.code ? 'report-choice active' : 'report-choice'} onClick={() => chooseReport(report)}>
                <strong>{report.title}</strong>
                <small>{report.description}</small>
              </button>
            ))}
            {!reports.length ? <div className="form-message">No reports match this search.</div> : null}
            {selected ? (
              <form className="workflow-form" onSubmit={(event) => { event.preventDefault(); setPage(1) }}>
                <h4>{selected.title}</h4>
                <div className="workflow-fields">
                  {selected.filters.map((name) => (
                    <FilterField
                      key={name}
                      name={name}
                      label={catalogue.filters?.[name] || name}
                      value={filters[name] || ''}
                      options={fieldOptions(name, selected, options, districts, wards)}
                      onChange={(value) => {
                        setPage(1)
                        setFilters((current) => ({ ...current, [name]: value, ...(name === 'province' ? { district: '', ward: '' } : {}), ...(name === 'district' ? { ward: '' } : {}) }))
                      }}
                    />
                  ))}
                </div>
                <div className="report-actions">
                  <button type="submit" className="primary-btn small">Update preview</button>
                  <button type="button" className="ghost-btn" onClick={() => { setFilters({}); setPage(1) }}>All records</button>
                  <button type="button" className="primary-btn small" disabled={!!downloading} onClick={() => download('pdf')}>{downloading === 'pdf' ? 'Preparing PDF…' : 'Download PDF'}</button>
                  <button type="button" className="primary-btn small" disabled={!!downloading} onClick={() => download('csv')}>{downloading === 'csv' ? 'Preparing CSV…' : 'Download CSV'}</button>
                </div>
              </form>
            ) : null}
            {previewing ? <div className="form-message">Preparing the preview...</div> : null}
            {preview ? <Preview preview={preview} page={page} setPage={setPage} /> : null}
            {catalogue.limitations?.length ? (
              <div className="report-note">
                <strong>Data notes</strong>
                <ul>{catalogue.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function cleanFilters(filters) {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== '' && value !== undefined))
}

function fieldOptions(name, report, options, districts, wards) {
  if (name === 'agricultural_year') return options.seasons.filter((season) => season.selectable !== false).map((season) => [String(season.id), season.name])
  if (name === 'season') return [['SUMMER', 'Summer'], ['WINTER', 'Winter']]
  if (name === 'province') return options.provinces.map((province) => [String(province.id), province.name])
  if (name === 'district') return districts.map((district) => [String(district.id), district.name])
  if (name === 'ward') return wards.map((ward) => [String(ward.id), ward.name])
  if (name === 'cluster') return options.clusters.map((cluster) => [String(cluster.id), cluster.name])
  if (name === 'crop') return options.crops.map((crop) => [crop.name, crop.name])
  if (name === 'programme') return options.programmes.map((programme) => [String(programme.id), programme.name])
  if ((name === 'status' || name === 'payment_status') && report.status_options?.length) return report.status_options
  return null
}

function FilterField({ name, label, value, options, onChange }) {
  return (
    <label className="form-field">{label}
      {options ? (
        <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="">All</option>
          {options.map(([optionValue, optionLabel]) => <option key={optionValue} value={optionValue}>{optionLabel}</option>)}
        </select>
      ) : name.endsWith('date') ? (
        <input aria-label={label} type="date" value={value} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} />
      )}
    </label>
  )
}

function Preview({ preview, page, setPage }) {
  const max = Math.max(...(preview.chart || []).map((row) => Number(row.value) || 0), 1)
  return (
    <section>
      <h4>{preview.title}</h4>
      {preview.filters?.length ? <p className="report-note">Filters: {preview.filters.join('; ')}</p> : <p className="report-note">All available records</p>}
      {preview.gap ? <p className="report-gap">{preview.gap}</p> : null}
      <div className="stats-grid">
        {(preview.summaries || []).map((item) => <article className="stat-card" key={item.label}><span>{item.label}</span><strong>{item.value}</strong></article>)}
      </div>
      {preview.chart?.length ? <Bars chart={{ title: preview.title, rows: preview.chart }} max={max} /> : null}
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr>{preview.columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
          <tbody>
            {preview.rows.map((row, index) => (
              <tr key={`${preview.code}-${index}`}>{preview.columns.map((column) => <td key={column.key}>{row[column.key] || '—'}</td>)}</tr>
            ))}
            {!preview.rows.length ? <tr><td colSpan={preview.columns.length}>No records match these filters.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <div className="report-pager">
        <span>{preview.count} records</span>
        <button type="button" className="ghost-btn" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</button>
        <span>Page {preview.page} of {preview.pages}</span>
        <button type="button" className="ghost-btn" disabled={page >= preview.pages} onClick={() => setPage((current) => current + 1)}>Next</button>
      </div>
    </section>
  )
}

function Bars({ chart, max }) {
  const scale = max || Math.max(...chart.rows.map((row) => Number(row.value) || 0), 1)
  return (
    <section className="report-bars" aria-label={chart.title}>
      <h4>{chart.title}</h4>
      {chart.rows.map((row) => (
        <div className="report-bar" key={`${chart.title}-${row.label}`}>
          <span>{row.label}</span>
          <span className="report-bar-track"><span style={{ width: `${Math.max((Number(row.value) || 0) / scale * 100, 0)}%` }} /></span>
          <strong>{row.display}</strong>
        </div>
      ))}
    </section>
  )
}

export default ReportsPage
