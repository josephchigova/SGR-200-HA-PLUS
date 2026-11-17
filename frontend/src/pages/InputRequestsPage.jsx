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
import { CATEGORY_LABEL, REQUEST_STATUS, hectares, loadAll } from '../programmeData'

const EMPTY = { programme: '', crop: '', input_category: '', requested_hectares: '', notes: '' }

function InputRequestsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { can } = useAuth()
  const canCreate = can('arda', 'create')
  const canApprove = can('arda', 'approve')
  const canDelete = can('arda', 'delete')
  const [rows, setRows] = useState([])
  const [programmes, setProgrammes] = useState([])
  const [filters, setFilters] = useState({ programme: '', status: '' })
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState(null)
  const [deciding, setDeciding] = useState(null)
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
    approved: sum.approved + Number(row.approved_hectares || 0),
    allocated: sum.allocated + Number(row.allocated_hectares || 0),
    remaining: sum.remaining + Number(row.remaining_hectares || 0),
  }), { requested: 0, approved: 0, allocated: 0, remaining: 0 }), [rows])

  const act = async (row, path, body, message) => {
    setError('')
    try {
      await apiClient.post(`/arda-request-batches/${row.id}/${path}/`, body || {})
      setNotice(message)
      reload()
      return true
    } catch (requestError) {
      setError(errorMessage(requestError, 'The request could not be updated.'))
      return false
    }
  }

  const remove = async (row) => {
    if (!window.confirm(`Delete draft request ${row.request_number}?`)) return
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
      <PageHead title="Input requests" subtitle="Hectares requested from a programme for one crop and agricultural year. Only approved hectares can be allocated to farmers; remaining hectares are approved capacity not yet allocated, not stock." />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {readOnlyYear ? <div className="form-message">{selectedSeason.name} is not the active agricultural year, so its requests are read-only.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      {canCreate && !blocked && !readOnlyYear ? (
        <RequestForm key={`new-${selectedSeason.id}`} season={selectedSeason} programmes={programmes} onSaved={(row) => { setNotice(`${row.request_number} saved as a draft. Submit it for approval when it is ready.`); reload() }} />
      ) : null}

      <section className="card">
        <div className="card-head">
          <div>
            <h3>Requests for {selectedSeason?.name || 'the agricultural year'}</h3>
            <div className="hectare-strip" aria-label="Hectare totals">
              <span><small>Requested</small><strong>{hectares(totals.requested)}</strong></span>
              <span><small>Approved</small><strong>{hectares(totals.approved)}</strong></span>
              <span><small>Allocated to farmers</small><strong>{hectares(totals.allocated)}</strong></span>
              <span><small>Remaining approved</small><strong>{hectares(totals.remaining)}</strong></span>
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
          <label className="form-field">Status
            <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
              <option value="">All statuses</option>
              {Object.entries(REQUEST_STATUS).map(([code, [label]]) => <option key={code} value={code}>{label}</option>)}
            </select>
          </label>
        </div>
        {loading ? <div className="form-message">Loading requests…</div> : null}
        {!loading && !blocked && !rows.length ? <EmptyState icon="send" title="No input requests">Requests for {selectedSeason?.name} appear here.</EmptyState> : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Request</th><th>Programme</th><th>Crop</th><th>Agricultural year</th><th>Season</th><th>Input type</th><th className="num">Requested</th><th className="num">Approved</th><th className="num">Allocated</th><th className="num">Remaining</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.map((row) => {
                  const [label, tone] = REQUEST_STATUS[row.status] || [row.status_label, '']
                  const editable = !readOnlyYear && row.status === 'PENDING'
                  return (
                    <tr key={row.id} className={row.status === 'REJECTED' ? 'inactive-row' : ''}>
                      <td><strong>{row.request_number}</strong>{row.decision_notes ? <small className="block-hint">{row.decision_notes}</small> : null}</td>
                      <td>{row.programme_name}{row.programme_active === false ? <small className="block-hint">Inactive programme</small> : null}</td>
                      <td>{row.crop || '—'}</td>
                      <td>{row.season_name}</td>
                      <td>{row.crop_season || '—'}</td>
                      <td>{row.input_category ? CATEGORY_LABEL[row.input_category] : 'All of the programme’s'}</td>
                      <td className="num">{hectares(row.requested_hectares)}</td>
                      <td className="num">{row.status === 'APPROVED' ? hectares(row.approved_hectares) : '—'}</td>
                      <td className="num">{hectares(row.allocated_hectares)}</td>
                      <td className="num"><strong>{row.status === 'APPROVED' ? hectares(row.remaining_hectares) : '—'}</strong></td>
                      <td><Pill tone={tone}>{label}</Pill>{row.approved_by_name ? <small className="block-hint">by {row.approved_by_name}</small> : null}</td>
                      <td>
                        <span className="table-actions">
                          {editable && canCreate ? <button type="button" className="icon-btn" title="Edit draft" aria-label={`Edit ${row.request_number}`} onClick={() => setEditing(row)}><Icon name="pencil" /></button> : null}
                          {editable && canCreate ? <button type="button" className="ghost-btn small" onClick={() => act(row, 'submit', null, `${row.request_number} submitted for approval.`)}>Submit</button> : null}
                          {!readOnlyYear && canApprove && row.status === 'SUBMITTED' ? <button type="button" className="primary-btn small" onClick={() => setDeciding(row)}>Approve or reject</button> : null}
                          {editable && canDelete ? <button type="button" className="icon-btn danger" title="Delete draft" aria-label={`Delete ${row.request_number}`} onClick={() => remove(row)}><Icon name="trash" /></button> : null}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
      {!blocked ? <EligibleFarmers season={selectedSeason} /> : null}
      {editing ? (
        <Modal wide title={`Edit draft ${editing.request_number}`} onClose={() => setEditing(null)}>
          <RequestForm request={editing} season={selectedSeason} programmes={programmes} onCancel={() => setEditing(null)} onSaved={(row) => { setEditing(null); setNotice(`${row.request_number} updated.`); reload() }} />
        </Modal>
      ) : null}
      {deciding ? (
        <Decision
          request={deciding}
          onClose={() => setDeciding(null)}
          onApprove={async (hectaresApproved, notes) => {
            if (await act(deciding, 'approve', { approved_hectares: hectaresApproved, notes }, `${deciding.request_number} approved for ${hectares(hectaresApproved)}. Those hectares can now be allocated to farmers.`)) setDeciding(null)
          }}
          onReject={async (notes) => {
            if (await act(deciding, 'reject', { notes }, `${deciding.request_number} rejected.`)) setDeciding(null)
          }}
        />
      ) : null}
    </div>
  )
}

function RequestForm({ request = null, season, programmes, onSaved, onCancel }) {
  const initial = request
    ? { programme: String(request.programme), crop: request.crop || '', input_category: request.input_category || '', requested_hectares: request.requested_hectares, notes: request.notes || '' }
    : EMPTY
  const [form, setForm] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})
  const draft = useFormDraft({ key: `input-request:${season.id}:${request?.id || 'new'}`, value: form, enabled: !request, onRestore: (data) => setForm((current) => ({ ...current, ...data })) })
  const open = programmes.filter((programme) => programme.capacity_status === 'ACTIVE' || String(programme.id) === String(form.programme))
  const programme = programmes.find((item) => String(item.id) === String(form.programme))

  const submit = async (event) => {
    event.preventDefault()
    setSaving(true)
    setErrors({})
    const payload = { ...form, programme: Number(form.programme), season: season.id }
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
          <select required value={form.programme} onChange={(event) => setForm({ ...form, programme: event.target.value, crop: '', input_category: '' })}>
            <option value="">{open.length ? 'Choose an active programme' : `No active programme for ${season.name}`}</option>
            {open.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          {errors.programme ? <span className="field-error">{errors.programme}</span> : null}
        </label>
        <label className="form-field">Crop
          <select required value={form.crop} disabled={!programme} onChange={(event) => setForm({ ...form, crop: event.target.value })}>
            <option value="">{programme ? 'Choose one of the programme’s crops' : 'Choose the programme first'}</option>
            {(programme?.crop_names || []).map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          {errors.crop ? <span className="field-error">{errors.crop}</span> : null}
        </label>
        <label className="form-field">Input type
          <select value={form.input_category} disabled={!programme} onChange={(event) => setForm({ ...form, input_category: event.target.value })}>
            <option value="">All of the programme’s input types</option>
            {(programme?.input_categories || []).map((code) => <option key={code} value={code}>{CATEGORY_LABEL[code]} only</option>)}
          </select>
          {errors.input_category ? <span className="field-error">{errors.input_category}</span> : null}
        </label>
        <label className="form-field">Requested hectares
          <input required type="number" min="0.01" step="0.01" value={form.requested_hectares} onChange={(event) => setForm({ ...form, requested_hectares: event.target.value })} />
          {errors.requested_hectares ? <span className="field-error">{errors.requested_hectares}</span> : null}
        </label>
        <label className="form-field">Agricultural year<input value={season.name} readOnly title="Change the agricultural year in the header" /></label>
        <label className="form-field">Notes<input value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} placeholder="Optional" /></label>
      </div>
      <div className="workflow-form-actions">
        <button type="submit" className="primary-btn small" disabled={saving}>{saving ? 'Saving…' : request ? 'Save draft' : 'Save as draft'}</button>
        {onCancel ? <button type="button" className="ghost-btn" onClick={onCancel}>Cancel</button> : null}
      </div>
    </form>
  )
}

function Decision({ request, onClose, onApprove, onReject }) {
  const [approved, setApproved] = useState(String(Number(request.requested_hectares)))
  const [notes, setNotes] = useState('')
  return (
    <Modal title={`Decide on ${request.request_number}`} subtitle={`${request.programme_name} · ${request.crop} · ${request.season_name}. ${hectares(request.requested_hectares)} requested. Approve all of it or part of it.`} onClose={onClose}
      footer={<>
        <button type="button" className="ghost-btn" onClick={onClose}>Close</button>
        <button type="button" className="danger-solid" disabled={!notes.trim()} title={notes.trim() ? '' : 'Give the reason in the notes'} onClick={() => onReject(notes)}>Reject</button>
        <button type="button" className="primary-btn" disabled={!(Number(approved) > 0)} onClick={() => onApprove(approved, notes)}>Approve {approved ? hectares(approved) : ''}</button>
      </>}>
      <label className="form-field">Approved hectares
        <input type="number" min="0.01" max={request.requested_hectares} step="0.01" value={approved} onChange={(event) => setApproved(event.target.value)} />
        <span className="field-hint">At most the {hectares(request.requested_hectares)} requested. Only approved hectares can be allocated to farmers.</span>
      </label>
      <label className="form-field">Notes<textarea rows="3" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Required when rejecting" /></label>
    </Modal>
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
