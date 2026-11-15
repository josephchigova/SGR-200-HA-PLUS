// Programme catalogue for one crop: crop -> programme -> category -> product -> quantity per ha -> price.
//
// The same crop can need different products at different prices under different programmes,
// so each programme keeps its own lines. Seed, Fertilizer and Chemicals are set up separately,
// and a programme may supply only some of them.

import { useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import Icon from './Icon'
import SearchSelect from './SearchSelect'
import { CATEGORIES } from '../inputCategories'
import { EmptyState, Pill, errorMessage } from './ui'
const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])
const money = (value) => (value === null || value === undefined || value === '' ? '—' : Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' }))
const quantity = (value) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 4 })

async function loadAll(path) {
  const rows = []
  let url = path
  for (let page = 0; url && page < 20; page += 1) {
    const response = await apiClient.get(url)
    rows.push(...listOf(response.data))
    url = response.data?.next ? response.data.next.replace(/^.*\/api/, '') : null
  }
  return rows
}

export default function ProgrammeCatalogue({ crop, readOnly }) {
  const [programmes, setProgrammes] = useState([])
  const [products, setProducts] = useState([])
  const [programmeId, setProgrammeId] = useState('')
  const [rows, setRows] = useState([])
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let active = true
    Promise.all([loadAll('/programmes/?page_size=200'), loadAll('/inputs/?page_size=500')])
      .then(([programmeRows, productRows]) => {
        if (!active) return
        setProgrammes(programmeRows.filter((programme) => programme.is_active !== false))
        setProducts(productRows)
      })
      .catch(() => { if (active) setError('Programmes and input products could not be loaded.') })
    return () => { active = false }
  }, [])

  const requestKey = `${crop?.id}:${programmeId}:${token}`
  const loading = Boolean(crop?.id && programmeId) && loadedKey !== requestKey
  const load = () => setToken((value) => value + 1)

  useEffect(() => {
    if (!crop?.id || !programmeId) return undefined
    let active = true
    loadAll(`/crop-input-requirements/?crop=${crop.id}&programme=${programmeId}`)
      .then((list) => { if (active) { setRows(list); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'The programme catalogue could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [crop?.id, programmeId, requestKey])

  const programme = programmes.find((item) => String(item.id) === String(programmeId))
  const supplied = programme?.input_categories?.length ? programme.input_categories : CATEGORIES.map(([code]) => code).filter((code) => rows.some((row) => row.input_category === code))

  const toggleCategory = async (code) => {
    if (!programme || readOnly) return
    const next = supplied.includes(code) ? supplied.filter((item) => item !== code) : [...supplied, code]
    try {
      const response = await apiClient.patch(`/programmes/${programme.id}/`, { input_categories: next })
      setProgrammes((current) => current.map((item) => (item.id === programme.id ? { ...item, ...response.data } : item)))
    } catch (requestError) {
      setError(errorMessage(requestError, 'The categories this programme supplies could not be saved.'))
    }
  }

  const addProduct = (product) => setProducts((current) => [...current, product])

  if (!crop) return null
  return (
    <section className="card programme-catalogue">
      <div className="card-head">
        <div>
          <h3>{crop.name}: inputs by programme</h3>
          <p className="card-sub">Each programme has its own products and prices for {crop.name}. Seed, Fertilizer and Chemicals are set up separately, and a farmer can get each from a different programme.</p>
        </div>
      </div>
      <div className="programme-catalogue-picker">
        <SearchSelect
          label="Programme"
          value={programmeId}
          onChange={(value) => { setNotice(''); setProgrammeId(value) }}
          placeholder="Choose a programme"
          options={programmes.map((item) => ({ value: String(item.id), label: `${item.name}${item.code ? ` (${item.code})` : ''}${item.season_name ? ` · ${item.season_name}` : ''}` }))}
          emptyText="No programmes yet. Add one on the Programmes page."
        />
        {programme ? (
          <div className="category-chips" role="group" aria-label="Categories this programme supplies">
            <span>Supplies:</span>
            {CATEGORIES.map(([code, label]) => (
              <button key={code} type="button" className={supplied.includes(code) ? 'chip active' : 'chip'} aria-pressed={supplied.includes(code)} disabled={readOnly} onClick={() => toggleCategory(code)}>{label}</button>
            ))}
          </div>
        ) : null}
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {!programme ? <EmptyState icon="book" title="Choose a programme">Pick the programme whose {crop.name} inputs and prices you want to see or change.</EmptyState> : null}
      {programme && loading ? <div className="form-message">Loading {programme.name}…</div> : null}
      {programme && !loading ? (
        <div className="category-grid">
          {CATEGORIES.map(([code, label, icon]) => (
            <CategoryPanel
              key={code}
              code={code}
              label={label}
              icon={icon}
              crop={crop}
              programme={programme}
              rows={rows.filter((row) => row.input_category === code)}
              products={products.filter((product) => product.category === code)}
              supplied={supplied.includes(code)}
              readOnly={readOnly}
              onProductCreated={addProduct}
              onChanged={(message) => { setNotice(message); load() }}
              onError={setError}
            />
          ))}
        </div>
      ) : null}
    </section>
  )
}

const EMPTY_LINE = { input_product: '', rate_per_hectare: '', unit: '', cost_per_unit: '' }

function CategoryPanel({ code, label, icon, crop, programme, rows, products, supplied, readOnly, onProductCreated, onChanged, onError }) {
  const [form, setForm] = useState(EMPTY_LINE)
  const [editingId, setEditingId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newProduct, setNewProduct] = useState({ name: '', unit: code === 'CHEMICALS' ? 'litres' : 'kg' })
  const used = useMemo(() => new Set(rows.map((row) => String(row.input_product))), [rows])
  const choices = products.filter((product) => !used.has(String(product.id)) || String(product.id) === String(form.input_product))
  const costPerHectare = rows.filter((row) => row.active).reduce((total, row) => total + Number(row.cost_per_hectare || 0), 0)

  const reset = () => { setForm(EMPTY_LINE); setEditingId(null) }

  const save = async (event) => {
    event.preventDefault()
    setSaving(true)
    onError('')
    const payload = {
      crop: crop.id, programme: programme.id, input_category: code, input_product: Number(form.input_product),
      rate_per_hectare: form.rate_per_hectare, cost_per_unit: form.cost_per_unit, unit: form.unit,
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

  return (
    <article className={supplied ? 'category-panel' : 'category-panel muted'}>
      <header>
        <h4><Icon name={icon} />{label}</h4>
        {supplied ? <Pill tone="good">Supplied</Pill> : <Pill>Not supplied</Pill>}
      </header>
      <div className="table-wrap">
        <table className="data-table compact">
          <thead><tr><th>Input product</th><th className="num">Qty per ha</th><th className="num">Unit price</th><th className="num">Cost per ha</th><th /></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={row.active ? '' : 'inactive-row'}>
                <td>{row.input_product_name}{row.active ? '' : ' (inactive)'}</td>
                <td className="num">{quantity(row.rate_per_hectare)} {row.unit}</td>
                <td className="num">{money(row.cost_per_unit)} / {row.unit}</td>
                <td className="num">{money(row.cost_per_hectare)}</td>
                <td>
                  {readOnly ? null : (
                    <span className="table-actions">
                      <button type="button" className="icon-btn" title="Edit" aria-label={`Edit ${row.input_product_name}`} onClick={() => { setEditingId(row.id); setForm({ input_product: String(row.input_product), rate_per_hectare: row.rate_per_hectare, unit: row.unit, cost_per_unit: row.cost_per_unit }) }}><Icon name="pencil" /></button>
                      <button type="button" className="ghost-btn small" onClick={() => toggleActive(row)}>{row.active ? 'Deactivate' : 'Activate'}</button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length ? <tr><td colSpan="5">{supplied ? `No ${label.toLowerCase()} set for ${crop.name} yet.` : `${programme.name} does not supply ${label.toLowerCase()}.`}</td></tr> : null}
          </tbody>
          {rows.length ? <tfoot><tr><td colSpan="3">{label} cost per hectare</td><td className="num"><strong>{money(costPerHectare)}</strong></td><td /></tr></tfoot> : null}
        </table>
      </div>
      {readOnly ? null : (
        <form className="category-form" onSubmit={save}>
          <label className="form-field">
            Input product
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
              <input aria-label={`New ${label.toLowerCase()} product name`} placeholder="Product name" value={newProduct.name} onChange={(event) => setNewProduct({ ...newProduct, name: event.target.value })} />
              <input aria-label="Unit" placeholder="Unit" value={newProduct.unit} onChange={(event) => setNewProduct({ ...newProduct, unit: event.target.value })} />
              <button type="button" className="ghost-btn small" onClick={createProduct}>Add product</button>
              <button type="button" className="ghost-btn small" onClick={() => setCreating(false)}>Cancel</button>
            </div>
          ) : <button type="button" className="link-btn" onClick={() => setCreating(true)}><Icon name="plus" />New {label.toLowerCase()} product</button>}
          <label className="form-field">Quantity per ha<input required type="number" min="0.0001" step="0.0001" value={form.rate_per_hectare} onChange={(event) => setForm({ ...form, rate_per_hectare: event.target.value })} /></label>
          <label className="form-field">Unit<input value={form.unit} onChange={(event) => setForm({ ...form, unit: event.target.value })} placeholder="kg" /></label>
          <label className="form-field">Unit price (USD)<input required type="number" min="0.01" step="0.01" value={form.cost_per_unit} onChange={(event) => setForm({ ...form, cost_per_unit: event.target.value })} /></label>
          <div className="category-form-actions">
            <button type="submit" className="primary-btn small" disabled={saving}>{saving ? 'Saving…' : editingId ? `Update ${label.toLowerCase()}` : `Add ${label.toLowerCase()}`}</button>
            {editingId ? <button type="button" className="ghost-btn small" onClick={reset}>Cancel</button> : null}
          </div>
        </form>
      )}
    </article>
  )
}
