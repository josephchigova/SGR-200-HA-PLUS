// Crop production records: the table, the capture and edit form, record details,
// moving a record to its next stage, and removing it.

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import { useFormDraft } from '../drafts'
import FarmerAutocomplete from './FarmerAutocomplete'
import Icon from './Icon'
import { DraftNotice, DraftStatus, EmptyState, Modal, Pill, errorMessage } from './ui'
import { SEASON_LABEL, STATUSES, STATUS_LABEL, exportRecords, hectares, loadAllRecords } from '../production'

const STATUS_TONE = Object.fromEntries(STATUSES.map(([code, , tone]) => [code, tone]))
const NEXT = { PENDING: 'PLANTED', PLANTED: 'HARVESTED', HARVESTED: 'COMPLETED' }
const EMPTY = {
  farmer: '', farm: '', season: '', crop: '', contracted_hectares: '', planted_hectares: '0', planting_date: '',
  expected_yield: '0', estimated_production: '0', actual_production: '0', harvest_date: '', crop_stage: '', status: 'PENDING',
}

const tonnes = (value) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })
const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])

export function StatusPill({ status }) {
  return <Pill tone={STATUS_TONE[status]}>{STATUS_LABEL[status] || status || '—'}</Pill>
}

const SORTS = [['farmer', 'Farmer'], ['crop', 'Crop'], ['registered', 'Registered (ha)'], ['planted', 'Planted (ha)'], ['status', 'Status'], ['created', 'Newest']]

