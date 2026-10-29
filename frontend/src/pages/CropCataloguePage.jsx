import { useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'

const costTypeChoices = [
  ['AGRICULTURAL_INPUT', 'Agricultural input'],
  ['OTHER_OPERATIONAL', 'Other agricultural inputs (not debt)'],
]

const toList = (data) => (Array.isArray(data) ? data : data?.results || [])

const dedupeCrops = (records) => {
  const byName = new Map()
  records.forEach((crop) => {
    const key = String(crop.name || '').trim().toLowerCase()
    if (!key) return
    const existing = byName.get(key)
    if (!existing || Number(crop.id) < Number(existing.id)) {
      byName.set(key, crop)
    }
  })
  return Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name))
}

function CropCataloguePage() {
  const [crops, setCrops] = useState([])
  const [selectedCropId, setSelectedCropId] = useState('')
  const [requirements, setRequirements] = useState([])
  const [seasons, setSeasons] = useState([])
  const [prices, setPrices] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [editingRequirementId, setEditingRequirementId] = useState(null)
  const [editingPriceId, setEditingPriceId] = useState(null)
  const [pendingDelete, setPendingDelete] = useState(null)

  const [requirementForm, setRequirementForm] = useState({
    group_name: '',
    item_name: '',
    rate_per_hectare: '',
    unit: '',
    cost_per_unit: '',
    cost_per_hectare: '',
    cost_type: 'AGRICULTURAL_INPUT',
    include_in_input_cost: true,
    active: true,
    notes: '',
  })

  const [priceForm, setPriceForm] = useState({
    season: '',
    price_per_tonne: '',
    currency: 'USD',
    active: true,
  })

  const selectedCrop = useMemo(
    () => crops.find((crop) => String(crop.id) === String(selectedCropId)) || null,
    [crops, selectedCropId],
  )

  const calculatedCostPerHa = useMemo(() => {
    const rate = Number(requirementForm.rate_per_hectare || 0)
    const costPerUnit = Number(requirementForm.cost_per_unit || 0)
    if (!Number.isFinite(rate) || !Number.isFinite(costPerUnit)) return '0.0000'
    return String((rate * costPerUnit).toFixed(4))
  }, [requirementForm.rate_per_hectare, requirementForm.cost_per_unit])

  const totalCostPerHa = useMemo(
    () => requirements
      .filter((requirement) => requirement.active && requirement.include_in_input_cost)
      .reduce((sum, requirement) => sum + Number(requirement.cost_per_hectare || 0), 0),
    [requirements],
  )

  const loadCrops = async (preferredCropId = '') => {
    const response = await apiClient.get('/crops/?active=true')
    const records = dedupeCrops(toList(response.data))
    setCrops(records)
    if (records.length === 0) {
      setSelectedCropId('')
      return
    }
    const hasPreferred = preferredCropId && records.some((crop) => String(crop.id) === String(preferredCropId))
    setSelectedCropId(hasPreferred ? String(preferredCropId) : '')
  }

  const loadRequirements = async (cropId) => {
    if (!cropId) {
      setRequirements([])
      return
    }
    const response = await apiClient.get(`/crop-input-requirements/?crop=${cropId}`)
    setRequirements(toList(response.data))
  }

  const loadPrices = async (cropId) => {
    if (!cropId) {
      setPrices([])
      return
    }
    const response = await apiClient.get(`/crop-selling-prices/?crop=${cropId}`)
    setPrices(toList(response.data).filter((row) => /^\d{4}\/\d{4}$/.test(String(row.season_name || ''))))
  }

  const loadSeasons = async () => {
    const response = await apiClient.get('/seasons/')
    const years = toList(response.data).filter((season) => season.selectable !== false)
    setSeasons(years)
    setPriceForm((current) => ({ ...current, season: current.season || (years[0] ? String(years[0].id) : '') }))
  }

  useEffect(() => {
    let mounted = true
    const load = async () => {
      setLoading(true)
      try {
        await Promise.all([loadCrops(), loadSeasons()])
        if (mounted) setError('')
      } catch {
        if (mounted) setError('Unable to load crop catalogue.')
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [])

  useEffect(() => {
    const loadDetails = async () => {
      try {
        await Promise.all([loadRequirements(selectedCropId), loadPrices(selectedCropId)])
      } catch {
        setError('Unable to load crop requirements.')
      }
    }
    loadDetails()
  }, [selectedCropId])

  const refresh = async () => {
    setLoading(true)
    try {
      await Promise.all([loadCrops(), loadSeasons()])
      setError('')
    } catch {
      setError('Unable to load crop catalogue.')
    } finally {
      setLoading(false)
    }
  }

  const submitRequirement = async (event) => {
    event.preventDefault()
    if (!selectedCropId) return
    setSaving(true)
    setError('')
    setMessage('')
    const payload = {
      ...requirementForm,
      crop: Number(selectedCropId),
      cost_per_unit: requirementForm.cost_per_unit === '' ? null : requirementForm.cost_per_unit,
      cost_per_hectare: calculatedCostPerHa,
    }
    try {
      if (editingRequirementId) {
        await apiClient.patch(`/crop-input-requirements/${editingRequirementId}/`, payload)
        setMessage('Input requirement updated.')
      } else {
        await apiClient.post('/crop-input-requirements/', payload)
        setMessage('Input requirement added.')
      }
      setEditingRequirementId(null)
      setRequirementForm({
        group_name: '',
        item_name: '',
        rate_per_hectare: '',
        unit: '',
        cost_per_unit: '',
        cost_per_hectare: '',
        cost_type: 'AGRICULTURAL_INPUT',
        include_in_input_cost: true,
        active: true,
        notes: '',
      })
      await Promise.all([loadRequirements(selectedCropId), loadCrops(selectedCropId)])
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'Unable to save crop requirement.')
    } finally {
      setSaving(false)
    }
  }

  const submitPrice = async (event) => {
    event.preventDefault()
    if (!selectedCropId) return
    setSaving(true)
    setError('')
    setMessage('')
    if (!priceForm.season) {
      setError('Select an agricultural year for this selling price.')
      setSaving(false)
      return
    }
    const payload = {
      crop: Number(selectedCropId),
      season: Number(priceForm.season),
      price_per_tonne: priceForm.price_per_tonne,
      currency: priceForm.currency || 'USD',
      active: priceForm.active,
    }
    try {
      if (editingPriceId) {
        await apiClient.patch(`/crop-selling-prices/${editingPriceId}/`, payload)
        setMessage('Selling price updated. Existing deliveries and recovery records keep the price already saved on them.')
      } else {
        await apiClient.post('/crop-selling-prices/', payload)
        setMessage('Selling price saved.')
      }
      setEditingPriceId(null)
      setPriceForm({ season: priceForm.season, price_per_tonne: '', currency: 'USD', active: true })
      await loadPrices(selectedCropId)
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'Unable to save selling price.')
    } finally {
      setSaving(false)
    }
  }

  const editRequirement = (row) => {
    setEditingRequirementId(row.id)
    setRequirementForm({
      group_name: row.group_name || '',
      item_name: row.item_name || '',
      rate_per_hectare: row.rate_per_hectare || '',
      unit: row.unit || '',
      cost_per_unit: row.cost_per_unit ?? '',
      cost_per_hectare: row.cost_per_hectare || '',
      cost_type: row.cost_type || 'AGRICULTURAL_INPUT',
      include_in_input_cost: row.include_in_input_cost,
      active: row.active,
      notes: row.notes || '',
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    try {
      await apiClient.delete(pendingDelete.url)
      setMessage(pendingDelete.kind === 'price' ? 'Selling price deleted.' : 'Input requirement deleted.')
      setPendingDelete(null)
      await Promise.all([loadRequirements(selectedCropId), loadPrices(selectedCropId), loadCrops(selectedCropId)])
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'This record could not be deleted.')
      setPendingDelete(null)
    }
  }

  const toggleActive = async (row) => {
    try {
      await apiClient.patch(`/crop-input-requirements/${row.id}/`, { active: !row.active })
      await Promise.all([loadRequirements(selectedCropId), loadCrops(selectedCropId)])
    } catch {
      setError('Unable to update input requirement status.')
    }
  }

  return (
    <section className="workflow-page">
      <div className="workflow-heading">
        <button type="button" className="ghost-btn" onClick={refresh}>Refresh</button>
      </div>
      {error ? <div className="form-message error">{error}</div> : null}
      {message ? <div className="form-message">{message}</div> : null}
      {pendingDelete ? (
        <div className="form-message error" role="alert">
          Delete {pendingDelete.label}? Historical records that already use it will be kept, and deletion is refused when that is not safe.
          <button type="button" className="ghost-btn small" onClick={confirmDelete}>Confirm delete</button>
          <button type="button" className="ghost-btn small" onClick={() => setPendingDelete(null)}>Cancel</button>
        </div>
      ) : null}

      <div className="workflow-form">
        <h4>Select Crop</h4>
        <div className="workflow-fields">
          <label className="form-field">Crop
            <select value={selectedCropId} onChange={(event) => setSelectedCropId(event.target.value)}>
              <option value="">Select crop</option>
              {crops.map((crop) => <option key={crop.id} value={crop.id}>{crop.name}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Crop</th><th>Input Cost/Ha</th><th>Inputs</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {crops.map((crop) => (
              <tr key={crop.id}>
                <td>{crop.name}</td>
                <td>{Number(crop.input_cost_per_hectare || 0).toFixed(2)}</td>
                <td>{crop.inputs_count ?? 0}</td>
                <td>{crop.active ? 'Active' : 'Inactive'}</td>
                <td><button type="button" className="ghost-btn small" onClick={() => setSelectedCropId(String(crop.id))}>View / Edit</button></td>
              </tr>
            ))}
            {!loading && crops.length === 0 ? <tr><td colSpan={5}>No crops configured.</td></tr> : null}
          </tbody>
        </table>
      </div>

      <form className="workflow-form" onSubmit={submitRequirement}>
        <h4>{selectedCrop ? `${selectedCrop.name.toUpperCase()} - INPUT REQUIREMENTS` : 'Input Requirements'}</h4>
        <div className="workflow-fields">
          <label className="form-field">Group
            <input value={requirementForm.group_name} onChange={(event) => setRequirementForm((current) => ({ ...current, group_name: event.target.value }))} required />
          </label>
          <label className="form-field">Item
            <input value={requirementForm.item_name} onChange={(event) => setRequirementForm((current) => ({ ...current, item_name: event.target.value }))} required />
          </label>
          <label className="form-field">Rate / Ha
            <input type="number" min="0" step="0.0001" value={requirementForm.rate_per_hectare} onChange={(event) => setRequirementForm((current) => ({ ...current, rate_per_hectare: event.target.value }))} required />
          </label>
          <label className="form-field">Unit
            <input value={requirementForm.unit} onChange={(event) => setRequirementForm((current) => ({ ...current, unit: event.target.value }))} />
          </label>
          <label className="form-field">Cost / Unit
            <input type="number" min="0" step="0.0001" value={requirementForm.cost_per_unit} onChange={(event) => setRequirementForm((current) => ({ ...current, cost_per_unit: event.target.value }))} />
          </label>
          <label className="form-field">Cost / Ha
            <input type="number" min="0" step="0.0001" value={calculatedCostPerHa} readOnly />
          </label>
          <label className="form-field">Type
            <select value={requirementForm.cost_type} onChange={(event) => setRequirementForm((current) => ({ ...current, cost_type: event.target.value }))}>
              {costTypeChoices.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="form-field">Include in input debt
            <select value={requirementForm.include_in_input_cost ? 'yes' : 'no'} onChange={(event) => setRequirementForm((current) => ({ ...current, include_in_input_cost: event.target.value === 'yes' }))}>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
          <label className="form-field">Status
            <select value={requirementForm.active ? 'active' : 'inactive'} onChange={(event) => setRequirementForm((current) => ({ ...current, active: event.target.value === 'active' }))}>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </label>
        </div>
        <div className="workflow-form-actions">
          <button className="primary-btn small" type="submit" disabled={saving || !selectedCropId}>{saving ? 'Saving…' : editingRequirementId ? 'Update input' : 'Add input'}</button>
          {editingRequirementId ? <button type="button" className="ghost-btn" onClick={() => { setEditingRequirementId(null); setRequirementForm({ group_name: '', item_name: '', rate_per_hectare: '', unit: '', cost_per_unit: '', cost_per_hectare: '', cost_type: 'AGRICULTURAL_INPUT', include_in_input_cost: true, active: true, notes: '' }) }}>Cancel</button> : null}
        </div>
      </form>

      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Group</th><th>Item</th><th>Rate/Ha</th><th>Unit</th><th>Cost/Unit</th><th>Cost/Ha</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {requirements.map((row) => (
              <tr key={row.id}>
                <td>{row.group_name}</td>
                <td>{row.item_name}</td>
                <td>{row.rate_per_hectare}</td>
                <td>{row.unit || '—'}</td>
                <td>{row.cost_per_unit ?? '—'}</td>
                <td>{row.cost_per_hectare}</td>
                <td>{row.active ? 'Active' : 'Inactive'}</td>
                <td>
                  <button type="button" className="ghost-btn small" onClick={() => editRequirement(row)}>Edit</button>
                  <button type="button" className="ghost-btn small" onClick={() => toggleActive(row)}>{row.active ? 'Deactivate' : 'Activate'}</button>
                  <button type="button" className="ghost-btn small" onClick={() => setPendingDelete({ kind: 'requirement', url: `/crop-input-requirements/${row.id}/`, label: row.item_name })}>Delete</button>
                </td>
              </tr>
            ))}
            {selectedCropId && !requirements.length ? <tr><td colSpan={8}>No input requirements configured.</td></tr> : null}
            {!selectedCropId ? <tr><td colSpan={8}>Select a crop to view input requirements.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <div className="form-message">TOTAL INPUT COST / HA: ${totalCostPerHa.toFixed(2)}</div>

      <form className="workflow-form" onSubmit={submitPrice}>
        <h4>{selectedCrop ? `${selectedCrop.name} — Selling Price per Tonne — Agricultural Year ${seasons.find((season) => String(season.id) === String(priceForm.season))?.name || ''}`.trim() : 'Selling Price per Tonne'}</h4>
        <p className="finance-note">A selling price belongs to an agricultural year. It is not carried forward to the next year.</p>
        <div className="workflow-fields">
          <label className="form-field">Agricultural year
            <select value={priceForm.season} onChange={(event) => setPriceForm((current) => ({ ...current, season: event.target.value }))} required>
              <option value="">Select agricultural year</option>
              {seasons.map((season) => <option key={season.id} value={season.id}>{season.name}</option>)}
            </select>
          </label>
          <label className="form-field">Price per tonne
            <input type="number" min="0.01" step="0.01" value={priceForm.price_per_tonne} onChange={(event) => setPriceForm((current) => ({ ...current, price_per_tonne: event.target.value }))} required />
          </label>
          <label className="form-field">Currency
            <input value={priceForm.currency} onChange={(event) => setPriceForm((current) => ({ ...current, currency: event.target.value }))} required />
          </label>
          <label className="form-field">Status
            <select value={priceForm.active ? 'active' : 'inactive'} onChange={(event) => setPriceForm((current) => ({ ...current, active: event.target.value === 'active' }))}>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </label>
        </div>
        <div className="workflow-form-actions">
          <button className="primary-btn small" type="submit" disabled={saving || !selectedCropId}>{saving ? 'Saving…' : editingPriceId ? 'Update selling price' : 'Save selling price'}</button>
          {editingPriceId ? <button type="button" className="ghost-btn" onClick={() => { setEditingPriceId(null); setPriceForm((current) => ({ ...current, price_per_tonne: '', active: true })) }}>Cancel</button> : null}
        </div>
      </form>
      {selectedCrop && priceForm.season && !prices.some((row) => String(row.season) === String(priceForm.season) && row.active) ? (
        <div className="form-message">No active selling price is configured for {selectedCrop.name} in this agricultural year.</div>
      ) : null}

      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Agricultural year</th><th>Price/Tonne</th><th>Currency</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {prices.map((row) => (
              <tr key={row.id}>
                <td>{row.season_name || 'Year not set'}</td>
                <td>{row.price_per_tonne}</td>
                <td>{row.currency}</td>
                <td>{row.active ? 'Active' : 'Inactive'}</td>
                <td>
                  <button type="button" className="ghost-btn small" onClick={() => { setEditingPriceId(row.id); setPriceForm({ season: row.season ? String(row.season) : '', price_per_tonne: row.price_per_tonne, currency: row.currency || 'USD', active: row.active }) }}>Edit</button>
                  <button type="button" className="ghost-btn small" onClick={async () => { try { await apiClient.patch(`/crop-selling-prices/${row.id}/`, { active: !row.active }); await loadPrices(selectedCropId) } catch { setError('Unable to update the selling price.') } }}>{row.active ? 'Deactivate' : 'Activate'}</button>
                  <button type="button" className="ghost-btn small" onClick={() => setPendingDelete({ kind: 'price', url: `/crop-selling-prices/${row.id}/`, label: `${row.crop_name || selectedCrop?.name || 'Crop'} ${row.season_name || ''} price` })}>Delete</button>
                </td>
              </tr>
            ))}
            {!prices.length ? <tr><td colSpan={5}>No selling prices configured for this crop.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default CropCataloguePage
