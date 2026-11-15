// Input allocation. Seed, Fertilizer and Chemicals each come from their own programme and batch.
//
// Steps: farmer, agri year, crop and hectares, then a programme (and batch) for each input
// category, then a summary of quantities, stock and costs, then a confirmation. Confirming takes
// the stock out of the chosen batches. Cancelling returns it, with a record in each batch's history.

import { useCallback, useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import FarmerAutocomplete from '../components/FarmerAutocomplete'
import Icon from '../components/Icon'
import { CATEGORIES } from '../inputCategories'
import SearchSelect from '../components/SearchSelect'
import { DraftNotice, EmptyState, Modal, PageHead, Pill, errorMessage } from '../components/ui'
import { useFormDraft } from '../drafts'

const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])
const STATUS = { ALLOCATED: ['Allocated', 'good'], PENDING: ['Pending farmer approval', 'warn'], COLLECTED: ['Collected', 'good'], CANCELLED: ['Cancelled', 'bad'] }
const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map(([code, label]) => [code, label]))
const EMPTY = { farmer: '', farm: '', crop: '', hectares: '', selections: { SEED: { programme: '', batch: '' }, FERTILIZER: { programme: '', batch: '' }, CHEMICALS: { programme: '', batch: '' } } }
const money = (value) => (value === null || value === undefined ? '—' : Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' }))
const qty = (value) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })

async function loadAll(path, params = {}) {
  const rows = []
  let response = await apiClient.get(path, { params: { ...params, page_size: 200 } })
  rows.push(...listOf(response.data))
  for (let page = 2; response.data?.next && page < 30; page += 1) {
    response = await apiClient.get(path, { params: { ...params, page_size: 200, page } })
    rows.push(...listOf(response.data))
  }
  return rows
}

function InputAllocationsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { can, profile } = useAuth()
  const canAllocate = can('allocations', 'create')
  const canCancel = can('allocations', 'edit')
  const showMoney = profile?.role !== 'lead_farmer'
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [token, setToken] = useState(0)
  const [expanded, setExpanded] = useState(null)
  const [cancelling, setCancelling] = useState(null)
  const blocked = periodStatus !== 'ready' || !selectedSeason

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id }
    if (cropSeason) params.crop_season = cropSeason
    if (statusFilter) params.status = statusFilter
    loadAll('/input-allocations/', params)
      .then((list) => { if (active) { setRows(list); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Input allocations could not be loaded.')) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, statusFilter, token])

  const refresh = useCallback(() => setToken((value) => value + 1), [])
  const totals = useMemo(() => {
    const live = rows.filter((row) => row.status !== 'CANCELLED')
    return { count: live.length, hectares: live.reduce((sum, row) => sum + Number(row.hectares || 0), 0), cost: live.reduce((sum, row) => sum + Number(row.total_input_cost || 0), 0) }
  }, [rows])

  return (
    <div className="page-card allocation-page">
      <PageHead title="Input allocations" subtitle="Allocate seed, fertilizer and chemicals to a farmer's crop. Each input category can come from a different programme, and stock is taken from that programme's request batch." />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}

      {canAllocate && !blocked ? (
        <AllocationForm
          season={selectedSeason}
          cropSeason={cropSeason}
          showMoney={showMoney}
          onAllocated={(allocation) => { setNotice(`Inputs allocated to ${allocation.farmer_name} for ${allocation.crop_name || allocation.crop}. Stock was taken from the chosen batches.`); refresh() }}
        />
      ) : null}

      <section className="card">
        <div className="card-head">
          <div>
            <h3>Allocations for {selectedSeason?.name || 'the agri year'}</h3>
            <p className="card-sub">{totals.count} active allocation{totals.count === 1 ? '' : 's'} · {qty(totals.hectares)} ha{showMoney ? ` · ${money(totals.cost)} in inputs` : ''}</p>
          </div>
          <select aria-label="Allocation status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">All statuses</option>
            <option value="ALLOCATED,PENDING,COLLECTED">Active</option>
            <option value="CANCELLED">Cancelled</option>
          </select>
        </div>
        {error ? <div className="form-message error" role="alert">{error}</div> : null}
        {loading && !blocked ? <div className="form-message">Loading allocations…</div> : null}
        {!loading && !rows.length ? <EmptyState icon="box" title="No allocations yet">Allocations for this agri year appear here.</EmptyState> : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Farmer</th><th>Crop</th><th className="num">Hectares</th><th>Seed</th><th>Fertilizer</th><th>Chemicals</th>{showMoney ? <th className="num">Input cost</th> : null}<th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.map((row) => {
                  const [label, tone] = STATUS[row.status] || [row.status, '']
                  const source = (code) => {
                    const lines = (row.calculation_lines || []).filter((line) => line.input_category === code)
                    if (!row.sourced_by_category) return code === 'SEED' ? row.programme_name : '—'
                    return lines.length ? [...new Set(lines.map((line) => line.programme_name))].join(', ') : 'Not supplied'
                  }
                  return (
                    <AllocationRow
                      key={row.id}
                      row={row}
                      label={label}
                      tone={tone}
                      source={source}
                      showMoney={showMoney}
                      open={expanded === row.id}
                      onToggle={() => setExpanded(expanded === row.id ? null : row.id)}
                      onCancel={canCancel && row.status !== 'CANCELLED' ? () => setCancelling(row) : null}
                    />
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
      {cancelling ? (
        <CancelAllocation
          allocation={cancelling}
          onClose={() => setCancelling(null)}
          onDone={(message) => { setCancelling(null); setNotice(message); refresh() }}
        />
      ) : null}
    </div>
  )
}

function AllocationRow({ row, label, tone, source, showMoney, open, onToggle, onCancel }) {
  const columns = showMoney ? 9 : 8
  return (
    <>
      <tr className={row.status === 'CANCELLED' ? 'inactive-row' : ''}>
        <td>{row.farmer_name}<small className="block-hint">{row.membership_number}</small></td>
        <td>{row.crop_name || row.crop}</td>
        <td className="num">{qty(row.hectares)}</td>
        <td>{source('SEED')}</td>
        <td>{source('FERTILIZER')}</td>
        <td>{source('CHEMICALS')}</td>
        {showMoney ? <td className="num">{money(row.total_input_cost)}</td> : null}
        <td><Pill tone={tone}>{label}</Pill></td>
        <td>
          <span className="table-actions">
            <button type="button" className="icon-btn" title={open ? 'Hide lines' : 'Show lines'} aria-label={`${open ? 'Hide' : 'Show'} lines for ${row.farmer_name}`} onClick={onToggle}><Icon name="eye" /></button>
            {onCancel ? <button type="button" className="ghost-btn small" onClick={onCancel}>Cancel</button> : null}
          </span>
        </td>
      </tr>
      {open ? (
        <tr className="allocation-lines">
          <td colSpan={columns}>
            {row.status === 'CANCELLED' ? <p className="card-sub">Cancelled {row.cancelled_at ? new Date(row.cancelled_at).toLocaleDateString() : ''}{row.cancelled_by_name ? ` by ${row.cancelled_by_name}` : ''}: {row.cancellation_reason || 'no reason recorded'}. Stock was returned to its batches.</p> : null}
            <table className="data-table compact">
              <thead><tr><th>Category</th><th>Programme</th><th>Input product</th><th>Batch</th><th className="num">Quantity</th>{showMoney ? <><th className="num">Unit price</th><th className="num">Cost</th></> : null}</tr></thead>
              <tbody>
                {(row.calculation_lines || []).map((line) => (
                  <tr key={line.id}>
                    <td>{CATEGORY_LABEL[line.input_category] || line.group_name}</td>
                    <td>{line.programme_name || row.programme_name}</td>
                    <td>{line.item_name}</td>
                    <td>{line.batch_number || '—'}</td>
                    <td className="num">{qty(line.required_quantity)} {line.unit}</td>
                    {showMoney ? <><td className="num">{money(line.cost_per_unit)}</td><td className="num">{money(line.calculated_cost)}</td></> : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      ) : null}
    </>
  )
}

function AllocationForm({ season, cropSeason, showMoney, onAllocated }) {
  const [form, setForm] = useState(EMPTY)
  const [farms, setFarms] = useState([])
  const [crops, setCrops] = useState([])
  const [options, setOptions] = useState(null)
  const [optionsKey, setOptionsKey] = useState('')
  const [plan, setPlan] = useState(null)
  const [planning, setPlanning] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const draft = useFormDraft({ key: `allocations:programme:${season.id}`, value: form, onRestore: (data) => setForm((current) => ({ ...current, ...data, selections: { ...EMPTY.selections, ...(data.selections || {}) } })) })

  useEffect(() => {
    let active = true
    loadAll('/crops/', cropSeason ? { active: true, category: cropSeason } : { active: true })
      .then((list) => { if (active) setCrops(list) })
      .catch(() => { if (active) setCrops([]) })
    return () => { active = false }
  }, [cropSeason])

  useEffect(() => {
    if (!form.farmer) return undefined
    let active = true
    apiClient.get('/farms/', { params: { farmer: form.farmer, page_size: 50 } })
      .then((response) => {
        if (!active) return
        const list = listOf(response.data)
        setFarms(list)
        if (list.length === 1) setForm((current) => (current.farm ? current : { ...current, farm: String(list[0].id) }))
      })
      .catch(() => { if (active) setFarms([]) })
    return () => { active = false }
  }, [form.farmer])

  // Programmes, products, prices and batches that can supply each category for this crop.
  useEffect(() => {
    if (!form.crop) return undefined
    let active = true
    const key = `${form.crop}:${form.farmer}:${season.id}`
    apiClient.get('/input-allocations/programme-options/', { params: { crop: form.crop, season: season.id, farmer: form.farmer || undefined } })
      .then((response) => {
        if (!active) return
        setOptions(response.data)
        if (response.data.crop_hectares) setForm((current) => (current.hectares ? current : { ...current, hectares: String(Number(response.data.crop_hectares)) }))
      })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Programmes for this crop could not be loaded.')) })
      .finally(() => { if (active) setOptionsKey(key) })
    return () => { active = false }
  }, [form.crop, form.farmer, season.id])
  const optionsLoading = Boolean(form.crop) && optionsKey !== `${form.crop}:${form.farmer}:${season.id}`

  const ready = form.farmer && form.crop && Number(form.hectares) > 0 && Object.values(form.selections).some((choice) => choice.programme)
  const payload = useMemo(() => ({
    farmer: Number(form.farmer), farm: form.farm ? Number(form.farm) : null, season: season.id, crop: Number(form.crop), hectares: form.hectares, crop_season: cropSeason || undefined,
    selections: Object.fromEntries(Object.entries(form.selections).filter(([, choice]) => choice.programme).map(([code, choice]) => [code, { programme: Number(choice.programme), batch: choice.batch ? Number(choice.batch) : null }])),
  }), [form, season.id, cropSeason])

  // The summary follows every change, so stock and costs are always current before confirming.
  useEffect(() => {
    if (!ready) return undefined
    let active = true
    const timer = setTimeout(() => {
      setPlanning(true)
      apiClient.post('/input-allocations/programme-preview/', payload)
        .then((response) => { if (active) { setPlan(response.data); setError('') } })
        .catch((requestError) => { if (active) { setPlan(null); setError(errorMessage(requestError, 'The allocation could not be worked out.')) } })
        .finally(() => { if (active) setPlanning(false) })
    }, 350)
    return () => { active = false; clearTimeout(timer) }
  }, [payload, ready])

  const setSelection = (code, changes) => setForm((current) => ({ ...current, selections: { ...current.selections, [code]: { ...current.selections[code], ...changes } } }))

  const confirm = async () => {
    setSaving(true)
    setError('')
    try {
      const response = await apiClient.post('/input-allocations/programme-allocate/', payload)
      draft.clear(EMPTY)
      setForm(EMPTY)
      setFarms([])
      setPlan(null)
      setOptions(null)
      setConfirming(false)
      onAllocated(response.data)
    } catch (requestError) {
      setConfirming(false)
      setError(errorMessage(requestError, 'The allocation could not be made.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card allocation-form">
      <div className="card-head"><h3><Icon name="plus" />New allocation</h3></div>
      <DraftNotice draft={draft} />
      <ol className="allocation-steps">
        <li>
          <h4><span>1</span>Farmer and crop</h4>
          <div className="workflow-fields">
            <FarmerAutocomplete label="Farmer" value={form.farmer} endpoint="/farmers/eligible/" seasonId={season.id} seasonName={season.name} required onChange={(farmer) => { setPlan(null); setForm((current) => ({ ...current, farmer: farmer ? String(farmer.id) : '', farm: '' })) }} />
            <label className="form-field">Farm
              <select value={form.farm} onChange={(event) => setForm({ ...form, farm: event.target.value })} disabled={!form.farmer}>
                <option value="">{form.farmer ? 'Choose a farm' : 'Choose a farmer first'}</option>
                {farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.farm_name} · {qty(farm.arable_hectares)} ha arable</option>)}
              </select>
            </label>
            <label className="form-field">Agri year<input value={season.name} readOnly title="Change the agri year in the header" /></label>
            <label className="form-field">Crop
              <select value={form.crop} onChange={(event) => { setPlan(null); setOptions(null); setForm({ ...form, crop: event.target.value, hectares: '', selections: EMPTY.selections }) }}>
                <option value="">Choose a crop</option>
                {crops.map((crop) => <option key={crop.id} value={crop.id}>{crop.name}</option>)}
              </select>
            </label>
            <label className="form-field">Hectares
              <input type="number" min="0.01" step="0.01" value={form.hectares} onChange={(event) => setForm({ ...form, hectares: event.target.value })} />
              {options?.crop_hectares ? <span className="field-hint">{qty(options.crop_hectares)} ha of this crop allocated to the farmer for {season.name}.</span> : null}
            </label>
          </div>
        </li>
        <li>
          <h4><span>2</span>Where each input comes from</h4>
          <p className="card-sub">Choose a programme for each category. They can all be different, or the same. Leave a category empty if the farmer does not get it.</p>
          {!form.crop ? <div className="form-message">Choose the crop first.</div> : null}
          {form.crop && optionsLoading ? <div className="form-message">Loading programmes…</div> : null}
          {form.crop && options ? (
            <div className="category-grid">
              {CATEGORIES.map(([code, label, icon]) => (
                <CategorySource
                  key={code}
                  label={label}
                  icon={icon}
                  entries={options.categories?.[code] || []}
                  choice={form.selections[code]}
                  showMoney={showMoney}
                  hectares={Number(form.hectares) || 0}
                  onChange={(changes) => setSelection(code, changes)}
                />
              ))}
            </div>
          ) : null}
        </li>
        <li>
          <h4><span>3</span>Summary</h4>
          {error ? <div className="form-message error" role="alert">{error}</div> : null}
          {!ready ? <div className="form-message">Fill in the farmer, crop, hectares and at least one programme to see the summary.</div> : null}
          {ready && planning && !plan ? <div className="form-message">Working out quantities and stock…</div> : null}
          {ready && plan ? <AllocationSummary plan={plan} showMoney={showMoney} /> : null}
          <div className="workflow-form-actions">
            <button type="button" className="primary-btn" disabled={!plan?.can_confirm || planning || saving} onClick={() => setConfirming(true)}><Icon name="check" />Review and confirm</button>
          </div>
        </li>
      </ol>
      {confirming && plan ? (
        <Modal
          wide
          title="Confirm this allocation"
          subtitle="Confirming takes these quantities out of the batches shown and records the cost as the farmer's input debt."
          onClose={() => setConfirming(false)}
          footer={<><button type="button" className="ghost-btn" onClick={() => setConfirming(false)}>Back</button><button type="button" className="primary-btn" disabled={saving} onClick={confirm}>{saving ? 'Allocating…' : 'Confirm allocation'}</button></>}
        >
          <AllocationSummary plan={plan} showMoney={showMoney} />
        </Modal>
      ) : null}
    </section>
  )
}

function CategorySource({ label, icon, entries, choice, showMoney, hectares, onChange }) {
  const entry = entries.find((item) => String(item.programme) === String(choice.programme))
  const batches = entry?.batches || []
  return (
    <article className={choice.programme ? 'category-panel' : 'category-panel muted'}>
      <header><h4><Icon name={icon} />{label}</h4>{choice.programme ? <Pill tone="good">{entry?.programme_name}</Pill> : <Pill>Not supplied</Pill>}</header>
      <SearchSelect
        label={`${label} programme`}
        value={choice.programme}
        onChange={(value) => onChange({ programme: value, batch: '' })}
        placeholder={entries.length ? `Choose the ${label.toLowerCase()} programme` : 'No programme supplies this'}
        disabled={!entries.length}
        options={[{ value: '', label: `No ${label.toLowerCase()}` }, ...entries.map((item) => ({ value: String(item.programme), label: `${item.programme_name}${item.programme_code ? ` (${item.programme_code})` : ''}` }))]}
        emptyText={`No programme has ${label.toLowerCase()} configured for this crop. Add it in the Crop Catalogue.`}
      />
      {entry ? (
        <>
          <label className="form-field">Request batch
            <select value={choice.batch} onChange={(event) => onChange({ batch: event.target.value })}>
              <option value="">Pick automatically (first batch with enough stock)</option>
              {batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.request_number}{batch.covers_all_products ? '' : ' (missing some products)'}</option>)}
            </select>
            {!batches.length ? <span className="field-error">No submitted or approved batch of {entry.programme_name} holds these products.</span> : null}
          </label>
          <ul className="source-products">
            {entry.products.map((product) => {
              const batch = batches.find((item) => String(item.id) === String(choice.batch)) || batches.find((item) => item.covers_all_products) || batches[0]
              const stock = batch?.products?.[product.input_product]
              return (
                <li key={product.input_product}>
                  <strong>{product.name}</strong>
                  <span>{qty(product.rate_per_hectare)} {product.unit}/ha{hectares ? ` → ${qty(product.rate_per_hectare * hectares)} ${product.unit}` : ''}{showMoney && product.unit_price ? ` · ${money(product.unit_price)}/${product.unit}` : ''}</span>
                  <span className={stock ? '' : 'field-error'}>{stock ? `${qty(stock.available)} ${stock.unit} available in ${batch.request_number}` : 'Not in a batch'}</span>
                </li>
              )
            })}
          </ul>
        </>
      ) : null}
    </article>
  )
}

function AllocationSummary({ plan, showMoney }) {
  const used = plan.categories.filter((entry) => entry.programme)
  return (
    <div className="allocation-summary">
      {plan.problems.length ? (
        <div className="form-message error" role="alert">
          <strong>This allocation cannot be confirmed yet:</strong>
          <ul>{plan.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
        </div>
      ) : null}
      <p className="card-sub">{plan.hectares} ha of {plan.crop_name} for {plan.season_name}.</p>
      <div className="table-wrap">
        <table className="data-table compact">
          <thead><tr><th>Category</th><th>Programme</th><th>Input product</th><th>Batch</th><th className="num">Required</th><th className="num">Available</th><th className="num">Left after</th>{showMoney ? <><th className="num">Unit price</th><th className="num">Total cost</th></> : null}</tr></thead>
          <tbody>
            {used.map((entry) => (
              <SummaryCategory key={entry.category} entry={entry} showMoney={showMoney} />
            ))}
          </tbody>
          {showMoney ? <tfoot><tr><td colSpan="8"><strong>Total input allocation cost</strong></td><td className="num"><strong>{money(plan.total_cost)}</strong></td></tr></tfoot> : null}
        </table>
      </div>
    </div>
  )
}

function SummaryCategory({ entry, showMoney }) {
  return (
    <>
      {entry.lines.map((line, index) => (
        <tr key={line.input_product} className={line.sufficient ? '' : 'shortage-row'}>
          <td>{index === 0 ? entry.label : ''}</td>
          <td>{index === 0 ? entry.programme_name : ''}</td>
          <td>{line.product_name}</td>
          <td>{line.batch_number || '—'}</td>
          <td className="num">{qty(line.required_quantity)} {line.unit}</td>
          <td className="num">{qty(line.available_quantity)} {line.unit}</td>
          <td className="num">{line.sufficient ? `${qty(line.available_after)} ${line.unit}` : 'Not enough'}</td>
          {showMoney ? <><td className="num">{money(line.unit_price)}</td><td className="num">{money(line.cost)}</td></> : null}
        </tr>
      ))}
      <tr className="category-total">
        <td colSpan={showMoney ? 4 : 4}>{entry.label} total</td>
        <td className="num">{qty(entry.total_quantity)}</td>
        <td colSpan={showMoney ? 3 : 2} />
        {showMoney ? <td className="num">{money(entry.total_cost)}</td> : null}
      </tr>
    </>
  )
}

function CancelAllocation({ allocation, onClose, onDone }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const submit = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      await apiClient.post(`/input-allocations/${allocation.id}/cancel/`, { reason })
      onDone(`Allocation for ${allocation.farmer_name} cancelled. Stock went back to its batches and the input debt was cancelled.`)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The allocation could not be cancelled.'))
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal title={`Cancel the allocation for ${allocation.farmer_name}`} subtitle="The stock goes back to the batches it came from, with a record in each batch's history. The allocation itself is kept, marked cancelled." onClose={onClose}
      footer={<><button type="button" className="ghost-btn" onClick={onClose}>Keep it</button><button type="submit" form="cancel-allocation-form" className="danger-solid" disabled={saving}>{saving ? 'Cancelling…' : 'Cancel allocation'}</button></>}>
      <form id="cancel-allocation-form" onSubmit={submit}>
        {error ? <div className="form-message error" role="alert">{error}</div> : null}
        <label className="form-field">Reason<textarea required rows="3" value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      </form>
    </Modal>
  )
}

export default InputAllocationsPage
