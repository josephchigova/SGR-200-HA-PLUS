// Admin reviews the requests lead farmers submit, and sets the variety caps those requests draw from.
//
// Approving consumes the cap. Rejecting or returning it does not. An approved request is reversed,
// not edited, and the reversal cancels the farmer allocations that approval created.

import { Fragment, useEffect, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import { EmptyState, Modal, PageHead, Pill, errorMessage } from '../components/ui'
import { CATEGORY_LABEL, loadAll, qty } from '../programmeData'
import { STATUS_TONE, when } from '../inputSupply'

const TABS = [
  ['pending', 'Awaiting approval'],
  ['all', 'All requests'],
  ['caps', 'Variety caps'],
]

function InputApprovalsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { can } = useAuth()
  const canDecide = can('input_approvals', 'approve')
  const canConfigure = can('input_caps', 'create')
  const [tab, setTab] = useState('pending')
  const [rows, setRows] = useState([])
  const [caps, setCaps] = useState([])
  const [combined, setCombined] = useState(null)
  const [programmes, setProgrammes] = useState([])
  const [crops, setCrops] = useState([])
  const [requirements, setRequirements] = useState([])
  const [requirementProgramme, setRequirementProgramme] = useState('')
  const [requirementCrop, setRequirementCrop] = useState('')
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [open, setOpen] = useState(null)
  const [decision, setDecision] = useState(null)
  const [remarks, setRemarks] = useState('')
  const [saving, setSaving] = useState(false)
  const [capForm, setCapForm] = useState({ programme: '', crop: '', requirement: '', cap_quantity: '' })
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const readOnlyYear = Boolean(selectedSeason?.status && selectedSeason.status !== 'ACTIVE')
  const requestKey = JSON.stringify([selectedSeason?.id, cropSeason, tab, token])

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id }
    if (cropSeason) params.crop_season = cropSeason
    const requests = tab === 'caps'
      ? Promise.resolve([])
      : loadAll('/input-supply-requests/', tab === 'pending' ? { ...params, status: 'SUBMITTED' } : params)
    Promise.all([
      requests,
      loadAll('/programme-variety-caps/', params),
      apiClient.get('/input-supply-requests/consolidated/', { params }).then((response) => response.data),
      loadAll('/programmes/', params),
      loadAll('/crops/'),
    ]).then(([requestRows, capRows, summary, programmeRows, cropRows]) => {
      if (!active) return
      setRows(requestRows)
      setCaps(capRows)
      setCombined(summary)
      setProgrammes(programmeRows)
      setCrops(cropRows)
      setError('')
    }).catch((requestError) => {
      if (active) setError(errorMessage(requestError, 'Input approvals could not be loaded.'))
    }).finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, tab, requestKey])

  const loadRequirements = (programmeId, cropId) => {
    setRequirementProgramme(programmeId)
    setRequirementCrop(cropId)
    if (!programmeId || !cropId) {
      setRequirements([])
      return
    }
    loadAll('/crop-input-requirements/', { programme: programmeId, crop: cropId })
      .then((list) => {
        setRequirements(list.filter((row) => row.active !== false && row.input_product))
      })
      .catch(() => setRequirements([]))
  }

  const loading = !blocked && loadedKey !== requestKey
  const reload = () => setToken((value) => value + 1)
  const selectedProgramme = programmes.find((item) => String(item.id) === capForm.programme)
  const programmeCrops = crops.filter((item) => (selectedProgramme?.crops || []).map(String).includes(String(item.id)) && (!cropSeason || item.category === cropSeason))
  const requirementChoices = requirementProgramme === capForm.programme && requirementCrop === capForm.crop ? requirements : []
  const selectedRequirement = requirementChoices.find((item) => String(item.id) === capForm.requirement)

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
      reload()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The decision could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  const addCap = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const response = await apiClient.post('/programme-variety-caps/', {
        programme: Number(capForm.programme),
        season: selectedSeason.id,
        crop: Number(capForm.crop),
        requirement: Number(capForm.requirement),
        cap_quantity: capForm.cap_quantity,
      })
      setNotice(`${response.data.product_name} capped at ${qty(response.data.cap_quantity)} ${response.data.unit}.`)
      setCapForm({ programme: capForm.programme, crop: capForm.crop, requirement: '', cap_quantity: '' })
      reload()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The cap could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  const changeCap = async (cap, quantity) => {
    setError('')
    try {
      await apiClient.patch(`/programme-variety-caps/${cap.id}/`, { cap_quantity: quantity })
      setNotice(`${cap.product_name} cap updated.`)
      reload()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The cap could not be updated.'))
    }
  }

  return (
    <div className="page-card">
      <PageHead title="Input approvals" subtitle="Set how much of each variety is available, then approve, reject or return the requests lead farmers submit. Approval is what uses the cap." />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {readOnlyYear ? <div className="form-message">{selectedSeason.name} is not the active agricultural year. You can still review requests that were already submitted.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      <div className="tabs" role="tablist" aria-label="Input approval sections">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}{id === 'pending' && combined ? ` (${combined.submitted_count})` : ''}</button>
        ))}
      </div>

      {tab !== 'caps' ? (
        <section className="card">
          <div className="card-head"><h3>Combined requirements</h3></div>
          {combined?.caps?.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Programme</th><th>Crop</th><th>Season</th><th>Input</th><th>Variety</th><th className="num">Cap</th><th className="num">Approved</th><th className="num">Awaiting approval</th><th className="num">Remaining</th></tr></thead>
                <tbody>
                  {combined.caps.map((cap) => (
                    <tr key={cap.id}>
                      <td>{cap.programme_name}</td>
                      <td>{cap.crop_name}</td>
                      <td>{cap.crop_season_label}</td>
                      <td>{cap.input_category_label}</td>
                      <td>{cap.product_name}</td>
                      <td className="num">{qty(cap.cap_quantity)} {cap.unit}</td>
                      <td className="num">{qty(cap.approved_quantity)} {cap.unit}</td>
                      <td className="num">{qty(cap.submitted_quantity)} {cap.unit}</td>
                      <td className="num"><strong>{qty(cap.remaining_quantity)} {cap.unit}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon="layers" title="No variety caps">Add caps before lead farmers can request inputs.</EmptyState>}
        </section>
      ) : null}

      {tab !== 'caps' ? (
        <section className="card">
          <div className="card-head"><h3>{tab === 'pending' ? 'Requests awaiting a decision' : 'All lead farmer requests'}</h3></div>
          {loading ? <div className="form-message">Loading requests…</div> : null}
          {!loading && !rows.length ? <EmptyState icon="shield" title={tab === 'pending' ? 'Nothing is waiting' : 'No requests'}>{tab === 'pending' ? 'Submitted requests from lead farmers appear here.' : 'Requests for this year appear here.'}</EmptyState> : null}
          {rows.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Lead farmer</th><th>Request</th><th>Programme</th><th>Year</th><th>Season</th><th>Crop</th><th>Farmers</th><th>Status</th><th></th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <Fragment key={row.id}>
                      <tr>
                        <td>{row.lead_farmer_name}</td>
                        <td><strong>{row.reference}</strong></td>
                        <td>{row.programme_name}</td>
                        <td>{row.season_name}</td>
                        <td>{row.crop_season_label}</td>
                        <td>{row.crop_name}<small className="block-hint">{qty(row.hectares_total)} ha</small></td>
                        <td>{row.farmer_count}</td>
                        <td><Pill tone={STATUS_TONE[row.status] || ''}>{row.status_label}</Pill></td>
                        <td><button type="button" className="ghost-btn" onClick={() => setOpen(open === row.id ? null : row.id)}>{open === row.id ? 'Hide' : 'Review'}</button></td>
                      </tr>
                      {open === row.id ? (
                        <tr>
                          <td colSpan={9}>
                            <RequestDetail row={row} canDecide={canDecide} onDecide={(action) => { setDecision({ row, action }); setRemarks('') }} />
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
      ) : null}

      {tab === 'caps' ? (
        <section className="card">
          <div className="card-head"><h3>Available quantity by variety</h3></div>
          <p className="card-sub">A cap is how much of one variety lead farmers may request. It is not allocated to a farmer from here.</p>
          {canConfigure && !readOnlyYear ? (
            <form className="filter-row" onSubmit={addCap}>
              <label className="form-field">Programme
                <select value={capForm.programme} onChange={(event) => { setCapForm({ programme: event.target.value, crop: '', requirement: '', cap_quantity: '' }); loadRequirements('', '') }}>
                  <option value="">Select</option>
                  {programmes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
              <label className="form-field">Crop
                <select value={capForm.crop} onChange={(event) => { const cropId = event.target.value; setCapForm({ ...capForm, crop: cropId, requirement: '' }); loadRequirements(capForm.programme, cropId) }}>
                  <option value="">Select</option>
                  {programmeCrops.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
              <label className="form-field">Variety
                <select value={capForm.requirement} onChange={(event) => setCapForm({ ...capForm, requirement: event.target.value })}>
                  <option value="">Select</option>
                  {requirementChoices.map((item) => <option key={item.id} value={item.id}>{CATEGORY_LABEL[item.input_category] || item.input_category}: {item.input_product_name} ({item.unit || 'unit'})</option>)}
                </select>
              </label>
              <label className="form-field">Available cap{selectedRequirement ? ` (${selectedRequirement.unit || 'unit'})` : ''}
                <input type="number" min="0" step="0.0001" value={capForm.cap_quantity} onChange={(event) => setCapForm({ ...capForm, cap_quantity: event.target.value })} required />
              </label>
              <button type="submit" className="primary-btn" disabled={saving || !capForm.requirement}><Icon name="plus" />Add cap</button>
            </form>
          ) : null}
          {selectedRequirement ? <p className="card-sub">Catalogue rate: {qty(selectedRequirement.rate_per_hectare)} {selectedRequirement.unit || ''} per hectare. The unit comes from the crop catalogue.</p> : null}
          {!caps.length ? <EmptyState icon="layers" title="No caps for this year">Add one variety at a time. Lead farmers only see varieties that have a cap.</EmptyState> : (
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Programme</th><th>Crop</th><th>Season</th><th>Input</th><th>Variety</th><th className="num">Cap</th><th className="num">Approved</th><th className="num">Remaining</th>{canConfigure && !readOnlyYear ? <th>Change cap</th> : null}</tr></thead>
                <tbody>
                  {caps.map((cap) => (
                    <CapRow key={cap.id} cap={cap} canEdit={canConfigure && !readOnlyYear} onSave={changeCap} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {decision ? (
        <Modal
          title={decision.action === 'approve' ? 'Approve request' : decision.action === 'reject' ? 'Reject request' : decision.action === 'return-for-corrections' ? 'Return for corrections' : 'Reverse approval'}
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
          {decision.action === 'reverse' ? <p className="card-sub">Reversing cancels the farmer allocations and releases the cap. The lead farmer can correct the request and submit it again.</p> : null}
        </Modal>
      ) : null}
    </div>
  )
}

function RequestDetail({ row, canDecide, onDecide }) {
  return (
    <div>
      {row.decision_notes ? <p><strong>Latest note:</strong> {row.decision_notes}</p> : null}
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Farmer</th><th>Farm</th><th className="num">Hectares</th><th>Varieties</th></tr></thead>
          <tbody>
            {row.farmers.map((farmer) => (
              <tr key={farmer.id}>
                <td>{farmer.farmer_name}</td>
                <td>{farmer.farm_name}</td>
                <td className="num">{qty(farmer.hectares)}</td>
                <td>{farmer.lines.map((line) => `${line.input_category_label} ${line.product_name}: ${qty(line.quantity)} ${line.unit}`).join('; ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Input</th><th>Variety</th><th className="num">Requested</th><th className="num">Cap</th><th className="num">Approved so far</th><th className="num">Remaining</th></tr></thead>
          <tbody>
            {row.totals.map((line) => (
              <tr key={line.requirement}>
                <td>{line.input_category_label}</td>
                <td>{line.product_name}</td>
                <td className="num"><strong>{qty(line.quantity)} {line.unit}</strong></td>
                <td className="num">{qty(line.cap_quantity)} {line.unit}</td>
                <td className="num">{qty(line.approved_quantity)} {line.unit}</td>
                <td className="num">{qty(line.remaining_quantity)} {line.unit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ol className="timeline">
        {(row.events || []).map((event) => (
          <li key={event.id}>
            <Pill tone={STATUS_TONE[event.action] || ''}>{event.action_label}</Pill>
            <span>{when(event.created_at)} · {event.actor_name || 'System'}</span>
            {event.remarks ? <p>{event.remarks}</p> : null}
          </li>
        ))}
      </ol>
      {canDecide && row.status === 'SUBMITTED' ? (
        <div className="page-actions">
          <button type="button" className="primary-btn" onClick={() => onDecide('approve')}><Icon name="check" />Approve</button>
          <button type="button" className="ghost-btn" onClick={() => onDecide('return-for-corrections')}>Return for corrections</button>
          <button type="button" className="ghost-btn" onClick={() => onDecide('reject')}>Reject</button>
        </div>
      ) : null}
      {canDecide && row.status === 'APPROVED' ? (
        <div className="page-actions">
          <button type="button" className="ghost-btn" onClick={() => onDecide('reverse')}>Reverse approval</button>
        </div>
      ) : null}
    </div>
  )
}

function CapRow({ cap, canEdit, onSave }) {
  const [quantity, setQuantity] = useState(cap.cap_quantity)
  return (
    <tr>
      <td>{cap.programme_name}</td>
      <td>{cap.crop_name}</td>
      <td>{cap.crop_season_label}</td>
      <td>{cap.input_category_label}</td>
      <td>{cap.product_name}</td>
      <td className="num">{qty(cap.cap_quantity)} {cap.unit}</td>
      <td className="num">{qty(cap.approved_quantity)} {cap.unit}</td>
      <td className="num"><strong>{qty(cap.remaining_quantity)} {cap.unit}</strong></td>
      {canEdit ? (
        <td>
          <span className="table-actions">
            <input aria-label={`New cap for ${cap.product_name}`} type="number" min="0" step="0.0001" value={quantity} onChange={(event) => setQuantity(event.target.value)} style={{ width: 120 }} />
            <button type="button" className="ghost-btn" onClick={() => onSave(cap, quantity)}>Save</button>
          </span>
        </td>
      ) : null}
    </tr>
  )
}

export default InputApprovalsPage
