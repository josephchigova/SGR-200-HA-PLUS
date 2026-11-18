// Lead farmer: input allocations for one programme, agricultural year and season.
//
// Farmers are sent to Admin in submissions. A lead farmer can send some farmers now and more
// later: once a submission is with Admin, new farmers go into the next one (one draft at a time).
// Each allocation (one farmer, one crop, its varieties and hectares) is saved, changed or
// removed on its own, straight away. The page always shows what the server saved; it never keeps
// a separate working copy that could drift.

import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import Icon from '../components/Icon'
import SearchSelect from '../components/SearchSelect'
import { AllocationsTable, CropBreakdown, HectareSummary, History, LimitsTable, StatusPill } from '../components/SubmissionParts'
import { EmptyState, Modal, PageHead, errorMessage } from '../components/ui'
import { CATEGORIES } from '../inputCategories'
import { OPEN_STATUSES, estimate, nextStep, submitLabel } from '../inputSupply'
import { hectares, listOf, money, qty } from '../programmeData'

const SEASON = { SUMMER: 'Summer', WINTER: 'Winter' }

function LeadInputAllocationsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const season = cropSeason || 'SUMMER'
  const [catalogue, setCatalogue] = useState(null)
  const [submissions, setSubmissions] = useState([])
  const [programme, setProgramme] = useState('')
  const [picked, setPicked] = useState(null)
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [token, setToken] = useState(0)
  const [loadedKey, setLoadedKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const readOnlyYear = Boolean(selectedSeason?.status && selectedSeason.status !== 'ACTIVE')
  const baseKey = JSON.stringify([selectedSeason?.id, season])
  const requestKey = `${baseKey}#${token}`

  // The catalogue and this season's submissions, read from the server every time something changes.
  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id, crop_season: season }
    Promise.all([
      apiClient.get('/input-supply-requests/catalogue/', { params }),
      apiClient.get('/input-supply-requests/', { params: { ...params, page_size: 100 } }),
    ])
      .then(([options, list]) => { if (active) { setCatalogue(options.data); setSubmissions(listOf(list.data)); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Your allocations could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, season, requestKey])

  // A reload after a save keeps the current figures on screen until the fresh ones arrive.
  const loading = !blocked && !loadedKey.startsWith(`${baseKey}#`)
  const reload = () => setToken((value) => value + 1)
  const programmes = catalogue?.programmes || []
  const chosen = programmes.find((item) => String(item.programme) === programme) || (programmes.length === 1 ? programmes[0] : null)
  // This programme's submissions, newest first. The draft is where new farmers go.
  const batches = chosen ? submissions.filter((item) => item.programme === chosen.programme && item.status !== 'REJECTED').sort((a, b) => b.id - a.id) : []
  const draft = batches.find((item) => item.status === 'DRAFT') || null
  const fallback = draft || batches.find((item) => item.editable) || batches.find((item) => OPEN_STATUSES.includes(item.status)) || null
  const submission = picked === 'new' ? null : batches.find((item) => item.id === picked) || fallback
  const canStartNew = !readOnlyYear && !draft
  const editable = !readOnlyYear && (submission ? submission.editable : canStartNew)
  // Farmer and crop pairs already in an open submission of this programme cannot be sent again.
  const pending = batches.filter((item) => OPEN_STATUSES.includes(item.status)).flatMap((item) => item.allocations || [])

  // A server response replaces what the page shows; nothing is kept from before it.
  const applied = (fresh, message, removedId = null) => {
    setSubmissions((current) => {
      const others = current.filter((item) => item.id !== fresh?.id && item.id !== removedId)
      return fresh ? [fresh, ...others] : others
    })
    setPicked(fresh ? fresh.id : null)
    setNotice(message)
    setError('')
    reload()
  }

  const failed = (requestError, fallback) => {
    setNotice('')
    if (requestError.response?.status === 409) {
      setError(`${requestError.response.data.detail} The latest figures are shown below.`)
      reload()
      return
    }
    setError(errorMessage(requestError, fallback))
  }

  const remove = async () => {
    const row = deleting
    setDeleting(null)
    setBusy(true)
    try {
      const response = await apiClient.delete(`/input-supply-requests/allocations/${row.id}/`, { params: { version: row.version } })
      applied(response.data.submission, `${row.farmer_name}’s ${row.crop_name} allocation was removed.`, submission?.id)
      if (editing?.id === row.id) setEditing(null)
    } catch (requestError) {
      failed(requestError, 'The allocation could not be removed.')
    } finally {
      setBusy(false)
    }
  }

  const submit = async () => {
    setBusy(true)
    try {
      const response = await apiClient.post(`/input-supply-requests/${submission.id}/submit/`)
      applied(response.data, `${response.data.reference} ${response.data.status_label.toLowerCase()}.`)
    } catch (requestError) {
      failed(requestError, 'The submission could not be sent.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-card lead-allocations-page">
      <PageHead title="Input allocations" subtitle="Choose a programme, then add each farmer’s crop, varieties and hectares. Quantities and costs are calculated for you. Every change is saved straight away." />
      {blocked ? <div className="form-message">Choose the agricultural year and season in the header.</div> : null}
      {readOnlyYear ? <div className="form-message">{selectedSeason.name} is not the active agricultural year, so its allocations are read-only.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {loading ? <div className="form-message">Loading…</div> : null}

      {!loading && !blocked ? (
        programmes.length ? (
          <section className="card">
            <SearchSelect
              label="Programme"
              value={chosen ? String(chosen.programme) : ''}
              onChange={(value) => { setProgramme(value); setPicked(null); setEditing(null); setNotice('') }}
              placeholder="Choose the programme"
              options={programmes.map((item) => ({ value: String(item.programme), label: item.programme_name }))}
            />
            {chosen ? <p className="card-sub">{selectedSeason.name} · {SEASON[season]} · {chosen.crops.map((crop) => crop.crop_name).join(', ')}</p> : null}
          </section>
        ) : <EmptyState icon="clipboard" title="No programme to allocate from">No active programme has a {SEASON[season].toLowerCase()} catalogue for {selectedSeason.name} yet.</EmptyState>
      ) : null}

      {chosen && !loading && (batches.length || !canStartNew) ? (
        <section className="card">
          <div className="card-head"><h3>Your submissions for {chosen.programme_name}</h3></div>
          <div className="category-chips submission-picker" role="group" aria-label="Submissions">
            {batches.map((item) => (
              <button key={item.id} type="button" className={submission?.id === item.id ? 'chip active' : 'chip'} aria-pressed={submission?.id === item.id} onClick={() => { setPicked(item.id); setEditing(null); setNotice('') }}>
                {item.reference} · {item.status_label} · {item.farmer_count} farmer{item.farmer_count === 1 ? '' : 's'} · {hectares(item.hectares_total)}
              </button>
            ))}
            {canStartNew ? <button type="button" className={submission ? 'chip' : 'chip active'} aria-pressed={!submission} onClick={() => { setPicked('new'); setEditing(null); setNotice('') }}><Icon name="plus" />New submission</button> : null}
          </div>
        </section>
      ) : null}

      {chosen && !loading ? (
        <>
          <section className="card">
            <div className="card-head">
              <div>
                <h3>{chosen.programme_name} · {selectedSeason.name} {SEASON[season]} · {submission ? <>{submission.reference} <StatusPill submission={submission} /></> : 'New submission'}</h3>
                <p className="card-sub">{submission ? nextStep(submission) : batches.length ? 'Add the farmers for your next submission. Your earlier submissions stay as they are with Admin.' : nextStep(null)}</p>
                {submission?.decision_notes ? <p className={submission.status === 'RETURNED' || submission.status === 'REJECTED' ? 'field-error' : 'card-sub'}>Admin: {submission.decision_notes}</p> : null}
                {submission?.limits_changed ? <div className="form-message warning" role="alert">Admin changed your approved hectares. Check the remaining hectares below before submitting.</div> : null}
              </div>
              {submission && submission.editable && submission.allocation_count && submission.status !== 'SUBMITTED' ? (
                <button type="button" className="primary-btn" disabled={busy} onClick={submit}><Icon name="send" />{submitLabel(submission)}</button>
              ) : null}
            </div>
            {submission ? <HectareSummary submission={submission} /> : null}
            {submission?.limits?.length ? <><h4>Your approved maximum hectares</h4><LimitsTable limits={submission.limits} /></> : null}
          </section>

          {editable ? (
            <AllocationForm
              key={editing ? `edit-${editing.id}-${editing.version}` : `new-${chosen.programme}-${submission?.id || 'new'}-${token}`}
              programme={chosen}
              farmers={catalogue.farmers}
              season={selectedSeason}
              cropSeason={season}
              submission={submission}
              pending={pending}
              allocation={editing}
              onCancel={() => setEditing(null)}
              onSaved={(fresh, message) => { setEditing(null); applied(fresh, message) }}
              onFailed={failed}
            />
          ) : null}

          <section className="card">
            <div className="card-head"><h3>Allocations</h3></div>
            <AllocationsTable
              allocations={submission?.allocations || []}
              empty={submission ? 'No allocations in this submission.' : 'No allocations yet. Add a farmer above to start this submission.'}
              actions={editable && submission?.editable ? (row) => (
                <span className="table-actions">
                  <button type="button" className="icon-btn" aria-label={`Edit ${row.farmer_name} ${row.crop_name}`} onClick={() => { setEditing(row); setNotice('') }}><Icon name="pencil" /></button>
                  <button type="button" className="icon-btn danger" aria-label={`Delete ${row.farmer_name} ${row.crop_name}`} onClick={() => setDeleting(row)}><Icon name="trash" /></button>
                </span>
              ) : null}
            />
            {submission?.crops?.length ? <><h4>Totals by crop and variety</h4><CropBreakdown crops={submission.crops} /></> : null}
          </section>
          {submission?.events?.length ? <section className="card"><div className="card-head"><h3>History</h3></div><History events={submission.events} /></section> : null}
        </>
      ) : null}

      {deleting ? (
        <Modal title={`Delete ${deleting.farmer_name}’s ${deleting.crop_name} allocation?`} subtitle={`${hectares(deleting.hectares)} · ${money(deleting.estimated_cost)}. This removes it from the database.`} onClose={() => setDeleting(null)}
          footer={<><button type="button" className="ghost-btn" onClick={() => setDeleting(null)}>Keep it</button><button type="button" className="danger-solid" disabled={busy} onClick={remove}>Delete</button></>}>
          <p>The totals are recalculated straight away.</p>
        </Modal>
      ) : null}
    </div>
  )
}

const blankLine = () => ({ category: '', requirement: '', hectares: '' })

function AllocationForm({ programme, farmers, season, cropSeason, submission, pending = [], allocation, onSaved, onCancel, onFailed }) {
  const crops = programme.crops
  const [form, setForm] = useState(() => (allocation
    ? {
        farmer: String(allocation.farmer), crop: String(allocation.crop),
        lines: allocation.lines.map((line) => ({ category: line.input_category, requirement: String(line.requirement), hectares: String(Number(line.hectares)) })),
      }
    : { farmer: '', crop: crops.length === 1 ? String(crops[0].crop) : '', lines: [blankLine()] }))
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const crop = crops.find((item) => String(item.crop) === form.crop)
  const varieties = crop?.varieties || []
  const farmer = farmers.find((item) => String(item.id) === form.farmer)
  const intended = farmer?.crops?.find((item) => String(item.crop) === form.crop)
  const taken = new Set(pending.filter((row) => row.id !== allocation?.id && String(row.crop) === form.crop).map((row) => String(row.farmer)))
  const setLine = (index, changes) => setForm((current) => ({ ...current, lines: current.lines.map((line, at) => (at === index ? { ...line, ...changes } : line)) }))
  const filled = form.lines.filter((line) => line.requirement && Number(line.hectares) > 0)
  const preview = filled.map((line) => ({ line, variety: varieties.find((item) => String(item.requirement) === line.requirement) })).filter((item) => item.variety)
  const totalCost = preview.reduce((sum, item) => sum + estimate(item.variety, item.line.hectares).cost, 0)

  const save = async (event) => {
    event.preventDefault()
    setMessage('')
    if (!filled.length) {
      setMessage('Choose at least one variety and enter its hectares.')
      return
    }
    setSaving(true)
    const lines = filled.map((line) => ({ requirement: Number(line.requirement), hectares: line.hectares }))
    try {
      const response = allocation
        ? await apiClient.patch(`/input-supply-requests/allocations/${allocation.id}/`, { lines, version: allocation.version })
        : await apiClient.post('/input-supply-requests/allocations/', { programme: programme.programme, season: season.id, crop_season: cropSeason, farmer: Number(form.farmer), crop: Number(form.crop), lines, ...(submission ? { submission: submission.id } : {}) })
      onSaved(response.data, allocation ? `${allocation.farmer_name}’s allocation was updated.` : `${farmer?.name}’s ${crop?.crop_name} allocation was saved.`)
    } catch (requestError) {
      onFailed(requestError, 'The allocation could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="card allocation-form" onSubmit={save}>
      <div className="card-head"><h3><Icon name={allocation ? 'pencil' : 'plus'} />{allocation ? `Edit ${allocation.farmer_name} · ${allocation.crop_name}` : 'Add an allocation'}</h3></div>
      {message ? <div className="form-message error" role="alert">{message}</div> : null}
      <div className="workflow-fields">
        <SearchSelect
          label="Farmer"
          searchable
          value={form.farmer}
          disabled={Boolean(allocation)}
          onChange={(value) => setForm({ ...form, farmer: value })}
          placeholder="Search your farmers"
          options={farmers.filter((item) => !taken.has(String(item.id)) || String(item.id) === form.farmer).map((item) => ({ value: String(item.id), label: `${item.name}${item.membership_number ? ` · ${item.membership_number}` : ''}` }))}
          emptyText="No farmers in your cluster."
        />
        <label className="form-field">Crop
          <select required value={form.crop} disabled={Boolean(allocation)} onChange={(event) => setForm({ ...form, crop: event.target.value, lines: [blankLine()] })}>
            <option value="">Choose the crop</option>
            {crops.map((item) => <option key={item.crop} value={item.crop}>{item.crop_name}</option>)}
          </select>
          {farmer && crop ? <span className="field-hint">{intended ? `${farmer.name} intends to plant ${hectares(intended.hectares)} of ${crop.crop_name}.` : `${farmer.name} has no ${crop.crop_name} planting recorded.`}</span> : null}
        </label>
      </div>
      {crop ? (
        <div className="allocation-lines-form">
          {form.lines.map((line, index) => {
            const options = varieties.filter((item) => (!line.category || item.input_category === line.category) && (String(item.requirement) === line.requirement || !form.lines.some((other, at) => at !== index && other.requirement === String(item.requirement))))
            const variety = varieties.find((item) => String(item.requirement) === line.requirement)
            const figures = variety ? estimate(variety, line.hectares) : null
            return (
              <div key={index} className="allocation-line">
                <label className="form-field">Input type
                  <select value={line.category} onChange={(event) => setLine(index, { category: event.target.value, requirement: '' })}>
                    <option value="">Any</option>
                    {CATEGORIES.filter(([code]) => varieties.some((item) => item.input_category === code)).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                  </select>
                </label>
                <label className="form-field">Variety or product
                  <select required value={line.requirement} onChange={(event) => setLine(index, { requirement: event.target.value })}>
                    <option value="">Choose</option>
                    {options.map((item) => <option key={item.requirement} value={item.requirement}>{item.product_name} · {item.input_category_label}</option>)}
                  </select>
                </label>
                <label className="form-field">Hectares
                  <input required type="number" min="0.01" step="any" aria-label={`Hectares for line ${index + 1}`} value={line.hectares} onChange={(event) => setLine(index, { hectares: event.target.value })} />
                </label>
                <div className="line-figures">
                  {figures && Number(line.hectares) > 0 ? <>{qty(figures.quantity)} {variety.unit}<small className="block-hint">{qty(variety.rate_per_hectare, 4)} {variety.unit}/ha · {money(figures.cost)}</small></> : <small className="block-hint">Quantity is calculated</small>}
                </div>
                {form.lines.length > 1 ? <button type="button" className="icon-btn danger" aria-label={`Remove line ${index + 1}`} onClick={() => setForm((current) => ({ ...current, lines: current.lines.filter((_, at) => at !== index) }))}><Icon name="trash" /></button> : null}
              </div>
            )
          })}
          {form.lines.length < varieties.length ? <button type="button" className="link-btn" onClick={() => setForm((current) => ({ ...current, lines: [...current.lines, blankLine()] }))}><Icon name="plus" />Add another variety</button> : null}
          {preview.length ? <p className="field-hint">Estimated cost {money(totalCost)}. The saved figures are calculated by the server from the catalogue.</p> : null}
        </div>
      ) : null}
      <div className="workflow-form-actions">
        <button type="submit" className="primary-btn small" disabled={saving || !form.farmer || !form.crop}>{saving ? 'Saving…' : allocation ? 'Save changes' : 'Save allocation'}</button>
        {allocation ? <button type="button" className="ghost-btn" onClick={onCancel}>Cancel</button> : null}
      </div>
    </form>
  )
}

export default LeadInputAllocationsPage
