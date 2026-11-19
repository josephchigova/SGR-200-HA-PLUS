// Lead farmer: input allocations for one programme, agricultural year and season.
//
// Farmers are sent to Admin in submissions. A lead farmer can send some farmers now and more
// later: once a submission is with Admin, new farmers go into the next one (one draft at a time).
// Where Admin sets maximum hectares on a submission, the lead farmer shares that maximum among
// its farmers and submits the final distribution; it cannot go past it. Other submissions are
// not limited by it.
// Each allocation (one farmer, one crop, its varieties and hectares) is saved, changed or
// removed on its own, straight away. The page always shows what the server saved; it never keeps
// a separate working copy that could drift.

import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import Icon from '../components/Icon'
import Redistribution from '../components/Redistribution'
import SearchSelect from '../components/SearchSelect'
import { AllocationsTable, CropBreakdown, HectareSummary, History, LimitsTable, StatusPill } from '../components/SubmissionParts'
import { EmptyState, Modal, PageHead, Pill, errorMessage } from '../components/ui'
import { OPEN_STATUSES, estimate, nextStep, submitLabel } from '../inputSupply'
import { hectares, listOf, money, qty } from '../programmeData'

const SEASON = { SUMMER: 'Summer', WINTER: 'Winter' }

function LeadInputAllocationsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const season = cropSeason || 'SUMMER'
  const [catalogue, setCatalogue] = useState(null)
  const [submissions, setSubmissions] = useState([])
  const [programme, setProgramme] = useState('')
  // A link from My input requests can open one submission directly.
  const [picked, setPicked] = useState(() => {
    const id = new URLSearchParams(window.location.search).get('submission')
    return /^\d+$/.test(id || '') ? Number(id) : null
  })
  const [adding, setAdding] = useState(false)
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
  const linked = typeof picked === 'number' ? submissions.find((item) => item.id === picked) : null
  const chosen = programmes.find((item) => String(item.programme) === programme)
    || (linked ? programmes.find((item) => item.programme === linked.programme) : null)
    || (programmes.length === 1 ? programmes[0] : null)
  // This programme's submissions, newest first. The draft is where new farmers go.
  const batches = chosen ? submissions.filter((item) => item.programme === chosen.programme && item.status !== 'REJECTED').sort((a, b) => b.id - a.id) : []
  const draft = batches.find((item) => item.status === 'DRAFT') || null
  const canStartNew = !readOnlyYear && !draft
  // Submissions where Admin set a maximum that the lead farmer still has to share out.
  const toShare = batches.filter((item) => item.hectares_capped && item.editable)
  // Open on the draft or a returned submission; otherwise start the next submission straight away.
  const preferred = draft || batches.find((item) => item.editable && item.status === 'RETURNED' && !item.hectares_capped) || null
  const fallback = preferred || (canStartNew ? null : batches[0] || null)
  const submission = picked === 'new' && canStartNew ? null : batches.find((item) => item.id === picked) || fallback
  const editable = !readOnlyYear && (submission ? submission.editable : canStartNew)
  // A maximum Admin set is shared out in this same submission, on its own screen.
  const sharing = editable && Boolean(submission?.hectares_capped)
  // Farmer and crop pairs already in an open submission of this programme cannot be sent again.
  const pending = batches.filter((item) => OPEN_STATUSES.includes(item.status)).flatMap((item) => item.allocations || [])

  // A server response replaces what the page shows; nothing is kept from before it.
  const applied = (fresh, message, removedId = null) => {
    setSubmissions((current) => {
      const others = current.filter((item) => item.id !== fresh?.id && item.id !== removedId)
      return fresh ? [fresh, ...others] : others
    })
    setPicked(fresh ? fresh.id : null)
    setAdding(false)
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
      applied(response.data, `${response.data.reference} was sent to Admin.`)
    } catch (requestError) {
      failed(requestError, 'The submission could not be sent.')
    } finally {
      setBusy(false)
    }
  }

  // Saves every changed hectare together; nothing is kept on screen that the server did not save.
  const saveShares = async (changes) => {
    const response = await apiClient.post(`/input-supply-requests/${submission.id}/redistribute/`, { changes })
    return response.data
  }

  const redistribute = async (changes) => {
    setBusy(true)
    try {
      const fresh = await saveShares(changes)
      applied(fresh, 'Your changes were saved. Send the submission back to Admin when every maximum is met.')
    } catch (requestError) {
      failed(requestError, 'The changes could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  const sendBack = async (changes) => {
    setBusy(true)
    try {
      if (changes) await saveShares(changes)
      const response = await apiClient.post(`/input-supply-requests/${submission.id}/submit/`)
      applied(response.data, `${response.data.reference} was sent back to Admin for approval.`)
    } catch (requestError) {
      // Saved changes stay saved even if sending fails; the page shows what the server has.
      failed(requestError, 'The submission could not be sent back.')
      reload()
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
              onChange={(value) => { setProgramme(value); setPicked(null); setEditing(null); setAdding(false); setNotice('') }}
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
              <button key={item.id} type="button" className={submission?.id === item.id ? 'chip active' : 'chip'} aria-pressed={submission?.id === item.id} onClick={() => { setPicked(item.id); setEditing(null); setAdding(false); setNotice('') }}>
                {item.reference} · {item.status_label} · {item.farmer_count} farmer{item.farmer_count === 1 ? '' : 's'} · {hectares(item.hectares_total)}
              </button>
            ))}
            {canStartNew ? <button type="button" className={submission ? 'chip' : 'chip active'} aria-pressed={!submission} onClick={() => { setPicked('new'); setEditing(null); setAdding(false); setNotice('') }}><Icon name="plus" />New submission</button> : null}
          </div>
          {toShare.length ? <p className="form-message warning">Admin set maximum hectares on {toShare.map((item) => item.reference).join(', ')}. Open {toShare.length === 1 ? 'it' : 'each'} to share the approved hectares among its farmers and submit the final distribution.</p> : null}
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
              {submission && submission.editable && submission.allocation_count && !sharing ? (
                <button type="button" className="primary-btn" disabled={busy} onClick={submit}><Icon name="send" />{submitLabel(submission)}</button>
              ) : null}
            </div>
            {submission && !sharing ? <HectareSummary submission={submission} /> : null}
            {submission?.limits?.length ? (
              <details className="expandable">
                <summary>Approved maximums by crop, input type and variety</summary>
                <LimitsTable limits={submission.limits} />
              </details>
            ) : null}
          </section>

          {sharing ? (
            <Redistribution
              key={`${submission.id}:${submission.allocations.map((row) => `${row.id}.${row.version}`).join(',')}`}
              submission={submission}
              busy={busy}
              onSave={redistribute}
              onSend={sendBack}
              onAddFarmer={() => { setAdding(true); setNotice('') }}
            />
          ) : null}

          {editable && (!sharing || adding || editing) ? (
            <AllocationForm
              key={editing ? `edit-${editing.id}-${editing.version}` : `new-${chosen.programme}-${submission?.id || 'new'}-${token}`}
              programme={chosen}
              farmers={catalogue.farmers}
              season={selectedSeason}
              cropSeason={season}
              submission={submission}
              pending={pending}
              allocation={editing}
              onCancel={() => { setEditing(null); setAdding(false) }}
              onSaved={(fresh, message) => { setEditing(null); applied(fresh, message) }}
              onFailed={failed}
            />
          ) : null}

          {!sharing ? (
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
            {submission?.crops?.length ? (
              <details className="expandable">
                <summary>Totals by crop and variety</summary>
                <CropBreakdown crops={submission.crops} />
              </details>
            ) : null}
          </section>
          ) : null}
          {submission?.events?.length ? (
            <section className="card">
              <details className="expandable">
                <summary>History and Admin feedback</summary>
                <History events={submission.events} />
              </details>
            </section>
          ) : null}
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

// One farmer's crop allocation. Varieties are found by searching and added as rows; each row
// takes its hectares, and the quantity and cost appear beside it. The server recalculates them.
function AllocationForm({ programme, farmers, season, cropSeason, submission, pending = [], allocation, onSaved, onCancel, onFailed }) {
  const crops = programme.crops
  const [farmer, setFarmer] = useState(allocation ? String(allocation.farmer) : '')
  const [cropId, setCropId] = useState(allocation ? String(allocation.crop) : crops.length === 1 ? String(crops[0].crop) : '')
  const [rows, setRows] = useState(() => (allocation ? allocation.lines.map((line) => ({ requirement: String(line.requirement), hectares: String(Number(line.hectares)) })) : []))
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const crop = crops.find((item) => String(item.crop) === cropId)
  const varieties = crop?.varieties || []
  const person = farmers.find((item) => String(item.id) === farmer)
  const intended = person?.crops?.find((item) => String(item.crop) === cropId)
  const taken = new Set(pending.filter((row) => row.id !== allocation?.id && String(row.crop) === cropId).map((row) => String(row.farmer)))
  const chosen = rows.map((row) => ({ ...row, variety: varieties.find((item) => String(item.requirement) === row.requirement) })).filter((row) => row.variety)
  const filled = chosen.filter((row) => Number(row.hectares) > 0)
  const totalCost = filled.reduce((sum, row) => sum + estimate(row.variety, row.hectares).cost, 0)
  const land = filled.reduce((most, row) => Math.max(most, Number(row.hectares)), 0)

  const addVariety = (requirement) => {
    // Inputs usually cover the same land, so a new row starts with the last row's hectares.
    const start = rows.length ? rows[rows.length - 1].hectares : intended ? String(Number(intended.hectares)) : ''
    setRows((current) => [...current, { requirement, hectares: start }])
    setMessage('')
  }
  const setHectares = (requirement, value) => setRows((current) => current.map((row) => (row.requirement === requirement ? { ...row, hectares: value } : row)))
  const removeRow = (requirement) => setRows((current) => current.filter((row) => row.requirement !== requirement))

  const save = async (event) => {
    event.preventDefault()
    setMessage('')
    if (!filled.length || filled.length !== chosen.length) {
      setMessage(chosen.length ? 'Enter the hectares for every variety, or remove it.' : 'Add at least one variety or product.')
      return
    }
    setSaving(true)
    const lines = filled.map((row) => ({ requirement: Number(row.requirement), hectares: row.hectares }))
    try {
      const response = allocation
        ? await apiClient.patch(`/input-supply-requests/allocations/${allocation.id}/`, { lines, version: allocation.version })
        : await apiClient.post('/input-supply-requests/allocations/', { programme: programme.programme, season: season.id, crop_season: cropSeason, farmer: Number(farmer), crop: Number(cropId), lines, ...(submission ? { submission: submission.id } : {}) })
      onSaved(response.data, allocation ? `${allocation.farmer_name}’s allocation was updated.` : `${person?.name}’s ${crop?.crop_name} allocation was saved.`)
    } catch (requestError) {
      onFailed(requestError, 'The allocation could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="card allocation-form" onSubmit={save}>
      <div className="card-head"><h3><Icon name={allocation ? 'pencil' : 'plus'} />{allocation ? `Edit ${allocation.farmer_name} · ${allocation.crop_name}` : 'Add a farmer'}</h3></div>
      {message ? <div className="form-message error" role="alert">{message}</div> : null}

      <div className="allocation-who">
        <SearchSelect
          label="Farmer"
          searchable
          value={farmer}
          disabled={Boolean(allocation)}
          onChange={setFarmer}
          placeholder="Search your farmers"
          options={farmers.filter((item) => !taken.has(String(item.id)) || String(item.id) === farmer).map((item) => ({ value: String(item.id), label: `${item.name}${item.membership_number ? ` · ${item.membership_number}` : ''}` }))}
          emptyText="No farmers in your cluster."
        />
        <div className="form-field">
          <span id="allocation-crop-label">Crop</span>
          <div className="crop-choice" role="group" aria-labelledby="allocation-crop-label">
            {crops.map((item) => (
              <button key={item.crop} type="button" className={String(item.crop) === cropId ? 'chip active' : 'chip'} aria-pressed={String(item.crop) === cropId} disabled={Boolean(allocation)}
                onClick={() => { if (String(item.crop) !== cropId) { setCropId(String(item.crop)); setRows([]) } }}>
                {item.crop_name}
              </button>
            ))}
          </div>
          {person && crop ? <span className="field-hint">{intended ? `${person.name} intends to plant ${hectares(intended.hectares)} of ${crop.crop_name}.` : `${person.name} has no ${crop.crop_name} planting recorded.`}</span> : null}
        </div>
      </div>

      {crop ? (
        <div className="variety-picker">
          <SearchSelect
            key={rows.length}
            label="Varieties and products"
            searchable
            value=""
            onChange={addVariety}
            placeholder="Search seed, fertilizer or chemicals to add"
            options={varieties.filter((item) => !rows.some((row) => row.requirement === String(item.requirement))).map((item) => ({
              value: String(item.requirement),
              label: `${item.product_name} · ${item.input_category_label} · ${qty(item.rate_per_hectare, 4)} ${item.unit}/ha`,
            }))}
            emptyText={`${crop.crop_name} has no catalogue in ${programme.programme_name}.`}
          />
          {chosen.length ? (
            <ul className="variety-rows">
              {chosen.map((row) => {
                const figures = estimate(row.variety, row.hectares)
                return (
                  <li key={row.requirement} className="variety-row">
                    <div className="variety-name">
                      <strong>{row.variety.product_name}</strong>
                      <small><Pill>{row.variety.input_category_label}</Pill> {qty(row.variety.rate_per_hectare, 4)} {row.variety.unit}/ha</small>
                    </div>
                    <label className="variety-hectares">
                      <input type="number" min="0.01" step="any" inputMode="decimal" aria-label={`Hectares of ${row.variety.product_name}`} value={row.hectares} onChange={(event) => setHectares(row.requirement, event.target.value)} />
                      <span>ha</span>
                    </label>
                    <div className="variety-figures">
                      {Number(row.hectares) > 0 ? <><strong>{qty(figures.quantity)} {row.variety.unit}</strong><small>{money(figures.cost)}</small></> : <small>Enter hectares</small>}
                    </div>
                    <button type="button" className="icon-btn danger" aria-label={`Remove ${row.variety.product_name}`} onClick={() => removeRow(row.requirement)}><Icon name="trash" /></button>
                  </li>
                )
              })}
            </ul>
          ) : <p className="field-hint">Search above and pick each variety or product this farmer needs. Hectares are filled in from the farmer’s planting; change them if needed.</p>}
        </div>
      ) : <p className="field-hint">Choose the crop to see its varieties and products.</p>}

      <div className="allocation-footer">
        <span>{filled.length ? <>{hectares(land)} · estimated <strong>{money(totalCost)}</strong></> : ' '}</span>
        <div className="workflow-form-actions">
          {allocation ? <button type="button" className="ghost-btn" onClick={onCancel}>Cancel</button> : null}
          <button type="submit" className="primary-btn small" disabled={saving || !farmer || !cropId}>{saving ? 'Saving…' : allocation ? 'Save changes' : 'Save allocation'}</button>
        </div>
      </div>
    </form>
  )
}

export default LeadInputAllocationsPage
