// Request batch stock: the inputs each batch holds, what is already allocated and what is left.
//
// Quantities belong to their batch. The same product in another programme's batch is a separate
// balance. Every change is kept in the batch's history: the opening quantity, changes to it,
// allocations to farmers and reversals.

import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from './Icon'
import { CATEGORIES } from '../inputCategories'
import { EmptyState, Modal, Pill, errorMessage } from './ui'

const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])
const quantity = (value) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })
const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map(([code, label]) => [code, label]))
const STATUS_TONE = { APPROVED: 'good', SUBMITTED: 'info', PENDING: 'warn', REJECTED: 'bad' }

export default function BatchStock({ selectedSeason }) {
  const { can } = useAuth()
  const canEdit = can('arda', 'edit')
  const [batches, setBatches] = useState([])
  const [batchId, setBatchId] = useState('')
  const [batchLines, setLines] = useState([])
  const [token, setToken] = useState(0)
  const [products, setProducts] = useState([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [form, setForm] = useState({ input_category: 'SEED', input_product: '', requested_quantity: '', unit: '' })
  const [changing, setChanging] = useState(null)
  const [history, setHistory] = useState(null)

  useEffect(() => {
    let active = true
    const params = { page_size: 200 }
    if (selectedSeason?.id) params.season = selectedSeason.id
    Promise.all([apiClient.get('/arda-request-batches/', { params }), apiClient.get('/inputs/', { params: { page_size: 500 } })])
      .then(([batchResponse, productResponse]) => {
        if (!active) return
        setBatches(listOf(batchResponse.data))
        setProducts(listOf(productResponse.data))
      })
      .catch(() => { if (active) setError('Request batches could not be loaded.') })
    return () => { active = false }
  }, [selectedSeason?.id])

  const lines = batchId ? batchLines : []
  const loadLines = () => setToken((value) => value + 1)

  useEffect(() => {
    if (!batchId) return undefined
    let active = true
    apiClient.get('/request-batch-inputs/', { params: { batch: batchId, page_size: 200 } })
      .then((response) => { if (active) setLines(listOf(response.data)) })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'The batch inputs could not be loaded.')) })
    return () => { active = false }
  }, [batchId, token])

  const batch = batches.find((item) => String(item.id) === String(batchId))
  const categoryProducts = products.filter((product) => product.category === form.input_category && !lines.some((line) => line.input_product === product.id))

  const addLine = async (event) => {
    event.preventDefault()
    setError('')
    try {
      await apiClient.post('/request-batch-inputs/', { ...form, batch: Number(batchId), input_product: Number(form.input_product) })
      setNotice('Input added to the batch.')
      setForm({ input_category: form.input_category, input_product: '', requested_quantity: '', unit: '' })
      loadLines()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The input could not be added.'))
    }
  }

  const remove = async (line) => {
    if (!window.confirm(`Remove ${line.product_name} from batch ${line.batch_number}?`)) return
    try {
      await apiClient.delete(`/request-batch-inputs/${line.id}/`)
      setNotice(`${line.product_name} removed from the batch.`)
      loadLines()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The input could not be removed.'))
    }
  }

  return (
    <section className="card batch-stock">
      <div className="card-head">
        <div>
          <h3><Icon name="box" />Request batch stock</h3>
          <p className="card-sub">The input products each request batch holds. Allocations take stock from their own batch only, and every change is kept in the batch history.</p>
        </div>
      </div>
      <label className="form-field batch-picker">
        Request batch
        <select value={batchId} onChange={(event) => { setNotice(''); setBatchId(event.target.value) }}>
          <option value="">Choose a request batch</option>
          {batches.map((item) => <option key={item.id} value={item.id}>{item.request_number} · {item.programme_name}{item.season_name ? ` · ${item.season_name}` : ''} · {item.status}</option>)}
        </select>
      </label>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {!batch ? <EmptyState icon="box" title="Choose a request batch">{batches.length ? 'Pick a batch to see the inputs it holds and how much is left.' : 'Create a request batch above first.'}</EmptyState> : (
        <>
          <p className="batch-meta">
            <strong>{batch.programme_name}</strong> · <Pill tone={STATUS_TONE[batch.status]}>{batch.status}</Pill>
            {['SUBMITTED', 'APPROVED'].includes(batch.status) ? ' Its stock can be allocated.' : ' Stock can be allocated once the batch is submitted or approved.'}
          </p>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Category</th><th>Input product</th><th className="num">Requested</th><th className="num">Allocated</th><th className="num">Available</th><th>Unit</th><th>Actions</th></tr></thead>
              <tbody>
                {lines.map((line) => {
                  const used = Number(line.requested_quantity) ? Math.round((Number(line.allocated_quantity) / Number(line.requested_quantity)) * 100) : 0
                  return (
                    <tr key={line.id}>
                      <td>{CATEGORY_LABEL[line.input_category] || line.input_category}</td>
                      <td>{line.product_name}</td>
                      <td className="num">{quantity(line.requested_quantity)}</td>
                      <td className="num">{quantity(line.allocated_quantity)} <small>({used}%)</small></td>
                      <td className="num"><strong>{quantity(line.available_quantity)}</strong></td>
                      <td>{line.unit}</td>
                      <td>
                        <span className="table-actions">
                          <button type="button" className="ghost-btn small" onClick={() => setHistory(line)}><Icon name="history" />History</button>
                          {canEdit ? <button type="button" className="icon-btn" title="Change requested quantity" aria-label={`Change ${line.product_name} quantity`} onClick={() => setChanging(line)}><Icon name="pencil" /></button> : null}
                          {canEdit && Number(line.allocated_quantity) === 0 ? <button type="button" className="icon-btn danger" title="Remove" aria-label={`Remove ${line.product_name}`} onClick={() => remove(line)}><Icon name="trash" /></button> : null}
                        </span>
                      </td>
                    </tr>
                  )
                })}
                {!lines.length ? <tr><td colSpan="7">This batch holds no input products yet.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {canEdit ? (
            <form className="workflow-form batch-line-form" onSubmit={addLine}>
              <h4>Add an input product to {batch.request_number}</h4>
              <div className="workflow-fields">
                <label className="form-field">Category
                  <select value={form.input_category} onChange={(event) => setForm({ ...form, input_category: event.target.value, input_product: '' })}>
                    {CATEGORIES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                  </select>
                </label>
                <label className="form-field">Input product
                  <select required value={form.input_product} onChange={(event) => {
                    const product = products.find((item) => String(item.id) === event.target.value)
                    setForm({ ...form, input_product: event.target.value, unit: product?.unit || '' })
                  }}>
                    <option value="">{categoryProducts.length ? 'Choose a product' : 'No products in this category. Add them in the Crop Catalogue.'}</option>
                    {categoryProducts.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
                  </select>
                </label>
                <label className="form-field">Requested quantity<input required type="number" min="0.0001" step="0.0001" value={form.requested_quantity} onChange={(event) => setForm({ ...form, requested_quantity: event.target.value })} /></label>
                <label className="form-field">Unit<input value={form.unit} onChange={(event) => setForm({ ...form, unit: event.target.value })} placeholder="kg" /></label>
              </div>
              <div className="workflow-form-actions"><button type="submit" className="primary-btn small"><Icon name="plus" />Add to batch</button></div>
            </form>
          ) : null}
        </>
      )}
      {changing ? <ChangeQuantity line={changing} onClose={() => setChanging(null)} onSaved={() => { setChanging(null); setNotice('Requested quantity changed and recorded in the batch history.'); loadLines() }} /> : null}
      {history ? <History line={history} onClose={() => setHistory(null)} /> : null}
    </section>
  )
}

function ChangeQuantity({ line, onClose, onSaved }) {
  const [value, setValue] = useState(line.requested_quantity)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const save = async (event) => {
    event.preventDefault()
    try {
      await apiClient.patch(`/request-batch-inputs/${line.id}/`, { requested_quantity: value, reason })
      onSaved()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The quantity could not be changed.'))
    }
  }
  return (
    <Modal title={`Change ${line.product_name} in ${line.batch_number}`} subtitle={`${quantity(line.allocated_quantity)} ${line.unit} is already allocated, so the quantity cannot go below that.`} onClose={onClose}
      footer={<><button type="button" className="ghost-btn" onClick={onClose}>Cancel</button><button type="submit" form="batch-quantity-form" className="primary-btn">Save quantity</button></>}>
      <form id="batch-quantity-form" onSubmit={save}>
        {error ? <div className="form-message error" role="alert">{error}</div> : null}
        <label className="form-field">Requested quantity ({line.unit})<input required type="number" min={line.allocated_quantity} step="0.0001" value={value} onChange={(event) => setValue(event.target.value)} /></label>
        <label className="form-field">Reason<input required value={reason} onChange={(event) => setReason(event.target.value)} placeholder="For example, second delivery received" /></label>
      </form>
    </Modal>
  )
}

function History({ line, onClose }) {
  const [rows, setRows] = useState(null)
  useEffect(() => {
    let active = true
    apiClient.get(`/request-batch-inputs/${line.id}/movements/`).then((response) => { if (active) setRows(response.data) }).catch(() => { if (active) setRows([]) })
    return () => { active = false }
  }, [line.id])
  return (
    <Modal wide title={`${line.product_name} in ${line.batch_number}: history`} onClose={onClose} footer={<button type="button" className="ghost-btn" onClick={onClose}>Close</button>}>
      {rows === null ? <div className="form-message">Loading…</div> : (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr><th>When</th><th>What happened</th><th className="num">Change ({line.unit})</th><th className="num">Available after</th><th>Farmer</th><th>By</th><th>Reason</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{new Date(row.created_at).toLocaleString()}</td>
                  <td>{row.kind_label}</td>
                  <td className="num">{Number(row.quantity) > 0 ? '+' : ''}{quantity(row.quantity)}</td>
                  <td className="num">{quantity(row.available_after)}</td>
                  <td>{row.farmer_name || '—'}</td>
                  <td>{row.created_by_name || '—'}</td>
                  <td>{row.reason || '—'}</td>
                </tr>
              ))}
              {!rows.length ? <tr><td colSpan="7">No history yet.</td></tr> : null}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
