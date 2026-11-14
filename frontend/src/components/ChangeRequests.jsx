// Change requests.
//
// A lead farmer whose record is held by administration does not edit it directly.
// They send the changes they want; an administrator approves or rejects them, and only
// an approved request changes the record.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import { useFormDraft } from '../drafts'
import Icon from './Icon'
import { DraftNotice, DraftStatus, EmptyState, Modal, Pill, errorMessage } from './ui'

const GENDERS = [['', 'Not recorded'], ['MALE', 'Male'], ['FEMALE', 'Female'], ['OTHER', 'Other']]
const IRRIGATION = [
  ['NONE', 'Not recorded'], ['RAINFED', 'Rainfed'], ['CENTRE_PIVOT', 'Centre pivot'], ['DRIP', 'Drip'],
  ['SPRINKLER', 'Sprinkler'], ['FLOOD', 'Flood'], ['OTHER', 'Other'],
]
const CHOICE_LABELS = { gender: Object.fromEntries(GENDERS), irrigation_type: Object.fromEntries(IRRIGATION) }
const STATUS_TONE = { PENDING: 'warn', APPROVED: 'good', REJECTED: 'bad' }

const shown = (field, value) => {
  if (value === '' || value === null || value === undefined) return '—'
  return CHOICE_LABELS[field]?.[value] || value
}

const asNumber = (value) => (value === '' || value === null || value === undefined ? '' : String(Number(value)))

// Compare the way the server does, so "5" and "5.00" count as the same size.
function sameValue(field, left, right) {
  if (['total_hectares', 'arable_hectares', 'irrigated_hectares', 'latitude', 'longitude', 'ward_number'].includes(field)) {
    return asNumber(left) === asNumber(right)
  }
  const clean = (value) => String(value ?? '').trim().toUpperCase().replace(/\s+/g, ' ')
  return clean(left) === clean(right)
}

