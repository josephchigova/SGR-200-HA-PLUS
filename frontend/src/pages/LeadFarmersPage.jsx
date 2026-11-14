import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import FarmerAutocomplete from '../components/FarmerAutocomplete'
import Icon from '../components/Icon'
import SearchSelect from '../components/SearchSelect'
import { EmptyState, Modal, PageHead, Pill, Skeleton, StatCard, errorMessage } from '../components/ui'
import { formatNationalId, nationalIdError, statusOf, upper } from '../registration'
import { Meter, PlaceTable } from './ClusterDashboard'

const STATUS = { ACTIVE: ['Active', 'good'], INACTIVE: ['Login deactivated', 'bad'], NO_LOGIN: ['No login yet', 'warn'] }
const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])
const wardOrder = (a, b) => (Number(a.name.replace(/\D/g, '')) || 0) - (Number(b.name.replace(/\D/g, '')) || 0) || a.name.localeCompare(b.name)
const when = (value) => (value ? new Date(value).toLocaleDateString('en-GB', { dateStyle: 'medium' }) : '—')

async function loadAll(path) {
  const rows = []
  let response = await apiClient.get(path)
  rows.push(...listOf(response.data))
  let guard = 0
  while (response.data?.next && guard < 40) {
    response = await apiClient.get(response.data.next)
    rows.push(...listOf(response.data))
    guard += 1
  }
  return rows
}

// Province, district and ward chosen from the official lists, each one unlocking the next.
function useLocations(provinceId, districtId) {
  const [provinces, setProvinces] = useState([])
  // Lists are kept per province and per district, so loading is simply "not fetched yet".
  const [districts, setDistricts] = useState({})
  const [wards, setWards] = useState({})
  useEffect(() => {
    loadAll('/provinces/?official=1&page_size=50').then(setProvinces).catch(() => {})
  }, [])
  useEffect(() => {
    if (!provinceId || districts[provinceId]) return undefined
    let active = true
    loadAll(`/districts/?province=${provinceId}&page_size=200`)
      .then((rows) => { if (active) setDistricts((current) => ({ ...current, [provinceId]: rows.sort((a, b) => a.name.localeCompare(b.name)) })) })
      .catch(() => { if (active) setDistricts((current) => ({ ...current, [provinceId]: [] })) })
    return () => { active = false }
  }, [provinceId, districts])
  useEffect(() => {
    if (!districtId || wards[districtId]) return undefined
    let active = true
    loadAll(`/wards/?district=${districtId}&page_size=200`)
      .then((rows) => { if (active) setWards((current) => ({ ...current, [districtId]: rows.sort(wardOrder) })) })
      .catch(() => { if (active) setWards((current) => ({ ...current, [districtId]: [] })) })
    return () => { active = false }
  }, [districtId, wards])
  return {
    lists: { provinces, districts: districts[provinceId] || [], wards: wards[districtId] || [] },
    loading: { districts: Boolean(provinceId) && !districts[provinceId], wards: Boolean(districtId) && !wards[districtId] },
  }
}

function LocationFields({ form, setForm, errors = {} }) {
  const { lists, loading } = useLocations(form.province, form.district)
  const pick = (name, value) => setForm((current) => ({
    ...current,
    [name]: value,
    ...(name === 'province' ? { district: '', ward: '' } : {}),
    ...(name === 'district' ? { ward: '' } : {}),
  }))
  return (
    <>
      <SearchSelect label="Province" required value={form.province} placeholder="Choose province"
        options={lists.provinces.map((item) => ({ value: item.id, label: item.name }))}
        onChange={(value) => pick('province', value)} error={errors.province} />
      <SearchSelect label="District" required value={form.district} disabled={!form.province} loading={loading.districts}
        placeholder={form.province ? 'Choose district' : 'Choose a province first'}
        options={form.province ? lists.districts.map((item) => ({ value: item.id, label: item.name })) : []}
        onChange={(value) => pick('district', value)} error={errors.district} />
      <label className="form-field">
        <span>Ward number<span className="req" aria-hidden="true"> *</span></span>
        <input
          required inputMode="numeric" autoComplete="off" maxLength={3} disabled={!form.district}
          className={errors.ward_number || errors.ward ? 'invalid' : ''}
          placeholder={form.district ? 'For example 12' : 'Choose a district first'}
          value={form.ward}
          onChange={(event) => pick('ward', event.target.value.replace(/\D/g, '').replace(/^0+/, '').slice(0, 3))}
        />
        {errors.ward_number || errors.ward
          ? <span className="field-error" role="alert">{errors.ward_number || errors.ward}</span>
          : <span className="field-hint">Type the ward number, from 1 to 999.</span>}
      </label>
    </>
  )
}

