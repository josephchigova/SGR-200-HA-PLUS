// Lead farmer input allocations.
//
// The lead farmer searches for one of their farmers, and the farm fills in. They then add the
// varieties they need and the hectares of each. Quantity and cost come from the catalogue.
// Hectares of one input cannot pass what that farmer intends to plant for the crop. Admin's
// approved hectares, once set, are a separate maximum for the whole submission.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import Icon from '../components/Icon'
import SearchSelect from '../components/SearchSelect'
import { EmptyState, PageHead, Pill, errorMessage } from '../components/ui'
import { canEditSubmission, STATUS_TONE, when } from '../inputSupply'
import { cropSeasonLabel } from '../period'
import { CATEGORY_LABEL, money, qty, requestTotal } from '../programmeData'

const blankLine = () => ({ requirement: '', hectares: '' })
const blankRow = () => ({ key: `${Date.now()}-${Math.random()}`, farmer: '', farm: '', lines: [blankLine()] })

const toAllocationRow = (entry) => ({
  key: `saved-${entry.id}`,
  farmer: String(entry.farmer),
  farm: entry.farm ? String(entry.farm) : '',
  lines: (entry.lines || []).length
    ? entry.lines.map((line) => ({ requirement: String(line.requirement), hectares: String(line.hectares) }))
    : [blankLine()],
})

const filledLines = (row) => (row.lines || []).filter((line) => line.requirement && Number(line.hectares) > 0)

function previewCost(variety, hectares) {
  const quantity = (Number(hectares) || 0) * Number(variety?.rate_per_hectare || 0)
  if (variety?.pack_size && variety?.pack_price) {
    return quantity / Number(variety.pack_size) * Number(variety.pack_price)
  }
  return quantity * Number(variety?.unit_price || 0)
}

function categoryTotals(lines, varieties) {
  const totals = {}
  lines.forEach((line) => {
    const variety = varieties.find((item) => String(item.requirement) === String(line.requirement))
    if (!variety) return
    totals[variety.input_category] = (totals[variety.input_category] || 0) + (Number(line.hectares) || 0)
  })
  return totals
}

function LeadInputAllocationsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const [catalogue, setCatalogue] = useState(null)
  const [programme, setProgramme] = useState('')
  const [crop, setCrop] = useState('')
  const [rows, setRows] = useState([])
  const [dirty, setDirty] = useState(false)
  const [boundKey, setBoundKey] = useState('')
  const [rowNotes, setRowNotes] = useState({})
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const readOnlyYear = Boolean(selectedSeason?.status && selectedSeason.status !== 'ACTIVE')
  const seasonId = selectedSeason?.id || ''
  const requestKey = JSON.stringify([seasonId, cropSeason, token])
  const seasonName = cropSeasonLabel(selectedSeason, cropSeason)

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: seasonId }
    if (cropSeason) params.crop_season = cropSeason
    apiClient.get('/input-supply-requests/catalogue/', { params })
      .then((response) => { if (active) { setCatalogue(response.data); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'The programme catalogue could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, seasonId, cropSeason, requestKey])

  const programmes = catalogue?.programmes || []
  const selectedProgramme = programmes.find((item) => String(item.programme) === programme) || null
  const crops = selectedProgramme?.crops || []
  const selectedCrop = crops.find((item) => String(item.crop) === crop) || null
  const varieties = selectedCrop?.varieties || []
  const farmers = catalogue?.farmers || []
  const loading = !blocked && loadedKey !== requestKey
  const openRequest = (catalogue?.open_requests || []).find((item) => String(item.programme) === programme && String(item.crop) === crop) || null
  const request = openRequest
  const editable = !readOnlyYear && canEditSubmission(request)
  const distributing = request?.stage === 'DISTRIBUTION'
  const limits = request?.limits || []

  useEffect(() => {
    if (!selectedCrop || loading) return undefined
    const nextKey = `${programme}:${crop}:${openRequest?.id || 'new'}:${openRequest?.status || ''}`
    if (dirty && boundKey.startsWith(`${programme}:${crop}:`)) return undefined
    if (boundKey === nextKey) return undefined
    const seeded = openRequest?.farmers?.length ? openRequest.farmers.map(toAllocationRow) : [blankRow()]
    setRows(seeded)
    setDirty(false)
    setRowNotes({})
    setBoundKey(nextKey)
    return undefined
  }, [selectedCrop, loading, programme, crop, openRequest, dirty, boundKey])

  const editRows = (next) => {
    setDirty(true)
    setRows(next)
  }
  const updateRow = (key, changes) => editRows((current) => current.map((row) => (row.key === key ? { ...row, ...changes } : row)))
  const note = (key, message) => setRowNotes((current) => ({ ...current, [key]: message }))

  const chooseFarmer = (key, farmerId) => {
    const farmer = farmers.find((item) => String(item.id) === farmerId)
    const farm = farmer?.farms?.[0]
    const onlyVariety = varieties.length === 1 ? String(varieties[0].requirement) : ''
    editRows((current) => current.map((row) => {
      if (row.key !== key) return row
      const lines = row.lines.some((line) => line.requirement)
        ? row.lines
        : [{ requirement: onlyVariety, hectares: '' }]
      return { ...row, farmer: farmerId, farm: farm ? String(farm.id) : '', lines }
    }))
    note(key, '')
  }

  const setLine = (key, index, changes) => {
    editRows((current) => current.map((row) => {
      if (row.key !== key) return row
      const lines = row.lines.map((line, lineIndex) => (lineIndex === index ? { ...line, ...changes } : line))
      return { ...row, lines }
    }))
  }

  const setHectares = (key, index, raw) => {
    const row = rows.find((item) => item.key === key)
    const farmer = farmers.find((item) => String(item.id) === row?.farmer)
    const intended = farmer ? Number(farmer.crops?.find((item) => String(item.crop) === crop)?.hectares) : NaN
    const variety = varieties.find((item) => String(item.requirement) === String(row?.lines?.[index]?.requirement))
    let value = raw
    let message = ''
    if (variety && Number.isFinite(intended) && raw !== '') {
      const others = (row.lines || []).reduce((total, line, lineIndex) => {
        if (lineIndex === index) return total
        const other = varieties.find((item) => String(item.requirement) === String(line.requirement))
        return other?.input_category === variety.input_category ? total + (Number(line.hectares) || 0) : total
      }, 0)
      const room = Math.max(intended - others, 0)
      if (Number(raw) > room) {
        value = room ? String(room) : ''
        message = `${farmer.name} intends to plant ${qty(intended)} ha of ${selectedCrop.crop_name}. ${variety.input_category_label} cannot go past that.`
      }
    }
    setLine(key, index, { hectares: value })
    note(key, message)
  }

  const preview = []
  const summed = new Map()
  rows.forEach((row) => {
    filledLines(row).forEach((line) => {
      const variety = varieties.find((item) => String(item.requirement) === String(line.requirement))
      if (!variety) return
      const current = summed.get(variety.requirement) || { ...variety, hectares: 0, quantity: 0, cost: 0 }
      current.hectares += Number(line.hectares) || 0
      current.quantity += (Number(line.hectares) || 0) * Number(variety.rate_per_hectare || 0)
      current.cost += previewCost(variety, line.hectares)
      summed.set(variety.requirement, current)
    })
  })
  summed.forEach((value) => preview.push(value))
  const land = rows.reduce((total, row) => total + requestTotal(filledLines(row).map((line) => {
    const variety = varieties.find((item) => String(item.requirement) === String(line.requirement))
    return { input_category: variety?.input_category, hectares: line.hectares }
  })), 0)

  const overLimit = rows.some((row) => {
    const farmer = farmers.find((item) => String(item.id) === row.farmer)
    if (!farmer || !filledLines(row).length) return false
    const intended = farmer.crops?.find((item) => String(item.crop) === crop)
    if (!intended) return true
    const ceiling = Number(intended.hectares)
    return Object.values(categoryTotals(filledLines(row), varieties)).some((area) => area > ceiling + 0.001)
  })

  const payloadFarmers = rows.filter((row) => row.farmer && filledLines(row).length).map((row) => ({
    farmer: Number(row.farmer),
    farm: row.farm ? Number(row.farm) : undefined,
    lines: filledLines(row).map((line) => ({ requirement: Number(line.requirement), hectares: line.hectares })),
  }))

  const payload = () => ({
    programme: Number(programme),
    season: seasonId,
    crop: Number(crop),
    crop_season: cropSeason || undefined,
    farmers: payloadFarmers,
  })

  const save = async (andSubmit) => {
    if (!payloadFarmers.length) {
      setError('Choose a farmer and enter the hectares of at least one variety.')
      return
    }
    if (overLimit) {
      setError('Input hectares cannot exceed what the farmer intends to plant.')
      return
    }
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
      const nextRows = current.farmers?.length ? current.farmers.map(toAllocationRow) : [blankRow()]
      setRows(nextRows)
      setDirty(false)
      setRowNotes({})
      setBoundKey(`${programme}:${crop}:${current.id}:${current.status}`)
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
        subtitle="Choose the agricultural year and season above, then a programme and crop. Search for each farmer, and enter the hectares of the varieties they need. Quantities and costs are calculated for you."
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
      {request?.status === 'SUBMITTED' && !distributing && editable ? (
        <div className="form-message" role="status">
          {request.reference} is submitted. Search for another farmer and submit them on this same programme. It stays open until Admin sets the hectare limits.
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
            <select value={programme} onChange={(event) => { setProgramme(event.target.value); setCrop(''); setRows([]); setDirty(false); setBoundKey(''); setRowNotes({}) }} disabled={blocked}>
              <option value="">Select a programme</option>
              {programmes.map((item) => <option key={item.programme} value={item.programme}>{item.programme_name}</option>)}
            </select>
          </label>
          <label className="form-field">Crop
            <select value={crop} onChange={(event) => { setCrop(event.target.value); setRows([]); setDirty(false); setBoundKey(''); setRowNotes({}) }} disabled={!selectedProgramme}>
              <option value="">Select a crop</option>
              {crops.map((item) => <option key={item.crop} value={item.crop}>{item.crop_name} ({item.crop_season_label})</option>)}
            </select>
          </label>
        </div>
        {loading ? <div className="form-message">Loading the catalogue…</div> : null}
        {!loading && catalogue && !programmes.length ? <EmptyState icon="box" title="No programme catalogue">Admin has not configured varieties for {selectedSeason?.name}{seasonName ? ` ${seasonName}` : ''} yet.</EmptyState> : null}
        {selectedCrop ? <p className="card-sub">{varieties.length} varieties are in this catalogue. Add only the ones each farmer needs. The rate and price appear on the line you choose.</p> : null}
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
            <div>
              <h3>Your farmers</h3>
              <p className="card-sub">Search for a farmer and the farm fills in. Add the next farmer with the button here. Each farmer only lists the varieties you add.</p>
            </div>
            {editable ? <button type="button" className="ghost-btn" onClick={() => editRows((current) => [...current, blankRow()])}><Icon name="plus" />Add farmer</button> : null}
          </div>
          {!farmers.length ? <EmptyState icon="users" title="No farmers in your cluster">Farmers you register appear here once they can receive inputs.</EmptyState> : null}
          {rows.map((row, index) => {
            const farmer = farmers.find((item) => String(item.id) === row.farmer)
            const intended = farmer?.crops?.find((item) => String(item.crop) === crop)
            const taken = new Set(rows.filter((item) => item.key !== row.key && item.farmer).map((item) => String(item.farmer)))
            const farmerOptions = farmers
              .filter((item) => String(item.id) === row.farmer || !taken.has(String(item.id)))
              .map((item) => ({ value: String(item.id), label: item.name }))
            const usedVarieties = new Set(row.lines.map((line) => String(line.requirement)).filter(Boolean))
            const farms = farmer?.farms || []
            return (
              <div key={row.key} className="card" style={{ marginBottom: 12 }}>
                <div className="filter-row">
                  <SearchSelect
                    label={`Farmer ${index + 1}`}
                    searchable
                    value={row.farmer}
                    options={farmerOptions}
                    placeholder="Search or choose a farmer"
                    disabled={!editable}
                    emptyText="No other farmers in your cluster."
                    onChange={(farmerId) => chooseFarmer(row.key, farmerId)}
                  />
                  <label className="form-field">Farm
                    {farms.length > 1 ? (
                      <select aria-label={`Farm for farmer ${index + 1}`} value={row.farm} disabled={!editable} onChange={(event) => updateRow(row.key, { farm: event.target.value })}>
                        {farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.name}</option>)}
                      </select>
                    ) : (
                      <input aria-label={`Farm for farmer ${index + 1}`} value={farms[0]?.name || (row.farmer ? 'No farm recorded' : '')} placeholder="Fills in when you choose a farmer" readOnly />
                    )}
                  </label>
                  {editable && rows.length > 1 ? <button type="button" className="ghost-btn" onClick={() => editRows((current) => current.filter((item) => item.key !== row.key))}>Remove</button> : null}
                </div>
                {farmer && intended ? <p className="card-sub">{farmer.name} intends to plant {qty(intended.hectares)} ha of {selectedCrop.crop_name}. Each input stays within that.</p> : null}
                {farmer && !intended ? <p className="card-sub">{farmer.name} has no intended planting for {selectedCrop.crop_name}. Record it on the farmer's registration before allocating inputs.</p> : null}
                {rowNotes[row.key] ? <div className="form-message error" role="alert">{rowNotes[row.key]}</div> : null}
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Variety</th><th>Hectares</th><th className="num">Quantity</th><th className="num">Estimated cost</th><th></th></tr></thead>
                    <tbody>
                      {row.lines.map((line, lineIndex) => {
                        const variety = varieties.find((item) => String(item.requirement) === String(line.requirement))
                        const quantity = (Number(line.hectares) || 0) * Number(variety?.rate_per_hectare || 0)
                        const varietyOptions = varieties
                          .filter((item) => String(item.requirement) === String(line.requirement) || !usedVarieties.has(String(item.requirement)))
                          .map((item) => ({ value: String(item.requirement), label: `${item.input_category_label} · ${item.product_name} · ${qty(item.rate_per_hectare)} ${item.unit}/ha · ${item.pack_size ? `${money(item.pack_price)} / ${qty(item.pack_size)} ${item.unit}` : money(item.unit_price)}` }))
                        return (
                          <tr key={`${row.key}-${lineIndex}`}>
                            <td>
                              <SearchSelect
                                label={`Variety ${lineIndex + 1} for farmer ${index + 1}`}
                                searchable
                                value={line.requirement}
                                options={varietyOptions}
                                placeholder="Search or choose a variety"
                                disabled={!editable || !row.farmer}
                                onChange={(requirementId) => setLine(row.key, lineIndex, { requirement: requirementId })}
                              />
                            </td>
                            <td>
                              <input
                                aria-label={variety ? `Hectares of ${variety.product_name} for farmer ${index + 1}` : `Hectares for farmer ${index + 1} line ${lineIndex + 1}`}
                                type="number"
                                min="0"
                                step="0.01"
                                value={line.hectares}
                                disabled={!editable || !line.requirement}
                                onChange={(event) => setHectares(row.key, lineIndex, event.target.value)}
                                style={{ width: 120 }}
                              />
                            </td>
                            <td className="num">{line.hectares && variety ? `${qty(quantity)} ${variety.unit}` : '—'}</td>
                            <td className="num">{line.hectares && variety ? money(previewCost(variety, line.hectares)) : '—'}</td>
                            <td>
                              {editable && row.lines.length > 1 ? (
                                <button type="button" className="icon-btn danger" aria-label={`Remove variety ${lineIndex + 1} for farmer ${index + 1}`} onClick={() => editRows((current) => current.map((item) => item.key === row.key ? { ...item, lines: item.lines.filter((_, itemIndex) => itemIndex !== lineIndex) } : item))}>
                                  <Icon name="trash" />
                                </button>
                              ) : null}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                {editable ? (
                  <button type="button" className="ghost-btn small" disabled={!row.farmer || row.lines.length >= varieties.length} onClick={() => editRows((current) => current.map((item) => item.key === row.key ? { ...item, lines: [...item.lines, blankLine()] } : item))}>
                    <Icon name="plus" />Add variety
                  </button>
                ) : null}
              </div>
            )
          })}
          <h3>{distributing ? 'Distribution' : 'Consolidated submission'}</h3>
          <p className="card-sub">Land allocated {qty(land)} ha. Varieties of one input type add together. Seed, fertilizer and chemicals share the same land, so the total is the largest of those.</p>
          {!preview.length ? <p className="card-sub">Choose a variety and enter hectares. The quantity is hectares times the catalogue rate, and the cost uses that programme's price.</p> : (
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
          {request && !dirty ? (
            <p className="card-sub">Last saved calculation: {qty(request.hectares_total)} ha, {money(request.estimated_cost)}. These figures come from the server.</p>
          ) : null}
          {editable ? (
            <div className="page-actions" style={{ marginTop: 16 }}>
              <button type="button" className="ghost-btn" disabled={saving || !payloadFarmers.length || overLimit} onClick={() => save(false)}>{saving ? 'Saving…' : 'Save draft'}</button>
              <button type="button" className="primary-btn" disabled={saving || !payloadFarmers.length || overLimit} onClick={() => save(true)}>
                <Icon name="send" />{distributing ? 'Submit final distribution' : request?.status === 'SUBMITTED' ? 'Submit another farmer' : 'Submit for approval'}
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