export function ChangeRows({ rows }) {
  return (
    <div className="table-wrap">
      <table className="data-table compact">
        <thead><tr><th>Detail</th><th>Now</th><th>Requested</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.field}>
              <td>{row.label}</td>
              <td>{shown(row.field, row.old)}</td>
              <td><strong>{shown(row.field, row.new)}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// On a farmer's page, for the lead farmer.
export function LeadChangeRequests({ farmerId, onChanged }) {
  const [requests, setRequests] = useState([])
  const [current, setCurrent] = useState(null)
  const [open, setOpen] = useState(false)
  const [notice, setNotice] = useState('')

  const load = useCallback(() => Promise.all([
    apiClient.get(`/farmers/${farmerId}/change-requests/`),
    apiClient.get(`/farmers/${farmerId}/change-requests/current/`),
  ]).then(([list, values]) => {
    setRequests(Array.isArray(list.data) ? list.data : [])
    setCurrent(values.data)
  }).catch(() => setRequests([])), [farmerId])

  useEffect(() => { load() }, [load])

  const pending = requests.find((request) => request.status === 'PENDING')
  const latest = requests[0]

  return (
    <section className="card change-requests">
      <div className="card-head">
        <h3>Changes to this record</h3>
        <button type="button" className="primary-btn small" disabled={!current} onClick={() => { setNotice(''); setOpen(true) }}>
          <Icon name="pencil" />{pending ? 'Update my request' : 'Request changes'}
        </button>
      </div>
      <p className="card-sub">This registration is complete. To correct a detail, send a change request. An administrator approves it before the record changes.</p>
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {pending ? (
        <>
          <p><Pill tone="warn">Waiting for approval</Pill> Sent {new Date(pending.created_at).toLocaleString()}</p>
          <ChangeRows rows={pending.rows} />
          {pending.note ? <p className="card-sub">Your note: {pending.note}</p> : null}
        </>
      ) : null}
      {!pending && latest?.status === 'REJECTED' ? (
        <div className="form-message warning" role="status"><strong>Your last request was rejected:</strong> {latest.remarks}</div>
      ) : null}
      {!pending && latest?.status === 'APPROVED' ? (
        <div className="form-message success" role="status">Your last request was approved by {latest.reviewed_by_name || 'an administrator'}.</div>
      ) : null}
      {open && current ? (
        <ChangeRequestForm
          farmerId={farmerId}
          values={current.values}
          pending={pending}
          onClose={() => setOpen(false)}
          onSent={() => {
            setOpen(false)
            setNotice('Your change request was sent for approval.')
            load()
            onChanged?.()
          }}
        />
      ) : null}
    </section>
  )
}

function ChangeRequestForm({ farmerId, values, pending, onClose, onSent }) {
  // Start from the record, with any change already waiting for approval on top.
  const start = useMemo(() => {
    const form = { ...values, note: pending?.note || '' }
    for (const row of pending?.rows || []) form[row.field] = row.new
    return form
  }, [values, pending])
  const [form, setForm] = useState(start)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const draft = useFormDraft({ key: `farmer:${farmerId}:changes`, value: form, onRestore: (data) => setForm((existing) => ({ ...existing, ...data })) })

  const changed = Object.keys(values).filter((field) => !sameValue(field, values[field], form[field]))
  const set = (event) => setForm((existing) => ({ ...existing, [event.target.name]: event.target.value }))

  const send = async (event) => {
    event.preventDefault()
    if (!changed.length) {
      setError('Nothing has changed. Edit at least one detail.')
      return
    }
    setSaving(true)
    setError('')
    const payload = { note: form.note || '' }
    for (const field of changed) {
      const value = form[field]
      payload[field] = ['latitude', 'longitude'].includes(field) && String(value).trim() === '' ? null : value
    }
    try {
      await apiClient.post(`/farmers/${farmerId}/change-requests/`, payload)
      draft.clear()
      onSent()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The change request could not be sent.'))
    } finally {
      setSaving(false)
    }
  }

  const field = (name, label, props = {}) => (
    <label className={changed.includes(name) ? 'form-field changed' : 'form-field'}>
      {label}
      <input name={name} value={form[name] ?? ''} onChange={set} {...props} />
    </label>
  )

  return (
    <Modal
      title="Request changes"
      subtitle="Change only what is wrong. Changed details are highlighted. An administrator approves the request before the record changes."
      wide
      onClose={onClose}
      footer={(
        <>
          <DraftStatus draft={draft} />
          <button type="button" className="ghost-btn" onClick={onClose}>Close</button>
          <button type="submit" form="change-request-form" className="primary-btn" disabled={saving}>{saving ? 'Sending…' : `Send for approval${changed.length ? ` (${changed.length})` : ''}`}</button>
        </>
      )}
    >
      <form id="change-request-form" onSubmit={send}>
        <DraftNotice draft={draft} />
        {error ? <div className="form-message error" role="alert">{error}</div> : null}
        <h4>Personal details</h4>
        <div className="workflow-fields">
          {field('first_name', 'First name', { required: true, maxLength: 100 })}
          {field('middle_name', 'Middle name', { maxLength: 100 })}
          {field('surname', 'Surname', { required: true, maxLength: 120 })}
          {field('phone_primary', 'Phone', { inputMode: 'numeric', pattern: '\\d{9,12}', title: 'Enter 9 to 12 digits' })}
          {field('email', 'Email', { type: 'email' })}
          <label className={changed.includes('gender') ? 'form-field changed' : 'form-field'}>
            Gender
            <select name="gender" value={form.gender ?? ''} onChange={set}>
              {GENDERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          {field('ward_number', 'Ward number', { type: 'number', min: 1, max: 999, step: 1 })}
        </div>
        <h4>Farm</h4>
        <div className="workflow-fields">
          {field('farm_name', 'Farm name', { required: true, maxLength: 180 })}
          {field('total_hectares', 'Total farm size (ha)', { type: 'number', min: '0.01', step: '0.01' })}
          {field('arable_hectares', 'Arable land (ha)', { type: 'number', min: '0', step: '0.01' })}
          {field('irrigated_hectares', 'Irrigated land (ha)', { type: 'number', min: '0', step: '0.01' })}
          <label className={changed.includes('irrigation_type') ? 'form-field changed' : 'form-field'}>
            Irrigation type
            <select name="irrigation_type" value={form.irrigation_type || 'NONE'} onChange={set}>
              {IRRIGATION.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          {field('latitude', 'Latitude', { type: 'number', min: -90, max: 90, step: 'any' })}
          {field('longitude', 'Longitude', { type: 'number', min: -180, max: 180, step: 'any' })}
        </div>
        <label className="form-field">
          Note for the administrator (optional)
          <textarea name="note" rows="2" maxLength="500" value={form.note ?? ''} onChange={set} placeholder="Why these details change, for example a new phone number." />
        </label>
      </form>
    </Modal>
  )
}

// On the approvals page, for administration.
export function ChangeRequestQueue({ canDecide, onCountChange }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [rejecting, setRejecting] = useState(null)
  const [busy, setBusy] = useState(null)

  const load = useCallback(() => apiClient.get('/farmer-change-requests/', { params: { status: 'PENDING' } })
      .then((response) => {
        const list = Array.isArray(response.data) ? response.data : response.data?.results || []
        setRows(list)
        onCountChange?.(list.length)
        setError('')
      })
      .catch(() => setError('Unable to load change requests.'))
      .finally(() => setLoading(false)), [onCountChange])

  useEffect(() => { load() }, [load])

  const approve = async (change) => {
    setBusy(change.id)
    setNotice('')
    try {
      await apiClient.post(`/farmer-change-requests/${change.id}/approve/`)
      setNotice(`Changes for ${change.farmer_name} approved. The record is updated.`)
      await load()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The change could not be approved.'))
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="form-message">Loading change requests...</div>
  return (
    <>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {rows.length ? rows.map((change) => (
        <article key={change.id} className="card change-request-card">
          <div className="card-head">
            <div>
              <h3><Link to={`/farmers/${change.farmer}`}>{change.farmer_name}</Link></h3>
              <p className="card-sub">
                {[change.membership_number, change.cluster_name].filter(Boolean).join(' · ')}
                {' · '}Requested by {change.requested_by_name || 'lead farmer'} on {new Date(change.created_at).toLocaleString()}
              </p>
            </div>
            <Pill tone={STATUS_TONE[change.status]}>{change.status_label}</Pill>
          </div>
          <ChangeRows rows={change.rows} />
          {change.note ? <p className="card-sub">Note: {change.note}</p> : null}
          {canDecide ? (
            <div className="workflow-form-actions">
              <button type="button" className="primary-btn small" disabled={busy === change.id} onClick={() => approve(change)}><Icon name="check" />Approve changes</button>
              <button type="button" className="ghost-btn small" disabled={busy === change.id} onClick={() => setRejecting(change)}>Reject</button>
            </div>
          ) : null}
        </article>
      )) : <EmptyState icon="check" title="No change requests">Lead farmers' requests to change approved records appear here.</EmptyState>}
      {rejecting ? (
        <RejectChange
          change={rejecting}
          onClose={() => setRejecting(null)}
          onDone={() => {
            setNotice(`Changes for ${rejecting.farmer_name} rejected. The lead farmer sees your reason.`)
            setRejecting(null)
            load()
          }}
        />
      ) : null}
    </>
  )
}

function RejectChange({ change, onClose, onDone }) {
  const [remarks, setRemarks] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const draft = useFormDraft({ key: `change-request:${change.id}:reject`, value: { remarks }, onRestore: (data) => setRemarks(data.remarks || '') })

  const submit = async (event) => {
    event.preventDefault()
    if (!remarks.trim()) {
      setError('Say why the change is rejected.')
      return
    }
    setSaving(true)
    try {
      await apiClient.post(`/farmer-change-requests/${change.id}/reject/`, { remarks })
      draft.clear()
      onDone()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The change could not be rejected.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`Reject changes for ${change.farmer_name}`}
      onClose={onClose}
      footer={(
        <>
          <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
          <button type="submit" form="reject-change-form" className="danger-solid" disabled={saving}>{saving ? 'Rejecting…' : 'Reject changes'}</button>
        </>
      )}
    >
      <form id="reject-change-form" onSubmit={submit}>
        <DraftNotice draft={draft} />
        {error ? <div className="form-message error" role="alert">{error}</div> : null}
        <label className="form-field">
          Reason (the lead farmer sees this)
          <textarea rows="3" value={remarks} onChange={(event) => setRemarks(event.target.value)} required />
        </label>
      </form>
    </Modal>
  )
}
