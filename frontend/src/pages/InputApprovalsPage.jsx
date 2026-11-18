// Admin: input approvals.
//
// Lead farmers' submissions arrive here. Admin either approves the requested hectares or sets a
// lower maximum for that lead farmer (per crop, input type and variety). The lead farmer shares
// the approved hectares among their farmers and submits the final distribution, which Admin then
// approves, returns for corrections or rejects. Only the final approval creates farmer debts.

import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import { AllocationsTable, CropBreakdown, HectareSummary, History, LimitsTable, StatusPill } from '../components/SubmissionParts'
import { EmptyState, Modal, PageHead, errorMessage } from '../components/ui'
import { when } from '../inputSupply'
import { hectares, listOf, money, qty } from '../programmeData'

const FILTERS = [
  ['SUBMITTED,CONFIRMATION', 'Waiting for me'],
  ['LIMITS_SET,RETURNED', 'With lead farmers'],
  ['APPROVED', 'Approved'],
  ['REJECTED', 'Rejected'],
  ['', 'All'],
]

function InputApprovalsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { can } = useAuth()
  const canDecide = can('input_approvals', 'approve')
  const [filter, setFilter] = useState(FILTERS[0][0])
  const [rows, setRows] = useState([])
  const [summary, setSummary] = useState(null)
  const [open, setOpen] = useState(null)
  const [token, setToken] = useState(0)
  const [loadedKey, setLoadedKey] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const baseKey = JSON.stringify([selectedSeason?.id, cropSeason, filter])
  const requestKey = `${baseKey}#${token}`

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id, page_size: 100 }
    if (cropSeason) params.crop_season = cropSeason
    Promise.all([
      apiClient.get('/input-supply-requests/', { params: filter ? { ...params, status: filter } : params }),
      apiClient.get('/input-supply-requests/consolidated/', { params }),
    ])
      .then(([list, totals]) => { if (active) { setRows(listOf(list.data)); setSummary(totals.data); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Input submissions could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, filter, requestKey])

  const loading = !blocked && !loadedKey.startsWith(`${baseKey}#`)
  const current = rows.find((row) => row.id === open)
  const decided = (fresh, message) => {
    setRows((list) => list.map((row) => (row.id === fresh.id ? fresh : row)))
    setNotice(message)
    setError('')
    setToken((value) => value + 1)
  }

  return (
    <div className="page-card">
      <PageHead title="Input approvals" subtitle="Review each lead farmer’s request, approve the hectares or set a maximum, then give the final approval to their farmer distribution. Only the final approval creates farmer input debts." />
      {blocked ? <div className="form-message">Choose the agricultural year and season in the header.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      {summary && !blocked ? <Consolidated summary={summary} season={selectedSeason} cropSeason={cropSeason} /> : null}

      <section className="card">
        <div className="card-head">
          <h3>Submissions</h3>
          <div className="category-chips" role="group" aria-label="Show">
            {FILTERS.map(([value, label]) => <button key={label} type="button" className={filter === value ? 'chip active' : 'chip'} aria-pressed={filter === value} onClick={() => { setFilter(value); setOpen(null) }}>{label}</button>)}
          </div>
        </div>
        {loading ? <div className="form-message">Loading…</div> : null}
        {!loading && !blocked && !rows.length ? <EmptyState icon="check" title="Nothing here">No submissions match this view.</EmptyState> : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Request</th><th>Lead farmer</th><th>Programme</th><th>Year and season</th><th className="num">Farmers</th><th className="num">Requested</th><th className="num">Approved max</th><th className="num">Distributed</th><th>Status</th><th>Submitted</th><th /></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className={open === row.id ? 'selected-row' : ''}>
                    <td><strong>{row.reference}</strong></td>
                    <td>{row.lead_farmer_name}</td>
                    <td>{row.programme_name}</td>
                    <td>{row.season_name} · {row.crop_season_label}</td>
                    <td className="num">{row.farmer_count}</td>
                    <td className="num">{hectares(row.requested_hectares)}</td>
                    <td className="num">{row.approved_hectares ? hectares(row.approved_hectares) : '—'}</td>
                    <td className="num">{hectares(row.hectares_total)}</td>
                    <td><StatusPill submission={row} /></td>
                    <td>{when(row.submitted_at)}</td>
                    <td><button type="button" className="ghost-btn small" onClick={() => setOpen(open === row.id ? null : row.id)}>{open === row.id ? 'Close' : 'Review'}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {current ? <Review key={`${current.id}:${current.status}:${token}`} submission={current} canDecide={canDecide} onDecided={decided} onError={setError} /> : null}
    </div>
  )
}

function Consolidated({ summary, season, cropSeason }) {
  const label = cropSeason === 'WINTER' ? 'Winter' : cropSeason === 'SUMMER' ? 'Summer' : ''
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>Consolidated totals · {season.name} {label}</h3>
          <p className="card-sub">{summary.counts.SUBMITTED} awaiting hectare decisions · {summary.counts.CONFIRMATION} awaiting final approval · {summary.counts.LIMITS_SET} with lead farmers · {summary.counts.APPROVED} approved</p>
        </div>
      </div>
      {summary.lead_farmers.length ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Request</th><th>Lead farmer</th><th>Programme</th><th className="num">Farmers</th><th className="num">Requested</th><th className="num">Approved maximum</th><th className="num">Difference</th><th className="num">Distributed</th><th>Status</th></tr></thead>
            <tbody>
              {summary.lead_farmers.map((row) => (
                <tr key={row.id}>
                  <td>{row.reference}</td><td>{row.lead_farmer_name}</td><td>{row.programme_name}</td><td className="num">{row.farmer_count}</td>
                  <td className="num">{hectares(row.requested_hectares)}</td>
                  <td className="num">{row.approved_hectares ? hectares(row.approved_hectares) : '—'}</td>
                  <td className="num">{row.difference_hectares && Number(row.difference_hectares) !== 0 ? hectares(row.difference_hectares) : '—'}</td>
                  <td className="num">{hectares(row.distributed_hectares)}</td>
                  <td>{row.status_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {summary.varieties.length ? (
        <details className="consolidated-varieties">
          <summary>Totals by crop and variety</summary>
          <div className="table-wrap">
            <table className="data-table compact">
              <thead><tr><th>Programme</th><th>Crop</th><th>Input</th><th>Variety or product</th><th className="num">Hectares</th><th className="num">Approved maximum</th><th className="num">Quantity</th><th className="num">Estimated cost</th><th className="num">Lead farmers</th></tr></thead>
              <tbody>
                {summary.varieties.map((row) => (
                  <tr key={`${row.programme_name}:${row.crop_name}:${row.product_name}`}>
                    <td>{row.programme_name}</td><td>{row.crop_name}</td><td>{row.input_category_label}</td><td>{row.product_name}</td>
                    <td className="num">{hectares(row.hectares)}</td><td className="num">{Number(row.approved_hectares) ? hectares(row.approved_hectares) : '—'}</td>
                    <td className="num">{qty(row.quantity)} {row.unit}</td><td className="num">{money(row.estimated_cost)}</td><td className="num">{row.lead_farmers}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </section>
  )
}

function Review({ submission, canDecide, onDecided, onError }) {
  const [limits, setLimits] = useState(null)
  const [confirming, setConfirming] = useState(null)
  const [busy, setBusy] = useState(false)
  const issuing = submission.status === 'SUBMITTED'
  const adjustable = ['LIMITS_SET', 'RETURNED', 'CONFIRMATION'].includes(submission.status) && submission.stage === 'DISTRIBUTION'

  // Requested hectares at crop, input type and variety level, to set the maximums against.
  const levels = issuing
    ? submission.crops.flatMap((crop) => [
        { key: `CROP:${crop.crop}`, scope: 'CROP', crop: crop.crop, name: crop.crop_name, level: 'Crop', requested: crop.hectares },
        ...crop.categories.map((category) => ({ key: `CATEGORY:${crop.crop}:${category.input_category}`, scope: 'CATEGORY', crop: crop.crop, input_category: category.input_category, name: `${crop.crop_name} ${category.input_category_label.toLowerCase()}`, level: 'Input type', requested: category.hectares })),
        ...crop.varieties.map((variety) => ({ key: `VARIETY:${variety.requirement}`, scope: 'VARIETY', crop: crop.crop, requirement: variety.requirement, category: variety.input_category, name: variety.product_name, level: 'Variety', requested: variety.hectares })),
      ])
    : submission.limits.map((row) => ({
        key: row.scope === 'VARIETY' ? `VARIETY:${row.requirement}` : row.scope === 'CATEGORY' ? `CATEGORY:${row.crop}:${row.input_category}` : `CROP:${row.crop}`,
        scope: row.scope, crop: row.crop, input_category: row.scope === 'CATEGORY' ? row.input_category : undefined, requirement: row.requirement ?? undefined, category: row.input_category,
        name: row.name, level: row.scope_label, requested: row.requested_hectares, approved: row.approved_hectares,
      }))

  // A lower level can never be above the level it belongs to, so lowering a crop or input type
  // brings the levels under it down with it.
  const changeLimit = (level, value) => setLimits((current) => {
    const next = { ...current, [level.key]: value }
    const cap = Number(value)
    if (level.scope !== 'VARIETY' && value !== '' && Number.isFinite(cap)) {
      levels.forEach((other) => {
        const below = other.crop === level.crop && (level.scope === 'CROP' ? other.scope !== 'CROP' : other.scope === 'VARIETY' && other.category === level.input_category)
        if (below && Number(next[other.key]) > cap) next[other.key] = String(cap)
      })
    }
    return next
  })

  const startLimits = () => setLimits(Object.fromEntries(levels.map((level) => [level.key, String(Number(level.approved ?? level.requested))])))

  const run = async (path, body, message) => {
    setBusy(true)
    try {
      const response = await apiClient.post(`/input-supply-requests/${submission.id}/${path}/`, body)
      setConfirming(null)
      setLimits(null)
      onDecided(response.data, message(response.data))
    } catch (requestError) {
      setConfirming(null)
      onError(errorMessage(requestError, 'The decision could not be saved.'))
    } finally {
      setBusy(false)
    }
  }

  const sendLimits = () => run('set-hectares', {
    mode: 'distribute',
    limits: levels.map((level) => ({ scope: level.scope, crop: level.crop, input_category: level.input_category, requirement: level.requirement, approved_hectares: limits[level.key] })),
  }, (fresh) => (fresh.limits_changed ? `Approved hectares for ${fresh.reference} changed. ${fresh.lead_farmer_name} was notified.` : `Maximum hectares issued to ${fresh.lead_farmer_name}.`))

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>{submission.reference} · {submission.lead_farmer_name} · {submission.programme_name} · {submission.season_name} {submission.crop_season_label} <StatusPill submission={submission} /></h3>
          {submission.decision_notes ? <p className="card-sub">Last decision: {submission.decision_notes}</p> : null}
        </div>
      </div>
      <HectareSummary submission={submission} />
      {submission.limits?.length ? <><h4>Approved maximum hectares</h4><LimitsTable limits={submission.limits} /></> : null}
      <h4>By crop and variety</h4>
      <CropBreakdown crops={submission.crops} />
      <h4>Farmer allocations</h4>
      <AllocationsTable allocations={submission.allocations} />

      {canDecide ? (
        <div className="decision-bar">
          {issuing ? (
            <>
              <button type="button" className="primary-btn" disabled={busy} onClick={() => setConfirming({ path: 'set-hectares', title: 'Approve the requested hectares?', body: { mode: 'approve' }, done: (fresh) => `Requested hectares approved for ${fresh.lead_farmer_name}. They can now submit the final distribution.` })}><Icon name="check" />Approve requested hectares</button>
              <button type="button" className="ghost-btn" disabled={busy} onClick={startLimits}>Set maximum hectares</button>
            </>
          ) : null}
          {adjustable ? <button type="button" className="ghost-btn" disabled={busy} onClick={startLimits}>Change approved hectares</button> : null}
          {submission.status === 'CONFIRMATION' ? <button type="button" className="primary-btn" disabled={busy} onClick={() => setConfirming({ path: 'approve', title: 'Give the final approval?', note: 'This makes every farmer allocation official and creates their input debts. It cannot be done twice.', done: (fresh) => `${fresh.reference} approved. ${fresh.allocation_count} farmer allocations are official.` })}><Icon name="check" />Final approval</button> : null}
          {['SUBMITTED', 'CONFIRMATION'].includes(submission.status) ? <button type="button" className="ghost-btn" disabled={busy} onClick={() => setConfirming({ path: 'return-for-corrections', title: 'Return for corrections?', needsReason: true, done: (fresh) => `${fresh.reference} returned to ${fresh.lead_farmer_name}.` })}>Return for corrections</button> : null}
          {['SUBMITTED', 'CONFIRMATION', 'LIMITS_SET', 'RETURNED'].includes(submission.status) ? <button type="button" className="danger-btn" disabled={busy} onClick={() => setConfirming({ path: 'reject', title: 'Reject this submission?', needsReason: true, note: 'It stays in the history and creates no debt.', done: (fresh) => `${fresh.reference} rejected.` })}>Reject</button> : null}
          {submission.status === 'APPROVED' ? <button type="button" className="danger-btn" disabled={busy} onClick={() => setConfirming({ path: 'reverse', title: 'Reverse the final approval?', needsReason: true, note: 'Its allocations and debts are cancelled, not deleted, and the submission returns to the lead farmer. Allocations with grain already recovered cannot be reversed.', done: (fresh) => `${fresh.reference} approval reversed.` })}>Reverse approval</button> : null}
        </div>
      ) : null}

      {limits ? (
        <div className="limits-editor">
          <h4>{issuing ? 'Set the maximum hectares for this lead farmer' : 'Change the approved hectares'}</h4>
          <p className="field-hint">These are maximums for the lead farmer to share among their farmers, not allocations to individual farmers.</p>
          <div className="table-wrap">
            <table className="data-table compact">
              <thead><tr><th>Approved for</th><th>Level</th><th className="num">Requested</th><th className="num">Approved maximum</th><th className="num">Difference</th></tr></thead>
              <tbody>
                {levels.map((level) => (
                  <tr key={level.key}>
                    <td>{level.name}</td><td>{level.level}</td><td className="num">{hectares(level.requested)}</td>
                    <td className="num"><input aria-label={`Approved hectares for ${level.name}`} type="number" min="0" step="any" value={limits[level.key]} onChange={(event) => changeLimit(level, event.target.value)} /></td>
                    <td className="num">{hectares(Number(limits[level.key] || 0) - Number(level.requested))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="workflow-form-actions">
            <button type="button" className="primary-btn small" disabled={busy} onClick={sendLimits}>{issuing ? 'Issue maximum hectares' : 'Save approved hectares'}</button>
            <button type="button" className="ghost-btn" onClick={() => setLimits(null)}>Cancel</button>
          </div>
        </div>
      ) : null}

      <h4>History</h4>
      <History events={submission.events} />

      {confirming ? <Confirm decision={confirming} busy={busy} onClose={() => setConfirming(null)} onConfirm={(remarks) => run(confirming.path, { ...(confirming.body || {}), remarks }, confirming.done)} /> : null}
    </section>
  )
}

function Confirm({ decision, busy, onClose, onConfirm }) {
  const [remarks, setRemarks] = useState('')
  return (
    <Modal title={decision.title} subtitle={decision.note} onClose={onClose}
      footer={<><button type="button" className="ghost-btn" onClick={onClose}>Cancel</button><button type="button" className="primary-btn" disabled={busy || (decision.needsReason && !remarks.trim())} onClick={() => onConfirm(remarks)}>{busy ? 'Saving…' : 'Confirm'}</button></>}>
      <label className="form-field">{decision.needsReason ? 'Reason (the lead farmer sees this)' : 'Comment (optional)'}
        <textarea rows="3" value={remarks} onChange={(event) => setRemarks(event.target.value)} />
      </label>
    </Modal>
  )
}

export default InputApprovalsPage
