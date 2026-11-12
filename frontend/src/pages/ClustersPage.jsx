import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import FarmerAutocomplete from '../components/FarmerAutocomplete'

const toList = (data) => (Array.isArray(data) ? data : data?.results || [])

const emptyForm = {
  name: '',
  province: '',
  district: '',
  lead_member: '',
  contact_person: '',
  phone: '',
  active: true,
}

async function getAllPages(path, params = {}) {
  const records = []
  let response = await apiClient.get(path, { params })
  records.push(...toList(response.data))
  while (response.data?.next) {
    response = await apiClient.get(response.data.next)
    records.push(...toList(response.data))
  }
  return records
}

function ClustersPage() {
  const { can } = useAuth()
  const canEdit = can('clusters', 'edit')
  const [clusters, setClusters] = useState([])
  const [provinces, setProvinces] = useState([])
  const [districts, setDistricts] = useState([])
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState(null)
  const [selectedId, setSelectedId] = useState('')
  const [members, setMembers] = useState([])
  const [memberToAdd, setMemberToAdd] = useState(null)
  const [transferClusterId, setTransferClusterId] = useState('')
  const [search, setSearch] = useState('')
  const [provinceFilter, setProvinceFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const selected = clusters.find((cluster) => String(cluster.id) === String(selectedId)) || null

  const loadClusters = async () => {
    const params = { include_inactive: 'true' }
    if (provinceFilter) params.province = provinceFilter
    if (search.trim()) params.search = search.trim()
    setClusters(await getAllPages('/clusters/', params))
  }

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      try {
        const [provinceRows] = await Promise.all([
          getAllPages('/provinces/'),
          loadClusters(),
        ])
        if (active) setProvinces(provinceRows)
      } catch {
        if (active) setError('Unable to load clusters.')
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!form.province) {
      setDistricts([])
      return undefined
    }
    let active = true
    getAllPages('/districts/', { province: form.province })
      .then((rows) => { if (active) setDistricts(rows) })
      .catch(() => { if (active) setError('Unable to load districts for this province.') })
    return () => { active = false }
  }, [form.province])

  useEffect(() => {
    if (!selectedId) {
      setMembers([])
      return undefined
    }
    let active = true
    getAllPages('/farmers/', { cluster: selectedId, page_size: 100 })
      .then((rows) => { if (active) setMembers(rows) })
      .catch(() => { if (active) setError('Unable to load cluster members.') })
    return () => { active = false }
  }, [selectedId])

  const refresh = async () => {
    setError('')
    try {
      await loadClusters()
    } catch {
      setError('Unable to load clusters.')
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    if (!form.lead_member) {
      setError('Select an existing registered farmer as the lead farmer.')
      setMessage('')
      return
    }
    setSaving(true)
    setError('')
    setMessage('')
    const payload = {
      name: form.name.trim(),
      province: Number(form.province),
      district: form.district ? Number(form.district) : null,
      lead_member: form.lead_member ? Number(form.lead_member) : null,
      contact_person: form.contact_person,
      phone: form.phone,
      active: form.active,
    }
    try {
      if (editingId) {
        await apiClient.patch(`/clusters/${editingId}/`, payload)
        setMessage('Cluster updated.')
      } else {
        const response = await apiClient.post('/clusters/', payload)
        setSelectedId(String(response.data.id))
        setMessage('Cluster created. Ordinary members can be added after the lead farmer is saved.')
      }
      setEditingId(null)
      setForm(emptyForm)
      await loadClusters()
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'Unable to save this cluster.')
    } finally {
      setSaving(false)
    }
  }

  const editCluster = (cluster) => {
    setEditingId(cluster.id)
    setSelectedId(String(cluster.id))
    setForm({
      name: cluster.name || '',
      province: cluster.province ? String(cluster.province) : '',
      district: cluster.district ? String(cluster.district) : '',
      lead_member: cluster.lead_member ? String(cluster.lead_member) : '',
      contact_person: cluster.contact_person || '',
      phone: cluster.phone || '',
      active: Boolean(cluster.active),
    })
  }

  const assignMember = async () => {
    if (!selected || !memberToAdd?.id) return
    setSaving(true)
    setError('')
    try {
      await apiClient.patch(`/farmers/${memberToAdd.id}/`, { cluster: selected.id })
      setMemberToAdd(null)
      setMessage(`${memberToAdd.full_name || 'Farmer'} added to ${selected.name}.`)
      setMembers(await getAllPages('/farmers/', { cluster: selected.id, page_size: 100 }))
      await loadClusters()
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'Unable to add this farmer to the cluster.')
    } finally {
      setSaving(false)
    }
  }

  const moveMember = async (farmer, clusterId) => {
    if (!selected) return
    const confirmed = window.confirm(clusterId
      ? `Transfer ${farmer.full_name} to the selected cluster?`
      : `Remove ${farmer.full_name} from ${selected.name}? The farmer record stays in the register.`)
    if (!confirmed) return
    setSaving(true)
    setError('')
    try {
      await apiClient.patch(`/farmers/${farmer.id}/`, { cluster: clusterId || null })
      setMembers(await getAllPages('/farmers/', { cluster: selected.id, page_size: 100 }))
      await loadClusters()
      setMessage(clusterId ? 'Farmer transferred.' : 'Farmer removed from the cluster.')
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'Unable to update cluster membership.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="workflow-page">
      <div className="workflow-heading">
        <div>
          <h3>Cluster Management</h3>
          <p>A cluster belongs to a province and is coordinated by one lead farmer from the farmer register.</p>
        </div>
        <button type="button" className="ghost-btn" onClick={refresh}>Refresh</button>
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {message ? <div className="form-message">{message}</div> : null}

      {canEdit ? <form className="workflow-form" onSubmit={submit}>
        <h4>{editingId ? 'Edit cluster' : 'Create cluster'}</h4>
        <div className="workflow-fields">
          <label className="form-field">Cluster name
            <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} required maxLength={180} />
          </label>
          <label className="form-field">Province
            <select value={form.province} onChange={(event) => setForm((current) => ({ ...current, province: event.target.value, district: '' }))} required>
              <option value="">Select province</option>
              {provinces.map((province) => <option key={province.id} value={province.id}>{province.name}</option>)}
            </select>
          </label>
          <label className="form-field">District
            <select value={form.district} onChange={(event) => setForm((current) => ({ ...current, district: event.target.value }))} disabled={!form.province}>
              <option value="">Whole province</option>
              {districts.map((district) => <option key={district.id} value={district.id}>{district.name}</option>)}
            </select>
          </label>
          <FarmerAutocomplete
            label="Lead farmer"
            value={form.lead_member}
            onChange={(farmer) => setForm((current) => ({ ...current, lead_member: farmer ? String(farmer.id) : '' }))}
            required={false}
          />
          <label className="form-field">Contact person
            <input value={form.contact_person} onChange={(event) => setForm((current) => ({ ...current, contact_person: event.target.value }))} />
          </label>
          <label className="form-field">Phone
            <input value={form.phone} onChange={(event) => setForm((current) => ({ ...current, phone: event.target.value }))} />
          </label>
          <label className="form-field">Status
            <select value={form.active ? 'active' : 'inactive'} onChange={(event) => setForm((current) => ({ ...current, active: event.target.value === 'active' }))}>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </label>
        </div>
        <div className="workflow-form-actions">
          <button className="primary-btn small" type="submit" disabled={saving}>{saving ? 'Saving…' : editingId ? 'Update cluster' : 'Create cluster'}</button>
          {editingId ? <button type="button" className="ghost-btn" onClick={() => { setEditingId(null); setForm(emptyForm) }}>Cancel</button> : null}
        </div>
      </form> : null}

      <div className="workflow-form">
        <h4>Find clusters</h4>
        <div className="workflow-fields">
          <label className="form-field">Province
            <select value={provinceFilter} onChange={(event) => setProvinceFilter(event.target.value)}>
              <option value="">All provinces</option>
              {provinces.map((province) => <option key={province.id} value={province.id}>{province.name}</option>)}
            </select>
          </label>
          <label className="form-field">Search
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name, lead farmer or province" />
          </label>
          <button type="button" className="ghost-btn" onClick={refresh}>Apply</button>
        </div>
      </div>

      {loading ? <div className="form-message">Loading clusters...</div> : null}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Cluster</th><th>Province</th><th>District</th><th>Lead farmer</th><th>Members</th><th>Status</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {clusters.map((cluster) => (
              <tr key={cluster.id}>
                <td>{cluster.name}</td>
                <td>{cluster.province_name || '—'}</td>
                <td>{cluster.district_name || 'Whole province'}</td>
                <td>{cluster.lead_farmer_name || 'Not assigned'}</td>
                <td>{cluster.member_count ?? 0}</td>
                <td>{cluster.active ? 'Active' : 'Inactive'}</td>
                <td>
                  {canEdit ? <button type="button" className="ghost-btn small" onClick={() => editCluster(cluster)}>Edit</button> : null}
                  <button type="button" className="ghost-btn small" onClick={() => setSelectedId(String(cluster.id))}>Members</button>
                </td>
              </tr>
            ))}
            {!loading && clusters.length === 0 ? <tr><td colSpan={7}>No clusters match this filter. Create a cluster before assigning ordinary members.</td></tr> : null}
          </tbody>
        </table>
      </div>

      {selected ? (
        <div className="workflow-form">
          <h4>{selected.name} members</h4>
          <p className="finance-note">
            Lead farmer: {selected.lead_farmer_name || 'Not assigned'}
            {selected.lead_member_national_id ? ` · National ID ${selected.lead_member_national_id}` : ''}
            {selected.lead_member_phone ? ` · ${selected.lead_member_phone}` : ''}
          </p>
          {canEdit ? <div className="workflow-fields">
            <FarmerAutocomplete
              label="Add registered farmer"
              value={memberToAdd?.id || ''}
              onChange={setMemberToAdd}
            />
            <button type="button" className="primary-btn small" disabled={saving || !memberToAdd} onClick={assignMember}>Add member</button>
          </div> : null}
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Farmer</th><th>National ID</th><th>Phone</th><th>Role</th><th>Actions</th></tr></thead>
              <tbody>
                {members.map((farmer) => (
                  <tr key={farmer.id}>
                    <td>{farmer.full_name}</td>
                    <td>{farmer.national_id || '—'}</td>
                    <td>{farmer.phone_primary || '—'}</td>
                    <td>{String(selected.lead_member) === String(farmer.id) ? 'Lead farmer' : 'Member'}</td>
                    <td>{canEdit ? <>
                      <button type="button" className="ghost-btn small" onClick={() => moveMember(farmer, null)}>Remove</button>
                      <select aria-label={`Transfer ${farmer.full_name}`} value={transferClusterId} onChange={(event) => setTransferClusterId(event.target.value)}>
                        <option value="">Transfer to…</option>
                        {clusters.filter((cluster) => String(cluster.id) !== String(selected.id) && cluster.active).map((cluster) => (
                          <option key={cluster.id} value={cluster.id}>{cluster.name}</option>
                        ))}
                      </select>
                      <button type="button" className="ghost-btn small" disabled={!transferClusterId} onClick={() => moveMember(farmer, Number(transferClusterId))}>Transfer</button>
                    </> : '—'}</td>
                  </tr>
                ))}
                {members.length === 0 ? <tr><td colSpan={5}>This cluster has no ordinary members yet. The lead farmer is stored on the cluster and does not need to be added here.</td></tr> : null}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  )
}

export default ClustersPage
