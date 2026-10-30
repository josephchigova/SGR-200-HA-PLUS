import { useEffect, useState } from 'react'

import apiClient from '../api/client'

const WRITE_ROLES = new Set(['super_admin', 'sgr_executive', 'finance_officer'])
const ADMIN_ROLES = new Set(['super_admin', 'sgr_executive'])

const CONDITIONS = [
  ['NEW', 'New'],
  ['GOOD', 'Good'],
  ['FAIR', 'Fair'],
  ['POOR', 'Poor'],
  ['DAMAGED', 'Damaged'],
]

const STATUSES = [
  ['ACTIVE', 'Active'],
  ['UNDER_MAINTENANCE', 'Under Maintenance'],
  ['DISPOSED', 'Disposed'],
  ['WRITTEN_OFF', 'Written Off'],
]

const METHODS = [
  ['STRAIGHT_LINE', 'Straight line'],
  ['REDUCING_BALANCE', 'Reducing balance'],
  ['NONE', 'No depreciation'],
]

const emptyForm = {
  name: '',
  category: '',
  asset_id: '',
  description: '',
  purchase_date: '',
  supplier: '',
  cost: '',
  current_value: '',
  location: '',
  department: '',
  responsible_person: '',
  condition: 'NEW',
  status: 'ACTIVE',
  warranty_expiry: '',
  notes: '',
  depreciation_method: 'STRAIGHT_LINE',
  useful_life_years: '',
  residual_value: '0.00',
  depreciation_rate: '',
  accumulated_depreciation: '0.00',
}

function money(value) {
  if (value === null || value === undefined || value === '') return '0.00'
  const amount = Number(value)
  if (Number.isNaN(amount)) return String(value)
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount)
}

function errorText(error, fallback) {
  const data = error?.response?.data
  if (!data) return fallback
  if (typeof data === 'string') return data
  if (typeof data.detail === 'string') return data.detail
  if (Array.isArray(data.detail)) return data.detail.join(' ')
  return Object.entries(data).map(([key, value]) => `${key}: ${[].concat(value).join(' ')}`).join(' ')
}

function listRows(data) {
  if (Array.isArray(data)) return { rows: data, count: data.length, next: null, previous: null }
  return { rows: data?.results || [], count: data?.count || 0, next: data?.next || null, previous: data?.previous || null }
}

function formFromAsset(asset) {
  return {
    name: asset.name || asset.display_name || '',
    category: asset.category || '',
    asset_id: asset.asset_id || '',
    description: asset.description || '',
    purchase_date: asset.purchase_date || '',
    supplier: asset.supplier || '',
    cost: asset.cost || '',
    current_value: asset.current_value || '',
    location: asset.location || '',
    department: asset.department || '',
    responsible_person: asset.responsible_person || '',
    condition: asset.condition || 'GOOD',
    status: asset.status || 'ACTIVE',
    warranty_expiry: asset.warranty_expiry || '',
    notes: asset.notes || '',
    depreciation_method: asset.depreciation_method || 'NONE',
    useful_life_years: asset.useful_life_years || '',
    residual_value: asset.residual_value || '0.00',
    depreciation_rate: asset.depreciation_rate || '',
    accumulated_depreciation: asset.accumulated_depreciation || '0.00',
  }
}

function payloadFromForm(form) {
  const payload = {
    name: form.name.trim(),
    description: form.description.trim(),
    category: form.category || null,
    purchase_date: form.purchase_date || null,
    supplier: form.supplier.trim(),
    cost: form.cost,
    location: form.location.trim(),
    department: form.department.trim(),
    responsible_person: form.responsible_person.trim(),
    condition: form.condition,
    status: form.status === 'DISPOSED' || form.status === 'WRITTEN_OFF' ? 'ACTIVE' : form.status,
    warranty_expiry: form.warranty_expiry || null,
    notes: form.notes.trim(),
    depreciation_method: form.depreciation_method,
    useful_life_years: form.useful_life_years === '' ? null : form.useful_life_years,
    residual_value: form.residual_value === '' ? '0.00' : form.residual_value,
    accumulated_depreciation: form.accumulated_depreciation === '' ? '0.00' : form.accumulated_depreciation,
  }
  if (form.asset_id.trim()) payload.asset_id = form.asset_id.trim()
  if (form.current_value !== '') payload.current_value = form.current_value
  if (form.depreciation_method === 'REDUCING_BALANCE') payload.depreciation_rate = form.depreciation_rate
  return payload
}

