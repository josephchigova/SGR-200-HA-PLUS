import { useCallback, useEffect, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import FarmerAutocomplete from '../components/FarmerAutocomplete'
import Icon from '../components/Icon'
import { EmptyState, Modal, PageHead, Pill, Skeleton, errorMessage } from '../components/ui'

const EMPTY = { email: '', first_name: '', last_name: '', phone_number: '', role: 'viewer', is_active: true, assigned_cluster: '', district: '', province: '', farmer: '', password: '' }
const MODULE_LABELS = {
  dashboard: 'Overview', farmers: 'Farmers', verification: 'Verification', clusters: 'Clusters', subscriptions: 'Subscriptions',
  crops: 'Crop catalogue', programmes: 'Programmes', arda: 'Input requests', allocations: 'Input allocations', production: 'Production',
  planting: 'Seasonal planting', deliveries: 'GMB deliveries', recovery: 'Grain recovery', finance: 'Finance', reports: 'Operational reports',
  reports_finance: 'Financial reports', reports_users: 'User reports', users: 'Team & access', audit: 'Audit log',
}
const ACTION_LETTERS = { view: 'View', create: 'Create', edit: 'Edit', delete: 'Delete', approve: 'Approve', export: 'Export' }

const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])

function UsersPage() {
  const { can, profile } = useAuth()
  const canManage = can('users', 'edit')
  const [tab, setTab] = useState('accounts')
  const [rows, setRows] = useState([])
  const [count, setCount] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [matrix, setMatrix] = useState(null)
  const [options, setOptions] = useState({ clusters: [], districts: [], provinces: [] })
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [temporary, setTemporary] = useState(null)
  const [confirmReset, setConfirmReset] = useState(null)
  const [selectedFarmer, setSelectedFarmer] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const response = await apiClient.get('/auth/users/', {
        params: { page, page_size: 25, search: search.trim() || undefined, role: roleFilter || undefined, is_active: activeFilter || undefined },
      })
      setRows(listOf(response.data))
      setCount(response.data?.count ?? listOf(response.data).length)
      setError('')
    } catch (requestError) {
      setError(errorMessage(requestError, 'The accounts could not be loaded.'))
    } finally {
      setLoading(false)
    }
  }, [page, search, roleFilter, activeFilter])

  useEffect(() => {
    const timer = window.setTimeout(load, 250)
    return () => window.clearTimeout(timer)
  }, [load])

  useEffect(() => {
    if (form.role !== 'lead_farmer' || !form.farmer) return undefined
    let active = true
    apiClient.get(`/farmers/${form.farmer}/`).then((response) => {
      if (active) setSelectedFarmer(response.data)
    }).catch(() => {})
    return () => { active = false }
  }, [form.farmer, form.role])

  useEffect(() => {
    apiClient.get('/auth/roles/').then((response) => setMatrix(response.data)).catch(() => {})
    Promise.all([
      apiClient.get('/clusters/?page_size=200'),
      apiClient.get('/districts/?page_size=300'),
      apiClient.get('/provinces/?page_size=200'),
    ]).then(([clusters, districts, provinces]) => {
      setOptions({ clusters: listOf(clusters.data), districts: listOf(districts.data), provinces: listOf(provinces.data) })
    }).catch(() => {})
  }, [])

  const roles = matrix?.roles || []

  const openCreate = () => {
    setForm(EMPTY)
    setSelectedFarmer(null)
    setFormError('')
    setEditing('new')
  }

  const openEdit = (user) => {
    setForm({
      email: user.email, first_name: user.first_name || '', last_name: user.last_name || '', phone_number: user.phone_number || '',
      role: user.role, is_active: user.is_active, assigned_cluster: user.assigned_cluster || '', district: user.district || '', province: user.province || '',
      farmer: user.farmer || '', password: '',
    })
    setSelectedFarmer(null)
    setFormError('')
    setEditing(user)
  }

  const changeRole = (role) => {
    setForm((current) => ({
      ...current,
      role,
      farmer: role === 'lead_farmer' ? current.farmer : '',
      first_name: current.role === 'lead_farmer' || role === 'lead_farmer' ? '' : current.first_name,
      last_name: current.role === 'lead_farmer' || role === 'lead_farmer' ? '' : current.last_name,
      assigned_cluster: role === 'lead_farmer' ? '' : '',
      district: role === 'district_coordinator' ? current.district : '',
      province: role === 'provincial_coordinator' ? current.province : '',
    }))
    if (role !== 'lead_farmer') setSelectedFarmer(null)
  }

  const chooseLeadFarmer = (farmer) => {
    setSelectedFarmer(farmer)
    const provinceIds = new Set((farmer?.registered_province_ids || (farmer?.province ? [farmer.province] : [])).map(String))
    const led = farmer
      ? options.clusters.find((cluster) => String(cluster.lead_member) === String(farmer.id) && provinceIds.has(String(cluster.province)))
      : null
    setForm((current) => ({
      ...current,
      farmer: farmer ? String(farmer.id) : '',
      first_name: farmer?.first_name || '',
      last_name: farmer?.surname || '',
      phone_number: farmer?.phone_primary || '',
      email: farmer ? (farmer.email || '') : '',
      province: farmer?.province ? String(farmer.province) : '',
      assigned_cluster: led ? String(led.id) : '',
    }))
  }

  const save = async (event) => {
    event.preventDefault()
    if (form.role === 'lead_farmer' && !form.farmer) {
      setFormError('Choose a registered farmer. A lead farmer account is only for someone already on the register.')
      return
    }
    setSaving(true)
    setFormError('')
    const payload = {
      ...form,
      farmer: form.role === 'lead_farmer' ? Number(form.farmer) : null,
      assigned_cluster: form.assigned_cluster || null,
      district: form.district || null,
      province: form.province || null,
    }
    if (!payload.password) delete payload.password
    try {
      if (editing === 'new') {
        await apiClient.post('/auth/users/', payload)
        setNotice(`Account created for ${form.email}. They must change the starting password after signing in.`)
      } else {
        await apiClient.patch(`/auth/users/${editing.id}/`, payload)
        setNotice(`Access updated for ${form.email}.`)
      }
      setEditing(null)
      load()
    } catch (requestError) {
      setFormError(errorMessage(requestError, 'The account could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (user) => {
    try {
      await apiClient.patch(`/auth/users/${user.id}/`, { is_active: !user.is_active })
      setNotice(`${user.email} is now ${user.is_active ? 'inactive and cannot sign in' : 'active'}.`)
      load()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The account could not be updated.'))
    }
  }

  const resetPassword = async () => {
    const user = confirmReset
    setConfirmReset(null)
    try {
      const response = await apiClient.post(`/auth/users/${user.id}/reset-password/`)
      setTemporary({ email: user.email, password: response.data.temporary_password })
    } catch (requestError) {
      setError(errorMessage(requestError, 'The password could not be reset.'))
    }
  }

  const pages = Math.max(Math.ceil(count / 25), 1)
  const leadProvinceIds = new Set((selectedFarmer?.registered_province_ids || (selectedFarmer?.province ? [selectedFarmer.province] : form.province ? [form.province] : [])).map(String))
  const leadClusters = form.role === 'lead_farmer' && form.farmer
    ? options.clusters.filter((cluster) => leadProvinceIds.has(String(cluster.province)))
    : []

  return (
    <div className="page-card">
      <PageHead title="Team & access" subtitle="Create staff and lead farmer accounts, assign roles, and control who can sign in.">
        {canManage ? <button type="button" className="primary-btn" onClick={openCreate}><Icon name="plus" />Add account</button> : <Pill tone="warn">Read only</Pill>}
      </PageHead>

      <div className="tabs" role="tablist" aria-label="Team sections">
        <button type="button" role="tab" aria-selected={tab === 'accounts'} onClick={() => setTab('accounts')}>Accounts</button>
        <button type="button" role="tab" aria-selected={tab === 'roles'} onClick={() => setTab('roles')}>Roles and permissions</button>
      </div>

      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}

      {tab === 'accounts' ? (
        <>
          <div className="report-toolbar">
            <input className="tab-search" type="search" aria-label="Search accounts" placeholder="Search name or email" value={search} onChange={(event) => { setPage(1); setSearch(event.target.value) }} />
            <select aria-label="Filter by role" style={{ width: 'auto' }} value={roleFilter} onChange={(event) => { setPage(1); setRoleFilter(event.target.value) }}>
              <option value="">All roles</option>
              {roles.map((role) => <option key={role.role} value={role.role}>{role.label}</option>)}
            </select>
            <select aria-label="Filter by status" style={{ width: 'auto' }} value={activeFilter} onChange={(event) => { setPage(1); setActiveFilter(event.target.value) }}>
              <option value="">Active and inactive</option>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
            </select>
          </div>
          <div className="table-wrap">
            {loading && !rows.length ? <div style={{ padding: 16, display: 'grid', gap: 8 }}><Skeleton kind="row" count={5} /></div> : null}
            {!loading && !rows.length ? <EmptyState icon="users" title="No accounts match">Change the search or filters.</EmptyState> : null}
            {rows.length ? (
              <table className="data-table">
                <thead><tr><th>Name</th><th>Role</th><th>Assignment</th><th>Status</th><th>Last sign-in</th>{canManage ? <th>Actions</th> : null}</tr></thead>
                <tbody>
                  {rows.map((user) => (
                    <tr key={user.id}>
                      <td><strong>{`${user.first_name || ''} ${user.last_name || ''}`.trim() || user.username}</strong><small>{user.email}</small></td>
                      <td>{user.role_label}</td>
                      <td>{user.cluster_name || user.district_name || user.province_name || '—'}</td>
                      <td>
                        {user.is_active ? <Pill tone="good">Active</Pill> : <Pill tone={user.last_login ? 'bad' : 'warn'}>{user.last_login ? 'Inactive' : 'Awaiting approval'}</Pill>}
                        {user.must_change_password ? <small>Temporary password</small> : null}
                      </td>
                      <td>{user.last_login ? new Date(user.last_login).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : 'Never'}</td>
                      {canManage ? (
                        <td>
                          <div className="table-actions">
                            <button type="button" className="ghost-btn small" onClick={() => openEdit(user)}>Edit access</button>
                            <button type="button" className="ghost-btn small" onClick={() => setConfirmReset(user)}>Reset password</button>
                            {user.id !== profile?.id ? (
                              <button type="button" className={user.is_active ? 'ghost-btn small danger' : 'ghost-btn small'} onClick={() => toggleActive(user)}>{user.is_active ? 'Deactivate' : 'Activate'}</button>
                            ) : null}
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {rows.length ? (
              <div className="table-foot">
                <span>{count} account{count === 1 ? '' : 's'}</span>
                <span className="table-actions">
                  <button type="button" className="ghost-btn small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
                  <span style={{ alignSelf: 'center' }}>Page {page} of {pages}</span>
                  <button type="button" className="ghost-btn small" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
                </span>
              </div>
            ) : null}
          </div>
        </>
      ) : null}

      {tab === 'roles' ? (
        matrix ? (
          <>
            <p className="card-sub">What each role may do in each module. The server applies these rules to every request. Lead farmers and coordinators only ever see records in their own cluster, district or province.</p>
            {roles.map((role) => (
              <section className="card" key={role.role}>
                <div className="card-head"><h3>{role.label}</h3></div>
                <div className="table-wrap">
                  <table className="data-table matrix">
                    <thead><tr><th>Module</th>{matrix.actions.map((action) => <th key={action}>{ACTION_LETTERS[action]}</th>)}</tr></thead>
                    <tbody>
                      {matrix.modules.filter((module) => role.modules[module]?.length).map((module) => (
                        <tr key={module}>
                          <td>{MODULE_LABELS[module] || module}</td>
                          {matrix.actions.map((action) => (
                            <td key={action} className={role.modules[module].includes(action) ? 'yes' : 'no'}>{role.modules[module].includes(action) ? 'Yes' : '—'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </>
        ) : <Skeleton kind="block" />
      ) : null}

      {editing ? (
        <Modal
          title={editing === 'new' ? 'Add account' : `Edit access: ${editing.email}`}
          subtitle="The role decides which modules and records this person can use."
          onClose={() => setEditing(null)}
          footer={(
            <>
              <button type="button" className="ghost-btn" onClick={() => setEditing(null)}>Cancel</button>
              <button type="submit" form="user-form" className="primary-btn" disabled={saving}>{saving ? 'Saving…' : editing === 'new' ? 'Create account' : 'Save changes'}</button>
            </>
          )}
        >
          <form id="user-form" className="form-grid" onSubmit={save}>
            <label>Role
              <select value={form.role} disabled={editing !== 'new' && editing.id === profile?.id} onChange={(event) => changeRole(event.target.value)}>
                {roles.map((role) => <option key={role.role} value={role.role}>{role.label}</option>)}
              </select>
            </label>
            {form.role === 'lead_farmer' ? (
              <div className="full-width">
                <FarmerAutocomplete label="Registered farmer" required value={form.farmer} onChange={chooseLeadFarmer} />
                <span className="field-hint">A lead farmer account is only for someone already on the farmer register. Other accounts are not.</span>
              </div>
            ) : (
              <>
                <label>First name<input required value={form.first_name} onChange={(event) => setForm({ ...form, first_name: event.target.value })} /></label>
                <label>Last name<input required value={form.last_name} onChange={(event) => setForm({ ...form, last_name: event.target.value })} /></label>
              </>
            )}
            {form.role === 'lead_farmer' && form.first_name ? (
              <p className="field-hint full-width">{form.first_name} {form.last_name}{selectedFarmer?.province_name ? ` · ${selectedFarmer.province_name}` : ''}</p>
            ) : null}
            <div>
              <label>Email address
                <input type="email" required value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
              </label>
              {form.role === 'lead_farmer' ? <span className="field-hint">Sign-in address. Filled from the register when the farmer has one.</span> : null}
            </div>
            <label>Phone number<input type="tel" value={form.phone_number} onChange={(event) => setForm({ ...form, phone_number: event.target.value })} /></label>
            {form.role === 'lead_farmer' ? (
              <div>
                <label>Cluster
                  <select required disabled={!form.farmer} value={form.assigned_cluster} onChange={(event) => setForm({ ...form, assigned_cluster: event.target.value })}>
                    <option value="">{form.farmer ? 'Select a cluster in their province' : 'Choose a registered farmer first'}</option>
                    {leadClusters.map((cluster) => <option key={cluster.id} value={cluster.id}>{cluster.name}{cluster.province_name ? ` (${cluster.province_name})` : ''}</option>)}
                  </select>
                </label>
                <span className="field-hint">
                  {form.farmer && !leadClusters.length
                    ? 'This farmer has no cluster in their province.'
                    : 'A lead farmer can only lead a cluster in their own province, and only sees farmers in that cluster.'}
                </span>
              </div>
            ) : null}
            {form.role === 'district_coordinator' ? (
              <label>District
                <select required value={form.district} onChange={(event) => setForm({ ...form, district: event.target.value })}>
                  <option value="">Select a district</option>
                  {options.districts.map((district) => <option key={district.id} value={district.id}>{district.name}</option>)}
                </select>
              </label>
            ) : null}
            {form.role === 'provincial_coordinator' ? (
              <label>Province
                <select required value={form.province} onChange={(event) => setForm({ ...form, province: event.target.value })}>
                  <option value="">Select a province</option>
                  {options.provinces.map((province) => <option key={province.id} value={province.id}>{province.name}</option>)}
                </select>
              </label>
            ) : null}
            {editing === 'new' ? (
              <label>Starting password
                <input type="text" autoComplete="off" required minLength="8" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />
                <span className="field-hint">The person must change it after their first sign-in.</span>
              </label>
            ) : null}
            <label className="check-row" style={{ alignSelf: 'end', minHeight: 40 }}>
              <input type="checkbox" checked={form.is_active} disabled={editing !== 'new' && editing.id === profile?.id} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} />
              Account can sign in
            </label>
          </form>
          {formError ? <div className="form-message error" role="alert">{formError}</div> : null}
        </Modal>
      ) : null}

      {confirmReset ? (
        <Modal
          title="Reset this password?"
          subtitle={`${confirmReset.email} will be given a temporary password and must choose a new one after signing in.`}
          onClose={() => setConfirmReset(null)}
          footer={(
            <>
              <button type="button" className="ghost-btn" onClick={() => setConfirmReset(null)}>Cancel</button>
              <button type="button" className="primary-btn" onClick={resetPassword}>Reset password</button>
            </>
          )}
        >
          <p className="card-sub">The current password stops working immediately.</p>
        </Modal>
      ) : null}

      {temporary ? (
        <Modal title="Temporary password" subtitle={`Give this to ${temporary.email}. It is shown once.`} onClose={() => setTemporary(null)} footer={<button type="button" className="primary-btn" onClick={() => setTemporary(null)}>Done</button>}>
          <input readOnly value={temporary.password} aria-label="Temporary password" onFocus={(event) => event.target.select()} style={{ fontFamily: 'var(--font-mono)', fontSize: '1.05rem' }} />
        </Modal>
      ) : null}
    </div>
  )
}

export default UsersPage
