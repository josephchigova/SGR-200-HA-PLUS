// Lead farmer input allocations.
//
// Admin has already decided which varieties are available, and how much of each. The lead
// farmer chooses their own farmers, the hectares and the varieties. Quantities are hectares
// times the catalogue rate. Saving does not send totals: the server calculates and stores them.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import Icon from '../components/Icon'
import { EmptyState, PageHead, Pill, errorMessage } from '../components/ui'
import { CATEGORY_LABEL, qty } from '../programmeData'
import { STATUS_TONE, when } from '../inputSupply'

const blankRow = () => ({ key: `${Date.now()}-${Math.random()}`, farmer: '', farm: '', hectares: '', requirements: [] })

const toAllocationRow = (entry) => ({
  key: `saved-${entry.id}`,
  farmer: String(entry.farmer),
  farm: String(entry.farm),
  hectares: entry.hectares,
  requirements: entry.lines.map((line) => line.requirement),
})

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

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id }
    if (cropSeason) params.crop_season = cropSeason
    apiClient.get('/input-supply-requests/catalogue/', { params })
      .then((response) => { if (active) { setCatalogue(response.data); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Available varieties could not be loaded.')) })
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
  const editable = !request || request.status === 'DRAFT' || request.status === 'RETURNED'
  const totals = []
  const summed = new Map()
  rows.forEach((row) => {
    row.requirements.forEach((requirementId) => {
      const variety = varieties.find((item) => item.requirement === requirementId)
      if (!variety) return
      const quantity = (Number(row.hectares) || 0) * Number(variety.rate_per_hectare || 0)
      const current = summed.get(requirementId) || { ...variety, quantity: 0 }
      current.quantity += quantity
      summed.set(requirementId, current)
    })
  })
  summed.forEach((value) => totals.push(value))

  const replaceRows = (next) => setOverride({ programme, crop, request, rows: typeof next === 'function' ? next(rows) : next })

  const updateRow = (key, changes) => replaceRows((current) => current.map((row) => (row.key === key ? { ...row, ...changes } : row)))

  const chooseFarmer = (key, farmerId) => {
    const farmer = farmers.find((item) => String(item.id) === farmerId)
    const farm = farmer?.farms?.[0]
    const allocated = farmer?.crops?.find((item) => String(item.crop) === crop)
    updateRow(key, { farmer: farmerId, farm: farm ? String(farm.id) : '', hectares: allocated?.hectares || '' })
  }

  const toggleVariety = (key, requirementId) => {
    const row = rows.find((item) => item.key === key)
    const selected = row.requirements.includes(requirementId)
    updateRow(key, { requirements: selected ? row.requirements.filter((id) => id !== requirementId) : [...row.requirements, requirementId] })
  }

  const payload = () => ({
    programme: Number(programme),
    season: selectedSeason.id,
    crop: Number(crop),
    crop_season: cropSeason || undefined,
    farmers: rows.map((row) => ({
      farmer: Number(row.farmer),
      farm: row.farm ? Number(row.farm) : undefined,
      hectares: row.hectares,
      requirements: row.requirements,
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
      setOverride({ programme, crop, request: current, rows: current.farmers.map(toAllocationRow) })
      setNotice(andSubmit ? `${current.reference} submitted for approval.` : `${current.reference} saved. The quantities below are calculated from the crop catalogue.`)
      setToken((value) => value + 1)
    } catch (requestError) {
      setError(errorMessage(requestError, andSubmit ? 'The request could not be submitted.' : 'The allocation could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page-card">
      <PageHead
        title="Input allocations"
        subtitle="Choose a programme and crop, then split the varieties Admin has made available across your farmers. Quantities are calculated from each farmer's hectares. Submit the total when it is ready."
      />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {readOnlyYear ? <div className="form-message">{selectedSeason.name} is not the active agricultural year, so allocations are read-only.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {request?.status === 'RETURNED' ? (
        <div className="form-message" role="status">
          Admin returned {request.reference} for corrections{request.decision_notes ? `: ${request.decision_notes}` : '.'} Update the allocations and submit again.
        </div>
      ) : null}
      {request && !editable ? (
        <div className="form-message" role="status">
          {request.reference} is {request.status_label.toLowerCase()}. <Link to="/my-input-requests">View it in your requests</Link>.
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
        {loading ? <div className="form-message">Loading varieties…</div> : null}
        {!loading && catalogue && !programmes.length ? <EmptyState icon="box" title="No varieties are available">Admin has not set input caps for {selectedSeason?.name} yet.</EmptyState> : null}
        {selectedCrop ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Input</th><th>Variety</th><th>Per hectare</th><th className="num">Available cap</th><th className="num">Already approved</th><th className="num">Remaining</th></tr></thead>
              <tbody>
                {varieties.map((variety) => (
                  <tr key={variety.id}>
                    <td>{variety.input_category_label}</td>
                    <td>{variety.product_name}</td>
                    <td>{qty(variety.rate_per_hectare)} {variety.unit}</td>
                    <td className="num">{qty(variety.cap_quantity)} {variety.unit}</td>
                    <td className="num">{qty(variety.approved_quantity)} {variety.unit}</td>
                    <td className="num"><strong>{qty(variety.remaining_quantity)} {variety.unit}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {selectedCrop ? (
        <section className="card">
          <div className="card-head">
            <h3>Your farmers</h3>
            {editable && !readOnlyYear ? <button type="button" className="ghost-btn" onClick={() => replaceRows((current) => [...current, blankRow()])}><Icon name="plus" />Add farmer</button> : null}
          </div>
          {!farmers.length ? <EmptyState icon="users" title="No farmers in your cluster">Farmers you register appear here once they can receive inputs.</EmptyState> : null}
          {rows.map((row, index) => {
            const farmer = farmers.find((item) => String(item.id) === row.farmer)
            return (
              <div key={row.key} className="card" style={{ marginBottom: 12 }}>
                <div className="filter-row">
                  <label className="form-field">Farmer {index + 1}
                    <select value={row.farmer} disabled={!editable || readOnlyYear} onChange={(event) => chooseFarmer(row.key, event.target.value)}>
                      <option value="">Select a farmer</option>
                      {farmers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                  </label>
                  <label className="form-field">Farm
                    <select value={row.farm} disabled={!editable || readOnlyYear} onChange={(event) => updateRow(row.key, { farm: event.target.value })}>
                      <option value="">Select a farm</option>
                      {(farmer?.farms || []).map((farm) => <option key={farm.id} value={farm.id}>{farm.name}</option>)}
                    </select>
                  </label>
                  <label className="form-field">Hectares
                    <input type="number" min="0" step="0.01" value={row.hectares} disabled={!editable || readOnlyYear} onChange={(event) => updateRow(row.key, { hectares: event.target.value })} />
                  </label>
                  {editable && !readOnlyYear ? <button type="button" className="ghost-btn" onClick={() => replaceRows((current) => current.filter((item) => item.key !== row.key))}>Remove</button> : null}
                </div>
                <div className="filter-row">
                  {varieties.map((variety) => (
                    <label key={variety.requirement} className="check-row">
                      <input
                        type="checkbox"
                        checked={row.requirements.includes(variety.requirement)}
                        disabled={!editable || readOnlyYear}
                        onChange={() => toggleVariety(row.key, variety.requirement)}
                      />
                      {variety.input_category_label}: {variety.product_name}
                      {row.hectares ? <small> · {qty((Number(row.hectares) || 0) * Number(variety.rate_per_hectare))} {variety.unit}</small> : null}
                    </label>
                  ))}
                </div>
              </div>
            )
          })}

          <h3>Consolidated request</h3>
          {!totals.length ? <p className="card-sub">Add farmers and varieties. The total of each variety is calculated here and again on the server when you save.</p> : (
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Input</th><th>Variety</th><th className="num">Total requested</th></tr></thead>
                <tbody>
                  {totals.map((row) => (
                    <tr key={row.requirement}>
                      <td>{row.input_category_label || CATEGORY_LABEL[row.input_category]}</td>
                      <td>{row.product_name}</td>
                      <td className="num"><strong>{qty(row.quantity)} {row.unit}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {editable && !readOnlyYear ? (
            <div className="page-actions" style={{ marginTop: 16 }}>
              <button type="button" className="ghost-btn" disabled={saving || !rows.length} onClick={() => save(false)}>{saving ? 'Saving…' : 'Save draft'}</button>
              <button type="button" className="primary-btn" disabled={saving || !rows.length} onClick={() => save(true)}><Icon name="send" />Submit for approval</button>
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