function fieldErrors(requestError) {
  const data = requestError?.response?.data
  if (!data || typeof data !== 'object' || Array.isArray(data)) return {}
  return Object.fromEntries(Object.entries(data).map(([key, value]) => [key, Array.isArray(value) ? value.join(' ') : String(value)]))
}

function LeadForm({ initial, creating, onClose, onSaved, cluster }) {
  const [form, setForm] = useState(initial)
  const [errors, setErrors] = useState({})
  const [problem, setProblem] = useState('')
  const [saving, setSaving] = useState(false)
  const busy = useRef(false)
  const idProblem = creating && form.national_id ? nationalIdError(form.national_id) : ''

  const field = (name, label, extra = {}) => (
    <label className="form-field">
      <span>{label}{extra.required ? <span className="req" aria-hidden="true"> *</span> : null}</span>
      <input
        value={form[name]}
        className={errors[name] ? 'invalid' : ''}
        onChange={(event) => {
          let value = event.target.value
          if (['first_name', 'middle_name', 'surname'].includes(name)) value = upper(value)
          if (name === 'national_id') value = formatNationalId(value)
          if (name === 'phone_primary') value = value.replace(/\D/g, '')
          setForm((current) => ({ ...current, [name]: value }))
        }}
        {...extra}
      />
      {errors[name] ? <span className="field-error" role="alert">{errors[name]}</span> : extra.hint ? <span className="field-hint">{extra.hint}</span> : null}
    </label>
  )

  const submit = async (event) => {
    event.preventDefault()
    // One save at a time: a second click never sends a second registration.
    if (busy.current) return
    if (creating && idProblem) {
      setErrors({ national_id: idProblem })
      return
    }
    busy.current = true
    setSaving(true)
    setErrors({})
    setProblem('')
    const payload = { ...form, ward_number: form.ward }
    delete payload.ward
    if (!creating) {
      delete payload.national_id
      delete payload.password
    }
    try {
      const response = creating
        ? await apiClient.post('/lead-farmers/', payload)
        : await apiClient.patch(`/lead-farmers/${cluster}/`, payload)
      onSaved(response.data)
    } catch (requestError) {
      const found = fieldErrors(requestError)
      setErrors(found)
      setProblem(found.detail || (Object.keys(found).length ? 'Check the highlighted fields.' : errorMessage(requestError, 'The lead farmer could not be saved.')))
    } finally {
      busy.current = false
      setSaving(false)
    }
  }

  return (
    <Modal
      title={creating ? 'Register a lead farmer' : 'Edit lead farmer'}
      subtitle={creating
        ? 'This creates the lead farmer on the register, their cluster (named after them) and their login, in one step.'
        : 'Changing the name renames the cluster and the login to match.'}
      onClose={onClose}
      footer={(
        <>
          <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
          <button type="submit" form="lead-form" className="primary-btn" disabled={saving}>{saving ? 'Saving…' : creating ? 'Register lead farmer' : 'Save changes'}</button>
        </>
      )}
    >
      <form id="lead-form" className="form-grid two" onSubmit={submit}>
        {field('first_name', 'First name', { required: true, autoComplete: 'off' })}
        {field('middle_name', 'Middle name (optional)', { autoComplete: 'off' })}
        {field('surname', 'Surname', { required: true, autoComplete: 'off' })}
        {creating ? field('national_id', 'National ID', { required: true, placeholder: '63-2330173E58', maxLength: 13, hint: idProblem || 'The hyphen is added for you.' }) : null}
        {field('phone_primary', 'Phone number', { required: true, type: 'tel', inputMode: 'numeric', placeholder: '0771234567' })}
        {field('email', 'Email (sign-in address)', { required: true, type: 'email', autoComplete: 'off' })}
        <LocationFields form={form} setForm={setForm} errors={errors} />
        {creating ? field('password', 'Starting password', { required: true, type: 'text', minLength: 8, autoComplete: 'off', hint: 'Give this to the lead farmer. They must change it after signing in.' }) : null}
      </form>
      {problem ? <div className="form-message error" role="alert">{problem}</div> : null}
    </Modal>
  )
}

