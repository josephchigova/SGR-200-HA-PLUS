// Programmes: name, agricultural year, the crops and input types each supports, and whether it is active.
//
// A programme supports several crops and one, two or all three input types. Its figures show
// the hectares requested, approved, allocated and still to allocate, overall and per crop.

import { useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import { DraftNotice, EmptyState, Modal, PageHead, Pill, errorMessage } from '../components/ui'
import { useFormDraft } from '../drafts'
import { CATEGORIES } from '../inputCategories'
import { hectares, loadAll } from '../programmeData'

const EMPTY = { name: '', season: '', crops: [], capacity_status: 'ACTIVE', input_categories: [] }

function ProgrammesPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { can } = useAuth()
  const canCreate = can('programmes', 'create')
  const canEdit = can('programmes', 'edit')
  const canDelete = can('programmes', 'delete')
  const [rows, setRows] = useState([])
  const [crops, setCrops] = useState([])
  const [seasons, setSeasons] = useState([])
  const [filters, setFilters] = useState({ search: '', crop: '', capacity_status: '' })
  const [loadedKey, setLoadedKey] = useState('')
  const [token, setToken] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const requestKey = JSON.stringify([selectedSeason?.id, cropSeason, filters, token])

  useEffect(() => {
    let active = true
    Promise.all([loadAll('/crops/', { active: true }), loadAll('/seasons/')])
      .then(([cropRows, seasonRows]) => {
        if (!active) return
        setCrops(cropRows)
        setSeasons(seasonRows.filter((season) => season.selectable !== false))
      })
      .catch(() => { if (active) setError('Crops and agricultural years could not be loaded.') })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id }
    if (cropSeason) params.crop_season = cropSeason
    Object.entries(filters).forEach(([key, value]) => { if (value) params[key] = value })
    loadAll('/programmes/', params)
      .then((list) => { if (active) { setRows(list); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Programmes could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, filters, requestKey])

  const loading = !blocked && loadedKey !== requestKey
  const reload = () => setToken((value) => value + 1)
  const totals = useMemo(() => rows.reduce((sum, row) => ({
    approved: sum.approved + Number(row.figures?.approved_hectares || 0),
    allocated: sum.allocated + Number(row.figures?.allocated_hectares || 0),
    remaining: sum.remaining + Number(row.figures?.remaining_hectares || 0),
  }), { approved: 0, allocated: 0, remaining: 0 }), [rows])

  const remove = async () => {
    try {
      await apiClient.delete(`/programmes/${deleting.id}/`)
      setNotice(`${deleting.name} deleted.`)
      setDeleting(null)
      reload()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The programme could not be deleted.'))
      setDeleting(null)
    }
  }

  return (
    <div className="page-card programmes-page">
      <PageHead title="Programmes" subtitle="Each programme names the crops and input types it supports. Its crops have their own catalogue, its input requests set the hectares it can allocate, and inactive programmes take no new requests or allocations." />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      {canCreate && !blocked && !editing ? (
        <ProgrammeForm key={`new-${selectedSeason.id}`} seasons={seasons} crops={crops} defaultSeason={selectedSeason} onSaved={(row) => { setNotice(`${row.name} created.`); reload() }} />
      ) : null}
      {editing ? (
        <Modal wide title={`Edit ${editing.name}`} onClose={() => setEditing(null)}>
          <ProgrammeForm programme={editing} seasons={seasons} crops={crops} defaultSeason={selectedSeason} onCancel={() => setEditing(null)} onSaved={(row) => { setEditing(null); setNotice(`${row.name} updated.`); reload() }} />
        </Modal>
      ) : null}

      <section className="card">
        <div className="card-head">
          <div>
            <h3>Programmes for {selectedSeason?.name || 'the agricultural year'}</h3>
            <p className="card-sub">{rows.length} programme{rows.length === 1 ? '' : 's'} · {hectares(totals.approved)} approved · {hectares(totals.allocated)} allocated · {hectares(totals.remaining)} still to allocate</p>
          </div>
        </div>
        <div className="filter-row">
          <label className="form-field">Programme<input type="search" placeholder="Search by name" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} /></label>
          <label className="form-field">Crop
            <select value={filters.crop} onChange={(event) => setFilters({ ...filters, crop: event.target.value })}>
              <option value="">All crops</option>
              {crops.map((crop) => <option key={crop.id} value={crop.id}>{crop.name}</option>)}
            </select>
          </label>
          <label className="form-field">Capacity status
            <select value={filters.capacity_status} onChange={(event) => setFilters({ ...filters, capacity_status: event.target.value })}>
              <option value="">Active and inactive</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Inactive</option>
            </select>
          </label>
        </div>
        {loading ? <div className="form-message">Loading programmes…</div> : null}
        {!loading && !blocked && !rows.length ? <EmptyState icon="clipboard" title="No programmes">No programme matches for {selectedSeason?.name}.</EmptyState> : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Programme</th><th>Agricultural year</th><th>Supported crops</th><th>Input types</th><th className="num">Approved</th><th className="num">Allocated</th><th className="num">Remaining</th><th>Capacity status</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <ProgrammeRow
                    key={row.id}
                    row={row}
                    open={expanded === row.id}
                    onToggle={() => setExpanded(expanded === row.id ? null : row.id)}
                    onEdit={canEdit ? () => setEditing(row) : null}
                    onDelete={canDelete ? () => setDeleting(row) : null}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
      {deleting ? (
        <Modal title={`Delete ${deleting.name}?`} subtitle="A programme with requests, allocations or financial records cannot be deleted. Make it inactive instead." onClose={() => setDeleting(null)}
          footer={<><button type="button" className="ghost-btn" onClick={() => setDeleting(null)}>Keep it</button><button type="button" className="danger-solid" onClick={remove}>Delete</button></>}>
          <p>This cannot be undone.</p>
        </Modal>
      ) : null}
    </div>
  )
}

function ProgrammeRow({ row, open, onToggle, onEdit, onDelete }) {
  const [figures, setFigures] = useState(null)
  useEffect(() => {
    if (!open) return undefined
    let active = true
    apiClient.get(`/programmes/${row.id}/figures/`).then((response) => { if (active) setFigures(response.data) }).catch(() => { if (active) setFigures({ crops: [] }) })
    return () => { active = false }
  }, [open, row.id])
  const active = row.capacity_status === 'ACTIVE'
  return (
    <>
      <tr className={active ? '' : 'inactive-row'}>
        <td><strong>{row.name}</strong></td>
        <td>{row.season_name || '—'}</td>
        <td>{row.crop_names?.length ? row.crop_names.join(', ') : '—'}</td>
        <td>{row.input_category_labels?.length ? row.input_category_labels.join(', ') : <span className="field-error">None chosen</span>}</td>
        <td className="num">{hectares(row.figures?.approved_hectares)}</td>
        <td className="num">{hectares(row.figures?.allocated_hectares)}</td>
        <td className="num"><strong>{hectares(row.figures?.remaining_hectares)}</strong></td>
        <td><Pill tone={active ? 'good' : 'bad'}>{active ? 'Active' : 'Inactive'}</Pill></td>
        <td>
          <span className="table-actions">
            <button type="button" className="icon-btn" title={open ? 'Hide crops' : 'Show crops'} aria-label={`${open ? 'Hide' : 'Show'} crop figures for ${row.name}`} onClick={onToggle}><Icon name="eye" /></button>
            {onEdit ? <button type="button" className="icon-btn" title="Edit" aria-label={`Edit ${row.name}`} onClick={onEdit}><Icon name="pencil" /></button> : null}
            {onDelete ? <button type="button" className="icon-btn danger" title="Delete" aria-label={`Delete ${row.name}`} onClick={onDelete}><Icon name="trash" /></button> : null}
          </span>
        </td>
      </tr>
      {open ? (
        <tr className="allocation-lines">
          <td colSpan="9">
            {!figures ? <div className="form-message">Loading…</div> : (
              <table className="data-table compact">
                <thead><tr><th>Crop</th><th>Season</th><th className="num">Requested</th><th className="num">Approved</th><th className="num">Allocated</th><th className="num">Remaining</th><th className="num">Farmers</th><th className="num">Catalogue products</th></tr></thead>
                <tbody>
                  {figures.crops.map((crop) => (
                    <tr key={crop.crop}>
                      <td>{crop.crop_name}</td>
                      <td>{crop.season}</td>
                      <td className="num">{hectares(crop.requested_hectares)}</td>
                      <td className="num">{hectares(crop.approved_hectares)}</td>
                      <td className="num">{hectares(crop.allocated_hectares)}</td>
                      <td className="num">{hectares(crop.remaining_hectares)}</td>
                      <td className="num">{crop.farmers}</td>
                      <td className="num">{crop.inputs_configured || <span className="field-error">None</span>}</td>
                    </tr>
                  ))}
                  {!figures.crops.length ? <tr><td colSpan="8">This programme supports no crops yet.</td></tr> : null}
                </tbody>
              </table>
            )}
          </td>
        </tr>
      ) : null}
    </>
  )
}

function ProgrammeForm({ programme = null, seasons, crops, defaultSeason, onSaved, onCancel }) {
  const initial = programme
    ? { name: programme.name, season: String(programme.season || ''), crops: (programme.crops || []).map(String), capacity_status: programme.capacity_status || 'ACTIVE', input_categories: programme.input_categories || [] }
    : { ...EMPTY, season: defaultSeason ? String(defaultSeason.id) : '' }
  const [form, setForm] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})
  const draft = useFormDraft({ key: `programme:${programme?.id || 'new'}`, value: form, enabled: !programme, onRestore: (data) => setForm((current) => ({ ...current, ...data })) })
  const toggle = (field, value) => setForm((current) => ({
    ...current,
    [field]: current[field].includes(value) ? current[field].filter((item) => item !== value) : [...current[field], value],
  }))

  const submit = async (event) => {
    event.preventDefault()
    const found = {}
    if (!form.crops.length) found.crops = 'Choose at least one crop.'
    if (!form.input_categories.length) found.input_categories = 'Choose at least one input type.'
    setErrors(found)
    if (Object.keys(found).length) return
    setSaving(true)
    const payload = { name: form.name.trim(), season: Number(form.season), crops: form.crops.map(Number), capacity_status: form.capacity_status, input_categories: form.input_categories }
    try {
      const response = programme ? await apiClient.patch(`/programmes/${programme.id}/`, payload) : await apiClient.post('/programmes/', payload)
      if (!programme) {
        draft.clear(EMPTY)
        setForm({ ...EMPTY, season: form.season })
      }
      onSaved(response.data)
    } catch (requestError) {
      const data = requestError.response?.data
      setErrors(data && typeof data === 'object' ? Object.fromEntries(Object.entries(data).map(([key, value]) => [key, [].concat(value).join(' ')])) : { non_field_errors: errorMessage(requestError, 'The programme could not be saved.') })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className={programme ? 'programme-form' : 'card programme-form'} onSubmit={submit}>
      {programme ? null : <div className="card-head"><h3><Icon name="plus" />New programme</h3></div>}
      {programme ? null : <DraftNotice draft={draft} />}
      {errors.non_field_errors || errors.detail ? <div className="form-message error" role="alert">{errors.non_field_errors || errors.detail}</div> : null}
      <div className="workflow-fields">
        <label className="form-field">Programme name
          <input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="For example ARDA Summer Inputs" />
          {errors.name ? <span className="field-error">{errors.name}</span> : null}
        </label>
        <label className="form-field">Agricultural year
          <select required value={form.season} onChange={(event) => setForm({ ...form, season: event.target.value })}>
            <option value="">Choose the agricultural year</option>
            {seasons.map((season) => <option key={season.id} value={season.id}>{season.name}</option>)}
          </select>
          {errors.season ? <span className="field-error">{errors.season}</span> : null}
        </label>
        <label className="form-field">Capacity status
          <select value={form.capacity_status} onChange={(event) => setForm({ ...form, capacity_status: event.target.value })}>
            <option value="ACTIVE">Active: takes requests and allocations</option>
            <option value="INACTIVE">Inactive: records kept, nothing new</option>
          </select>
        </label>
      </div>
      <fieldset className="chip-field">
        <legend>Crops</legend>
        <div className="category-chips" role="group" aria-label="Crops this programme supports">
          {crops.map((crop) => {
            const on = form.crops.includes(String(crop.id))
            return <button key={crop.id} type="button" className={on ? 'chip active' : 'chip'} aria-pressed={on} onClick={() => toggle('crops', String(crop.id))}>{crop.name} <small>({crop.category === 'WINTER' ? 'Winter' : 'Summer'})</small></button>
          })}
        </div>
        {errors.crops ? <span className="field-error">{errors.crops}</span> : null}
      </fieldset>
      <fieldset className="chip-field">
        <legend>Input types</legend>
        <div className="category-chips" role="group" aria-label="Input types this programme supplies">
          {CATEGORIES.map(([code, label, icon]) => {
            const on = form.input_categories.includes(code)
            return <button key={code} type="button" className={on ? 'chip active' : 'chip'} aria-pressed={on} onClick={() => toggle('input_categories', code)}><Icon name={icon} />{label}</button>
          })}
        </div>
        {errors.input_categories ? <span className="field-error">{errors.input_categories}</span> : null}
      </fieldset>
      <div className="workflow-form-actions">
        <button type="submit" className="primary-btn small" disabled={saving}>{saving ? 'Saving…' : programme ? 'Save changes' : 'Create programme'}</button>
        {onCancel ? <button type="button" className="ghost-btn" onClick={onCancel}>Cancel</button> : null}
      </div>
    </form>
  )
}

export default ProgrammesPage
