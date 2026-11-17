// Input allocation: programme -> programme crop catalogue -> approved input request -> farmer.
//
// Steps: farmer, crop, programme, approved request, input types and hectares, then a summary of
// products, quantities and costs from the programme's own catalogue, then a confirmation. The
// server works out every quantity and price again before saving, and the allocation uses the
// request's approved hectares. Cancelling gives them back.

import { useCallback, useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import FarmerAutocomplete from '../components/FarmerAutocomplete'
import Icon from '../components/Icon'
import { CATEGORIES } from '../inputCategories'
import { DraftNotice, EmptyState, Modal, PageHead, Pill, errorMessage } from '../components/ui'
import { useFormDraft } from '../drafts'
import { CATEGORY_LABEL, listOf, loadAll, money, qty } from '../programmeData'

const STATUS = { ALLOCATED: ['Allocated', 'good'], PENDING: ['Pending farmer approval', 'warn'], COLLECTED: ['Collected', 'good'], CANCELLED: ['Cancelled', 'bad'] }
const EMPTY = { farmer: '', farm: '', crop: '', programme: '', request_batch: '', hectares: '', input_categories: [], request_lines: [] }

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
  const [search, setSearch] = useState('')
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
    if (search.trim()) params.search = search.trim()
    loadAll('/input-allocations/', params)
      .then((list) => { if (active) { setRows(list); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Input allocations could not be loaded.')) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, statusFilter, search, token])

  const refresh = useCallback(() => setToken((value) => value + 1), [])
  const totals = useMemo(() => {
    const live = rows.filter((row) => row.status !== 'CANCELLED')
    return { count: live.length, hectares: live.reduce((sum, row) => sum + Number(row.hectares || 0), 0), cost: live.reduce((sum, row) => sum + Number(row.total_input_cost || 0), 0) }
  }, [rows])

  return (
    <div className="page-card allocation-page">
      <PageHead title="Input allocations" subtitle="Give a farmer the inputs a programme's catalogue sets for their crop, from one of the programme's approved input requests. The farmer can get different input types from different programmes, but never the same input type twice." />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}

      {canAllocate && !blocked ? (
        <AllocationForm
          season={selectedSeason}
          cropSeason={cropSeason}
          showMoney={showMoney}
          onAllocated={(allocation) => { setNotice(`Inputs allocated to ${allocation.farmer_name} for ${allocation.crop_name || allocation.crop} from ${allocation.programme_name} (${allocation.request_number}).`); refresh() }}
        />
      ) : null}

      <section className="card">
        <div className="card-head">
          <div>
            <h3>Allocations for {selectedSeason?.name || 'the agri year'}</h3>
            <p className="card-sub">{totals.count} active allocation{totals.count === 1 ? '' : 's'} · {qty(totals.hectares)} ha{showMoney ? ` · ${money(totals.cost)} in inputs` : ''}</p>
          </div>
          <div className="filter-row compact">
            <input type="search" aria-label="Search allocations" placeholder="Farmer, membership or request" value={search} onChange={(event) => setSearch(event.target.value)} />
            <select aria-label="Allocation status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">All statuses</option>
              <option value="ALLOCATED,PENDING,COLLECTED">Active</option>
              <option value="CANCELLED">Cancelled</option>
            </select>
          </div>
        </div>
        {error ? <div className="form-message error" role="alert">{error}</div> : null}
        {loading && !blocked ? <div className="form-message">Loading allocations…</div> : null}
        {!loading && !rows.length ? <EmptyState icon="box" title="No allocations yet">Allocations for this agri year appear here.</EmptyState> : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Farmer</th><th>Programme</th><th>Crop</th><th>Year and season</th><th>Request</th><th className="num">Hectares</th><th>Inputs</th>{showMoney ? <th className="num">Total cost</th> : null}<th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.map((row) => {
                  const [label, tone] = STATUS[row.status] || [row.status, '']
                  return (
                    <AllocationRow
                      key={row.id}
                      row={row}
                      label={label}
                      tone={tone}
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

function AllocationRow({ row, label, tone, showMoney, open, onToggle, onCancel }) {
  const columns = showMoney ? 10 : 9
  const types = [...new Set((row.calculation_lines || []).map((line) => CATEGORY_LABEL[line.input_category] || line.group_name))]
  return (
    <>
      <tr className={row.status === 'CANCELLED' ? 'inactive-row' : ''}>
        <td>{row.farmer_name}<small className="block-hint">{row.membership_number}</small></td>
        <td>{row.programme_name}</td>
        <td>{row.crop_name || row.crop}</td>
        <td>{row.season_name}{row.crop_season ? ` · ${row.crop_season}` : ''}</td>
        <td>{row.request_number || <small className="block-hint">Before approved requests</small>}</td>
        <td className="num">{qty(row.hectares)} ha</td>
        <td>{types.join(', ') || '—'}<small className="block-hint">{(row.calculation_lines || []).length} product{(row.calculation_lines || []).length === 1 ? '' : 's'}</small></td>
        {showMoney ? <td className="num">{money(row.total_input_cost)}</td> : null}
        <td><Pill tone={tone}>{label}</Pill></td>
        <td>
          <span className="table-actions">
            <button type="button" className="icon-btn" title={open ? 'Hide products' : 'Show products'} aria-label={`${open ? 'Hide' : 'Show'} products for ${row.farmer_name}`} onClick={onToggle}><Icon name="eye" /></button>
            {onCancel ? <button type="button" className="ghost-btn small" onClick={onCancel}>Cancel</button> : null}
          </span>
        </td>
      </tr>
      {open ? (
        <tr className="allocation-lines">
          <td colSpan={columns}>
            {row.status === 'CANCELLED' ? <p className="card-sub">Cancelled {row.cancelled_at ? new Date(row.cancelled_at).toLocaleDateString() : ''}{row.cancelled_by_name ? ` by ${row.cancelled_by_name}` : ''}: {row.cancellation_reason || 'no reason recorded'}. Its hectares went back to the input request.</p> : null}
            <p className="card-sub">Prices are the ones in {row.programme_name}'s catalogue when this allocation was made.</p>
            <table className="data-table compact">
              <thead><tr><th>Input type</th><th>Product or variety</th><th className="num">Qty per ha</th><th className="num">Quantity</th>{showMoney ? <><th className="num">Unit price</th><th className="num">Cost</th></> : null}</tr></thead>
              <tbody>
                {(row.calculation_lines || []).map((line) => (
                  <tr key={line.id}>
                    <td>{CATEGORY_LABEL[line.input_category] || line.group_name}</td>
                    <td>{line.item_name}</td>
                    <td className="num">{qty(line.rate_per_hectare, 4)} {line.unit}</td>
                    <td className="num">{qty(line.required_quantity)} {line.unit}{line.pack_size ? <small className="block-hint">{qty(Math.ceil(Number(line.required_quantity) / Number(line.pack_size)), 0)} × {line.pack_label || `${qty(line.pack_size)} ${line.unit} pack`}</small> : null}</td>
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
  const draft = useFormDraft({ key: `allocations:request:${season.id}`, value: form, onRestore: (data) => setForm((current) => ({ ...current, ...data })) })

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

  // Active programmes supporting this crop, their approved requests and their own catalogue.
  const optionsRequest = `${form.crop}:${form.farmer}:${season.id}`
  useEffect(() => {
    if (!form.crop) return undefined
    let active = true
    apiClient.get('/input-allocations/programme-options/', { params: { crop: form.crop, season: season.id, farmer: form.farmer || undefined } })
      .then((response) => {
        if (!active) return
        setOptions(response.data)
        setError('')
        if (response.data.crop_hectares) setForm((current) => (current.hectares ? current : { ...current, hectares: String(Number(response.data.crop_hectares)) }))
      })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Programmes for this crop could not be loaded.')) })
      .finally(() => { if (active) setOptionsKey(optionsRequest) })
    return () => { active = false }
  }, [form.crop, form.farmer, season.id, optionsRequest])
  const optionsLoading = Boolean(form.crop) && optionsKey !== optionsRequest

  const programme = options?.options?.find((item) => String(item.programme) === String(form.programme)) || null
  const batch = programme?.batches.find((item) => String(item.id) === String(form.request_batch)) || null
  const covered = options?.covered || {}
  const allowed = programme ? (batch?.input_category ? [batch.input_category] : programme.input_categories) : []
  const batchProducts = batch?.products || []
  const hasProducts = batchProducts.length > 0
  // Products the request approved, by input type, leaving out input types the farmer already has.
  const defaultLines = (item) => {
    const products = (item?.products || []).filter((product) => !covered[product.input_category])
    const seeds = products.filter((product) => product.input_category === 'SEED')
    return products.filter((product) => product.input_category !== 'SEED' || seeds.length === 1).map((product) => String(product.id))
  }
  const toggleLine = (product) => {
    const id = String(product.id)
    const others = form.request_lines.filter((value) => value !== id)
    if (product.input_category === 'SEED') {
      // One seed variety per hectare: picking one replaces any other.
      const seedIds = batchProducts.filter((item) => item.input_category === 'SEED').map((item) => String(item.id))
      change({ request_lines: form.request_lines.includes(id) ? others : [...others.filter((value) => !seedIds.includes(value)), id] })
    } else {
      change({ request_lines: form.request_lines.includes(id) ? others : [...others, id] })
    }
  }

  const ready = form.farmer && form.crop && form.programme && form.request_batch && Number(form.hectares) > 0 && (!batchProducts.length || form.request_lines.length > 0)
  const payload = useMemo(() => ({
    farmer: Number(form.farmer), farm: form.farm ? Number(form.farm) : null, season: season.id, crop: Number(form.crop),
    programme: Number(form.programme), request_batch: Number(form.request_batch), hectares: form.hectares,
    input_categories: form.input_categories.length ? form.input_categories : undefined, crop_season: cropSeason || undefined,
    request_lines: hasProducts ? form.request_lines.map(Number) : undefined,
  }), [form, season.id, cropSeason, hasProducts])

  // The summary follows every change, and comes from the server, so prices and hectares are always current.
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

  const change = (changes) => { setPlan(null); setForm((current) => ({ ...current, ...changes })) }
  const toggleCategory = (code) => change({ input_categories: form.input_categories.includes(code) ? form.input_categories.filter((item) => item !== code) : [...form.input_categories, code] })

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
            <FarmerAutocomplete label="Farmer" value={form.farmer} endpoint="/farmers/eligible/" seasonId={season.id} seasonName={season.name} required onChange={(farmer) => change({ farmer: farmer ? String(farmer.id) : '', farm: '', hectares: '', input_categories: [] })} />
            <label className="form-field">Farm
              <select value={form.farm} onChange={(event) => change({ farm: event.target.value })} disabled={!form.farmer}>
                <option value="">{form.farmer ? 'Choose a farm' : 'Choose a farmer first'}</option>
                {farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.farm_name} · {qty(farm.arable_hectares)} ha arable</option>)}
              </select>
            </label>
            <label className="form-field">Agricultural year<input value={season.name} readOnly title="Change the agricultural year in the header" /></label>
            <label className="form-field">Crop
              <select value={form.crop} onChange={(event) => { setOptions(null); change({ crop: event.target.value, programme: '', request_batch: '', hectares: '', input_categories: [] }) }}>
                <option value="">Choose a crop</option>
                {crops.map((crop) => <option key={crop.id} value={crop.id}>{crop.name} ({crop.category === 'WINTER' ? 'Winter' : 'Summer'})</option>)}
              </select>
            </label>
          </div>
        </li>
        <li>
          <h4><span>2</span>Programme and approved request</h4>
          {!form.crop ? <div className="form-message">Choose the crop first.</div> : null}
          {form.crop && optionsLoading ? <div className="form-message">Loading programmes…</div> : null}
          {form.crop && options && !optionsLoading ? (
            options.options.length ? (
              <div className="workflow-fields">
                <label className="form-field">Programme
                  <select value={form.programme} onChange={(event) => change({ programme: event.target.value, request_batch: '', input_categories: [] })}>
                    <option value="">Choose a programme</option>
                    {options.options.map((item) => <option key={item.programme} value={item.programme}>{item.programme_name}</option>)}
                  </select>
                </label>
                <label className="form-field">Approved input request
                  <select value={form.request_batch} disabled={!programme} onChange={(event) => change({ request_batch: event.target.value, input_categories: [], request_lines: defaultLines(programme?.batches.find((item) => String(item.id) === event.target.value)) })}>
                    <option value="">{!programme ? 'Choose the programme first' : programme.batches.length ? 'Choose an approved request' : 'No approved request for this crop'}</option>
                    {(programme?.batches || []).map((item) => <option key={item.id} value={item.id}>{item.request_number} · {item.input_category_label} · {qty(item.remaining_hectares)} of {qty(item.approved_hectares)} ha left</option>)}
                  </select>
                  {programme && !programme.batches.length ? <span className="field-error">{programme.programme_name} has no approved {crops.find((crop) => String(crop.id) === form.crop)?.name} request for {season.name}. Approve one on the Input requests page.</span> : null}
                </label>
                <label className="form-field">Hectares
                  <input type="number" min="0.01" step="0.01" value={form.hectares} onChange={(event) => change({ hectares: event.target.value })} />
                  {options.crop_hectares ? <span className="field-hint">{qty(options.crop_hectares)} ha of this crop allocated to the farmer for {season.name}.</span> : null}
                </label>
              </div>
            ) : <EmptyState icon="clipboard" title="No programme supports this crop">No active programme for {season.name} supports this crop. Add it to a programme on the Programmes page.</EmptyState>
          ) : null}
          {batch && batchProducts.length ? (
            <fieldset className="chip-field">
              <legend>Products approved in {batch.request_number}</legend>
              {CATEGORIES.filter(([code]) => batchProducts.some((product) => product.input_category === code)).map(([code, label, icon]) => {
                const taken = covered[code]
                return (
                  <div key={code} className="request-product-group">
                    <span className="request-product-type"><Icon name={icon} />{label}{code === 'SEED' ? ' · choose one variety' : ''}{taken ? ` · already from ${taken.programme_name}` : ''}</span>
                    <div className="category-chips" role="group" aria-label={`${label} products`}>
                      {batchProducts.filter((product) => product.input_category === code).map((product) => {
                        const on = form.request_lines.includes(String(product.id))
                        const short = Number(product.remaining_hectares) < Number(form.hectares || 0)
                        return (
                          <button key={product.id} type="button" className={on ? 'chip active' : 'chip'} aria-pressed={on} disabled={Boolean(taken)} onClick={() => toggleLine(product)}>
                            {product.name} <small>{qty(product.remaining_hectares)} of {qty(product.approved_hectares)} ha left</small>{short ? <small className="field-error"> · not enough</small> : null}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
              <span className="field-hint">Only the products and varieties approved in this request can be allocated, each within its own approved hectares.</span>
            </fieldset>
          ) : null}
          {batch && !batchProducts.length ? (
            <fieldset className="chip-field">
              <legend>Input types from {programme.programme_name}</legend>
              <div className="category-chips" role="group" aria-label="Input types to allocate">
                {CATEGORIES.filter(([code]) => allowed.includes(code)).map(([code, label, icon]) => {
                  const taken = covered[code]
                  const empty = !(programme.catalogue[code] || []).length
                  const on = !taken && !empty && (form.input_categories.length ? form.input_categories.includes(code) : true)
                  return (
                    <button key={code} type="button" className={on ? 'chip active' : 'chip'} aria-pressed={on} disabled={Boolean(taken) || empty} title={taken ? `Already allocated from ${taken.programme_name}` : empty ? 'Nothing in the catalogue' : ''} onClick={() => toggleCategory(code)}>
                      <Icon name={icon} />{label}{taken ? ` · from ${taken.programme_name}` : empty ? ' · not in catalogue' : ''}
                    </button>
                  )
                })}
              </div>
              <span className="field-hint">All available input types are included unless you pick some. Input types the farmer already has for this crop are greyed out.</span>
            </fieldset>
          ) : null}
        </li>
        <li>
          <h4><span>3</span>Summary</h4>
          {error ? <div className="form-message error" role="alert">{error}</div> : null}
          {!ready ? <div className="form-message">Choose the farmer, crop, programme, approved request, products and hectares to see the quantities and costs.</div> : null}
          {ready && planning && !plan ? <div className="form-message">Working out quantities and costs…</div> : null}
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
          subtitle={`Confirming gives ${plan.farmer_name} these inputs, uses ${qty(plan.hectares)} ha of request ${plan.request_number} and records the cost as the farmer's input debt.`}
          onClose={() => setConfirming(false)}
          footer={<><button type="button" className="ghost-btn" onClick={() => setConfirming(false)}>Back</button><button type="button" className="primary-btn" disabled={saving} onClick={confirm}>{saving ? 'Allocating…' : 'Confirm allocation'}</button></>}
        >
          <AllocationSummary plan={plan} showMoney={showMoney} />
        </Modal>
      ) : null}
    </section>
  )
}

function AllocationSummary({ plan, showMoney }) {
  const columns = showMoney ? 7 : 5
  return (
    <div className="allocation-summary">
      {plan.problems.length ? (
        <div className="form-message error" role="alert">
          <strong>This allocation cannot be confirmed yet:</strong>
          <ul>{plan.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
        </div>
      ) : null}
      <dl className="summary-facts">
        <div><dt>Farmer</dt><dd>{plan.farmer_name}</dd></div>
        <div><dt>Programme</dt><dd>{plan.programme_name}</dd></div>
        <div><dt>Crop</dt><dd>{plan.crop_name} · {plan.crop_season}</dd></div>
        <div><dt>Agricultural year</dt><dd>{plan.season_name}</dd></div>
        <div><dt>Request</dt><dd>{plan.request_number}</dd></div>
        <div><dt>Hectares</dt><dd>{qty(plan.hectares)} ha{plan.crop_hectares_limit ? ` of ${qty(plan.crop_hectares_limit)} ha allocated` : ''}</dd></div>
        <div><dt>Request hectares left</dt><dd>{qty(plan.remaining_hectares)} ha → {qty(Math.max(Number(plan.remaining_after), 0))} ha after</dd></div>
      </dl>
      <div className="table-wrap">
        <table className="data-table compact">
          <thead><tr><th>Input type</th><th>Product or variety</th><th className="num">Qty per ha</th><th className="num">Total quantity</th><th>Packs</th>{showMoney ? <><th className="num">Unit price</th><th className="num">Total cost</th></> : null}</tr></thead>
          <tbody>
            {plan.categories.map((entry) => (
              <SummaryCategory key={entry.category} entry={entry} showMoney={showMoney} columns={columns} />
            ))}
          </tbody>
          {showMoney ? <tfoot><tr><td colSpan={columns - 1}><strong>Total input allocation cost</strong></td><td className="num"><strong>{money(plan.total_cost)}</strong></td></tr></tfoot> : null}
        </table>
      </div>
    </div>
  )
}

function SummaryCategory({ entry, showMoney, columns }) {
  return (
    <>
      {entry.lines.map((line, index) => (
        <tr key={line.input_product}>
          <td>{index === 0 ? entry.label : ''}</td>
          <td>{line.product_name}</td>
          <td className="num">{qty(line.rate_per_hectare, 4)} {line.unit}</td>
          <td className="num">{qty(line.required_quantity)} {line.unit}</td>
          <td>{line.packs ? `${qty(line.packs, 0)} × ${line.pack_label || 'pack'}` : '—'}</td>
          {showMoney ? <><td className="num">{money(line.unit_price)}</td><td className="num">{money(line.cost)}</td></> : null}
        </tr>
      ))}
      {showMoney ? (
        <tr className="category-total">
          <td colSpan={columns - 1}>{entry.label} total</td>
          <td className="num">{money(entry.total_cost)}</td>
        </tr>
      ) : null}
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
      onDone(`Allocation for ${allocation.farmer_name} cancelled. Its hectares went back to the input request and the input debt was cancelled.`)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The allocation could not be cancelled.'))
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal title={`Cancel the allocation for ${allocation.farmer_name}`} subtitle="Its hectares go back to the approved input request. The allocation itself is kept, marked cancelled, and its debt is cancelled." onClose={onClose}
      footer={<><button type="button" className="ghost-btn" onClick={onClose}>Keep it</button><button type="submit" form="cancel-allocation-form" className="danger-solid" disabled={saving}>{saving ? 'Cancelling…' : 'Cancel allocation'}</button></>}>
      <form id="cancel-allocation-form" onSubmit={submit}>
        {error ? <div className="form-message error" role="alert">{error}</div> : null}
        <label className="form-field">Reason<textarea required rows="3" value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      </form>
    </Modal>
  )
}

export default InputAllocationsPage
