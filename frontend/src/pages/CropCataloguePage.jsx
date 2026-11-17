// Crop catalogue, one programme at a time.
//
// Pick a programme, then one of its crops: its Seed, Fertilizer and Chemicals products,
// quantities per hectare and prices belong to that programme only. There is no general
// catalogue. Lines saved before programme catalogues are listed at the end until an
// administrator assigns each one to a programme. The selling price per tonne at the bottom is
// the crop's price for grain recovery, separate from what the programme charges for inputs.

import { useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import Icon from '../components/Icon'
import ProgrammeCatalogue from '../components/ProgrammeCatalogue'
import SearchSelect from '../components/SearchSelect'
import { useAuth } from '../auth'
import { DraftNotice, EmptyState, Modal, Pill, errorMessage } from '../components/ui'
import { useFormDraft } from '../drafts'
import { CATEGORIES } from '../inputCategories'
import { loadAll, money, qty } from '../programmeData'

export function formatCatalogueMoney(value) {
  if (value === null || value === undefined || value === '') return ''
  const amount = Number(value)
  if (!Number.isFinite(amount)) return ''
  return amount.toFixed(2)
}

function CropCataloguePage() {
  const { can } = useAuth()
  const readOnly = !can('crops', 'edit')
  const [programmes, setProgrammes] = useState([])
  const [crops, setCrops] = useState([])
  const [programmeId, setProgrammeId] = useState('')
  const [cropId, setCropId] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    Promise.all([loadAll('/programmes/'), loadAll('/crops/')])
      .then(([programmeRows, cropRows]) => {
        if (!active) return
        setProgrammes(programmeRows)
        setCrops(cropRows)
      })
      .catch(() => { if (active) setError('Programmes and crops could not be loaded.') })
    return () => { active = false }
  }, [])

  const programme = programmes.find((item) => String(item.id) === String(programmeId)) || null
  const programmeCrops = useMemo(() => crops.filter((crop) => (programme?.crops || []).map(String).includes(String(crop.id))), [crops, programme])
  const crop = programmeCrops.find((item) => String(item.id) === String(cropId)) || programmeCrops[0] || null

  return (
    <section className="workflow-page crop-catalogue-page">
      <div className="page-head">
        <h1>Crop catalogue</h1>
        <p className="page-sub">Every programme sets up its own catalogue for each crop it supports: the products or varieties, quantity per hectare and the programme's price. Choose the programme first.</p>
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      <div className="card catalogue-picker">
        <SearchSelect
          label="Programme"
          value={programmeId}
          onChange={(value) => { setProgrammeId(value); setCropId('') }}
          placeholder="Choose the programme"
          options={programmes.map((item) => ({ value: String(item.id), label: `${item.name}${item.season_name ? ` · ${item.season_name}` : ''}${item.capacity_status === 'INACTIVE' ? ' · inactive' : ''}` }))}
          emptyText="No programmes yet. Add one on the Programmes page."
        />
        {programme ? (
          <div className="crop-tabs" role="tablist" aria-label={`${programme.name} crops`}>
            {programmeCrops.map((item) => (
              <button key={item.id} type="button" role="tab" aria-selected={crop?.id === item.id} className={crop?.id === item.id ? 'chip active' : 'chip'} onClick={() => setCropId(String(item.id))}>{item.name}</button>
            ))}
            {!programmeCrops.length ? <span className="field-error">{programme.name} supports no crops. Add them on the Programmes page.</span> : null}
          </div>
        ) : null}
      </div>

      {!programme ? <EmptyState icon="book" title="Choose a programme">Its crops and their Seed, Fertilizer and Chemicals appear here.</EmptyState> : null}
      {programme && crop ? (
        <div className="card">
          <div className="card-head">
            <div>
              <h3>Editing {programme.name} · {crop.name}</h3>
              <p className="card-sub">
                {programme.season_name ? `${programme.season_name}. ` : ''}Supplies {programme.input_category_labels?.join(', ') || 'no input types yet'}.
                {programme.capacity_status === 'INACTIVE' ? ' This programme is inactive: its catalogue is kept but it takes no new allocations.' : ''}
              </p>
            </div>
            {programme.capacity_status === 'INACTIVE' ? <Pill tone="bad">Inactive</Pill> : <Pill tone="good">Active</Pill>}
          </div>
          <ProgrammeCatalogue programme={programme} crop={crop} readOnly={readOnly} />
        </div>
      ) : null}

      <UnlinkedLines programmes={programmes} crops={crops} readOnly={readOnly} />
      <SellingPrices crops={crops} defaultCropId={crop?.id} readOnly={readOnly} />
    </section>
  )
}

