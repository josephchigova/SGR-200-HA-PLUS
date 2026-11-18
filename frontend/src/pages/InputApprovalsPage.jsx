// Admin reviews consolidated submissions from lead farmers.
//
// A submitted request can be approved as requested, or Admin can set the maximum hectares
// that lead farmer may use. The lead farmer then distributes those hectares and submits
// again. Only the confirmation of that distribution creates farmer allocations.

import { Fragment, useEffect, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import { EmptyState, Modal, PageHead, Pill, errorMessage } from '../components/ui'
import { STATUS_TONE, when } from '../inputSupply'
import { loadAll, money, qty } from '../programmeData'

const TABS = [
  ['hectares', 'Hectare decisions'],
  ['confirmation', 'Final confirmation'],
  ['all', 'All submissions'],
]

const limitKey = (limit) => (limit.scope === 'CROP' ? 'crop' : limit.scope === 'CATEGORY' ? `cat:${limit.input_category}` : `var:${limit.requirement}`)

function seedLimits(row) {
  const seed = { crop: row.hectares_total || '' }
  ;(row.categories || []).forEach((category) => { seed[`cat:${category.input_category}`] = category.hectares })
  ;(row.totals || []).forEach((variety) => { seed[`var:${variety.requirement}`] = variety.hectares })
  ;(row.limits || []).forEach((limit) => { seed[limitKey(limit)] = limit.approved_hectares })
  return seed
}

function clampLimits(current, key, value) {
  const next = { ...current, [key]: value }
  const crop = Number(next.crop)
  if (key === 'crop' && Number.isFinite(crop)) {
    Object.keys(next).forEach((child) => {
      if (child !== 'crop' && Number(next[child]) > crop) next[child] = value
    })
  }
  return next
}

function InputApprovalsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { can } = useAuth()
  const canDecide = can('input_approvals', 'approve')
  const [tab, setTab] = useState('hectares')
  const [rows, setRows] = useState([])
  const [counts, setCounts] = useState(null)
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [open, setOpen] = useState(null)
  const [decision, setDecision] = useState(null)
  const [remarks, setRemarks] = useState('')
  const [approved, setApproved] = useState({})
  const [saving, setSaving] = useState(false)
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const requestKey = JSON.stringify([selectedSeason?.id, cropSeason, tab, token])

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id }
    if (cropSeason) params.crop_season = cropSeason
    const status = tab === 'hectares' ? 'SUBMITTED' : tab === 'confirmation' ? 'CONFIRMATION' : ''
    Promise.all([
      loadAll('/input-supply-requests/', status ? { ...params, status } : params),
      apiClient.get('/input-supply-requests/consolidated/', { params }).then((response) => response.data),
    ]).then(([requestRows, summary]) => {
      if (!active) return
      setRows(requestRows)
      setCounts(summary)
      setError('')
    }).catch((requestError) => {
      if (active) setError(errorMessage(requestError, 'Input approvals could not be loaded.'))
    }).finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, tab, requestKey])

  const loading = !blocked && loadedKey !== requestKey
  const reload = () => setToken((value) => value + 1)
  const reveal = (row) => {
    setOpen(open === row.id ? null : row.id)
    setApproved(seedLimits(row))
  }

  const decide = async () => {
    if (!decision) return
    setSaving(true)
    setError('')
    try {
      const response = await apiClient.post(`/input-supply-requests/${decision.row.id}/${decision.action}/`, { remarks })
      setNotice(`${response.data.reference} is now ${response.data.status_label.toLowerCase()}.`)
      setDecision(null)
      setRemarks('')
      setOpen(response.data.id)
      setApproved(seedLimits(response.data))
      reload()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The decision could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  const sendLimits = async (row, mode) => {
    setSaving(true)
    setError('')
    try {
      const limits = limitPayload(row, approved)
      const response = await apiClient.post(`/input-supply-requests/${row.id}/set-hectares/`, { mode, limits, remarks })
      setNotice(mode === 'approve'
        ? `${response.data.reference}: requested hectares approved. ${response.data.lead_farmer_name} can now distribute them.`
        : `${response.data.reference}: approved hectares sent to ${response.data.lead_farmer_name}.`)
      setRemarks('')
      setOpen(response.data.id)
      setApproved(seedLimits(response.data))
      reload()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The approved hectares could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page-card">
      <PageHead
        title="Input approvals"
        subtitle="Review what each lead farmer requested. Approve those hectares, or set the maximum hectares they may use. Confirm the farmer distribution only after they submit it."
      />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      <div className="tabs" role="tablist" aria-label="Input approval sections">
        {TABS.map(([id, label]) => {
          const count = id === 'hectares' ? counts?.submitted_count : id === 'confirmation' ? counts?.confirmation_count : null
          return (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
              {label}{count ? ` (${count})` : ''}
            </button>
          )
        })}
      </div>

      <section className="card">
        <div className="card-head">
          <h3>{tab === 'hectares' ? 'Submissions awaiting hectare limits' : tab === 'confirmation' ? 'Distributions awaiting confirmation' : 'All submissions'}</h3>
        </div>
        {loading ? <div className="form-message">Loading submissions…</div> : null}
        {!loading && !rows.length ? (
          <EmptyState icon="shield" title={tab === 'all' ? 'No submissions' : 'Nothing is waiting'}>
            {tab === 'hectares' ? 'Submitted requests from lead farmers appear here.' : 'Lead farmers submit a final distribution after you set their hectare limits.'}
          </EmptyState>
        ) : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Lead farmer</th><th>Submission</th><th>Programme</th><th>Year</th><th>Season</th><th>Crop</th><th className="num">Hectares</th><th className="num">Estimated cost</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <Fragment key={row.id}>
                    <tr>
                      <td>{row.lead_farmer_name}</td>
                      <td><strong>{row.reference}</strong></td>
                      <td>{row.programme_name}</td>
                      <td>{row.season_name}</td>
                      <td>{row.crop_season_label}</td>
                      <td>{row.crop_name}</td>
                      <td className="num">{qty(row.hectares_total)} ha</td>
                      <td className="num">{money(row.estimated_cost)}</td>
                      <td><Pill tone={STATUS_TONE[row.status] || ''}>{row.status_label}</Pill></td>
                      <td><button type="button" className="ghost-btn" onClick={() => reveal(row)}>{open === row.id ? 'Hide' : 'Review'}</button></td>
                    </tr>
                    {open === row.id ? (
                      <tr>
                        <td colSpan={10}>
                          <RequestDetail
                            row={row}
                            canDecide={canDecide}
                            approved={approved}
                            remarks={remarks}
                            saving={saving}
                            onApproved={(key, value) => setApproved((current) => clampToParents(row, current, key, value))}
                            onRemarks={setRemarks}
                            onApproveRequested={() => sendLimits(row, 'approve')}
                            onDistribute={() => sendLimits(row, 'distribute')}
                            onDecide={(action) => { setDecision({ row, action }); setRemarks('') }}
                          />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {decision ? (
        <Modal
          title={decision.action === 'approve' ? 'Confirm distribution' : decision.action === 'reject' ? 'Reject submission' : decision.action === 'return-for-corrections' ? 'Return for corrections' : 'Reverse confirmation'}
          subtitle={`${decision.row.reference} · ${decision.row.lead_farmer_name}`}
          onClose={() => setDecision(null)}
          footer={(
            <>
              <button type="button" className="ghost-btn" onClick={() => setDecision(null)}>Cancel</button>
              <button type="button" className="primary-btn" disabled={saving || (decision.action !== 'approve' && !remarks.trim())} onClick={decide}>{saving ? 'Saving…' : 'Confirm'}</button>
            </>
          )}
        >
          <label className="form-field">{decision.action === 'approve' ? 'Note to the lead farmer (optional)' : 'Explain the decision'}
            <textarea value={remarks} onChange={(event) => setRemarks(event.target.value)} rows={4} />
          </label>
          {decision.action === 'approve' ? <p className="card-sub">Confirming creates the farmer allocations and their input debt. Requested hectares are not confirmed until this step.</p> : null}
          {decision.action === 'reverse' ? <p className="card-sub">Reversing cancels the farmer allocations and their debt. The approved hectare limits stay, and the lead farmer can correct the distribution.</p> : null}
        </Modal>
      ) : null}
    </div>
  )
}

function limitPayload(row, approved) {
  const limits = [{ scope: 'CROP', approved_hectares: approved.crop }]
  ;(row.categories || []).forEach((category) => {
    limits.push({ scope: 'CATEGORY', input_category: category.input_category, approved_hectares: approved[`cat:${category.input_category}`] })
  })
  ;(row.totals || []).forEach((variety) => {
    limits.push({ scope: 'VARIETY', requirement: variety.requirement, approved_hectares: approved[`var:${variety.requirement}`] })
  })
  return limits
}

function capVarieties(row, next, category, cap) {
  ;(row.totals || []).filter((variety) => variety.input_category === category).forEach((variety) => {
    const varietyKey = `var:${variety.requirement}`
    if (Number(next[varietyKey]) > Number(cap)) next[varietyKey] = String(cap)
  })
}

function clampToParents(row, current, key, value) {
  const next = clampLimits(current, key, value)
  const crop = Number(next.crop)
  if (key === 'crop') {
    ;(row.categories || []).forEach((category) => capVarieties(row, next, category.input_category, next[`cat:${category.input_category}`]))
  }
  if (key.startsWith('cat:')) {
    if (Number.isFinite(crop) && Number(next[key]) > crop) next[key] = next.crop
    capVarieties(row, next, key.slice(4), next[key])
  }
  if (key.startsWith('var:')) {
    const variety = (row.totals || []).find((item) => `var:${item.requirement}` === key)
    const categoryCap = variety ? Number(next[`cat:${variety.input_category}`]) : NaN
    if (Number.isFinite(categoryCap) && Number(next[key]) > categoryCap) next[key] = String(categoryCap)
    if (Number.isFinite(crop) && Number(next[key]) > crop) next[key] = next.crop
  }
  return next
}

function RequestDetail({ row, canDecide, approved, remarks, saving, onApproved, onRemarks, onApproveRequested, onDistribute, onDecide }) {
  const awaitingLimits = row.status === 'SUBMITTED' && row.stage !== 'DISTRIBUTION'
  const canAdjust = canDecide && (row.status === 'LIMITS_SET' || (row.stage === 'DISTRIBUTION' && row.status === 'RETURNED') || row.status === 'CONFIRMATION')
  const cropLimit = (row.limits || []).find((limit) => limit.scope === 'CROP')
  return (
    <div>
      {row.decision_notes ? <p><strong>Latest note:</strong> {row.decision_notes}</p> : null}
      {row.reviewed_by_name ? <p className="card-sub">Last reviewed by {row.reviewed_by_name} on {when(row.reviewed_at)}.</p> : null}
      <p className="card-sub">{row.stage_label}. {row.farmer_count} farmer{row.farmer_count === 1 ? '' : 's'}.</p>

      <h4>Crop and input categories</h4>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Level</th><th>Item</th><th className="num">Requested ha</th><th className="num">Approved ha</th><th className="num">Estimated cost</th></tr></thead>
          <tbody>
            <tr>
              <td>Crop</td>
              <td>{row.crop_name}</td>
              <td className="num">{qty(cropLimit?.requested_hectares || row.hectares_total)}</td>
              <td className="num">{cropLimit ? qty(cropLimit.approved_hectares) : '—'}</td>
              <td className="num">{money(row.estimated_cost)}</td>
            </tr>
            {(row.categories || []).map((category) => (
              <tr key={category.input_category}>
                <td>Input category</td>
                <td>{category.input_category_label}</td>
                <td className="num">{qty(category.requested_hectares || category.hectares)}</td>
                <td className="num">{category.approved_hectares ? qty(category.approved_hectares) : '—'}</td>
                <td className="num">{money(category.estimated_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4>Varieties</h4>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Input</th><th>Variety</th><th className="num">Hectares</th><th className="num">Approved ha</th><th className="num">Quantity</th><th className="num">Estimated cost</th></tr></thead>
          <tbody>
            {(row.totals || []).map((line) => (
              <tr key={line.requirement}>
                <td>{line.input_category_label}</td>
                <td>{line.product_name}</td>
                <td className="num">{qty(line.hectares)} ha</td>
                <td className="num">{line.approved_hectares ? `${qty(line.approved_hectares)} ha` : '—'}</td>
                <td className="num"><strong>{qty(line.quantity)} {line.unit}</strong></td>
                <td className="num">{money(line.estimated_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4>Farmers</h4>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Farmer</th><th>Farm</th><th className="num">Land ha</th><th>Varieties</th></tr></thead>
          <tbody>
            {row.farmers.map((farmer) => (
              <tr key={farmer.id}>
                <td>{farmer.farmer_name}</td>
                <td>{farmer.farm_name}</td>
                <td className="num">{qty(farmer.hectares)}</td>
                <td>{farmer.lines.map((line) => `${line.product_name}: ${qty(line.hectares)} ha = ${qty(line.quantity)} ${line.unit} (${money(line.estimated_cost)})`).join('; ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {canDecide && (awaitingLimits || canAdjust) ? (
        <div className="card" style={{ marginTop: 12 }}>
          <h4>{awaitingLimits ? 'Set the maximum hectares' : 'Adjust the approved hectares'}</h4>
          <p className="card-sub">These are the most hectares this lead farmer may allocate. They are not assigned to individual farmers. A category cannot exceed the crop, and a variety cannot exceed its category.</p>
          <div className="filter-row">
            <label className="form-field">{row.crop_name} hectares
              <input aria-label={`Approved hectares for ${row.crop_name}`} type="number" min="0" step="0.01" value={approved.crop ?? ''} onChange={(event) => onApproved('crop', event.target.value)} />
            </label>
            {(row.categories || []).map((category) => (
              <label key={category.input_category} className="form-field">{category.input_category_label} hectares
                <input aria-label={`Approved hectares for ${category.input_category_label}`} type="number" min="0" step="0.01" value={approved[`cat:${category.input_category}`] ?? ''} onChange={(event) => onApproved(`cat:${category.input_category}`, event.target.value)} />
              </label>
            ))}
            {(row.totals || []).map((variety) => (
              <label key={variety.requirement} className="form-field">{variety.product_name} hectares
                <input aria-label={`Approved hectares for ${variety.product_name}`} type="number" min="0" step="0.01" value={approved[`var:${variety.requirement}`] ?? ''} onChange={(event) => onApproved(`var:${variety.requirement}`, event.target.value)} />
              </label>
            ))}
          </div>
          <label className="form-field">Note to the lead farmer (optional)
            <textarea value={remarks} onChange={(event) => onRemarks(event.target.value)} rows={3} />
          </label>
          <div className="page-actions">
            {awaitingLimits ? <button type="button" className="primary-btn" disabled={saving} onClick={onApproveRequested}><Icon name="check" />Approve requested hectares</button> : null}
            <button type="button" className="primary-btn" disabled={saving} onClick={onDistribute}>{awaitingLimits ? 'Distribute these hectares' : 'Save approved hectares'}</button>
          </div>
        </div>
      ) : null}

      <History events={row.events} />
      {canDecide && row.status === 'CONFIRMATION' ? (
        <div className="page-actions">
          <button type="button" className="primary-btn" onClick={() => onDecide('approve')}><Icon name="check" />Confirm distribution</button>
          <button type="button" className="ghost-btn" onClick={() => onDecide('return-for-corrections')}>Return for corrections</button>
          <button type="button" className="ghost-btn" onClick={() => onDecide('reject')}>Reject</button>
        </div>
      ) : null}
      {canDecide && awaitingLimits ? (
        <div className="page-actions">
          <button type="button" className="ghost-btn" onClick={() => onDecide('return-for-corrections')}>Return for corrections</button>
          <button type="button" className="ghost-btn" onClick={() => onDecide('reject')}>Reject</button>
        </div>
      ) : null}
      {canDecide && row.status === 'APPROVED' ? (
        <div className="page-actions">
          <button type="button" className="ghost-btn" onClick={() => onDecide('reverse')}>Reverse confirmation</button>
        </div>
      ) : null}
    </div>
  )
}

function History({ events }) {
  if (!events?.length) return null
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.id}>
          <Pill tone={STATUS_TONE[event.action] || ''}>{event.action_label}</Pill>
          <span>{when(event.created_at)} · {event.actor_name || 'System'}</span>
          {event.remarks ? <p>{event.remarks}</p> : null}
          {event.detail?.limits?.length ? (
            <p className="card-sub">
              {event.detail.limits.map((limit) => `${limit.name}: requested ${qty(limit.requested_hectares)} ha, approved ${qty(limit.approved_hectares)} ha`).join(' · ')}
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  )
}

export default InputApprovalsPage
