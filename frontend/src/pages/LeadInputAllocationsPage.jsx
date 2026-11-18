// Lead farmer input allocations.
//
// The lead farmer chooses their own farmers, a programme variety and the hectares for that
// variety. Quantity and cost are calculated from the catalogue. Admin's approved hectares,
// once set, are a maximum: unused hectares stay unused, and the total cannot go over them.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import Icon from '../components/Icon'
import { EmptyState, PageHead, Pill, errorMessage } from '../components/ui'
import { canEditSubmission, STATUS_TONE, when } from '../inputSupply'
import { cropSeasonLabel } from '../period'
import { CATEGORY_LABEL, money, qty, requestTotal } from '../programmeData'

const blankRow = () => ({ key: `${Date.now()}-${Math.random()}`, farmer: '', farm: '', lines: {} })

const toAllocationRow = (entry) => ({
  key: `saved-${entry.id}`,
  farmer: String(entry.farmer),
  farm: String(entry.farm),
  lines: Object.fromEntries((entry.lines || []).map((line) => [String(line.requirement), line.hectares])),
})

const positiveLines = (row) => Object.entries(row.lines || {}).filter(([, hectares]) => Number(hectares) > 0)

function previewCost(variety, hectares) {
  const quantity = (Number(hectares) || 0) * Number(variety?.rate_per_hectare || 0)
  if (variety?.pack_size && variety?.pack_price) {
    return quantity / Number(variety.pack_size) * Number(variety.pack_price)
  }
  return quantity * Number(variety?.unit_price || 0)
}

function LeadInputAllocationsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const [catalogue, setCatalogue] = useState(null)
  const [programme, setProgramme] = useState('')
  const [crop, setCrop] = useState('')
  const [override, setOverride] = useState(null)
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const readOnlyYear = Boolean(selectedSeason?.status && selectedSeason.status !== 'ACTIVE')
  const requestKey = JSON.stringify([selectedSeason?.id, cropSeason, token])
  const seasonName = cropSeasonLabel(selectedSeason, cropSeason)

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id }
    if (cropSeason) params.crop_season = cropSeason
    apiClient.get('/input-supply-requests/catalogue/', { params })
      .then((response) => { if (active) { setCatalogue(response.data); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'The programme catalogue could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, requestKey])

  const programmes = catalogue?.programmes || []
  const selectedProgramme = programmes.find((item) => String(item.programme) === programme) || null
  const crops = selectedProgramme?.crops || []
  const selectedCrop = crops.find((item) => String(item.crop) === crop) || null
  const varieties = selectedCrop?.varieties || []
  const farmers = catalogue?.farmers || []
  const loading = !blocked && loadedKey !== requestKey
  const openRequest = (catalogue?.open_requests || []).find((item) => String(item.programme) === programme && String(item.crop) === crop) || null
  const usingOverride = override && override.programme === programme && override.crop === crop
  const request = usingOverride ? override.request : openRequest
  const rows = usingOverride ? override.rows : (openRequest ? openRequest.farmers.map(toAllocationRow) : [])
  const editable = !readOnlyYear && canEditSubmission(request)
  const distributing = request?.stage === 'DISTRIBUTION'
  const limits = request?.limits || []

  const replaceRows = (next, dirty = true) => setOverride({
    programme,
    crop,
    request,
    dirty,
    rows: typeof next === 'function' ? next(rows) : next,
  })
  const updateRow = (key, changes) => replaceRows((current) => current.map((row) => (row.key === key ? { ...row, ...changes } : row)))
  const chooseFarmer = (key, farmerId) => {
    const farmer = farmers.find((item) => String(item.id) === farmerId)
    const farm = farmer?.farms?.[0]
    updateRow(key, { farmer: farmerId, farm: farm ? String(farm.id) : '' })
  }
  const setHectares = (key, requirementId, hectares) => {
    const row = rows.find((item) => item.key === key)
    updateRow(key, { lines: { ...row.lines, [requirementId]: hectares } })
  }

  const preview = []
  const summed = new Map()
  rows.forEach((row) => {
    positiveLines(row).forEach(([requirementId, hectares]) => {
      const variety = varieties.find((item) => String(item.requirement) === String(requirementId))
      if (!variety) return
      const current = summed.get(variety.requirement) || { ...variety, hectares: 0, quantity: 0, cost: 0 }
      current.hectares += Number(hectares) || 0
      current.quantity += (Number(hectares) || 0) * Number(variety.rate_per_hectare || 0)
      current.cost += previewCost(variety, hectares)
      summed.set(variety.requirement, current)
    })
  })
  summed.forEach((value) => preview.push(value))
  const land = rows.reduce((total, row) => total + requestTotal(positiveLines(row).map(([requirementId, hectares]) => {
    const variety = varieties.find((item) => String(item.requirement) === String(requirementId))
    return { input_category: variety?.input_category, hectares }
  })), 0)

  const payload = () => ({
    programme: Number(programme),
    season: selectedSeason.id,
    crop: Number(crop),
    crop_season: cropSeason || undefined,
    farmers: rows.filter((row) => row.farmer).map((row) => ({
      farmer: Number(row.farmer),
      farm: row.farm ? Number(row.farm) : undefined,
      lines: positiveLines(row).map(([requirementId, hectares]) => ({
        requirement: Number(requirementId),
        hectares,
      })),
    })),
  })

  const save = async (andSubmit) => {
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const saved = await apiClient.post('/input-supply-requests/', payload())
      let current = saved.data
      if (andSubmit) {
        const submitted = await apiClient.post(`/input-supply-requests/${saved.data.id}/submit/`)
        current = submitted.data
      }
      setOverride({ programme, crop, request: current, dirty: false, rows: current.farmers.map(toAllocationRow) })
      const savedLand = `${qty(current.hectares_total)} ha`
      const savedCost = money(current.estimated_cost)
      setNotice(andSubmit
        ? `${current.reference} ${current.status_label.toLowerCase()}. Calculated total ${savedLand}, estimated cost ${savedCost}.`
        : `${current.reference} saved. Quantities and costs were calculated from the catalogue (${savedLand}, ${savedCost}).`)
      setToken((value) => value + 1)
    } catch (requestError) {
      setError(errorMessage(requestError, andSubmit ? 'The submission could not be sent.' : 'The allocation could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page-card">
      <PageHead
        title="Input allocations"
        subtitle="Choose the agricultural year and season above, then a programme, crop and variety. Enter the hectares for each variety. Quantities and costs are calculated for you."
      />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {readOnlyYear ? <div className="form-message">{selectedSeason.name} is not the active agricultural year, so allocations are read-only.</div> : null}
      {!blocked ? <p className="card-sub">Agricultural year {selectedSeason.name}{seasonName ? ` · ${seasonName} season` : ''}.</p> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {request?.status === 'RETURNED' ? (
        <div className="form-message" role="status">
          Admin returned {request.reference} for corrections{request.decision_notes ? `: ${request.decision_notes}` : '.'} Update the allocations and submit again.
        </div>
      ) : null}
      {distributing && editable ? (
        <div className="form-message" role="status">
          Admin approved a maximum of {qty(limits.find((limit) => limit.scope === 'CROP')?.approved_hectares)} ha for this crop.
          Share it across your farmers. Hectares you do not use stay unallocated.
        </div>
      ) : null}
      {request && !editable ? (
        <div className="form-message" role="status">
          {request.reference} is {request.status_label.toLowerCase()}. <Link to="/my-input-requests">Open it in your submission history</Link>.
        </div>
      ) : null}

      <section className="card">
        <div className="filter-row">
          <label className="form-field">Programme
            <select value={programme} onChange={(event) => { setProgramme(event.target.value); setCrop(''); setOverride(null) }} disabled={blocked}>
              <option value="">Select a programme</option>
              {programmes.map((item) => <option key={item.programme} value={item.programme}>{item.programme_name}</option>)}
            </select>
          </label>
          <label className="form-field">Crop
            <select value={crop} onChange={(event) => { setCrop(event.target.value); setOverride(null) }} disabled={!selectedProgramme}>
              <option value="">Select a crop</option>
              {crops.map((item) => <option key={item.crop} value={item.crop}>{item.crop_name} ({item.crop_season_label})</option>)}
            </select>
          </label>
        </div>
        {loading ? <div className="form-message">Loading the catalogue…</div> : null}
        {!loading && catalogue && !programmes.length ? <EmptyState icon="box" title="No programme catalogue">Admin has not configured varieties for {selectedSeason?.name}{seasonName ? ` ${seasonName}` : ''} yet.</EmptyState> : null}
        {selectedCrop ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Input</th><th>Variety</th><th>Unit</th><th className="num">Rate per hectare</th><th className="num">Unit price</th></tr></thead>
              <tbody>
                {varieties.map((variety) => (
                  <tr key={variety.requirement}>
                    <td>{variety.input_category_label}</td>
                    <td>{variety.product_name}</td>
                    <td>{variety.unit}</td>
                    <td className="num">{qty(variety.rate_per_hectare)} {variety.unit}</td>
                    <td className="num">{variety.pack_size ? `${money(variety.pack_price)} / ${qty(variety.pack_size)} ${variety.unit}` : money(variety.unit_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {limits.length ? (
        <section className="card">
          <div className="card-head"><h3>Approved hectare limits</h3></div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Level</th><th>Item</th><th className="num">Requested</th><th className="num">Approved maximum</th><th className="num">Allocated now</th><th className="num">Still available</th></tr></thead>
              <tbody>
                {limits.map((limit) => (
                  <tr key={limit.id}>
                    <td>{limit.scope_label}</td>
                    <td>{limit.name}</td>
                    <td className="num">{qty(limit.requested_hectares)} ha</td>
                    <td className="num"><strong>{qty(limit.approved_hectares)} ha</strong></td>
                    <td className="num">{qty(limit.allocated_hectares)} ha</td>
                    <td className="num">{qty(limit.remaining_hectares)} ha</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {selectedCrop ? (
        <section className="card">
          <div className="card-head">
            <h3>Your farmers</h3>
            {editable ? <button type="button" className="ghost-btn" onClick={() => replaceRows((current) => [...current, blankRow()])}><Icon name="plus" />Add farmer</button> : null}
          </div>
          {!farmers.length ? <EmptyState icon="users" title="No farmers in your cluster">Farmers you register appear here once they can receive inputs.</EmptyState> : null}
          {rows.map((row, index) => {
            const farmer = farmers.find((item) => String(item.id) === row.farmer)
            const approved = farmer?.crops?.find((item) => String(item.crop) === crop)
            return (
              <div key={row.key} className="card" style={{ marginBottom: 12 }}>
                <div className="filter-row">
                  <label className="form-field">Farmer {index + 1}
                    <select value={row.farmer} disabled={!editable} onChange={(event) => chooseFarmer(row.key, event.target.value)}>
                      <option value="">Select a farmer</option>
                      {farmers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                  </label>
                  <label className="form-field">Farm
                    <select value={row.farm} disabled={!editable} onChange={(event) => updateRow(row.key, { farm: event.target.value })}>
                      <option value="">Select a farm</option>
                      {(farmer?.farms || []).map((farm) => <option key={farm.id} value={farm.id}>{farm.name}</option>)}
                    </select>
                  </label>
                  {editable ? <button type="button" className="ghost-btn" onClick={() => replaceRows((current) => current.filter((item) => item.key !== row.key))}>Remove</button> : null}
                </div>
                {approved ? <p className="card-sub">Approved {selectedCrop.crop_name}: {qty(approved.hectares)} ha. Each input category must stay within that.</p> : null}
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Input</th><th>Variety</th><th>Hectares</th><th className="num">Quantity</th><th className="num">Estimated cost</th></tr></thead>
                    <tbody>
                      {varieties.map((variety) => {
                        const hectares = row.lines[String(variety.requirement)] ?? row.lines[variety.requirement] ?? ''
                        const quantity = (Number(hectares) || 0) * Number(variety.rate_per_hectare || 0)
                        return (
                          <tr key={variety.requirement}>
                            <td>{variety.input_category_label}</td>
                            <td>{variety.product_name}</td>
                            <td>
                              <input
                                aria-label={`Hectares of ${variety.product_name} for farmer ${index + 1}`}
                                type="number"
                                min="0"
                                step="0.01"
                                value={hectares}
                                disabled={!editable}
                                onChange={(event) => setHectares(row.key, String(variety.requirement), event.target.value)}
                                style={{ width: 120 }}
                              />
                            </td>
                            <td className="num">{hectares ? `${qty(quantity)} ${variety.unit}` : '—'}</td>
                            <td className="num">{hectares ? money(previewCost(variety, hectares)) : '—'}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          })}

          <h3>{distributing ? 'Distribution' : 'Consolidated submission'}</h3>
          <p className="card-sub">Land allocated {qty(land)} ha. Varieties of one input type add together. Seed, fertilizer and chemicals share the same land, so the total is the largest of those.</p>
          {!preview.length ? <p className="card-sub">Enter hectares against a variety. The quantity is hectares times the catalogue rate, and the cost uses that programme's price.</p> : (
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Input</th><th>Variety</th><th className="num">Hectares</th><th className="num">Quantity</th><th className="num">Estimated cost</th></tr></thead>
                <tbody>
                  {preview.map((row) => (
                    <tr key={row.requirement}>
                      <td>{row.input_category_label || CATEGORY_LABEL[row.input_category]}</td>
                      <td>{row.product_name}</td>
                      <td className="num">{qty(row.hectares)} ha</td>
                      <td className="num"><strong>{qty(row.quantity)} {row.unit}</strong></td>
                      <td className="num">{money(row.cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {request && !override?.dirty ? (
            <p className="card-sub">Last saved calculation: {qty(request.hectares_total)} ha, {money(request.estimated_cost)}. These figures come from the server.</p>
          ) : null}
          {editable ? (
            <div className="page-actions" style={{ marginTop: 16 }}>
              <button type="button" className="ghost-btn" disabled={saving || !rows.length} onClick={() => save(false)}>{saving ? 'Saving…' : 'Save draft'}</button>
              <button type="button" className="primary-btn" disabled={saving || !rows.length} onClick={() => save(true)}>
                <Icon name="send" />{distributing ? 'Submit final distribution' : 'Submit for approval'}
              </button>
            </div>
          ) : null}
          {request?.events?.length ? (
            <ol className="timeline">
              {request.events.map((event) => (
                <li key={event.id}>
                  <Pill tone={STATUS_TONE[event.action] || ''}>{event.action_label}</Pill>
                  <span>{when(event.created_at)} · {event.actor_name || 'System'}</span>
                  {event.remarks ? <p>{event.remarks}</p> : null}
                </li>
              ))}
            </ol>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}

export default LeadInputAllocationsPage