// Lines saved before programme catalogues. They are never given a programme automatically.
function UnlinkedLines({ programmes, crops, readOnly }) {
  const [rows, setRows] = useState(null)
  const [assigning, setAssigning] = useState(null)
  const [notice, setNotice] = useState('')
  const [token, setToken] = useState(0)

  useEffect(() => {
    let active = true
    loadAll('/crop-input-requirements/', { programme: 'none' })
      .then((list) => { if (active) setRows(list.filter((row) => row.active)) })
      .catch(() => { if (active) setRows([]) })
    return () => { active = false }
  }, [token])

  if (!rows || (!rows.length && !notice)) return null
  const cropName = (id) => crops.find((crop) => crop.id === id)?.name || ''
  return (
    <section className="card unlinked-lines">
      <div className="card-head">
        <div>
          <h3><Icon name="alert" />Catalogue lines not linked to a programme ({rows.length})</h3>
          <p className="card-sub">These were saved before each programme had its own catalogue. They are not used for new allocations. Assign each one to the programme it belongs to; nothing is assigned automatically.</p>
        </div>
      </div>
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {rows.length ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>Crop</th><th>Group</th><th>Item</th><th className="num">Qty per ha</th><th className="num">Unit price</th><th /></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.crop_name || cropName(row.crop)}</td>
                  <td>{row.group_name}</td>
                  <td>{row.item_name}</td>
                  <td className="num">{qty(row.rate_per_hectare, 4)} {row.unit}</td>
                  <td className="num">{money(row.cost_per_unit)}</td>
                  <td>{readOnly ? null : <button type="button" className="ghost-btn small" onClick={() => setAssigning(row)}>Assign to a programme</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {assigning ? (
        <AssignLine
          line={assigning}
          programmes={programmes.filter((item) => (item.crops || []).includes(assigning.crop))}
          onClose={() => setAssigning(null)}
          onDone={(message) => { setAssigning(null); setNotice(message); setToken((value) => value + 1) }}
        />
      ) : null}
    </section>
  )
}

function AssignLine({ line, programmes, onClose, onDone }) {
  const guess = /chem|herbic|insectic|fungic/i.test(line.group_name) ? 'CHEMICALS' : /fert/i.test(line.group_name) ? 'FERTILIZER' : /seed/i.test(line.group_name) ? 'SEED' : ''
  const [programme, setProgramme] = useState('')
  const [category, setCategory] = useState(guess)
  const [error, setError] = useState('')
  const chosen = programmes.find((item) => String(item.id) === programme)
  const submit = async (event) => {
    event.preventDefault()
    try {
      await apiClient.post(`/crop-input-requirements/${line.id}/assign/`, { programme: Number(programme), input_category: category })
      onDone(`${line.item_name} added to ${chosen?.name}'s ${line.crop_name} catalogue. The old line is kept, switched off.`)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The line could not be assigned.'))
    }
  }
  return (
    <Modal title={`Assign ${line.item_name}`} subtitle={`${line.crop_name} · ${qty(line.rate_per_hectare, 4)} ${line.unit} per ha at ${money(line.cost_per_unit)}. Choose the programme it belongs to.`} onClose={onClose}
      footer={<><button type="button" className="ghost-btn" onClick={onClose}>Cancel</button><button type="submit" form="assign-line-form" className="primary-btn" disabled={!programme || !category}>Assign</button></>}>
      <form id="assign-line-form" onSubmit={submit}>
        {error ? <div className="form-message error" role="alert">{error}</div> : null}
        <label className="form-field">Programme
          <select required value={programme} onChange={(event) => setProgramme(event.target.value)}>
            <option value="">{programmes.length ? 'Choose a programme' : `No programme supports ${line.crop_name}`}</option>
            {programmes.map((item) => <option key={item.id} value={item.id}>{item.name}{item.season_name ? ` · ${item.season_name}` : ''}</option>)}
          </select>
        </label>
        <label className="form-field">Input type
          <select required value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="">Choose the input type</option>
            {CATEGORIES.filter(([code]) => !chosen || (chosen.input_categories || []).includes(code)).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>
      </form>
    </Modal>
  )
}

// The crop's selling price per tonne for each agricultural year. Unchanged from before.
function SellingPrices({ crops, defaultCropId, readOnly }) {
  const [cropId, setCropId] = useState('')
  const [seasons, setSeasons] = useState([])
  const [prices, setPrices] = useState([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [editingPriceId, setEditingPriceId] = useState(null)
  const [pendingDelete, setPendingDelete] = useState(null)
  const [token, setToken] = useState(0)
  const [priceForm, setPriceForm] = useState({ season: '', price_per_tonne: '', currency: 'USD', active: true })
  const selectedCropId = cropId || (defaultCropId ? String(defaultCropId) : '')
  const selectedCrop = crops.find((crop) => String(crop.id) === String(selectedCropId)) || null
  const priceDraft = useFormDraft({
    key: `catalogue:${selectedCropId}:price:${editingPriceId || 'new'}`,
    value: priceForm,
    enabled: Boolean(selectedCropId),
    exclude: ['season'],
    onRestore: (data) => setPriceForm((current) => ({ ...current, ...data })),
  })

  useEffect(() => {
    let active = true
    loadAll('/seasons/').then((list) => {
      if (!active) return
      const years = list.filter((season) => season.selectable !== false)
      setSeasons(years)
      setPriceForm((current) => ({ ...current, season: current.season || (years[0] ? String(years[0].id) : '') }))
    }).catch(() => {})
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!selectedCropId) return undefined
    let active = true
    apiClient.get(`/crop-selling-prices/?crop=${selectedCropId}`)
      .then((response) => {
        if (!active) return
        const list = Array.isArray(response.data) ? response.data : response.data?.results || []
        setPrices(list.filter((row) => /^\d{4}\/\d{4}$/.test(String(row.season_name || ''))))
      })
      .catch(() => { if (active) setError('Unable to load selling prices.') })
    return () => { active = false }
  }, [selectedCropId, token])

  const reload = () => setToken((value) => value + 1)
  const shownPrices = selectedCropId ? prices : []

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
    const payload = { crop: Number(selectedCropId), season: Number(priceForm.season), price_per_tonne: priceForm.price_per_tonne, currency: priceForm.currency || 'USD', active: priceForm.active }
    try {
      if (editingPriceId) {
        await apiClient.patch(`/crop-selling-prices/${editingPriceId}/`, payload)
        setMessage('Selling price updated. Existing deliveries and recovery records keep the price already saved on them.')
      } else {
        await apiClient.post('/crop-selling-prices/', payload)
        setMessage('Selling price saved.')
      }
      priceDraft.clear({ season: priceForm.season, price_per_tonne: '', currency: 'USD', active: true })
      setEditingPriceId(null)
      setPriceForm({ season: priceForm.season, price_per_tonne: '', currency: 'USD', active: true })
      reload()
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'Unable to save selling price.')
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async () => {
    try {
      await apiClient.delete(pendingDelete.url)
      setMessage('Selling price deleted.')
      setPendingDelete(null)
      reload()
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'This record could not be deleted.')
      setPendingDelete(null)
    }
  }

  return (
    <section className="selling-prices">
      {error ? <div className="form-message error">{error}</div> : null}
      {message ? <div className="form-message">{message}</div> : null}
      {pendingDelete ? (
        <div className="form-message error" role="alert">
          Delete {pendingDelete.label}? Historical records that already use it will be kept, and deletion is refused when that is not safe.
          <button type="button" className="ghost-btn small" onClick={confirmDelete}>Confirm delete</button>
          <button type="button" className="ghost-btn small" onClick={() => setPendingDelete(null)}>Cancel</button>
        </div>
      ) : null}
      <form className="workflow-form" onSubmit={submitPrice}>
        <DraftNotice draft={priceDraft} />
        <h4>{selectedCrop ? `${selectedCrop.name} — Selling Price per Tonne — Agricultural Year ${seasons.find((season) => String(season.id) === String(priceForm.season))?.name || ''}`.trim() : 'Selling Price per Tonne'}</h4>
        <p className="finance-note">The price GMB grain is valued at when it repays input debt. It belongs to the crop and an agricultural year, not to a programme, and is not carried forward to the next year.</p>
        <div className="workflow-fields">
          <label className="form-field">Crop
            <select value={selectedCropId} onChange={(event) => setCropId(event.target.value)}>
              <option value="">Select crop</option>
              {crops.map((crop) => <option key={crop.id} value={crop.id}>{crop.name}</option>)}
            </select>
          </label>
          <label className="form-field">Agricultural year
            <select value={priceForm.season} disabled={readOnly} onChange={(event) => setPriceForm((current) => ({ ...current, season: event.target.value }))} required>
              <option value="">Select agricultural year</option>
              {seasons.map((season) => <option key={season.id} value={season.id}>{season.name}</option>)}
            </select>
          </label>
          {readOnly ? null : (
            <>
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
            </>
          )}
        </div>
        {readOnly ? null : (
          <div className="workflow-form-actions">
            <button className="primary-btn small" type="submit" disabled={saving || !selectedCropId}>{saving ? 'Saving…' : editingPriceId ? 'Update selling price' : 'Save selling price'}</button>
            {editingPriceId ? <button type="button" className="ghost-btn" onClick={() => { setEditingPriceId(null); setPriceForm((current) => ({ ...current, price_per_tonne: '', active: true })) }}>Cancel</button> : null}
          </div>
        )}
      </form>
      {selectedCrop && priceForm.season && !shownPrices.some((row) => String(row.season) === String(priceForm.season) && row.active) ? (
        <div className="form-message">No active selling price is configured for {selectedCrop.name} in this agricultural year.</div>
      ) : null}
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Agricultural year</th><th>Price/Tonne</th><th>Currency</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {shownPrices.map((row) => (
              <tr key={row.id}>
                <td>{row.season_name || 'Year not set'}</td>
                <td>{formatCatalogueMoney(row.price_per_tonne)}</td>
                <td>{row.currency}</td>
                <td>{row.active ? 'Active' : 'Inactive'}</td>
                <td>
                  {readOnly ? 'View only' : null}
                  <button type="button" className="icon-btn" hidden={readOnly} title="Edit" aria-label="Edit selling price" onClick={() => { setEditingPriceId(row.id); setPriceForm({ season: row.season ? String(row.season) : '', price_per_tonne: formatCatalogueMoney(row.price_per_tonne), currency: row.currency || 'USD', active: row.active }) }}><Icon name="pencil" /></button>
                  <button type="button" className="ghost-btn small" hidden={readOnly} onClick={async () => { try { await apiClient.patch(`/crop-selling-prices/${row.id}/`, { active: !row.active }); reload() } catch { setError('Unable to update the selling price.') } }}>{row.active ? 'Deactivate' : 'Activate'}</button>
                  <button type="button" className="icon-btn danger" hidden={readOnly} title="Delete" aria-label="Delete selling price" onClick={() => setPendingDelete({ kind: 'price', url: `/crop-selling-prices/${row.id}/`, label: `${row.crop_name || selectedCrop?.name || 'Crop'} ${row.season_name || ''} price` })}><Icon name="trash" /></button>
                </td>
              </tr>
            ))}
            {!shownPrices.length ? <tr><td colSpan={5}>{selectedCropId ? 'No selling prices configured for this crop.' : 'Select a crop to see its selling prices.'}</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default CropCataloguePage
