// Lead farmer input requests: one consolidated request per lead farmer, programme, agricultural
// year and season.
//
// A lead farmer adds their farmers, each with a crop, hectares and the products wanted from the
// programme's own input request. Quantities are worked out from the programme catalogue. The lead
// farmer submits the whole request once; Admin approves or rejects it as one, and approving it
// creates every farmer's input allocation.

import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import { EmptyState, Modal, PageHead, Pill, errorMessage } from '../components/ui'
import { CATEGORIES } from '../inputCategories'
import { hectares, loadAll, money, qty } from '../programmeData'

const STATUS = { DRAFT: ['Draft', ''], SUBMITTED: ['Submitted to Admin', 'info'], APPROVED: ['Approved', 'good'], REJECTED: ['Rejected', 'bad'] }
const SEASONS = { SUMMER: 'Summer', WINTER: 'Winter' }

function LeadRequestsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { can, profile } = useAuth()
  const isLead = profile?.role === 'lead_farmer'
  const canCreate = can('lead_requests', 'create')
  const canApprove = can('lead_requests', 'approve')
  const season = cropSeason || 'SUMMER'
  const [requests, setRequests] = useState([])
  const [summary, setSummary] = useState(null)
  const [selected, setSelected] = useState(null)
  const [token, setToken] = useState(0)
  const [loadedKey, setLoadedKey] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const requestKey = JSON.stringify([selectedSeason?.id, season, token])

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id, crop_season: season }
    Promise.all([loadAll('/lead-requests/', params), apiClient.get('/lead-requests/summary/', { params })])
      .then(([list, totals]) => { if (active) { setRequests(list); setSummary(totals.data); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Lead farmer requests could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, season, requestKey])

  const loading = !blocked && loadedKey !== requestKey
  const reload = () => setToken((value) => value + 1)
  const showMoney = !isLead

  return (
    <div className="page-card lead-requests-page">
      <PageHead
        title="Lead farmer requests"
        subtitle={isLead
          ? 'One request per programme for each agricultural year and season. Add your farmers, their crops, hectares and products; the quantities are worked out for you. Submit it to Admin when it is complete.'
          : 'Each lead farmer sends one consolidated request per programme, agricultural year and season. Approving it creates every farmer’s input allocation from the programme’s input request.'}
      />
      {blocked ? <div className="form-message">Choose an agricultural year and season in the header.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      {canCreate && !blocked ? (
        <StartRequest season={selectedSeason} cropSeason={season} isLead={isLead} onCreated={(row) => { setNotice(`Request started for ${row.programme_name}, ${row.season_name} ${row.crop_season_label}. Add your farmers below.`); setSelected(row.id); reload() }} />
      ) : null}

      {!blocked && !isLead && summary ? <Consolidated summary={summary} season={selectedSeason} cropSeason={season} showMoney={showMoney} /> : null}

      <section className="card">
        <div className="card-head">
          <div>
            <h3>{isLead ? 'Your requests' : 'Requests by lead farmer'} · {selectedSeason?.name} {SEASONS[season]}</h3>
          </div>
        </div>
        {loading ? <div className="form-message">Loading requests…</div> : null}
        {!loading && !blocked && !requests.length ? <EmptyState icon="send" title="No requests yet">No lead farmer request for {selectedSeason?.name} {SEASONS[season]}.</EmptyState> : null}
        {requests.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Lead farmer</th><th>Cluster</th><th>Programme</th><th>Year and season</th><th className="num">Farmers</th><th className="num">Hectares</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {requests.map((row) => {
                  const [label, tone] = STATUS[row.status] || [row.status_label, '']
                  return (
                    <tr key={row.id} className={selected === row.id ? 'selected-row' : ''}>
                      <td><strong>{row.lead_farmer_name}</strong></td>
                      <td>{row.cluster_name}</td>
                      <td>{row.programme_name}</td>
                      <td>{row.season_name} · {row.crop_season_label}</td>
                      <td className="num">{row.farmers}</td>
                      <td className="num">{hectares(row.total_hectares)}</td>
                      <td><Pill tone={tone}>{label}</Pill></td>
                      <td><button type="button" className="ghost-btn small" onClick={() => setSelected(row.id)}>{row.status === 'DRAFT' || row.status === 'REJECTED' ? (canCreate ? 'Open and edit' : 'Open') : 'Open'}</button></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {selected ? (
        <RequestDetail
          key={`${selected}:${token}`}
          id={selected}
          canEdit={canCreate}
          canApprove={canApprove}
          showMoney={showMoney}
          onChanged={(message) => { if (message) setNotice(message); reload() }}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  )
}

function StartRequest({ season, cropSeason, isLead, onCreated }) {
  const [programmes, setProgrammes] = useState([])
  const [clusters, setClusters] = useState([])
  const [form, setForm] = useState({ programme: '', cluster: '' })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    loadAll('/programmes/', { season: season.id, crop_season: cropSeason, capacity_status: 'ACTIVE' })
      .then((list) => { if (active) setProgrammes(list) })
      .catch(() => { if (active) setProgrammes([]) })
    if (!isLead) {
      loadAll('/clusters/').then((list) => { if (active) setClusters(list) }).catch(() => { if (active) setClusters([]) })
    }
    return () => { active = false }
  }, [season.id, cropSeason, isLead])

  const submit = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const response = await apiClient.post('/lead-requests/', { programme: Number(form.programme), season: season.id, crop_season: cropSeason, cluster: form.cluster ? Number(form.cluster) : undefined })
      setForm({ programme: '', cluster: form.cluster })
      onCreated(response.data)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The request could not be started.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-head"><h3><Icon name="plus" />Start a request for {season.name} {SEASONS[cropSeason]}</h3></div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      <div className="workflow-fields">
        {isLead ? null : (
          <label className="form-field">Lead farmer’s cluster
            <select required value={form.cluster} onChange={(event) => setForm({ ...form, cluster: event.target.value })}>
              <option value="">Choose the cluster</option>
              {clusters.map((cluster) => <option key={cluster.id} value={cluster.id}>{cluster.name}{cluster.lead_farmer_name ? ` · ${cluster.lead_farmer_name}` : ''}</option>)}
            </select>
          </label>
        )}
        <label className="form-field">Programme
          <select required value={form.programme} onChange={(event) => setForm({ ...form, programme: event.target.value })}>
            <option value="">{programmes.length ? 'Choose a programme' : `No active programme for ${season.name} ${SEASONS[cropSeason]}`}</option>
            {programmes.map((programme) => <option key={programme.id} value={programme.id}>{programme.name}</option>)}
          </select>
        </label>
        <label className="form-field">Agricultural year and season<input readOnly value={`${season.name} · ${SEASONS[cropSeason]}`} title="Change these in the header" /></label>
      </div>
      <div className="workflow-form-actions"><button type="submit" className="primary-btn small" disabled={saving}>{saving ? 'Starting…' : 'Start request'}</button></div>
    </form>
  )
}

function TotalsTable({ totals, showMoney, caption }) {
  if (!totals?.rows?.length) return <div className="form-message">No products yet.</div>
  return (
    <div className="table-wrap">
      <table className="data-table compact">
        {caption ? <caption>{caption}</caption> : null}
        <thead><tr><th>Crop</th><th>Input</th><th>Variety or product</th><th className="num">Hectares</th><th className="num">Farmers</th><th className="num">Total quantity</th>{showMoney ? <th className="num">Cost</th> : null}</tr></thead>
        <tbody>
          {totals.rows.map((row) => (
            <tr key={`${row.crop}:${row.product_name}`}>
              <td>{row.crop}</td>
              <td>{row.input_category_label}</td>
              <td>{row.product_name}</td>
              <td className="num">{hectares(row.hectares)}</td>
              <td className="num">{row.farmers}</td>
              <td className="num"><strong>{qty(row.quantity)} {row.unit}</strong></td>
              {showMoney ? <td className="num">{money(row.cost)}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Consolidated({ summary, season, cropSeason, showMoney }) {
  const [lead, setLead] = useState('')
  const chosen = summary.requests.find((item) => String(item.request) === lead)
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>Consolidated totals · {season.name} {SEASONS[cropSeason]}</h3>
          <p className="card-sub">Across {summary.requests.length} lead farmer request{summary.requests.length === 1 ? '' : 's'} and {summary.totals.farmers} farmer{summary.totals.farmers === 1 ? '' : 's'}, excluding rejected requests.</p>
        </div>
        <label className="form-field compact">Show
          <select value={lead} onChange={(event) => setLead(event.target.value)}>
            <option value="">All lead farmers</option>
            {summary.requests.map((item) => <option key={item.request} value={item.request}>{item.lead_farmer_name} · {item.programme_name}</option>)}
          </select>
        </label>
      </div>
      <TotalsTable totals={chosen ? chosen.totals : summary.totals} showMoney={showMoney} />
    </section>
  )
}

function RequestDetail({ id, canEdit, canApprove, showMoney, onChanged, onClose }) {
  const [request, setRequest] = useState(null)
  const [choices, setChoices] = useState(null)
  const [editingLine, setEditingLine] = useState(null)
  const [deciding, setDeciding] = useState(false)
  const [error, setError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let active = true
    Promise.all([apiClient.get(`/lead-requests/${id}/`), apiClient.get(`/lead-requests/${id}/choices/`)])
      .then(([detail, options]) => { if (active) { setRequest(detail.data); setChoices(options.data); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'The request could not be loaded.')) })
    return () => { active = false }
  }, [id, reloadKey])

  const refresh = (message) => { setReloadKey((value) => value + 1); onChanged(message) }
  const editable = request && ['DRAFT', 'REJECTED'].includes(request.status) && canEdit

  const act = async (path, body, message) => {
    setError('')
    try {
      await apiClient.post(`/lead-requests/${id}/${path}/`, body || {})
      refresh(message)
      return true
    } catch (requestError) {
      setError(errorMessage(requestError, 'The request could not be updated.'))
      return false
    }
  }

  const removeLine = async (line) => {
    if (!window.confirm(`Remove ${line.farmer_name} (${line.crop_name}) from this request?`)) return
    try {
      await apiClient.delete(`/lead-request-lines/${line.id}/`)
      refresh(`${line.farmer_name} removed.`)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The farmer could not be removed.'))
    }
  }

  if (!request) return <section className="card">{error ? <div className="form-message error" role="alert">{error}</div> : <div className="form-message">Loading the request…</div>}</section>
  const [label, tone] = STATUS[request.status] || [request.status_label, '']
  return (
    <section className="card lead-request-detail">
      <div className="card-head">
        <div>
          <h3>{request.lead_farmer_name} · {request.programme_name} · {request.season_name} {request.crop_season_label}</h3>
          <p className="card-sub">{request.cluster_name} · {request.farmers} farmer{request.farmers === 1 ? '' : 's'} · {hectares(request.total_hectares)} <Pill tone={tone}>{label}</Pill></p>
          {request.decision_notes ? <p className={request.status === 'REJECTED' ? 'field-error' : 'card-sub'}>Admin: {request.decision_notes}</p> : null}
        </div>
        <button type="button" className="icon-btn" aria-label="Close request" onClick={onClose}><Icon name="close" /></button>
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      {editable ? <LineForm key={editingLine?.id || 'new'} request={request} choices={choices} line={editingLine} onCancel={() => setEditingLine(null)} onSaved={(message) => { setEditingLine(null); refresh(message) }} /> : null}

      <h4>Farmers in this request</h4>
      {request.lines.length ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Farmer</th><th>Crop</th><th className="num">Hectares</th><th>Products and quantities</th>{showMoney ? <th className="num">Cost</th> : null}<th>{request.status === 'APPROVED' ? 'Allocation' : ''}</th></tr></thead>
            <tbody>
              {request.lines.map((line) => (
                <tr key={line.id}>
                  <td>{line.farmer_name}<small className="block-hint">{line.membership_number}</small></td>
                  <td>{line.crop_name}<small className="block-hint">{line.request_number}</small></td>
                  <td className="num">{hectares(line.hectares)}</td>
                  <td>{line.items.map((item) => <div key={item.request_line}>{item.input_category_label}: {item.product_name} · {qty(item.quantity)} {item.unit}</div>)}</td>
                  {showMoney ? <td className="num">{money(line.items.reduce((sum, item) => sum + Number(item.cost || 0), 0))}</td> : null}
                  <td>
                    {request.status === 'APPROVED' ? (line.allocation ? <Pill tone="good">Allocated</Pill> : '—') : null}
                    {editable ? (
                      <span className="table-actions">
                        <button type="button" className="icon-btn" aria-label={`Edit ${line.farmer_name} ${line.crop_name}`} onClick={() => setEditingLine(line)}><Icon name="pencil" /></button>
                        <button type="button" className="icon-btn danger" aria-label={`Remove ${line.farmer_name} ${line.crop_name}`} onClick={() => removeLine(line)}><Icon name="trash" /></button>
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyState icon="users" title="No farmers yet">{editable ? 'Add your farmers above.' : 'This request has no farmers.'}</EmptyState>}

      <h4>Totals for this request</h4>
      <TotalsTable totals={request.totals} showMoney={showMoney} />

      <div className="workflow-form-actions">
        {editable && request.lines.length ? <button type="button" className="primary-btn" onClick={() => act('submit', null, 'Request submitted to Admin.')}><Icon name="send" />Submit to Admin</button> : null}
        {canApprove && request.status === 'SUBMITTED' ? <button type="button" className="primary-btn" onClick={() => setDeciding(true)}>Approve or reject</button> : null}
      </div>
      {deciding ? (
        <Decision
          request={request}
          onClose={() => setDeciding(false)}
          onApprove={async (notes) => { if (await act('approve', { notes }, `Approved. ${request.lines.length} farmer allocation${request.lines.length === 1 ? '' : 's'} created.`)) setDeciding(false) }}
          onReject={async (notes) => { if (await act('reject', { notes }, 'Request returned to the lead farmer.')) setDeciding(false) }}
        />
      ) : null}
    </section>
  )
}

function LineForm({ request, choices, line, onSaved, onCancel }) {
  const [form, setForm] = useState(line
    ? { farmer: String(line.farmer), crop: String(line.crop), hectares: String(Number(line.hectares)), products: line.items.map((item) => item.request_line) }
    : { farmer: '', crop: '', hectares: '', products: [] })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const crop = choices?.crops.find((item) => String(item.id) === form.crop)
  const products = crop?.products || []
  const grouped = CATEGORIES.map(([code, label]) => [code, label, products.filter((item) => item.input_category === code)]).filter(([, , items]) => items.length)

  const toggle = (product) => {
    const others = form.products.filter((value) => value !== product.id)
    if (product.input_category === 'SEED') {
      const seeds = products.filter((item) => item.input_category === 'SEED').map((item) => item.id)
      setForm({ ...form, products: form.products.includes(product.id) ? others : [...others.filter((value) => !seeds.includes(value)), product.id] })
    } else {
      setForm({ ...form, products: form.products.includes(product.id) ? others : [...others, product.id] })
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    const payload = { request: request.id, farmer: Number(form.farmer), crop: Number(form.crop), hectares: form.hectares, products: form.products }
    try {
      if (line) await apiClient.patch(`/lead-request-lines/${line.id}/`, payload)
      else await apiClient.post('/lead-request-lines/', payload)
      onSaved(line ? 'Farmer updated.' : 'Farmer added.')
    } catch (requestError) {
      setError(errorMessage(requestError, 'The farmer could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="lead-line-form" onSubmit={submit}>
      <h4>{line ? `Change ${line.farmer_name} · ${line.crop_name}` : 'Add a farmer'}</h4>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      <div className="workflow-fields">
        <label className="form-field">Farmer
          <select required value={form.farmer} onChange={(event) => setForm({ ...form, farmer: event.target.value })}>
            <option value="">Choose a farmer in {request.cluster_name}</option>
            {(choices?.farmers || []).map((farmer) => <option key={farmer.id} value={farmer.id}>{farmer.name}{farmer.membership_number ? ` · ${farmer.membership_number}` : ''}</option>)}
          </select>
        </label>
        <label className="form-field">Crop
          <select required value={form.crop} onChange={(event) => setForm({ ...form, crop: event.target.value, products: [] })}>
            <option value="">Choose a {request.crop_season_label.toLowerCase()} crop</option>
            {(choices?.crops || []).map((item) => <option key={item.id} value={item.id} disabled={!item.request_number}>{item.name}{item.request_number ? '' : ' · no programme request yet'}</option>)}
          </select>
        </label>
        <label className="form-field">Hectares<input required type="number" min="0.01" step="any" value={form.hectares} onChange={(event) => setForm({ ...form, hectares: event.target.value })} /></label>
      </div>
      {crop ? (
        <fieldset className="chip-field">
          <legend>Products from {request.programme_name}’s {crop.name} request ({crop.request_number})</legend>
          {grouped.map(([code, label, items]) => (
            <div key={code} className="request-product-group">
              <span className="request-product-type">{label}{code === 'SEED' ? ' · choose one variety' : ''}</span>
              <div className="category-chips" role="group" aria-label={`${label} products`}>
                {items.map((product) => {
                  const on = form.products.includes(product.id)
                  return (
                    <button key={product.id} type="button" className={on ? 'chip active' : 'chip'} aria-pressed={on} onClick={() => toggle(product)}>
                      {product.name} <small>{qty(product.rate_per_hectare, 4)} {product.unit}/ha{Number(form.hectares) > 0 ? ` → ${qty(Number(product.rate_per_hectare) * Number(form.hectares))} ${product.unit}` : ''}</small>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </fieldset>
      ) : null}
      <div className="workflow-form-actions">
        <button type="submit" className="primary-btn small" disabled={saving || !form.products.length}>{saving ? 'Saving…' : line ? 'Save farmer' : 'Add farmer'}</button>
        {line ? <button type="button" className="ghost-btn" onClick={onCancel}>Cancel</button> : null}
      </div>
    </form>
  )
}

function Decision({ request, onClose, onApprove, onReject }) {
  const [notes, setNotes] = useState('')
  return (
    <Modal title={`Decide on ${request.lead_farmer_name}’s request`} subtitle={`${request.programme_name} · ${request.season_name} ${request.crop_season_label} · ${request.farmers} farmers · ${hectares(request.total_hectares)}. Approving creates every farmer’s allocation; if any farmer cannot be allocated, nothing is.`} onClose={onClose}
      footer={<>
        <button type="button" className="ghost-btn" onClick={onClose}>Close</button>
        <button type="button" className="danger-solid" disabled={!notes.trim()} title={notes.trim() ? '' : 'Give the reason in the notes'} onClick={() => onReject(notes)}>Return to lead farmer</button>
        <button type="button" className="primary-btn" onClick={() => onApprove(notes)}>Approve request</button>
      </>}>
      <label className="form-field">Notes<textarea rows="3" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Required when returning the request" /></label>
    </Modal>
  )
}

export default LeadRequestsPage
