import { useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import Icon from '../components/Icon'
import { EmptyState, Modal, PageHead, Skeleton, StatCard, errorMessage } from '../components/ui'

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

function cleanFilters(filters) {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== '' && value !== undefined))
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
  const [previewError, setPreviewError] = useState('')
  const [showCharts, setShowCharts] = useState(false)

  useEffect(() => {
    let mounted = true
    const load = async () => {
      setLoading(true)
      try {
        const [catalogueResponse, analyticsResponse] = await Promise.all([
          apiClient.get('/reports/catalogue/'),
          apiClient.get('/reports/analytics/'),
        ])
        if (!mounted) return
        setCatalogue(catalogueResponse.data)
        setAnalytics(analyticsResponse.data)
        setError('')
      } catch (requestError) {
        if (mounted) setError(errorMessage(requestError, 'Unable to load the reporting centre.'))
      } finally {
        if (mounted) setLoading(false)
      }
      // Filter choices load separately. A role that cannot read one list still gets its reports.
      const names = ['provinces', 'districts', 'wards', 'clusters', 'crops', 'programmes', 'seasons']
      const paths = ['/provinces/?page_size=200', '/districts/?page_size=300', '/wards/?page_size=300', '/clusters/?page_size=200', '/crops/?page_size=100', '/programmes/?page_size=200', '/seasons/?page_size=50']
      const results = await Promise.allSettled(paths.map(loadAll))
      if (!mounted) return
      setOptions(Object.fromEntries(names.map((name, index) => [name, results[index].status === 'fulfilled' ? results[index].value : []])))
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

  const grouped = useMemo(() => (catalogue?.categories || [])
    .map((item) => ({ ...item, reports: reports.filter((report) => report.category === item.code) }))
    .filter((item) => item.reports.length), [catalogue, reports])

  const periodFilters = (report) => {
    const next = {}
    if (report.filters.includes('agricultural_year') && selectedSeason?.id) next.agricultural_year = String(selectedSeason.id)
    if (report.filters.includes('season') && cropSeason) next.season = cropSeason
    return next
  }

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
          setPreviewError('')
        }
      } catch (requestError) {
        if (!mounted) return
        setPreviewError(errorMessage(requestError, 'Unable to preview this report.'))
        setPreview(null)
      } finally {
        if (mounted) setPreviewing(false)
      }
    }
    loadPreview()
    return () => { mounted = false }
  }, [selected, filters, page])

  const chooseReport = (report) => {
    setFilters(periodFilters(report))
    setPage(1)
    setPreview(null)
    setPreviewError('')
    setSelected(report)
  }

  const closeReport = () => {
    setSelected(null)
    setPreview(null)
  }

  const download = async (report, format, reportFilters) => {
    setDownloading(`${report.code}:${format}`)
    try {
      const response = await apiClient.get(`/reports/${report.code}/export/`, {
        params: { ...cleanFilters(reportFilters), file_format: format },
        responseType: 'blob',
        timeout: 120000,
      })
      const url = URL.createObjectURL(response.data)
      const disposition = response.headers?.['content-disposition'] || ''
      const named = /filename="([^"]+)"/.exec(disposition)
      const link = document.createElement('a')
      link.href = url
      link.download = named?.[1] || `${report.code}.${format}`
      link.click()
      URL.revokeObjectURL(url)
      setError('')
      setPreviewError('')
    } catch (requestError) {
      const message = requestError.response?.status === 403
        ? 'Your role is not allowed to export this report.'
        : `Unable to download the ${format.toUpperCase()} report.`
      if (selected) setPreviewError(message)
      else setError(message)
    } finally {
      setDownloading('')
    }
  }

  const districts = options.districts.filter((district) => !filters.province || String(district.province) === String(filters.province))
  const wards = options.wards.filter((ward) => !filters.district || String(ward.district) === String(filters.district))
  const charts = (analytics?.charts || []).filter((chart) => chart.rows?.length)
  const periodLabel = selectedSeason?.name ? `${selectedSeason.name}${cropSeason ? ` · ${cropSeason.charAt(0)}${cropSeason.slice(1).toLowerCase()}` : ''}` : ''

  return (
    <div className="page-card">
      <PageHead title="Reports" subtitle="Standard reports computed from the live records. View, print or export a report for the selected agricultural year." />

      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {loading ? (
        <>
          <div className="stats-grid"><Skeleton kind="stat" count={4} /></div>
          <Skeleton kind="block" />
        </>
      ) : null}

      {!loading && analytics?.cards?.length ? (
        <div className="stats-grid">
          {analytics.cards.map((card) => <StatCard key={card.label} label={card.label} value={card.value} />)}
        </div>
      ) : null}

      {!loading && charts.length ? (
        <div>
          <button type="button" className="ghost-btn small" aria-expanded={showCharts} onClick={() => setShowCharts((value) => !value)}>
            <Icon name="chart" />{showCharts ? 'Hide summary charts' : 'Show summary charts'}
          </button>
          {showCharts ? <div className="report-charts" style={{ marginTop: 14 }}>{charts.map((chart) => <div className="card" key={chart.title}><Bars chart={chart} /></div>)}</div> : null}
        </div>
      ) : null}

      {!loading && catalogue ? (
        <>
          <div className="report-toolbar no-print">
            <input className="tab-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search reports" aria-label="Search reports" />
            <span className="card-sub">{reports.length} of {catalogue.reports.length} reports{periodLabel ? ` · Period ${periodLabel}` : ''}</span>
          </div>
          <div className="chip-row no-print" role="group" aria-label="Report categories">
            <button type="button" className={category ? 'chip' : 'chip active'} aria-pressed={!category} onClick={() => setCategory('')}>All <small>{catalogue.reports.length}</small></button>
            {(catalogue.categories || []).map((item) => (
              <button type="button" key={item.code} className={category === item.code ? 'chip active' : 'chip'} aria-pressed={category === item.code} onClick={() => setCategory(item.code)}>
                {item.label} <small>{item.count}</small>
              </button>
            ))}
          </div>

          {!grouped.length ? <div className="card"><EmptyState icon="search" title="No reports match this search">Try another word or choose a different category.</EmptyState></div> : null}

          {grouped.map((group) => (
            <section className="report-section" key={group.code}>
              <h3>{group.label}</h3>
              <div className="report-grid">
                {group.reports.map((report) => (
                  <article className="report-card" key={report.code}>
                    <h4>{report.title}</h4>
                    <p>{report.description}</p>
                    <footer>
                      <code>{report.filters.includes('agricultural_year') && selectedSeason?.name ? selectedSeason.name : 'All dates'}</code>
                      <span className="table-actions">
                        <button type="button" className="ghost-btn small" aria-label={`Export ${report.title} as CSV`} disabled={Boolean(downloading)} onClick={() => download(report, 'csv', periodFilters(report))}>
                          <Icon name="download" />{downloading === `${report.code}:csv` ? 'Preparing…' : 'CSV'}
                        </button>
                        <button type="button" className="ghost-btn small" aria-label={`Export ${report.title} as PDF`} disabled={Boolean(downloading)} onClick={() => download(report, 'pdf', periodFilters(report))}>
                          <Icon name="printer" />{downloading === `${report.code}:pdf` ? 'Preparing…' : 'PDF'}
                        </button>
                        <button type="button" className="primary-btn small" aria-label={`View ${report.title}`} onClick={() => chooseReport(report)}>
                          <Icon name="eye" />View
                        </button>
                      </span>
                    </footer>
                  </article>
                ))}
              </div>
            </section>
          ))}

          {catalogue.limitations?.length ? (
            <details className="report-note">
              <summary>Data notes</summary>
              <ul>{catalogue.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
            </details>
          ) : null}
        </>
      ) : null}

      {selected ? (
        <Modal
          wide
          title={selected.title}
          subtitle={selected.description}
          onClose={closeReport}
          footer={(
            <>
              <button type="button" className="ghost-btn" onClick={() => window.print()}><Icon name="printer" />Print this page</button>
              <button type="button" className="ghost-btn" disabled={Boolean(downloading)} onClick={() => download(selected, 'csv', filters)}>{downloading === `${selected.code}:csv` ? 'Preparing CSV…' : 'Download CSV'}</button>
              <button type="button" className="primary-btn" disabled={Boolean(downloading)} onClick={() => download(selected, 'pdf', filters)}>{downloading === `${selected.code}:pdf` ? 'Preparing PDF…' : 'Download PDF'}</button>
            </>
          )}
        >
          {selected.filters.length ? (
            <form className="no-print" onSubmit={(event) => event.preventDefault()}>
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
                <button type="button" className="ghost-btn small" onClick={() => { setFilters({}); setPage(1) }}>Clear filters</button>
                <button type="button" className="ghost-btn small" onClick={() => { setFilters(periodFilters(selected)); setPage(1) }}>Selected period</button>
              </div>
            </form>
          ) : null}
          {previewError ? <div className="form-message error" role="alert">{previewError}</div> : null}
          {previewing && !preview ? <Skeleton kind="block" /> : null}
          {preview ? <Preview preview={preview} page={page} setPage={setPage} busy={previewing} /> : null}
        </Modal>
      ) : null}
    </div>
  )
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

function Preview({ preview, page, setPage, busy }) {
  const max = Math.max(...(preview.chart || []).map((row) => Number(row.value) || 0), 1)
  return (
    <section className="finance-stack" aria-busy={busy}>
      <p className="card-sub">{preview.filters?.length ? `Filters: ${preview.filters.join('; ')}` : 'All available records'}</p>
      {preview.gap ? <p className="report-gap">{preview.gap}</p> : null}
      <div className="stats-grid">
        {(preview.summaries || []).map((item) => <StatCard key={item.label} label={item.label} value={item.value} />)}
      </div>
      {preview.chart?.length ? <div className="card no-print"><Bars chart={{ title: preview.title, rows: preview.chart }} max={max} /></div> : null}
      <div className="table-wrap">
        {preview.rows.length ? (
          <table className="data-table">
            <thead><tr>{preview.columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
            <tbody>
              {preview.rows.map((row, index) => (
                <tr key={`${preview.code}-${index}`}>{preview.columns.map((column) => <td key={column.key}>{row[column.key] || '—'}</td>)}</tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState icon="database" title="No records match these filters">Clear a filter or choose another period.</EmptyState>}
        <div className="report-pager no-print">
          <span>{preview.count} record{preview.count === 1 ? '' : 's'}</span>
          <span className="table-actions">
            <button type="button" className="ghost-btn small" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</button>
            <span style={{ alignSelf: 'center' }}>Page {preview.page} of {preview.pages}</span>
            <button type="button" className="ghost-btn small" disabled={page >= preview.pages} onClick={() => setPage((current) => current + 1)}>Next</button>
          </span>
        </div>
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