function AssetsPanel() {
  const [profile, setProfile] = useState(null)
  const [summary, setSummary] = useState(null)
  const [categories, setCategories] = useState([])
  const [rows, setRows] = useState([])
  const [page, setPage] = useState({ count: 0, next: null, previous: null, number: 1 })
  const [filters, setFilters] = useState({ search: '', category: '', location: '', condition: '', status: '', ordering: 'asset_id' })
  const [applied, setApplied] = useState(filters)
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [selected, setSelected] = useState(null)
  const [history, setHistory] = useState(null)
  const [maintenance, setMaintenance] = useState({ activity_date: '', description: '', cost: '', supplier: '', notes: '' })
  const [transfer, setTransfer] = useState({ transfer_date: '', to_location: '', to_department: '', to_person: '', notes: '' })
  const [disposal, setDisposal] = useState({ kind: 'DISPOSED', disposed_on: '', reason: '', proceeds: '0.00' })
  const [categoryForm, setCategoryForm] = useState({ name: '', description: '' })
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const canWrite = WRITE_ROLES.has(profile?.role)
  const canConfigureCategories = ADMIN_ROLES.has(profile?.role)
  const closed = selected?.status === 'DISPOSED' || selected?.status === 'WRITTEN_OFF'

  const loadRegister = async (pageNumber = page.number, query = applied) => {
    const params = { page: pageNumber, ordering: query.ordering }
    if (query.search) params.search = query.search
    if (query.category) params.category = query.category
    if (query.location) params.location = query.location
    if (query.condition) params.condition = query.condition
    if (query.status) params.status = query.status
    const [summaryResponse, categoryResponse, listResponse] = await Promise.all([
      apiClient.get('/assets/summary/'),
      apiClient.get('/asset-categories/'),
      apiClient.get('/assets/', { params }),
    ])
    const listed = listRows(listResponse.data)
    setSummary(summaryResponse.data)
    setCategories(Array.isArray(categoryResponse.data) ? categoryResponse.data : categoryResponse.data?.results || [])
    setRows(listed.rows)
    setPage({ count: listed.count, next: listed.next, previous: listed.previous, number: pageNumber })
  }

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const me = await apiClient.get('/auth/me/').catch(() => ({ data: null }))
        if (cancelled) return
        setProfile(me.data)
        await loadRegister(1, applied)
      } catch (requestError) {
        if (!cancelled) setError(errorText(requestError, 'The asset register could not be loaded.'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  const refresh = async (pageNumber = page.number) => {
    await loadRegister(pageNumber, applied)
  }

  const openAsset = async (asset) => {
    setError('')
    setMessage('')
    setSelected(asset)
    setShowForm(false)
    try {
      const [detail, past] = await Promise.all([
        apiClient.get(`/assets/${asset.id}/`),
        apiClient.get(`/assets/${asset.id}/history/`),
      ])
      setSelected(detail.data)
      setHistory(past.data)
    } catch (requestError) {
      setError(errorText(requestError, 'The asset record could not be opened.'))
    }
  }

  const startCreate = () => {
    setEditingId(null)
    setForm(emptyForm)
    setShowForm(true)
    setSelected(null)
    setMessage('')
    setError('')
  }

  const startEdit = (asset) => {
    setEditingId(asset.id)
    setForm(formFromAsset(asset))
    setShowForm(true)
    setMessage('')
    setError('')
  }

  const saveAsset = async (event) => {
    event.preventDefault()
    setError('')
    setMessage('')
    try {
      const body = payloadFromForm(form)
      const response = editingId
        ? await apiClient.patch(`/assets/${editingId}/`, body)
        : await apiClient.post('/assets/', body)
      setMessage(editingId ? 'Asset updated. No ledger entry was posted.' : `Asset ${response.data.asset_id} registered. Acquisition cost was not posted as an expense.`)
      setShowForm(false)
      setEditingId(null)
      await refresh(editingId ? page.number : 1)
      await openAsset(response.data)
    } catch (requestError) {
      setError(errorText(requestError, 'The asset was not saved.'))
    }
  }

  const applyFilters = async (event) => {
    event.preventDefault()
    setApplied(filters)
    setLoading(true)
    try {
      await loadRegister(1, filters)
    } catch (requestError) {
      setError(errorText(requestError, 'The asset list could not be filtered.'))
    } finally {
      setLoading(false)
    }
  }

  const runAction = async (path, body, success) => {
    setError('')
    setMessage('')
    try {
      await apiClient.post(path, body)
      setMessage(success)
      await refresh()
      if (selected) await openAsset(selected)
    } catch (requestError) {
      setError(errorText(requestError, 'The asset action was not saved.'))
    }
  }

  const uploadDocument = async (event) => {
    event.preventDefault()
    const input = event.target.elements.file
    if (!input?.files?.[0] || !selected) return
    const body = new FormData()
    body.append('file', input.files[0])
    body.append('title', event.target.elements.title.value || input.files[0].name)
    setError('')
    try {
      await apiClient.post(`/assets/${selected.id}/documents/`, body)
      event.target.reset()
      setMessage('Supporting document saved with the asset.')
      await openAsset(selected)
    } catch (requestError) {
      setError(errorText(requestError, 'The document was not saved.'))
    }
  }

  const saveCategory = async (event) => {
    event.preventDefault()
    setError('')
    try {
      await apiClient.post('/asset-categories/', categoryForm)
      setCategoryForm({ name: '', description: '' })
      setMessage('Asset category saved.')
      await refresh()
    } catch (requestError) {
      setError(errorText(requestError, 'The category was not saved.'))
    }
  }

  const largestCategory = Math.max(1, ...(summary?.by_category || []).map((row) => Number(row.acquisition_value) || 0))

  return (
    <section className="asset-register" aria-label="Asset management">
      <div className="section-head">
        <div>
          <h4>Asset register</h4>
          <p className="finance-note">Acquisition cost stays on the asset register. Saving an asset, maintenance, transfer or disposal does not post an operating expense or a journal.</p>
        </div>
        {canWrite ? <button type="button" className="primary-btn" onClick={startCreate}>Register asset</button> : <span className="status-pill review">Read only</span>}
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {message ? <div className="form-message" role="status">{message}</div> : null}
      {loading && !summary ? <div className="form-message">Loading the asset register...</div> : null}

      {summary ? (
        <>
          <div className="finance-grid asset-summary">
            <article className="stat-card"><span>Registered assets</span><strong>{summary.total_assets}</strong></article>
            <article className="stat-card"><span>Acquisition value</span><strong>{money(summary.total_acquisition_value)}</strong><small>Sum of purchase cost for every registered asset.</small></article>
            <article className="stat-card"><span>Current estimated value</span><strong>{money(summary.total_current_value)}</strong><small>Active assets and assets under maintenance.</small></article>
            <article className="stat-card"><span>Net book value</span><strong>{money(summary.total_net_book_value)}</strong><small>Cost minus accumulated depreciation. Not a posted ledger balance.</small></article>
            <article className="stat-card"><span>Under maintenance</span><strong>{summary.under_maintenance}</strong></article>
            <article className="stat-card"><span>Disposed or written off</span><strong>{summary.disposed_or_written_off}</strong></article>
          </div>
          <article className="asset-chart">
            <h4>Assets by category</h4>
            {summary.by_category?.length ? summary.by_category.map((row) => (
              <div className="dashboard-bar" key={row.category}>
                <span>{row.category}</span>
                <div><i style={{ width: `${Math.max(4, (Number(row.acquisition_value) / largestCategory) * 100)}%` }} /></div>
                <strong>{row.count}</strong>
              </div>
            )) : <p className="finance-note">Register an asset to see the category breakdown.</p>}
          </article>
        </>
      ) : null}

      <form className="asset-filters" onSubmit={applyFilters}>
        <label>Search<input value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} placeholder="Name, code, supplier" /></label>
        <label>Category
          <select value={filters.category} onChange={(event) => setFilters({ ...filters, category: event.target.value })}>
            <option value="">All categories</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </select>
        </label>
        <label>Location<input value={filters.location} onChange={(event) => setFilters({ ...filters, location: event.target.value })} /></label>
        <label>Condition
          <select value={filters.condition} onChange={(event) => setFilters({ ...filters, condition: event.target.value })}>
            <option value="">All conditions</option>
            {CONDITIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>Status
          <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
            <option value="">All statuses</option>
            {STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>Sort
          <select value={filters.ordering} onChange={(event) => setFilters({ ...filters, ordering: event.target.value })}>
            <option value="asset_id">Asset code</option>
            <option value="name">Name</option>
            <option value="-cost">Acquisition cost</option>
            <option value="-purchase_date">Acquisition date</option>
            <option value="status">Status</option>
          </select>
        </label>
        <button type="submit" className="ghost-btn">Apply filters</button>
      </form>

      {showForm && canWrite ? (
        <form className="asset-form" onSubmit={saveAsset}>
          <h4>{editingId ? 'Edit asset' : 'Register an asset'}</h4>
          <fieldset>
            <legend>Identity</legend>
            <div className="form-grid">
              <label className="form-field">Asset name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
              <label className="form-field">Category
                <select required value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>
                  <option value="">Select</option>
                  {categories.filter((category) => category.is_active || String(category.id) === String(form.category)).map((category) => (
                    <option key={category.id} value={category.id}>{category.name}</option>
                  ))}
                </select>
              </label>
              <label className="form-field">Asset code<input value={form.asset_id} placeholder="Assigned automatically when left blank" disabled={Boolean(editingId)} onChange={(event) => setForm({ ...form, asset_id: event.target.value })} /></label>
              <label className="form-field full-width">Description<textarea required rows="3" maxLength="255" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
            </div>
          </fieldset>
          <fieldset>
            <legend>Acquisition</legend>
            <div className="form-grid">
              <label className="form-field">Acquisition date<input type="date" required value={form.purchase_date} onChange={(event) => setForm({ ...form, purchase_date: event.target.value })} /></label>
              <label className="form-field">Supplier<input value={form.supplier} onChange={(event) => setForm({ ...form, supplier: event.target.value })} /></label>
              <label className="form-field">Purchase cost<input required inputMode="decimal" value={form.cost} onChange={(event) => setForm({ ...form, cost: event.target.value })} /></label>
              <label className="form-field">Current estimated value<input inputMode="decimal" value={form.current_value} placeholder="Defaults to purchase cost" onChange={(event) => setForm({ ...form, current_value: event.target.value })} /></label>
            </div>
          </fieldset>
          <fieldset>
            <legend>Responsibility</legend>
            <div className="form-grid">
              <label className="form-field">Location / branch<input value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} /></label>
              <label className="form-field">Department<input value={form.department} onChange={(event) => setForm({ ...form, department: event.target.value })} /></label>
              <label className="form-field">Responsible person<input value={form.responsible_person} onChange={(event) => setForm({ ...form, responsible_person: event.target.value })} /></label>
            </div>
          </fieldset>
          <fieldset>
            <legend>Condition and cover</legend>
            <div className="form-grid">
              <label className="form-field">Condition
                <select value={form.condition} onChange={(event) => setForm({ ...form, condition: event.target.value })}>
                  {CONDITIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <label className="form-field">Status
                <select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
                  {STATUSES.filter(([value]) => value === 'ACTIVE' || value === 'UNDER_MAINTENANCE').map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <label className="form-field">Warranty expiry<input type="date" value={form.warranty_expiry} onChange={(event) => setForm({ ...form, warranty_expiry: event.target.value })} /></label>
            </div>
          </fieldset>
          <fieldset>
            <legend>Depreciation</legend>
            <p className="finance-note">The method, useful life, residual value, rate, accumulated depreciation and net book value are stored on the asset. They are not posted to the ledger from this form. An explicit depreciation posting remains a separate finance action.</p>
            <div className="form-grid">
              <label className="form-field">Method
                <select value={form.depreciation_method} onChange={(event) => setForm({ ...form, depreciation_method: event.target.value })}>
                  {METHODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              {form.depreciation_method === 'STRAIGHT_LINE' ? (
                <label className="form-field">Useful life (years)<input required inputMode="decimal" value={form.useful_life_years} onChange={(event) => setForm({ ...form, useful_life_years: event.target.value })} /></label>
              ) : null}
              {form.depreciation_method === 'REDUCING_BALANCE' ? (
                <label className="form-field">Depreciation rate (%)<input required inputMode="decimal" value={form.depreciation_rate} onChange={(event) => setForm({ ...form, depreciation_rate: event.target.value })} /></label>
              ) : null}
              <label className="form-field">Residual value<input inputMode="decimal" value={form.residual_value} onChange={(event) => setForm({ ...form, residual_value: event.target.value })} /></label>
              <label className="form-field">Accumulated depreciation<input inputMode="decimal" value={form.accumulated_depreciation} onChange={(event) => setForm({ ...form, accumulated_depreciation: event.target.value })} /></label>
            </div>
          </fieldset>
          <fieldset>
            <legend>Notes</legend>
            <label className="form-field">Notes<textarea rows="3" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label>
          </fieldset>
          <div className="form-actions">
            <button type="button" className="ghost-btn" onClick={() => setShowForm(false)}>Cancel</button>
            <button type="submit" className="primary-btn">{editingId ? 'Save changes' : 'Save asset'}</button>
          </div>
        </form>
      ) : null}

      <div className="table-wrap">
        <table className="data-table finance-table">
          <thead>
            <tr>
              <th>Code</th><th>Name</th><th>Category</th><th>Location</th><th>Condition</th><th>Status</th><th className="num">Cost</th><th className="num">Current value</th><th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((asset) => (
              <tr key={asset.id}>
                <td>{asset.asset_id}</td>
                <td>{asset.display_name || asset.name}</td>
                <td>{asset.category_name || '—'}</td>
                <td>{asset.location || '—'}</td>
                <td>{CONDITIONS.find(([value]) => value === asset.condition)?.[1] || '—'}</td>
                <td><span className={`status-pill ${asset.status === 'ACTIVE' ? 'active' : 'review'}`}>{STATUSES.find(([value]) => value === asset.status)?.[1] || asset.status}</span></td>
                <td className="num">{money(asset.cost)}</td>
                <td className="num">{money(asset.current_value)}</td>
                <td><button type="button" className="ghost-btn small" onClick={() => openAsset(asset)}>View</button></td>
              </tr>
            ))}
            {!loading && rows.length === 0 ? <tr><td className="mobile-span" colSpan="9">No assets have been registered.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <div className="subscription-pagination">
        <span>{page.count} assets</span>
        <div>
          <button type="button" className="ghost-btn small" disabled={!page.previous} onClick={() => refresh(page.number - 1)}>Previous</button>
          <button type="button" className="ghost-btn small" disabled={!page.next} onClick={() => refresh(page.number + 1)}>Next</button>
        </div>
      </div>

      {selected && history ? (
        <article className="asset-detail">
          <div className="section-head">
            <div>
              <h4>{selected.asset_id} · {selected.display_name || selected.name}</h4>
              <p className="finance-note">{selected.description}</p>
            </div>
            {canWrite && !closed ? <button type="button" className="ghost-btn" onClick={() => startEdit(selected)}>Edit</button> : null}
          </div>
          <div className="detail-grid">
            <p><span>Category</span><strong>{selected.category_name || '—'}</strong></p>
            <p><span>Supplier</span><strong>{selected.supplier || '—'}</strong></p>
            <p><span>Acquired</span><strong>{selected.purchase_date || '—'}</strong></p>
            <p><span>Location</span><strong>{selected.location || '—'}</strong></p>
            <p><span>Department</span><strong>{selected.department || '—'}</strong></p>
            <p><span>Responsible person</span><strong>{selected.responsible_person || '—'}</strong></p>
            <p><span>Purchase cost</span><strong>{money(selected.cost)}</strong></p>
            <p><span>Current estimated value</span><strong>{money(selected.current_value)}</strong></p>
            <p><span>Method</span><strong>{METHODS.find(([value]) => value === selected.depreciation_method)?.[1] || selected.depreciation_method}</strong></p>
            <p><span>Useful life</span><strong>{selected.useful_life_years || '—'}</strong></p>
            <p><span>Residual value</span><strong>{money(selected.residual_value)}</strong></p>
            <p><span>Depreciation rate</span><strong>{selected.depreciation_rate}%</strong></p>
            <p><span>Annual depreciation</span><strong>{money(selected.annual_depreciation)}</strong></p>
            <p><span>Accumulated depreciation</span><strong>{money(selected.accumulated_depreciation)}</strong></p>
            <p><span>Net book value</span><strong>{money(selected.net_book_value)}</strong></p>
            <p><span>Warranty expiry</span><strong>{selected.warranty_expiry || '—'}</strong></p>
          </div>
          {selected.notes ? <p className="finance-note">{selected.notes}</p> : null}

          <h4>Acquisition and valuation history</h4>
          <HistoryTable columns={['Date', 'Type', 'Amount', 'Note']} rows={(history.valuations || []).map((row) => [row.valued_on, row.kind === 'ACQUISITION' ? 'Acquisition cost' : 'Estimated value', money(row.amount), row.note])} empty="No valuation history yet." />

          <h4>Maintenance</h4>
          <HistoryTable columns={['Date', 'Activity', 'Cost', 'Supplier']} rows={(history.maintenance || []).map((row) => [row.activity_date, row.description, money(row.cost), row.supplier || '—'])} empty="No maintenance has been recorded." />
          {canWrite ? (
            <form className="asset-inline-form" onSubmit={(event) => { event.preventDefault(); runAction(`/assets/${selected.id}/maintenance/`, maintenance, 'Maintenance recorded. The cost was not posted as an operating expense.') }}>
              <label>Date<input type="date" required value={maintenance.activity_date} onChange={(event) => setMaintenance({ ...maintenance, activity_date: event.target.value })} /></label>
              <label>Activity<input required value={maintenance.description} onChange={(event) => setMaintenance({ ...maintenance, description: event.target.value })} /></label>
              <label>Cost<input required inputMode="decimal" value={maintenance.cost} onChange={(event) => setMaintenance({ ...maintenance, cost: event.target.value })} /></label>
              <label>Supplier<input value={maintenance.supplier} onChange={(event) => setMaintenance({ ...maintenance, supplier: event.target.value })} /></label>
              <button type="submit" className="ghost-btn">Record maintenance</button>
            </form>
          ) : null}

          <h4>Transfers</h4>
          <HistoryTable columns={['Date', 'To location', 'To department', 'To person']} rows={(history.transfers || []).map((row) => [row.transfer_date, row.to_location || '—', row.to_department || '—', row.to_person || '—'])} empty="No transfers have been recorded." />
          {canWrite && !closed ? (
            <form className="asset-inline-form" onSubmit={(event) => { event.preventDefault(); runAction(`/assets/${selected.id}/transfer/`, transfer, 'Transfer recorded.') }}>
              <label>Date<input type="date" required value={transfer.transfer_date} onChange={(event) => setTransfer({ ...transfer, transfer_date: event.target.value })} /></label>
              <label>Location<input value={transfer.to_location} onChange={(event) => setTransfer({ ...transfer, to_location: event.target.value })} /></label>
              <label>Department<input value={transfer.to_department} onChange={(event) => setTransfer({ ...transfer, to_department: event.target.value })} /></label>
              <label>Responsible person<input value={transfer.to_person} onChange={(event) => setTransfer({ ...transfer, to_person: event.target.value })} /></label>
              <button type="submit" className="ghost-btn">Record transfer</button>
            </form>
          ) : null}

          <h4>Disposal or write-off</h4>
          {history.disposal ? (
            <p className="finance-note">{history.disposal.kind === 'WRITTEN_OFF' ? 'Written off' : 'Disposed'} on {history.disposal.disposed_on}. Proceeds {money(history.disposal.proceeds)}. {history.disposal.reason}</p>
          ) : canWrite ? (
            <form className="asset-inline-form" onSubmit={(event) => { event.preventDefault(); runAction(`/assets/${selected.id}/dispose/`, disposal, 'Disposal recorded. Proceeds were not posted to the ledger.') }}>
              <label>Type
                <select value={disposal.kind} onChange={(event) => setDisposal({ ...disposal, kind: event.target.value })}>
                  <option value="DISPOSED">Disposed</option>
                  <option value="WRITTEN_OFF">Written off</option>
                </select>
              </label>
              <label>Date<input type="date" required value={disposal.disposed_on} onChange={(event) => setDisposal({ ...disposal, disposed_on: event.target.value })} /></label>
              <label>Proceeds<input inputMode="decimal" value={disposal.proceeds} onChange={(event) => setDisposal({ ...disposal, proceeds: event.target.value })} /></label>
              <label className="full-width">Reason<input required value={disposal.reason} onChange={(event) => setDisposal({ ...disposal, reason: event.target.value })} /></label>
              <button type="submit" className="ghost-btn">Record disposal</button>
            </form>
          ) : <p className="finance-note">This asset has not been disposed or written off.</p>}

          <h4>Supporting documents</h4>
          <ul className="asset-documents">
            {(history.documents || []).map((document) => (
              <li key={document.id}>{document.file_url ? <a href={document.file_url}>{document.title || 'Document'}</a> : document.title}</li>
            ))}
            {!(history.documents || []).length ? <li>No documents attached.</li> : null}
          </ul>
          {canWrite ? (
            <form className="asset-inline-form" onSubmit={uploadDocument}>
              <label>Title<input name="title" /></label>
              <label>File<input name="file" type="file" required /></label>
              <button type="submit" className="ghost-btn">Attach document</button>
            </form>
          ) : null}

          <h4>Audit trail</h4>
          <HistoryTable columns={['When', 'Action', 'By', 'Detail']} rows={(history.audit || []).map((row) => [String(row.created_at || '').slice(0, 16).replace('T', ' '), row.action, row.actor_name || '—', row.detail])} empty="No audit events yet." />
        </article>
      ) : null}

      {canConfigureCategories ? (
        <section className="asset-categories">
          <h4>Asset categories</h4>
          <p className="finance-note">Administrators can add categories. Categories already used by an asset cannot be deleted.</p>
          <ul>{categories.map((category) => <li key={category.id}>{category.name}{category.is_active ? '' : ' (inactive)'}</li>)}</ul>
          <form className="asset-inline-form" onSubmit={saveCategory}>
            <label>Name<input required value={categoryForm.name} onChange={(event) => setCategoryForm({ ...categoryForm, name: event.target.value })} /></label>
            <label>Description<input value={categoryForm.description} onChange={(event) => setCategoryForm({ ...categoryForm, description: event.target.value })} /></label>
            <button type="submit" className="ghost-btn">Add category</button>
          </form>
        </section>
      ) : null}
    </section>
  )
}

function HistoryTable({ columns, rows, empty }) {
  if (!rows.length) return <p className="finance-note">{empty}</p>
  return (
    <div className="table-wrap">
      <table className="data-table finance-table">
        <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={`${row[0]}-${index}`}>{row.map((cell, cellIndex) => <td key={columns[cellIndex]}>{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

export default AssetsPanel
