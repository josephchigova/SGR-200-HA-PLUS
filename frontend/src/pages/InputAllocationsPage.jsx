import { useCallback, useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import FarmerAutocomplete from '../components/FarmerAutocomplete'

const toList = (data) => (Array.isArray(data) ? data : data?.results || [])

const getAllPages = async (path) => {
  const rows = []
  let response = await apiClient.get(path)
  rows.push(...toList(response.data))
  while (response.data?.next) {
    response = await apiClient.get(response.data.next)
    rows.push(...toList(response.data))
  }
  return rows
}

function InputAllocationsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const [rows, setRows] = useState([])
  const [farms, setFarms] = useState([])
  const [farmsLoading, setFarmsLoading] = useState(false)
  const [crops, setCrops] = useState([])
  const [programmes, setProgrammes] = useState([])
  const [form, setForm] = useState({ farmer: '', farm: '', crop_reference: '', programme: '', hectares: '' })
  const [preview, setPreview] = useState(null)
  const [loadedKey, setLoadedKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const seasonQuery = useMemo(() => {
    if (!selectedSeason) return ''
    const params = new URLSearchParams({
      season: String(selectedSeason.id),
      season_name: selectedSeason.name,
    })
    if (cropSeason) params.set('crop_season', cropSeason)
    return params.toString()
  }, [cropSeason, selectedSeason])

  const visibleCrops = useMemo(
    () => crops.filter((crop) => !cropSeason || crop.category === cropSeason),
    [cropSeason, crops],
  )
  const requestKey = `${periodStatus}:${seasonQuery}`
  const periodBlocked = periodStatus !== 'ready' || !selectedSeason
  const rowsReady = !periodBlocked && loadedKey === requestKey
  const visibleRows = rowsReady ? rows : []
  const loading = periodStatus === 'loading' || (!periodBlocked && !rowsReady)

  const scoped = useCallback((path) => {
    if (!seasonQuery) return path
    return `${path}${path.includes('?') ? '&' : '?'}${seasonQuery}`
  }, [seasonQuery])

  useEffect(() => {
    if (!selectedSeason || periodStatus !== 'ready') return undefined
    let mounted = true
    const load = async () => {
      try {
        const [allocationRows, cropRows, programmeRows] = await Promise.all([
          getAllPages(scoped('/input-allocations/')),
          getAllPages('/crops/?active=true'),
          getAllPages(scoped('/programmes/')),
        ])
        if (!mounted) return
        setRows(allocationRows)
        setCrops(cropRows)
        setProgrammes(programmeRows)
        setError('')
        setLoadedKey(requestKey)
      } catch {
        if (!mounted) return
        setRows([])
        setError('Unable to load input allocations.')
        setLoadedKey(requestKey)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [periodStatus, requestKey, scoped, selectedSeason])

  const refresh = async () => {
    try {
      const [allocationRows, cropRows, programmeRows] = await Promise.all([
        getAllPages(scoped('/input-allocations/')),
        getAllPages('/crops/?active=true'),
        getAllPages(scoped('/programmes/')),
      ])
      setRows(allocationRows)
      setCrops(cropRows)
      setProgrammes(programmeRows)
      setError('')
      setLoadedKey(requestKey)
    } catch {
      setError('Unable to load input allocations.')
      setLoadedKey(requestKey)
    }
  }

  const [formSeason, setFormSeason] = useState(cropSeason)
  if (formSeason !== cropSeason) {
    setFormSeason(cropSeason)
    if (form.crop_reference) setForm((current) => ({ ...current, crop_reference: '' }))
  }

  useEffect(() => {
    let active = true
    const loadFarms = async () => {
      if (!form.farmer) {
        setFarms([])
        return
      }
      setFarmsLoading(true)
      try {
        const response = await apiClient.get(`/farms/?farmer=${form.farmer}&page_size=100`)
        if (active) setFarms(toList(response.data))
      } catch {
        if (active) setFarms([])
      } finally {
        if (active) setFarmsLoading(false)
      }
    }

    loadFarms()
    return () => {
      active = false
    }
  }, [form.farmer])

  const updateForm = (updates) => {
    setPreview(null)
    setForm((current) => ({ ...current, ...updates }))
  }

  useEffect(() => {
    const canPreview = form.farmer && form.crop_reference && form.programme && form.hectares
    if (!canPreview) return
    const loadPreview = async () => {
      setPreviewLoading(true)
      setError('')
      try {
        const params = new URLSearchParams({
          farmer: form.farmer,
          crop_reference: form.crop_reference,
          programme: form.programme,
          hectares: form.hectares,
        })
        if (form.farm) params.set('farm', form.farm)
        const response = await apiClient.get(`/input-allocations/preview/?${params.toString()}`)
        setPreview(response.data)
      } catch (requestError) {
        setPreview(null)
        const data = requestError.response?.data
        setError(data ? Object.values(data).flat().join(' ') : 'Unable to preview input calculation.')
      } finally {
        setPreviewLoading(false)
      }
    }
    loadPreview()
  }, [form])

  const submit = async (event) => {
    event.preventDefault()
    if (!form.farmer) {
      setError('Select a farmer from the search suggestions.')
      return
    }
    setSaving(true)
    setError('')
    setMessage('')
    try {
      await apiClient.post('/input-allocations/', {
        farmer: Number(form.farmer),
        farm: form.farm ? Number(form.farm) : null,
        crop_reference: Number(form.crop_reference),
        programme: Number(form.programme),
        hectares: form.hectares,
      })
      setMessage('Input allocation saved and debt generated.')
      setForm({ farmer: '', farm: '', crop_reference: '', programme: '', hectares: '' })
      setPreview(null)
      await refresh()
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'Unable to create allocation.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="workflow-page">
      <div className="workflow-heading">
        <div><p className="eyebrow">Golden Path</p><h3>Input Allocations</h3></div>
        <button type="button" className="ghost-btn" onClick={refresh}>Refresh</button>
      </div>
      {error ? <div className="form-message error">{error}</div> : null}
      {message ? <div className="form-message">{message}</div> : null}

      <form className="workflow-form" onSubmit={submit}>
        <h4>Allocate crop inputs</h4>
        <div className="workflow-fields">
          <FarmerAutocomplete
            label="Eligible farmer"
            value={form.farmer}
            endpoint="/farmers/eligible/"
            seasonId={selectedSeason?.id}
            seasonName={selectedSeason?.name}
            required
            onChange={(farmer) => updateForm({ farmer: farmer ? String(farmer.id) : '', farm: '' })}
          />
          <label className="form-field">Farm
            <select value={form.farm} onChange={(event) => updateForm({ farm: event.target.value })} disabled={!form.farmer}>
              <option value="">Select</option>
              {farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.farm_name}</option>)}
            </select>
            {farmsLoading ? <small>Loading farms...</small> : null}
          </label>
          <label className="form-field">Crop
            <select value={form.crop_reference} onChange={(event) => updateForm({ crop_reference: event.target.value })} required>
              <option value="">Select</option>
              {visibleCrops.map((crop) => <option key={crop.id} value={crop.id}>{crop.name}</option>)}
            </select>
          </label>
          <label className="form-field">Programme
            <select value={form.programme} onChange={(event) => updateForm({ programme: event.target.value })} required>
              <option value="">Select</option>
              {programmes.map((programme) => <option key={programme.id} value={programme.id}>{programme.name}</option>)}
            </select>
          </label>
          <label className="form-field">Hectares
            <input type="number" min="0.01" step="0.01" value={form.hectares} onChange={(event) => updateForm({ hectares: event.target.value })} required />
          </label>
        </div>
        <div className="workflow-form-actions">
          <button type="submit" className="primary-btn small" disabled={saving || previewLoading || !preview}>{saving ? 'Saving…' : 'Save allocation'}</button>
        </div>
      </form>

      {preview ? (
        <>
          <div className="workflow-list-heading"><h4>Input calculation</h4><span>{preview.lines?.length || 0} inputs</span></div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Input</th><th>Rate/Ha</th><th>Required Qty</th><th>Unit Cost</th><th>Total Cost</th></tr></thead>
              <tbody>
                {preview.lines?.map((line, index) => (
                  <tr key={`${line.item_name}-${index}`}>
                    <td>{line.item_name}</td>
                    <td>{line.rate_per_hectare}</td>
                    <td>{line.required_quantity} {line.unit || ''}</td>
                    <td>{line.cost_per_unit ?? '—'}</td>
                    <td>{line.calculated_cost}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="form-message">
            ARDA Requested: {preview.arda_requested_hectares} ha | Already Allocated: {preview.arda_allocated_hectares} ha | Available: {preview.arda_available_hectares} ha
          </div>
          <div className="form-message">
            Input Cost / Ha: ${preview.calculated_input_cost_per_hectare} | Total Farmer Input Cost: ${preview.total_input_cost} | Selling Price/Tonne: ${preview.selling_price_per_tonne} | Required Recovery: {preview.required_recovery_tonnes} tonnes
          </div>
        </>
      ) : previewLoading ? <div className="form-message">Calculating allocation preview...</div> : null}

      <div className="workflow-list-heading"><h4>Records</h4><span>{loading ? 'Loading…' : `${visibleRows.length} records`}</span></div>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Farmer</th><th>Programme</th><th>Crop</th><th>Hectares</th><th>Input Cost/Ha</th><th>Total Input Cost</th><th>Status</th></tr></thead>
          <tbody>
            {visibleRows.map((row) => (
              <tr key={row.id}>
                <td>{row.farmer_name}</td>
                <td>{row.programme_name}</td>
                <td>{row.crop_name || row.crop}</td>
                <td>{row.hectares}</td>
                <td>{row.calculated_input_cost_per_hectare}</td>
                <td>{row.total_input_cost}</td>
                <td>{row.status}</td>
              </tr>
            ))}
            {!loading && visibleRows.length === 0 ? <tr><td colSpan={7}>No allocations for the selected period.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default InputAllocationsPage
