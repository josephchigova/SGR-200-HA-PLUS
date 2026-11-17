// One programme's catalogue for one of its crops: input type -> product or variety -> unit ->
// quantity per hectare -> the programme's own price.
//
// Only the programme's input types are shown. A product can be priced per unit (per kg, per
// litre) or per pack (for example a 50 kg bag at $32), in which case the price per unit is
// worked out from the pack. Allocations keep the price they were made at.

import { useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import Icon from './Icon'
import { CATEGORIES } from '../inputCategories'
import { EmptyState, Pill, errorMessage } from './ui'
import { loadAll, money, qty } from '../programmeData'

export default function ProgrammeCatalogue({ programme, crop, readOnly }) {
  const [products, setProducts] = useState([])
  const [rows, setRows] = useState([])
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const requestKey = `${programme?.id}:${crop?.id}:${token}`

  useEffect(() => {
    let active = true
    loadAll('/inputs/').then((list) => { if (active) setProducts(list) }).catch(() => { if (active) setProducts([]) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!programme || !crop) return undefined
    let active = true
    loadAll('/crop-input-requirements/', { crop: crop.id, programme: programme.id })
      .then((list) => { if (active) { setRows(list); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'The catalogue could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [programme, crop, requestKey])

  if (!programme || !crop) return null
  const loading = loadedKey !== requestKey
  const supplied = CATEGORIES.filter(([code]) => (programme.input_categories || []).includes(code))
  return (
    <section className="programme-catalogue">
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {!supplied.length ? <EmptyState icon="book" title="No input types">{programme.name} supplies no input types yet. Choose them on the Programmes page.</EmptyState> : null}
      {loading ? <div className="form-message">Loading {programme.name}'s {crop.name} catalogue…</div> : (
        <div className="category-grid">
          {supplied.map(([code, label, icon]) => (
            <CategoryPanel
              key={code}
              code={code}
              label={label}
              icon={icon}
              crop={crop}
              programme={programme}
              rows={rows.filter((row) => row.input_category === code)}
              products={products.filter((product) => product.category === code)}
              readOnly={readOnly}
              onProductCreated={(product) => setProducts((current) => [...current, product])}
              onChanged={(message) => { setNotice(message); setToken((value) => value + 1) }}
              onError={setError}
            />
          ))}
        </div>
      )}
    </section>
  )
}

const EMPTY_LINE = { input_product: '', rate_per_hectare: '', unit: '', price_basis: 'unit', cost_per_unit: '', pack_label: '', pack_size: '', pack_price: '' }

function CategoryPanel({ code, label, icon, crop, programme, rows, products, readOnly, onProductCreated, onChanged, onError }) {
  const [form, setForm] = useState(EMPTY_LINE)
  const [editingId, setEditingId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newProduct, setNewProduct] = useState({ name: '', unit: code === 'CHEMICALS' ? 'litres' : 'kg' })
  const used = useMemo(() => new Set(rows.map((row) => String(row.input_product))), [rows])
  const choices = products.filter((product) => !used.has(String(product.id)) || String(product.id) === String(form.input_product))
  const costPerHectare = rows.filter((row) => row.active).reduce((total, row) => total + Number(row.cost_per_hectare || 0), 0)
  const byPack = form.price_basis === 'pack'
  const unitPrice = byPack ? (Number(form.pack_size) > 0 ? Number(form.pack_price || 0) / Number(form.pack_size) : 0) : Number(form.cost_per_unit || 0)
  const previewPerHectare = unitPrice * Number(form.rate_per_hectare || 0)

  const reset = () => { setForm(EMPTY_LINE); setEditingId(null) }

  const save = async (event) => {
    event.preventDefault()
    setSaving(true)
    onError('')
    const payload = {
      crop: crop.id, programme: programme.id, input_category: code, input_product: Number(form.input_product),
      rate_per_hectare: form.rate_per_hectare, unit: form.unit,
      ...(byPack
        ? { pack_label: form.pack_label, pack_size: form.pack_size, pack_price: form.pack_price }
        : { cost_per_unit: form.cost_per_unit, pack_label: '', pack_size: null, pack_price: null }),
    }
    try {
      if (editingId) await apiClient.patch(`/crop-input-requirements/${editingId}/`, payload)
      else await apiClient.post('/crop-input-requirements/', payload)
      reset()
      onChanged(`${label} for ${crop.name} under ${programme.name} saved. Allocations already made keep the price they were made at.`)
    } catch (requestError) {
      onError(errorMessage(requestError, `The ${label.toLowerCase()} line could not be saved.`))
    } finally {
      setSaving(false)
    }
  }

  const createProduct = async () => {
    if (!newProduct.name.trim()) return
    try {
      const response = await apiClient.post('/inputs/', { name: newProduct.name.trim(), category: code, unit: newProduct.unit || 'kg', active: true })
      onProductCreated(response.data)
      setForm((current) => ({ ...current, input_product: String(response.data.id), unit: response.data.unit }))
      setCreating(false)
      setNewProduct({ name: '', unit: newProduct.unit })
    } catch (requestError) {
      onError(errorMessage(requestError, 'The product could not be added.'))
    }
  }

  const toggleActive = async (row) => {
    try {
      await apiClient.patch(`/crop-input-requirements/${row.id}/`, { active: !row.active })
      onChanged(`${row.input_product_name} ${row.active ? 'deactivated' : 'activated'} for ${programme.name}.`)
    } catch (requestError) {
      onError(errorMessage(requestError, 'The line could not be updated.'))
    }
  }

  const edit = (row) => {
    setEditingId(row.id)
    setForm({
      input_product: String(row.input_product), rate_per_hectare: row.rate_per_hectare, unit: row.unit,
      price_basis: row.pack_size ? 'pack' : 'unit', cost_per_unit: row.cost_per_unit || '',
      pack_label: row.pack_label || '', pack_size: row.pack_size || '', pack_price: row.pack_price || '',
    })
  }

  return (
    <article className="category-panel">
      <header>
        <h4><Icon name={icon} />{label}</h4>
        <Pill tone={rows.some((row) => row.active) ? 'good' : 'warn'}>{rows.filter((row) => row.active).length} product{rows.filter((row) => row.active).length === 1 ? '' : 's'}</Pill>
      </header>
      <div className="table-wrap">
        <table className="data-table compact">
          <thead><tr><th>Product or variety</th><th className="num">Qty per ha</th><th className="num">Price</th><th className="num">Cost per ha</th><th /></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={row.active ? '' : 'inactive-row'}>
                <td>{row.input_product_name}{row.active ? '' : ' (inactive)'}</td>
                <td className="num">{qty(row.rate_per_hectare, 4)} {row.unit}</td>
                <td className="num">
                  {money(row.cost_per_unit)} / {row.unit}
                  {row.pack_size ? <small className="block-hint">{money(row.pack_price)} per {row.pack_label || `${qty(row.pack_size)} ${row.unit} pack`}</small> : null}
                </td>
                <td className="num">{money(row.cost_per_hectare)}</td>
                <td>
                  {readOnly ? null : (
                    <span className="table-actions">
                      <button type="button" className="icon-btn" title="Edit" aria-label={`Edit ${row.input_product_name}`} onClick={() => edit(row)}><Icon name="pencil" /></button>
                      <button type="button" className="ghost-btn small" onClick={() => toggleActive(row)}>{row.active ? 'Deactivate' : 'Activate'}</button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length ? <tr><td colSpan="5">No {label.toLowerCase()} set for {crop.name} under {programme.name} yet.</td></tr> : null}
          </tbody>
          {rows.length ? <tfoot><tr><td colSpan="3">{label} cost per hectare</td><td className="num"><strong>{money(costPerHectare)}</strong></td><td /></tr></tfoot> : null}
        </table>
      </div>
      {readOnly ? null : (
        <form className="category-form" onSubmit={save}>
          <label className="form-field">
            Product or variety
            <select required value={form.input_product} onChange={(event) => {
              const product = products.find((item) => String(item.id) === event.target.value)
              setForm((current) => ({ ...current, input_product: event.target.value, unit: current.unit || product?.unit || '' }))
            }}>
              <option value="">Choose a {label.toLowerCase()} product</option>
              {choices.map((product) => <option key={product.id} value={product.id}>{product.name} ({product.unit})</option>)}
            </select>
          </label>
          {creating ? (
            <div className="new-product">
              <input aria-label={`New ${label.toLowerCase()} product name`} placeholder="Product or variety name" value={newProduct.name} onChange={(event) => setNewProduct({ ...newProduct, name: event.target.value })} />
              <input aria-label="Unit" placeholder="Unit" value={newProduct.unit} onChange={(event) => setNewProduct({ ...newProduct, unit: event.target.value })} />
              <button type="button" className="ghost-btn small" onClick={createProduct}>Add product</button>
              <button type="button" className="ghost-btn small" onClick={() => setCreating(false)}>Cancel</button>
            </div>
          ) : <button type="button" className="link-btn" onClick={() => setCreating(true)}><Icon name="plus" />New {label.toLowerCase()} product</button>}
          <label className="form-field">Unit<input required value={form.unit} onChange={(event) => setForm({ ...form, unit: event.target.value })} placeholder="kg, litres, bags" /></label>
          <label className="form-field">Quantity per ha ({form.unit || 'unit'})<input required type="number" min="0.0001" step="0.0001" value={form.rate_per_hectare} onChange={(event) => setForm({ ...form, rate_per_hectare: event.target.value })} /></label>
          <label className="form-field">Priced
            <select value={form.price_basis} onChange={(event) => setForm({ ...form, price_basis: event.target.value })}>
              <option value="unit">Per {form.unit || 'unit'}</option>
              <option value="pack">Per pack or bag</option>
            </select>
          </label>
          {byPack ? (
            <>
              <label className="form-field">Pack name<input value={form.pack_label} onChange={(event) => setForm({ ...form, pack_label: event.target.value })} placeholder="50 kg bag" /></label>
              <label className="form-field">{form.unit || 'Units'} per pack<input required type="number" min="0.0001" step="0.0001" value={form.pack_size} onChange={(event) => setForm({ ...form, pack_size: event.target.value })} /></label>
              <label className="form-field">Price per pack (USD)<input required type="number" min="0.01" step="0.01" value={form.pack_price} onChange={(event) => setForm({ ...form, pack_price: event.target.value })} /></label>
            </>
          ) : (
            <label className="form-field">Price per {form.unit || 'unit'} (USD)<input required type="number" min="0.0001" step="0.0001" value={form.cost_per_unit} onChange={(event) => setForm({ ...form, cost_per_unit: event.target.value })} /></label>
          )}
          {unitPrice > 0 && Number(form.rate_per_hectare) > 0 ? (
            <p className="field-hint">{money(unitPrice)} per {form.unit || 'unit'} · {money(previewPerHectare)} per hectare</p>
          ) : null}
          <div className="category-form-actions">
            <button type="submit" className="primary-btn small" disabled={saving}>{saving ? 'Saving…' : editingId ? `Update ${label.toLowerCase()}` : `Add ${label.toLowerCase()}`}</button>
            {editingId ? <button type="button" className="ghost-btn small" onClick={reset}>Cancel</button> : null}
          </div>
        </form>
      )}
    </article>
  )
}