export default function ProductionRecords({ filters, compact = false, reloadToken = 0, onChanged, onCapture, permissions, periodLabel }) {
  const [rows, setRows] = useState([])
  const [count, setCount] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [status, setStatus] = useState('')
  const [ordering, setOrdering] = useState('farmer')
  const [loaded, setLoaded] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [viewing, setViewing] = useState(null)
  const [editing, setEditing] = useState(null)
  const [removing, setRemoving] = useState(null)
  const [advancing, setAdvancing] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [localToken, setLocalToken] = useState(0)
  const pageSize = compact ? 5 : 25

  useEffect(() => {
    const timer = setTimeout(() => { setPage(1); setAppliedSearch(search.trim()) }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const params = useMemo(() => {
    const next = { ...filters, ordering }
    if (appliedSearch) next.search = appliedSearch
    if (status) next.status = status
    return next
  }, [filters, ordering, appliedSearch, status])
  const requestKey = JSON.stringify([params, page, pageSize, reloadToken, localToken])
  const loading = loaded !== requestKey

  useEffect(() => {
    if (!filters) return undefined
    let active = true
    apiClient.get('/farmer-productions/', { params: { ...params, page, page_size: pageSize } })
      .then((response) => {
        if (!active) return
        setRows(listOf(response.data))
        setCount(Number(response.data?.count ?? listOf(response.data).length))
        setError('')
      })
      .catch((requestError) => {
        if (active) setError(errorMessage(requestError, 'Production records could not be loaded.'))
      })
      .finally(() => { if (active) setLoaded(requestKey) })
    return () => { active = false }
  }, [filters, params, page, pageSize, requestKey])

  const pages = Math.max(1, Math.ceil(count / pageSize))
  const changed = (message) => {
    setNotice(message)
    setLocalToken((value) => value + 1)
    onChanged?.()
  }

  const advance = async (row) => {
    const next = NEXT[row.status]
    if (!next) return
    setAdvancing(row.id)
    setNotice('')
    try {
      const body = { status: next }
      if (next === 'PLANTED' && Number(row.planted_hectares) === 0) body.planted_hectares = row.contracted_hectares
      await apiClient.patch(`/farmer-productions/${row.id}/`, body)
      changed(`${row.farmer_name} · ${row.crop} moved to ${STATUS_LABEL[next]}.`)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The record could not be moved to its next stage.'))
    } finally {
      setAdvancing(null)
    }
  }

  const exportAll = async () => {
    setExporting(true)
    try {
      exportRecords(await loadAllRecords(params), periodLabel)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The records could not be exported.'))
    } finally {
      setExporting(false)
    }
  }

  const sortBy = (key) => setOrdering((current) => (current === key ? `-${key}` : key))
  const sortMark = (key) => (ordering === key ? ' ▲' : ordering === `-${key}` ? ' ▼' : '')
  const firstRow = count ? (page - 1) * pageSize + 1 : 0

  return (
    <section className="card production-records">
      <div className="card-head production-records-head">
        <h3><Icon name="sprout" />Crop production records</h3>
        <div className="page-actions">
          <label className="tab-search production-search">
            <Icon name="search" />
            <input type="search" aria-label="Search production records" placeholder="Search farmer, crop, cluster..." value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          {compact ? null : (
            <select aria-label="Production status" value={status} onChange={(event) => { setPage(1); setStatus(event.target.value) }}>
              <option value="">All statuses</option>
              {STATUSES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
            </select>
          )}
          {compact ? null : (
            <select aria-label="Sort records" value={ordering.replace('-', '')} onChange={(event) => setOrdering(event.target.value)}>
              {SORTS.map(([key, label]) => <option key={key} value={key}>Sort: {label}</option>)}
            </select>
          )}
          <button type="button" className="ghost-btn small" onClick={exportAll} disabled={exporting || !count}><Icon name="download" />{exporting ? 'Exporting…' : 'Export'}</button>
        </div>
      </div>
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      <div className="table-wrap">
        {rows.length ? (
          <table className="data-table production-table">
            <thead>
              <tr>
                <th>#</th>
                <th><button type="button" className="sort-btn" onClick={() => sortBy('farmer')}>Farmer{sortMark('farmer')}</button></th>
                <th>Farmer ID</th>
                <th>Cluster (lead farmer)</th>
                <th><button type="button" className="sort-btn" onClick={() => sortBy('crop')}>Crop{sortMark('crop')}</button></th>
                <th>Season</th>
                <th>Agri year</th>
                <th className="num"><button type="button" className="sort-btn" onClick={() => sortBy('registered')}>Registered (ha){sortMark('registered')}</button></th>
                <th className="num">Irrigated (ha)</th>
                <th><button type="button" className="sort-btn" onClick={() => sortBy('status')}>Status{sortMark('status')}</button></th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={row.id}>
                  <td>{firstRow + index}</td>
                  <td><Link to={`/farmers/${row.farmer}`}>{row.farmer_name}</Link></td>
                  <td>{row.membership_number || '—'}</td>
                  <td>{row.lead_farmer_name || row.cluster_name || '—'}</td>
                  <td>{row.crop}</td>
                  <td>{SEASON_LABEL[row.crop_season] || '—'}</td>
                  <td>{row.season_name}</td>
                  <td className="num">{hectares(row.contracted_hectares)}</td>
                  <td className="num">{hectares(row.irrigated_hectares)}</td>
                  <td><StatusPill status={row.status} /></td>
                  <td>
                    <span className="table-actions">
                      <button type="button" className="icon-btn" title="View record" aria-label={`View ${row.farmer_name} ${row.crop}`} onClick={() => setViewing(row)}><Icon name="eye" /></button>
                      {permissions.edit ? <button type="button" className="icon-btn" title="Edit record" aria-label={`Edit ${row.farmer_name} ${row.crop}`} onClick={() => setEditing(row)}><Icon name="pencil" /></button> : null}
                      {permissions.edit && NEXT[row.status] ? (
                        <button type="button" className="icon-btn" disabled={advancing === row.id} title={`Move to ${STATUS_LABEL[NEXT[row.status]]}`} aria-label={`Move ${row.farmer_name} ${row.crop} to ${STATUS_LABEL[NEXT[row.status]]}`} onClick={() => advance(row)}><Icon name="arrowRight" /></button>
                      ) : null}
                      {permissions.delete ? <button type="button" className="icon-btn danger" title="Delete record" aria-label={`Delete ${row.farmer_name} ${row.crop}`} onClick={() => setRemoving(row)}><Icon name="trash" /></button> : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : loading ? <div className="form-message">Loading production records…</div> : (
          <EmptyState icon="tractor" title="No production records">
            {appliedSearch || status ? 'Change the search or filters.' : 'Capture production to start tracking crops for this period.'}
            {permissions.create && !appliedSearch && !status ? <div className="form-actions" style={{ justifyContent: 'center' }}><button type="button" className="primary-btn" onClick={onCapture}><Icon name="plus" />Capture production</button></div> : null}
          </EmptyState>
        )}
        <div className="table-foot">
          <span>{count ? `Showing ${firstRow}–${firstRow + rows.length - 1} of ${count} records` : '0 records'}</span>
          {pages > 1 ? (
            <span className="table-actions">
              <button type="button" className="ghost-btn small" disabled={page <= 1 || loading} onClick={() => setPage((value) => value - 1)}>Previous</button>
              <span style={{ alignSelf: 'center' }}>Page {page} of {pages}</span>
              <button type="button" className="ghost-btn small" disabled={page >= pages || loading} onClick={() => setPage((value) => value + 1)}>Next</button>
            </span>
          ) : null}
        </div>
      </div>

      {viewing ? <RecordDetails row={viewing} onClose={() => setViewing(null)} onEdit={permissions.edit ? () => { setEditing(viewing); setViewing(null) } : null} /> : null}
      {editing ? <ProductionForm record={editing} onClose={() => setEditing(null)} onSaved={(saved) => { setEditing(null); changed(`${saved.farmer_name} · ${saved.crop} updated.`) }} /> : null}
      {removing ? (
        <Modal
          title="Delete production record"
          onClose={() => setRemoving(null)}
          footer={(
            <>
              <button type="button" className="ghost-btn" onClick={() => setRemoving(null)}>Cancel</button>
              <button
                type="button"
                className="danger-solid"
                onClick={async () => {
                  const row = removing
                  try {
                    await apiClient.delete(`/farmer-productions/${row.id}/`)
                    setRemoving(null)
                    changed(`${row.farmer_name} · ${row.crop} deleted.`)
                  } catch (requestError) {
                    setRemoving(null)
                    setError(errorMessage(requestError, 'The record could not be deleted.'))
                  }
                }}
              >
                <Icon name="trash" />Delete record
              </button>
            </>
          )}
        >
          <p>Delete {removing.crop} for {removing.farmer_name} ({removing.season_name}, {hectares(removing.contracted_hectares)} ha)? This cannot be undone.</p>
        </Modal>
      ) : null}
    </section>
  )
}

function RecordDetails({ row, onClose, onEdit }) {
  const items = [
    ['Farmer', row.farmer_name], ['Farmer ID', row.membership_number || '—'], ['Cluster', row.cluster_name || '—'],
    ['Lead farmer', row.lead_farmer_name || '—'], ['Province / district', [row.province_name, row.district_name].filter(Boolean).join(' · ') || '—'],
    ['Farm', row.farm_name || '—'], ['Crop', row.crop], ['Season', SEASON_LABEL[row.crop_season] || '—'], ['Agri year', row.season_name],
    ['Registered', `${hectares(row.contracted_hectares)} ha`], ['Planted', `${hectares(row.planted_hectares)} ha`], ['Irrigated', `${hectares(row.irrigated_hectares)} ha`],
    ['Planting date', row.planting_date || '—'], ['Crop stage', row.crop_stage || '—'], ['Expected yield', `${tonnes(row.expected_yield)} t/ha`],
    ['Estimated production', `${tonnes(row.estimated_production)} t`], ['Actual production', `${tonnes(row.actual_production)} t`], ['Harvest date', row.harvest_date || '—'],
  ]
  return (
    <Modal
      title={`${row.crop} · ${row.farmer_name}`}
      subtitle={<StatusPill status={row.status} />}
      wide
      onClose={onClose}
      footer={(
        <>
          <button type="button" className="ghost-btn" onClick={onClose}>Close</button>
          {onEdit ? <button type="button" className="primary-btn" onClick={onEdit}><Icon name="pencil" />Edit record</button> : null}
        </>
      )}
    >
      <dl className="detail-grid">
        {items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </Modal>
  )
}

export function ProductionForm({ record = null, defaults = {}, onClose, onSaved }) {
  const start = useMemo(() => (record ? {
    farmer: String(record.farmer || ''), farm: String(record.farm || ''), season: String(record.season || ''), crop: record.crop || '',
    contracted_hectares: record.contracted_hectares ?? '', planted_hectares: record.planted_hectares ?? '0', planting_date: record.planting_date || '',
    expected_yield: record.expected_yield ?? '0', estimated_production: record.estimated_production ?? '0', actual_production: record.actual_production ?? '0',
    harvest_date: record.harvest_date || '', crop_stage: record.crop_stage || '', status: record.status || 'PENDING',
  } : { ...EMPTY, ...defaults }), [record, defaults])
  const [form, setForm] = useState(start)
  const [farms, setFarms] = useState([])
  const [seasons, setSeasons] = useState([])
  const [crops, setCrops] = useState([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const draft = useFormDraft({ key: `production:${record?.id || 'new'}`, value: form, onRestore: (data) => setForm((current) => ({ ...current, ...data })) })

  useEffect(() => {
    let active = true
    Promise.all([apiClient.get('/seasons/', { params: { page_size: 100 } }), apiClient.get('/crops/', { params: { page_size: 200 } })])
      .then(([seasonResponse, cropResponse]) => {
        if (!active) return
        setSeasons(listOf(seasonResponse.data))
        setCrops(listOf(cropResponse.data).filter((crop) => crop.active !== false))
      })
      .catch(() => { if (active) setError('Seasons and crops could not be loaded.') })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!form.farmer) return undefined
    let active = true
    apiClient.get('/farms/', { params: { farmer: form.farmer, page_size: 100 } })
      .then((response) => {
        if (!active) return
        const list = listOf(response.data)
        setFarms(list)
        if (list.length === 1) setForm((current) => (current.farm ? current : { ...current, farm: String(list[0].id) }))
      })
      .catch(() => { if (active) setFarms([]) })
    return () => { active = false }
  }, [form.farmer])

  const set = (name, value) => setForm((current) => ({ ...current, [name]: value }))
  const field = (name, label, props = {}) => (
    <label className="form-field">
      {label}
      <input name={name} value={form[name] ?? ''} onChange={(event) => set(name, event.target.value)} {...props} />
    </label>
  )
  const selectedFarm = farms.find((farm) => String(farm.id) === String(form.farm))

  const save = async (event) => {
    event.preventDefault()
    if (!form.farmer) {
      setError('Choose a farmer from the suggestions.')
      return
    }
    setSaving(true)
    setError('')
    const payload = Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value === '' && ['planting_date', 'harvest_date', 'farm'].includes(key) ? null : value]))
    try {
      const response = record
        ? await apiClient.patch(`/farmer-productions/${record.id}/`, payload)
        : await apiClient.post('/farmer-productions/', payload)
      draft.clear()
      onSaved(response.data)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The production record could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={record ? `Edit ${record.crop} · ${record.farmer_name}` : 'Capture production'}
      subtitle="Registered hectares cannot pass the farm's arable land. Planted hectares cannot pass the registered hectares."
      wide
      onClose={onClose}
      footer={(
        <>
          <DraftStatus draft={draft} />
          <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
          <button type="submit" form="production-form" className="primary-btn" disabled={saving}>{saving ? 'Saving…' : record ? 'Save changes' : 'Capture production'}</button>
        </>
      )}
    >
      <form id="production-form" onSubmit={save}>
        <DraftNotice draft={draft} />
        {error ? <div className="form-message error" role="alert">{error}</div> : null}
        <h4>Farmer and crop</h4>
        <div className="workflow-fields">
          <FarmerAutocomplete label="Farmer" value={form.farmer} required onChange={(farmer) => setForm((current) => ({ ...current, farmer: farmer ? String(farmer.id) : '', farm: '' }))} />
          <label className="form-field">
            Farm
            <select value={form.farm} onChange={(event) => set('farm', event.target.value)} disabled={!form.farmer}>
              <option value="">{form.farmer ? 'Choose a farm' : 'Choose a farmer first'}</option>
              {farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.farm_name} · {hectares(farm.arable_hectares)} ha arable</option>)}
            </select>
          </label>
          <label className="form-field">
            Agri year
            <select required value={form.season} onChange={(event) => set('season', event.target.value)}>
              <option value="">Choose the agri year</option>
              {seasons.map((season) => <option key={season.id} value={season.id}>{season.name}</option>)}
            </select>
          </label>
          <label className="form-field">
            Crop
            <select required value={form.crop} onChange={(event) => set('crop', event.target.value)}>
              <option value="">Choose a crop</option>
              {crops.map((crop) => <option key={crop.id} value={crop.name}>{crop.name}{crop.category ? ` · ${SEASON_LABEL[crop.category] || crop.category}` : ''}</option>)}
              {form.crop && !crops.some((crop) => crop.name === form.crop) ? <option value={form.crop}>{form.crop}</option> : null}
            </select>
          </label>
        </div>
        <h4>Hectares and stage</h4>
        <div className="workflow-fields">
          {field('contracted_hectares', 'Registered hectares', { type: 'number', min: '0.01', step: '0.01', required: true, max: selectedFarm?.arable_hectares || undefined })}
          {field('planted_hectares', 'Planted hectares', { type: 'number', min: '0', step: '0.01', max: form.contracted_hectares || undefined })}
          {field('planting_date', 'Planting date', { type: 'date' })}
          {field('crop_stage', 'Crop stage', { maxLength: 80, placeholder: 'For example vegetative' })}
          <label className="form-field">
            Status
            <select value={form.status} onChange={(event) => set('status', event.target.value)}>
              {STATUSES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
            </select>
          </label>
        </div>
        <h4>Yield and production</h4>
        <div className="workflow-fields">
          {field('expected_yield', 'Expected yield (t/ha)', { type: 'number', min: '0', step: '0.01' })}
          {field('estimated_production', 'Estimated production (t)', { type: 'number', min: '0', step: '0.01' })}
          {field('actual_production', 'Actual production (t)', { type: 'number', min: '0', step: '0.01' })}
          {field('harvest_date', 'Harvest date', { type: 'date' })}
        </div>
      </form>
    </Modal>
  )
}
