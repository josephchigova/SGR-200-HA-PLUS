// Input requests: hectares requested from a programme for one crop and agricultural year.
//
// A request starts as a draft, is submitted, and is then approved (in full or in part) or
// rejected. Only approved hectares can be allocated to farmers. A request is not stock: its
// remaining hectares are the approved programme capacity not yet given to farmers.

import { useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import { DraftNotice, EmptyState, Modal, PageHead, Pill, errorMessage } from '../components/ui'
import { useFormDraft } from '../drafts'
import { CATEGORIES } from '../inputCategories'
import { CATEGORY_LABEL, hectares, loadAll, money, qty, requestTotal } from '../programmeData'

const EMPTY = { programme: '', crop: '', input_category: '', notes: '', lines: {} }
const CATEGORY_ORDER = Object.fromEntries(CATEGORIES.map(([code], index) => [code, index]))
// Seed first, then fertilizer, then chemicals, as on the catalogue.
const ordered = (lines = []) => [...lines].sort((a, b) => (CATEGORY_ORDER[a.input_category] ?? 9) - (CATEGORY_ORDER[b.input_category] ?? 9) || a.product_name.localeCompare(b.product_name))

function InputRequestsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { can } = useAuth()
  const canCreate = can('arda', 'create')
  const canEdit = can('arda', 'edit')
  const canDelete = can('arda', 'delete')
  const [rows, setRows] = useState([])
  const [programmes, setProgrammes] = useState([])
  const [filters, setFilters] = useState({ programme: '' })
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const readOnlyYear = Boolean(selectedSeason?.status && selectedSeason.status !== 'ACTIVE')
  const requestKey = JSON.stringify([selectedSeason?.id, cropSeason, filters, token])

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    loadAll('/programmes/', { season: selectedSeason.id })
      .then((list) => { if (active) setProgrammes(list) })
      .catch(() => { if (active) setProgrammes([]) })
    return () => { active = false }
  }, [blocked, selectedSeason, token])

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id }
    if (cropSeason) params.crop_season = cropSeason
    Object.entries(filters).forEach(([key, value]) => { if (value) params[key] = value })
    loadAll('/arda-request-batches/', params)
      .then((list) => { if (active) { setRows(list); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Input requests could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, filters, requestKey])

  const loading = !blocked && loadedKey !== requestKey
  const reload = () => setToken((value) => value + 1)
  const totals = useMemo(() => rows.filter((row) => row.status !== 'REJECTED').reduce((sum, row) => ({
    requested: sum.requested + Number(row.requested_hectares || 0),
    allocated: sum.allocated + Number(row.allocated_hectares || 0),
    remaining: sum.remaining + Number(row.remaining_hectares || 0),
  }), { requested: 0, allocated: 0, remaining: 0 }), [rows])

  const remove = async () => {
    const row = deleting
    setDeleting(null)
    try {
      await apiClient.delete(`/arda-request-batches/${row.id}/`)
      setNotice(`${row.request_number} deleted.`)
      reload()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The request could not be deleted.'))
    }
  }

  return (
    <div className="page-card input-requests-page">
      <PageHead title="Input requests" subtitle="The hectares a programme has agreed to supply for one crop and agricultural year, split by the exact products and varieties in its catalogue. A request can be allocated to farmers as soon as it is made." />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {readOnlyYear ? <div className="form-message">{selectedSeason.name} is not the active agricultural year, so its requests are read-only.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      {canCreate && !blocked && !readOnlyYear ? (
        <RequestForm key={`new-${selectedSeason.id}`} season={selectedSeason} programmes={programmes} onSaved={(row) => { setNotice(`${row.request_number} created for ${hectares(row.requested_hectares)}. It can be allocated to farmers now.`); reload() }} />
      ) : null}

      <section className="card">
        <div className="card-head">
          <div>
            <h3>Requests for {selectedSeason?.name || 'the agricultural year'}</h3>
            <div className="hectare-strip" aria-label="Hectare totals">
              <span><small>Requested</small><strong>{hectares(totals.requested)}</strong></span>
              <span><small>Allocated to farmers</small><strong>{hectares(totals.allocated)}</strong></span>
              <span><small>Remaining</small><strong>{hectares(totals.remaining)}</strong></span>
            </div>
          </div>
        </div>
        <div className="filter-row">
          <label className="form-field">Programme
            <select value={filters.programme} onChange={(event) => setFilters({ ...filters, programme: event.target.value })}>
              <option value="">All programmes</option>
              {programmes.map((programme) => <option key={programme.id} value={programme.id}>{programme.name}</option>)}
            </select>
          </label>
        </div>
        {loading ? <div className="form-message">Loading requests…</div> : null}
        {!loading && !blocked && !rows.length ? <EmptyState icon="send" title="No input requests">Requests for {selectedSeason?.name} appear here.</EmptyState> : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Request</th><th>Programme</th><th>Crop</th><th>Agricultural year</th><th>Season</th><th>Input type</th><th className="num">Requested</th><th className="num">Allocated</th><th className="num">Remaining</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.map((row) => {
                  const rejected = row.status === 'REJECTED'
                  const changeable = !readOnlyYear && !rejected
                  return (
                    <RequestRows key={row.id} open={expanded === row.id} row={row}>
                      <tr className={rejected ? 'inactive-row' : ''}>
                        <td><strong>{row.request_number}</strong>{rejected ? <small className="block-hint">Rejected earlier{row.decision_notes ? `: ${row.decision_notes}` : ''}</small> : null}</td>
                        <td>{row.programme_name}{row.programme_active === false ? <small className="block-hint">Inactive programme</small> : null}</td>
                        <td>{row.crop || '—'}</td>
                        <td>{row.season_name}</td>
                        <td>{row.crop_season || '—'}</td>
                        <td>{row.input_category ? CATEGORY_LABEL[row.input_category] : 'All of the programme’s'}</td>
                        <td className="num">{hectares(row.requested_hectares)}</td>
                        <td className="num">{hectares(row.allocated_hectares)}</td>
                        <td className="num"><strong>{rejected ? '—' : hectares(row.remaining_hectares)}</strong></td>
                        <td>
                          <span className="table-actions">
                            <button type="button" className="icon-btn" title={expanded === row.id ? 'Hide products' : 'Show products'} aria-label={`${expanded === row.id ? 'Hide' : 'Show'} products in ${row.request_number}`} onClick={() => setExpanded(expanded === row.id ? null : row.id)}><Icon name="eye" /></button>
                            {changeable && canEdit ? <button type="button" className="icon-btn" title="Edit" aria-label={`Edit ${row.request_number}`} onClick={() => setEditing(row)}><Icon name="pencil" /></button> : null}
                            {changeable && canDelete ? <button type="button" className="icon-btn danger" title={Number(row.allocated_hectares) > 0 ? 'Cancel its allocations before deleting' : 'Delete'} aria-label={`Delete ${row.request_number}`} disabled={Number(row.allocated_hectares) > 0} onClick={() => setDeleting(row)}><Icon name="trash" /></button> : null}
                          </span>
                        </td>
                      </tr>
                    </RequestRows>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
      {!blocked ? <EligibleFarmers season={selectedSeason} /> : null}
      {editing ? (
        <Modal wide title={`Edit ${editing.request_number}`} subtitle="Products already given to farmers cannot go below what is allocated or be removed." onClose={() => setEditing(null)}>
          <RequestForm request={editing} season={selectedSeason} programmes={programmes} onCancel={() => setEditing(null)} onSaved={(row) => { setEditing(null); setNotice(`${row.request_number} updated.`); reload() }} />
        </Modal>
      ) : null}
      {deleting ? (
        <Modal title={`Delete ${deleting.request_number}?`} subtitle={`${deleting.programme_name} · ${deleting.crop} · ${hectares(deleting.requested_hectares)}. Its products go with it. Cancelled allocations made from it are kept.`} onClose={() => setDeleting(null)}
          footer={<><button type="button" className="ghost-btn" onClick={() => setDeleting(null)}>Keep it</button><button type="button" className="danger-solid" onClick={remove}>Delete</button></>}>
          <p>This cannot be undone.</p>
        </Modal>
      ) : null}
    </div>
  )
}

function RequestForm({ request = null, season, programmes, onSaved, onCancel }) {
  const initial = request
    ? {
        programme: String(request.programme), crop: request.crop || '', input_category: request.input_category || '', notes: request.notes || '',
        lines: Object.fromEntries((request.products || []).map((line) => [String(line.requirement), String(Number(line.requested_hectares))])),
      }
    : EMPTY
  const allocated = Object.fromEntries((request?.products || []).map((line) => [String(line.requirement), Number(line.allocated_hectares || 0)]))
  const used = Number(request?.allocated_hectares || 0) > 0
  const [form, setForm] = useState(initial)
  const [catalogue, setCatalogue] = useState({ key: '', rows: [] })
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})
  const draft = useFormDraft({ key: `input-request:${season.id}:${request?.id || 'new'}`, value: form, enabled: !request, onRestore: (data) => setForm((current) => ({ ...current, lines: {}, ...data })) })
  const open = programmes.filter((programme) => programme.capacity_status === 'ACTIVE' || String(programme.id) === String(form.programme))
  const programme = programmes.find((item) => String(item.id) === String(form.programme))
  const cropId = programme ? (programme.crops || [])[(programme.crop_names || []).indexOf(form.crop)] : null
  const catalogueKey = `${form.programme}:${cropId}`

  // The products and varieties come from the programme's own catalogue for this crop.
  useEffect(() => {
    if (!form.programme || !cropId) return undefined
    let active = true
    loadAll('/crop-input-requirements/', { programme: form.programme, crop: cropId })
      .then((rows) => { if (active) setCatalogue({ key: catalogueKey, rows: rows.filter((row) => row.active || form.lines[row.id]) }) })
      .catch(() => { if (active) setCatalogue({ key: catalogueKey, rows: [] }) })
    return () => { active = false }
    // The saved lines only matter for the first load of an edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.programme, cropId, catalogueKey])
  const products = catalogue.key === catalogueKey ? catalogue.rows.filter((row) => !form.input_category || row.input_category === form.input_category) : []
  const setLine = (requirement, value) => setForm((current) => ({ ...current, lines: { ...current.lines, [requirement]: value } }))
  const chosen = products.filter((row) => Number(form.lines[row.id]) > 0)
  const total = requestTotal(chosen.map((row) => ({ input_category: row.input_category, hectares: form.lines[row.id] })))
  const legacy = request && !(request.products || []).length

  const submit = async (event) => {
    event.preventDefault()
    if (!chosen.length && !legacy) {
      setErrors({ lines: 'Enter hectares for at least one product or variety.' })
      return
    }
    setSaving(true)
    setErrors({})
    const lines = chosen.map((row) => ({ requirement: row.id, requested_hectares: form.lines[row.id] }))
    const payload = { programme: Number(form.programme), season: season.id, crop: form.crop, input_category: form.input_category, notes: form.notes, lines }
    try {
      const response = request ? await apiClient.patch(`/arda-request-batches/${request.id}/`, payload) : await apiClient.post('/arda-request-batches/', payload)
      if (!request) {
        draft.clear(EMPTY)
        setForm(EMPTY)
      }
      onSaved(response.data)
    } catch (requestError) {
      const data = requestError.response?.data
      setErrors(data && typeof data === 'object' ? Object.fromEntries(Object.entries(data).map(([key, value]) => [key, [].concat(value).join(' ')])) : { non_field_errors: errorMessage(requestError, 'The request could not be saved.') })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className={request ? '' : 'card'} onSubmit={submit}>
      {request ? null : <div className="card-head"><h3><Icon name="plus" />New input request</h3></div>}
      {request ? null : <DraftNotice draft={draft} />}
      {errors.non_field_errors || errors.detail ? <div className="form-message error" role="alert">{errors.non_field_errors || errors.detail}</div> : null}
      <div className="workflow-fields">
        <label className="form-field">Programme
          <select required value={form.programme} disabled={used} onChange={(event) => setForm({ ...form, programme: event.target.value, crop: '', input_category: '', lines: {} })}>
            <option value="">{open.length ? 'Choose an active programme' : `No active programme for ${season.name}`}</option>
            {open.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          {errors.programme ? <span className="field-error">{errors.programme}</span> : null}
        </label>
        <label className="form-field">Crop
          <select required value={form.crop} disabled={!programme || used} onChange={(event) => setForm({ ...form, crop: event.target.value, lines: {} })}>
            <option value="">{programme ? 'Choose one of the programme’s crops' : 'Choose the programme first'}</option>
            {(programme?.crop_names || []).map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          {errors.crop ? <span className="field-error">{errors.crop}</span> : null}
        </label>
        <label className="form-field">Input type
          <select value={form.input_category} disabled={!programme || used} onChange={(event) => setForm({ ...form, input_category: event.target.value })}>
            <option value="">All of the programme’s input types</option>
            {(programme?.input_categories || []).map((code) => <option key={code} value={code}>{CATEGORY_LABEL[code]} only</option>)}
          </select>
          {errors.input_category ? <span className="field-error">{errors.input_category}</span> : null}
        </label>
        <label className="form-field">Total hectares
          <output className="computed-total" aria-label="Total hectares">{legacy && !chosen.length ? hectares(request.requested_hectares) : hectares(total)}</output>
          <span className="field-hint">Worked out from the products below.</span>
          {errors.requested_hectares ? <span className="field-error">{errors.requested_hectares}</span> : null}
        </label>
        <label className="form-field">Agricultural year<input value={season.name} readOnly title="Change the agricultural year in the header" /></label>
        <label className="form-field">Notes<input value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} placeholder="Optional" /></label>
      </div>
      {used ? <p className="field-hint">Farmers already have allocations from this request, so its programme, crop and input type stay as they are.</p> : null}
      {programme && form.crop ? (
        <fieldset className="request-products">
          <legend>Products and varieties from {programme.name}’s {form.crop} catalogue</legend>
          <p className="field-hint">Enter the hectares for each product. Leave a product empty to leave it out. Varieties of the same input type add up; different input types go on the same land.</p>
          {!products.length ? <div className="form-message">{catalogue.key === catalogueKey ? `${programme.name} has no ${form.input_category ? CATEGORY_LABEL[form.input_category].toLowerCase() : 'products'} in its ${form.crop} catalogue yet. Add them in the Crop Catalogue.` : 'Loading the catalogue…'}</div> : (
            <div className="table-wrap">
              <table className="data-table compact">
                <thead><tr><th>Input type</th><th>Product or variety</th><th className="num">Qty per ha</th><th className="num">Price</th><th className="num">Hectares</th></tr></thead>
                <tbody>
                  {CATEGORIES.flatMap(([code]) => products.filter((row) => row.input_category === code)).map((row) => (
                    <tr key={row.id}>
                      <td>{CATEGORY_LABEL[row.input_category]}</td>
                      <td>{row.input_product_name}{row.active ? '' : ' (switched off in catalogue)'}</td>
                      <td className="num">{qty(row.rate_per_hectare, 4)} {row.unit}</td>
                      <td className="num">{money(row.cost_per_unit)} / {row.unit}</td>
                      <td className="num">
                        <input aria-label={`Hectares for ${row.input_product_name}`} type="number" min={allocated[row.id] || 0} step="any" value={form.lines[row.id] || ''} onChange={(event) => setLine(row.id, event.target.value)} />
                        {allocated[row.id] ? <small className="block-hint">{hectares(allocated[row.id])} allocated</small> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {errors.lines ? <span className="field-error" role="alert">{errors.lines}</span> : null}
        </fieldset>
      ) : null}
      <div className="workflow-form-actions">
        <button type="submit" className="primary-btn small" disabled={saving}>{saving ? 'Saving…' : request ? 'Save changes' : 'Create request'}</button>
        {onCancel ? <button type="button" className="ghost-btn" onClick={onCancel}>Cancel</button> : null}
      </div>
    </form>
  )
}

function RequestRows({ row, open, children }) {
  return (
    <>
      {children}
      {open ? (
        <tr className="allocation-lines">
          <td colSpan="10">
            {(row.products || []).length ? (
              <table className="data-table compact">
                <thead><tr><th>Input type</th><th>Product or variety</th><th className="num">Qty per ha</th><th className="num">Price</th><th className="num">Hectares</th><th className="num">Allocated</th><th className="num">Remaining</th><th className="num">Farmers</th></tr></thead>
                <tbody>
                  {ordered(row.products).map((line) => (
                    <tr key={line.id}>
                      <td>{CATEGORY_LABEL[line.input_category]}</td>
                      <td>{line.product_name}{line.catalogue_active ? '' : ' (switched off in catalogue)'}</td>
                      <td className="num">{qty(line.rate_per_hectare, 4)} {line.unit}</td>
                      <td className="num">{line.unit_price === null ? '—' : `${money(line.unit_price)} / ${line.unit}`}</td>
                      <td className="num">{hectares(line.requested_hectares)}</td>
                      <td className="num">{hectares(line.allocated_hectares)}</td>
                      <td className="num"><strong>{row.status === 'APPROVED' ? hectares(line.remaining_hectares) : '—'}</strong></td>
                      <td className="num">{line.farmers}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="card-sub">This request does not name products. Allocations from it use every product in {row.programme_name}’s {row.crop} catalogue.</p>}
          </td>
        </tr>
      ) : null}
    </>
  )
}

function EligibleFarmers({ season }) {
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return undefined
    let active = true
    loadAll('/farmers/eligible/', { season: season.id, season_name: season.name })
      .then((list) => { if (active) setRows(list) })
      .catch(() => { if (active) setRows([]) })
    return () => { active = false }
  }, [open, season])
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>Subscription-eligible farmers</h3>
          <p className="card-sub">Verified, active farmers with a farm and a paid or part-paid subscription for {season.name}.</p>
        </div>
        <button type="button" className="ghost-btn small" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show'}</button>
      </div>
      {open && rows === null ? <div className="form-message">Loading farmers…</div> : null}
      {open && rows ? (
        rows.length ? (
          <div className="table-wrap">
            <table className="data-table compact">
              <thead><tr><th>Farmer</th><th>Membership</th><th>National ID</th><th>Phone</th><th>District</th><th>Subscription</th></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}><td>{row.full_name}</td><td>{row.membership_number}</td><td>{row.national_id}</td><td>{row.phone_primary || '—'}</td><td>{row.district_name || '—'}</td><td><Pill tone={row.subscription_status === 'PAID' ? 'good' : 'warn'}>{row.subscription_status}</Pill></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState icon="users" title="No eligible farmers">No farmer qualifies for {season.name} yet.</EmptyState>
      ) : null}
    </section>
  )
}

export default InputRequestsPage