function LoginForm({ lead, onClose, onSaved }) {
  const [form, setForm] = useState({ email: lead.email || '', password: '' })
  const [problem, setProblem] = useState('')
  const [saving, setSaving] = useState(false)
  const submit = async (event) => {
    event.preventDefault()
    if (saving) return
    setSaving(true)
    setProblem('')
    try {
      onSaved((await apiClient.post(`/lead-farmers/${lead.cluster_id}/login/`, form)).data)
    } catch (requestError) {
      const found = fieldErrors(requestError)
      setProblem(Object.values(found).join(' ') || errorMessage(requestError, 'The login could not be created.'))
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal title={`Create a login for ${lead.lead_farmer}`} subtitle="The lead farmer signs in with this email and must change the password at first sign-in." onClose={onClose}
      footer={<><button type="button" className="ghost-btn" onClick={onClose}>Cancel</button><button type="submit" form="login-form" className="primary-btn" disabled={saving}>{saving ? 'Creating…' : 'Create login'}</button></>}>
      <form id="login-form" className="form-grid" onSubmit={submit}>
        <label>Email<input type="email" required value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
        <label>Starting password<input type="text" required minLength={8} autoComplete="off" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /></label>
      </form>
      {problem ? <div className="form-message error" role="alert">{problem}</div> : null}
    </Modal>
  )
}

function ReassignForm({ farmer, from, leads, onClose, onDone }) {
  const [target, setTarget] = useState('')
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState('')
  const [saving, setSaving] = useState(false)
  const choices = leads.filter((lead) => lead.cluster_id !== from?.cluster_id && lead.status !== 'INACTIVE' && (!farmer.province || !lead.province || lead.province.id === farmer.province))
  const chosen = choices.find((lead) => String(lead.cluster_id) === String(target))
  const submit = async () => {
    if (saving) return
    setSaving(true)
    setProblem('')
    try {
      const response = await apiClient.post('/lead-farmers/reassign/', { farmer: farmer.id, cluster: target, reason })
      onDone(response.data.detail)
    } catch (requestError) {
      setProblem(errorMessage(requestError, 'The farmer could not be moved.'))
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal
      title={from ? `Move ${farmer.name} to another lead farmer` : `Give ${farmer.name} a lead farmer`}
      subtitle="The farmer and their farms move to the chosen lead farmer's cluster. The move is recorded in the farmer's history and the audit log."
      onClose={onClose}
      footer={(
        <>
          <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="primary-btn" disabled={saving || !target || !reason.trim()} onClick={submit}>{saving ? 'Moving…' : chosen ? `Move to ${chosen.lead_farmer}` : 'Move farmer'}</button>
        </>
      )}
    >
      <label className="form-field">New lead farmer
        <select value={target} onChange={(event) => setTarget(event.target.value)}>
          <option value="">Choose a lead farmer in the same province</option>
          {choices.map((lead) => <option key={lead.cluster_id} value={lead.cluster_id}>{lead.lead_farmer} · {lead.district?.name || lead.province?.name || ''} · {lead.farmers} farmers</option>)}
        </select>
        {!choices.length ? <span className="field-hint">There is no other active lead farmer in this farmer's province.</span> : null}
      </label>
      <label className="form-field">Reason for the move
        <textarea required value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why this farmer is changing lead farmer. Kept in the audit trail." />
      </label>
      {problem ? <div className="form-message error" role="alert">{problem}</div> : null}
    </Modal>
  )
}

function LeadDetail({ clusterId, seasonName, leads, canManage, onClose, onChanged }) {
  const [lead, setLead] = useState(null)
  const [error, setError] = useState('')
  const [token, setToken] = useState(0)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [editing, setEditing] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const [moving, setMoving] = useState(null)
  const [adding, setAdding] = useState(null)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let active = true
    apiClient.get(`/lead-farmers/${clusterId}/`, { params: seasonName ? { season_name: seasonName } : {} })
      .then((response) => { if (active) { setLead(response.data); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'The lead farmer could not be loaded.')) })
    return () => { active = false }
  }, [clusterId, seasonName, token])

  const refresh = (message) => {
    setNotice(message || '')
    setToken((value) => value + 1)
    onChanged()
  }

  const toggleLogin = async () => {
    try {
      await apiClient.post(`/lead-farmers/${clusterId}/status/`, { is_active: lead.status !== 'ACTIVE' })
      refresh(lead.status === 'ACTIVE' ? 'The login is deactivated. The cluster and its farmers are kept.' : 'The login is active again.')
    } catch (requestError) {
      setError(errorMessage(requestError, 'The login could not be changed.'))
    }
  }

  const farmers = useMemo(() => {
    const rows = lead?.overview?.farmers || []
    const term = search.trim().toLowerCase()
    return rows.filter((row) => (!status || (status === 'pending' ? ['SUBMITTED', 'UNDER_REVIEW', 'PENDING'].includes(row.verification_status) : row.verification_status === status))
      && (!term || `${row.name} ${row.membership_number}`.toLowerCase().includes(term)))
  }, [lead, search, status])

  const overview = lead?.overview
  const perf = overview?.performance || {}
  const [label, tone] = STATUS[lead?.status] || ['—', '']

  return (
    <Modal wide title={lead ? lead.lead_farmer : 'Lead farmer'} subtitle={lead ? `Cluster: ${lead.cluster}` : ''} onClose={onClose}
      footer={lead && canManage ? (
        <>
          {lead.status === 'NO_LOGIN'
            ? <button type="button" className="primary-btn" onClick={() => setLoginOpen(true)}><Icon name="lock" />Create login</button>
            : <button type="button" className={lead.status === 'ACTIVE' ? 'ghost-btn danger' : 'ghost-btn'} onClick={toggleLogin}>{lead.status === 'ACTIVE' ? 'Deactivate login' : 'Activate login'}</button>}
          <button type="button" className="ghost-btn" onClick={() => setEditing(true)}><Icon name="settings" />Edit details</button>
          <button type="button" className="ghost-btn" onClick={() => setAdding({})}><Icon name="plus" />Add an existing farmer</button>
        </>
      ) : <button type="button" className="ghost-btn" onClick={onClose}>Close</button>}>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {!lead && !error ? <Skeleton kind="block" /> : null}
      {lead ? (
        <>
          <div className="split">
            <section className="review-block">
              <header><h4>Lead farmer</h4><Pill tone={tone}>{label}</Pill></header>
              <dl>
                <div><dt>National ID</dt><dd>{lead.national_id || '—'}</dd></div>
                <div><dt>Phone</dt><dd>{lead.phone || '—'}</dd></div>
                <div><dt>Sign-in email</dt><dd>{lead.account?.email || 'No login'}</dd></div>
                <div><dt>Last sign-in</dt><dd>{lead.account?.last_login ? when(lead.account.last_login) : 'Never'}</dd></div>
                <div><dt>Own registration</dt><dd>{statusOf(lead.own_record_status)[0]} · <Link to={`/farmers/${lead.farmer_id}`} onClick={onClose}>Open record</Link></dd></div>
              </dl>
            </section>
            <section className="review-block">
              <header><h4>Location</h4></header>
              <dl>
                <div><dt>Province</dt><dd>{lead.province?.name || '—'}</dd></div>
                <div><dt>District</dt><dd>{lead.district?.name || '—'}</dd></div>
                <div><dt>Ward</dt><dd>{lead.ward?.name || '—'}</dd></div>
                <div><dt>Registers farmers in</dt><dd>{lead.province?.name || '—'}</dd></div>
              </dl>
            </section>
          </div>

          <div className="stats-grid">
            <StatCard label="Farmers registered" value={lead.farmers} />
            <StatCard label="Approved" value={lead.approved} tone="good" />
            <StatCard label="Pending approval" value={lead.pending} />
            <StatCard label="Rejected" value={lead.rejected} tone={lead.rejected ? 'bad' : ''} />
            <StatCard label="Incomplete" value={lead.incomplete + lead.corrections} hint={lead.corrections ? `${lead.corrections} need corrections` : 'Drafts not yet submitted'} />
          </div>

          <div className="perf-grid">
            {[
              ['Subscription compliance', perf.subscription_compliance],
              ['Agricultural participation', perf.participation],
              ['Crop allocation recorded', perf.crop_allocation],
              ['KYC documents verified', perf.kyc_progress],
            ].map(([name, value]) => (
              <div className="progress-row" key={name}>
                <header><span>{name}</span><span>{value || 0}%</span></header>
                <div className="progress-track"><i style={{ width: `${Math.min(value || 0, 100)}%` }} /></div>
              </div>
            ))}
          </div>

          <section>
            <div className="card-head">
              <h4 className="group-title">Farmers in this cluster</h4>
              <div className="table-actions">
                <input className="tab-search" type="search" aria-label="Search this cluster" placeholder="Search name or membership number" value={search} onChange={(event) => setSearch(event.target.value)} />
                <select aria-label="Filter by status" style={{ width: 'auto' }} value={status} onChange={(event) => setStatus(event.target.value)}>
                  <option value="">All statuses</option>
                  <option value="VERIFIED">Approved</option>
                  <option value="pending">Awaiting approval</option>
                  <option value="DRAFT">Incomplete</option>
                  <option value="CORRECTIONS_REQUESTED">Corrections needed</option>
                  <option value="REJECTED">Rejected</option>
                </select>
              </div>
            </div>
            {farmers.length ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Farmer</th><th>Registered</th><th>Status</th><th>Crop allocation</th><th>Subscription compliance</th><th>Cropping</th>{canManage ? <th>Action</th> : null}</tr></thead>
                  <tbody>
                    {farmers.map((row) => {
                      const [rowLabel, rowTone] = statusOf(row.verification_status)
                      return (
                        <tr key={row.id}>
                          <td><Link to={`/farmers/${row.id}`} onClick={onClose}>{row.name}</Link><small>{row.membership_number}{row.district ? ` · ${row.district}` : ''}{row.ward ? ` · ${row.ward}` : ''}</small></td>
                          <td>{when(row.registration_date)}</td>
                          <td><Pill tone={rowTone}>{rowLabel}</Pill></td>
                          <td>{row.crops?.length ? row.crops.join('; ') : <span className="card-sub">Not recorded</span>}</td>
                          <td>{row.subscription_compliance !== null ? <Meter value={row.subscription_compliance} label={`${row.name} subscription compliance`} /> : <span className="card-sub">After approval</span>}</td>
                          <td>{row.planting_recorded ? <Pill tone="good">Recorded</Pill> : <Pill>Not yet</Pill>}</td>
                          {canManage ? <td><button type="button" className="ghost-btn small" onClick={() => setMoving(row)}>Move</button></td> : null}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState icon="users" title={lead.farmers ? 'No farmers match' : 'No farmers registered yet'}>{lead.farmers ? 'Change the search or status.' : 'Farmers appear here when this lead farmer registers them.'}</EmptyState>}
          </section>

          {overview?.by_district?.length ? (
            <section className="split">
              <PlaceTable title="District" rows={overview.by_district} />
              <PlaceTable title="Ward" rows={overview.by_ward || []} />
            </section>
          ) : null}
        </>
      ) : null}

      {editing && lead ? (
        <LeadForm
          creating={false}
          cluster={clusterId}
          initial={{
            first_name: lead.first_name || '', middle_name: lead.middle_name || '', surname: lead.surname || '',
            phone_primary: lead.phone || '', email: lead.account?.email || lead.email || '',
            province: String(lead.province?.id || ''), district: String(lead.district?.id || ''), ward: String(lead.ward?.name || '').replace(/\D/g, ''),
          }}
          onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); refresh('The details were saved. The cluster name follows the lead farmer’s name.') }}
        />
      ) : null}
      {loginOpen && lead ? <LoginForm lead={lead} onClose={() => setLoginOpen(false)} onSaved={() => { setLoginOpen(false); refresh('The login was created.') }} /> : null}
      {moving ? <ReassignForm farmer={{ id: moving.id, name: moving.name, province: lead?.province?.id }} from={lead} leads={leads} onClose={() => setMoving(null)} onDone={(message) => { setMoving(null); refresh(message) }} /> : null}
      {adding ? (
        <Modal title={`Add an existing farmer to ${lead?.lead_farmer}`} subtitle="For a farmer already on the register. New farmers are registered by the lead farmer." onClose={() => setAdding(null)}
          footer={<button type="button" className="ghost-btn" onClick={() => setAdding(null)}>Cancel</button>}>
          <FarmerAutocomplete label="Farmer on the register" value={adding.id || ''} onChange={(farmer) => setAdding(farmer || {})} />
          {adding.id ? (
            <ReassignForm
              farmer={{ id: adding.id, name: adding.full_name, province: adding.province }}
              from={adding.cluster ? { cluster_id: adding.cluster } : null}
              leads={leads.filter((item) => item.cluster_id === lead?.cluster_id)}
              onClose={() => setAdding(null)}
              onDone={(message) => { setAdding(null); refresh(message) }}
            />
          ) : null}
        </Modal>
      ) : null}
    </Modal>
  )
}

function LeadFarmersPage({ selectedSeason = null }) {
  const { can } = useAuth()
  const canManage = can('clusters', 'create')
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState({ search: '', province: '', status: '' })
  const [provinces, setProvinces] = useState([])
  const [token, setToken] = useState(0)
  const [opened, setOpened] = useState(null)
  const [notice, setNotice] = useState('')
  // Older links to the registration dialog now open the shared registration form.
  const registering = params.get('register') === '1'
  const seasonName = selectedSeason?.name || ''

  const load = useCallback(async () => {
    try {
      const response = await apiClient.get('/lead-farmers/', { params: seasonName ? { season_name: seasonName } : {} })
      setData(response.data)
      setError('')
    } catch (requestError) {
      setError(errorMessage(requestError, 'The lead farmers could not be loaded.'))
    }
  }, [seasonName])

  useEffect(() => {
    const timer = window.setTimeout(load, 0)
    return () => window.clearTimeout(timer)
  }, [load, token])

  useEffect(() => {
    loadAll('/provinces/?official=1&page_size=50').then(setProvinces).catch(() => {})
  }, [])

  const rows = useMemo(() => {
    const term = filters.search.trim().toLowerCase()
    return (data?.results || []).filter((row) => (!term || `${row.lead_farmer} ${row.national_id} ${row.email}`.toLowerCase().includes(term))
      && (!filters.province || String(row.province?.id) === filters.province)
      && (!filters.status || row.status === filters.status))
  }, [data, filters])

  const overview = data?.overview

  if (registering && canManage) return <Navigate to="/farmers/register?as=lead" replace />

  return (
    <div className="page-card">
      <PageHead title="Lead farmers" subtitle="Each lead farmer is one cluster, named after them. Farmers join a cluster when that lead farmer registers them. There are no clusters to create.">
        {canManage ? <Link className="primary-btn" to="/farmers/register?as=lead"><Icon name="plus" />Register lead farmer</Link> : <Pill tone="warn">Read only</Pill>}
      </PageHead>

      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {overview?.farmers_without_lead ? (
        <div className="form-message warning" role="status">
          {overview.farmers_without_lead} farmer{overview.farmers_without_lead === 1 ? '' : 's'} on the register {overview.farmers_without_lead === 1 ? 'has' : 'have'} no lead farmer
          {overview.clusters_without_lead ? `, and ${overview.clusters_without_lead} older cluster${overview.clusters_without_lead === 1 ? ' has' : 's have'} no lead farmer` : ''}.
          They are never assigned automatically. Open a lead farmer and use <strong>Add an existing farmer</strong> to place each one, with a reason that is kept in the audit trail.
        </div>
      ) : null}

      {!data && !error ? <><div className="kpi-grid"><Skeleton kind="stat" count={6} /></div><Skeleton kind="block" /></> : null}

      {overview ? (
        <section className="kpi-grid" aria-label="Cluster overview">
          <StatCard label="Lead farmers" value={overview.lead_farmers} hint={`${overview.active_logins} with an active login`} icon="userCheck" />
          <StatCard label="Clusters" value={overview.clusters} hint="One per lead farmer" icon="layers" />
          <StatCard label="Registered farmers" value={overview.farmers} hint="In lead farmer clusters" icon="users" />
          <StatCard label="Average per lead farmer" value={overview.average_cluster_size} icon="chart" />
          <StatCard label="Largest cluster" value={overview.largest_cluster?.farmers ?? 0} hint={overview.largest_cluster?.lead_farmer || '—'} />
          <StatCard label="Smallest cluster" value={overview.smallest_cluster?.farmers ?? 0} hint={overview.smallest_cluster?.lead_farmer || '—'} />
          <StatCard label="Approved farmers" value={overview.approved} tone="good" icon="shield" />
          <StatCard label="Pending registrations" value={overview.pending} icon="history" />
          <StatCard label="Rejected registrations" value={overview.rejected} tone={overview.rejected ? 'bad' : ''} />
        </section>
      ) : null}

      {data ? (
        <>
          <div className="report-toolbar">
            <input className="tab-search" type="search" aria-label="Search lead farmers" placeholder="Search name, national ID or email" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} />
            <select aria-label="Filter by province" style={{ width: 'auto' }} value={filters.province} onChange={(event) => setFilters({ ...filters, province: event.target.value })}>
              <option value="">All provinces</option>
              {provinces.map((province) => <option key={province.id} value={province.id}>{province.name}</option>)}
            </select>
            <select aria-label="Filter by login status" style={{ width: 'auto' }} value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
              <option value="">All logins</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Deactivated</option>
              <option value="NO_LOGIN">No login yet</option>
            </select>
          </div>
          <div className="table-wrap">
            {rows.length ? (
              <table className="data-table">
                <thead><tr><th>Lead farmer / cluster</th><th>Province</th><th>District</th><th>Ward</th><th className="num">Farmers</th><th className="num">Approved</th><th className="num">Pending</th><th className="num">Rejected</th><th>Status</th><th>Action</th></tr></thead>
                <tbody>
                  {rows.map((row) => {
                    const [label, tone] = STATUS[row.status] || ['—', '']
                    return (
                      <tr key={row.cluster_id}>
                        <td><strong>{row.lead_farmer}</strong><small>{row.cluster !== row.lead_farmer ? `Cluster: ${row.cluster}` : row.national_id}</small></td>
                        <td>{row.province?.name || '—'}</td>
                        <td>{row.district?.name || '—'}</td>
                        <td>{row.ward?.name || '—'}</td>
                        <td className="num">{row.farmers}</td>
                        <td className="num">{row.approved}</td>
                        <td className="num">{row.pending}</td>
                        <td className="num">{row.rejected}</td>
                        <td><Pill tone={tone}>{label}</Pill></td>
                        <td><button type="button" className="primary-btn small" onClick={() => { setNotice(''); setOpened(row.cluster_id) }}><Icon name="eye" />View cluster</button></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <EmptyState icon="userCheck" title={data.results.length ? 'No lead farmers match' : 'No lead farmers yet'}>
                {data.results.length ? 'Change the search or filters.' : 'Register the first lead farmer. Their cluster is created with them.'}
              </EmptyState>
            )}
            <div className="table-foot"><span>{rows.length} of {data.results.length} lead farmers</span></div>
          </div>
        </>
      ) : null}

      {opened ? (
        <LeadDetail
          clusterId={opened}
          seasonName={seasonName}
          leads={data?.results || []}
          canManage={canManage}
          onClose={() => setOpened(null)}
          onChanged={() => setToken((value) => value + 1)}
        />
      ) : null}
    </div>
  )
}

export default LeadFarmersPage
