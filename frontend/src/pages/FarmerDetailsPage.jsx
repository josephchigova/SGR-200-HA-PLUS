import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import apiClient from '../api/client'
import FarmLocationFields from '../components/FarmLocationFields'
import { coordinateError, googleMapsUrl } from '../coordinates'
import { formatDisplay } from '../formatNumbers'

function FarmerDetailsPage() {
  const { id } = useParams()
  const [farmer, setFarmer] = useState(null)
  const [farms, setFarms] = useState([])
  const [showFarmForm, setShowFarmForm] = useState(false)
  const [editingFarmId, setEditingFarmId] = useState(null)
  const [farmForm, setFarmForm] = useState({ farm_name: '', total_hectares: '', arable_hectares: '', irrigated_hectares: '0', latitude: '', longitude: '' })
  const [savingFarm, setSavingFarm] = useState(false)
  const [error, setError] = useState('')

  const loadDetails = useCallback(() => Promise.all([apiClient.get(`/farmers/${id}/`), apiClient.get('/farms/', { params: { farmer: id, include_inactive: '1' } })])
      .then(([farmerResponse, farmResponse]) => {
        setFarmer(farmerResponse.data)
        setFarms(farmResponse.data?.results || farmResponse.data || [])
      })
      .catch((requestError) => setError(requestError.response?.status === 401 ? 'Sign in to view farmer details.' : 'Unable to load this farmer.')), [id])

  useEffect(() => { loadDetails() }, [loadDetails])

  const updateFarmField = (event) => {
    const { name, value } = event.target
    setFarmForm((current) => ({ ...current, [name]: value }))
  }

  const startFarmEdit = (farm) => {
    setEditingFarmId(farm.id)
    setFarmForm({
      farm_name: farm.farm_name || '',
      total_hectares: farm.total_hectares || '',
      arable_hectares: farm.arable_hectares || '',
      irrigated_hectares: farm.irrigated_hectares || '0',
      latitude: farm.latitude ?? '',
      longitude: farm.longitude ?? '',
    })
    setShowFarmForm(true)
  }

  const resetFarmForm = () => {
    setEditingFarmId(null)
    setFarmForm({ farm_name: '', total_hectares: '', arable_hectares: '', irrigated_hectares: '0', latitude: '', longitude: '' })
    setShowFarmForm(false)
  }

  const saveFarm = async (event) => {
    event.preventDefault()
    const locationError = coordinateError(farmForm.latitude, farmForm.longitude)
    if (locationError) {
      setError(locationError)
      return
    }
    setSavingFarm(true)
    setError('')
    try {
      const payload = {
        ...farmForm,
        farmer: id,
        latitude: String(farmForm.latitude).trim() || null,
        longitude: String(farmForm.longitude).trim() || null,
      }
      if (!editingFarmId) {
        payload.province = farmer?.province || null
        payload.district = farmer?.district || null
        payload.ward = farmer?.ward || null
        payload.cluster = farmer?.cluster || null
      }
      if (editingFarmId) {
        await apiClient.patch(`/farms/${editingFarmId}/`, payload)
      } else {
        await apiClient.post('/farms/', payload)
      }
      resetFarmForm()
      await loadDetails()
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'Unable to save farm.')
    } finally {
      setSavingFarm(false)
    }
  }

  const setFarmActive = async (farm, isActive) => {
    try {
      await apiClient.patch(`/farms/${farm.id}/`, { is_active: isActive })
      await loadDetails()
    } catch (requestError) {
      setError(requestError.response?.data ? Object.values(requestError.response.data).flat().join(' ') : 'Unable to update this farm.')
    }
  }

  const deleteFarm = async (farmId) => {
    if (!window.confirm('Delete this farm record?')) return
    try {
      await apiClient.delete(`/farms/${farmId}/`)
      await loadDetails()
    } catch (requestError) {
      setError(requestError.response?.data ? Object.values(requestError.response.data).flat().join(' ') : 'Unable to delete farm.')
    }
  }

  if (error) return <div className="form-message error" role="alert">{error}</div>
  if (!farmer) return <div className="form-message">Loading farmer…</div>

  return (
    <section className="workflow-page">
      <div className="workflow-heading"><div><p className="eyebrow">Farmer record</p><h3>{farmer.full_name}</h3></div><Link className="ghost-btn" to="/farmers">Back to register</Link></div>
      <dl className="detail-grid">
        <div><dt>National ID</dt><dd>{farmer.national_id || '—'}</dd></div>
        <div><dt>Membership number</dt><dd>{farmer.membership_number || '—'}</dd></div>
        <div><dt>Verification</dt><dd>{farmer.verification_status}</dd></div>
        <div><dt>Membership</dt><dd>{farmer.membership_status}</dd></div>
        <div><dt>Province</dt><dd>{farmer.province_name || '—'}</dd></div>
        <div><dt>District</dt><dd>{farmer.district_name || '—'}</dd></div>
        <div><dt>Cluster</dt><dd>{farmer.cluster_name || '—'}</dd></div>
        <div><dt>Phone</dt><dd>{farmer.phone_primary || '—'}</dd></div>
        <div><dt>Farms</dt><dd>{farmer.farm_count ?? farms.length}</dd></div>
        <div><dt>Total hectares</dt><dd>{formatDisplay('farm_hectares', farmer.farm_hectares) || '0'}</dd></div>
        <div><dt>Arable hectares</dt><dd>{formatDisplay('arable_hectares', farmer.total_arable_hectares) || '0'}</dd></div>
        <div><dt>Irrigated hectares</dt><dd>{formatDisplay('irrigated_hectares', farmer.total_irrigated_hectares) || '0'}</dd></div>
      </dl>
      <div className="workflow-list-heading"><h4>Farms</h4><span>{farms.length} records</span><button type="button" className="primary-btn small" onClick={() => { resetFarmForm(); setShowFarmForm(true) }}>Add farm</button></div>
      {showFarmForm ? <form className="workflow-form" onSubmit={saveFarm}>
        <h4>{editingFarmId ? 'Update farm record' : 'Add farm record'}</h4>
        <div className="workflow-fields">
          <label className="form-field">Farm name<input name="farm_name" value={farmForm.farm_name} onChange={updateFarmField} required maxLength="180" /></label>
          <label className="form-field">Total hectares<input name="total_hectares" type="number" min="0.01" step="0.01" value={farmForm.total_hectares} onChange={updateFarmField} required /></label>
          <label className="form-field">Arable hectares<input name="arable_hectares" type="number" min="0" max={farmForm.total_hectares || undefined} step="0.01" value={farmForm.arable_hectares} onChange={updateFarmField} required /></label>
          <label className="form-field">Irrigated hectares<input name="irrigated_hectares" type="number" min="0" max={farmForm.arable_hectares || undefined} step="0.01" value={farmForm.irrigated_hectares} onChange={updateFarmField} /></label>
          <FarmLocationFields latitude={farmForm.latitude} longitude={farmForm.longitude} onChange={(name, value) => setFarmForm((current) => ({ ...current, [name]: value }))} />
        </div>
        <div className="workflow-form-actions"><button type="submit" className="primary-btn small" disabled={savingFarm}>{savingFarm ? 'Saving…' : 'Save farm'}</button><button type="button" className="ghost-btn" onClick={resetFarmForm}>Cancel</button></div>
      </form> : null}
      <div className="table-wrap"><table className="data-table"><thead><tr><th>Farm</th><th>Province</th><th>District</th><th>Cluster</th><th>Total ha</th><th>Arable ha</th><th>Irrigated ha</th><th>Farm coordinates</th><th>Status</th><th>Actions</th></tr></thead><tbody>
        {farms.map((farm) => {
          const mapsUrl = googleMapsUrl(farm.latitude, farm.longitude)
          return <tr key={farm.id}><td>{farm.farm_name}</td><td>{farm.province_name || '—'}</td><td>{farm.district_name || '—'}</td><td>{farm.cluster_name || '—'}</td><td>{formatDisplay('total_hectares', farm.total_hectares)}</td><td>{formatDisplay('arable_hectares', farm.arable_hectares)}</td><td>{formatDisplay('irrigated_hectares', farm.irrigated_hectares)}</td><td>{mapsUrl ? <><span>{farm.latitude}, {farm.longitude}</span> <a href={mapsUrl} target="_blank" rel="noopener noreferrer">View on Google Maps</a></> : '—'}</td><td>{farm.is_active ? farm.verification_status : 'Inactive'}</td><td><button type="button" className="ghost-btn small" onClick={() => startFarmEdit(farm)}>Edit</button> <button type="button" className="ghost-btn small" onClick={() => setFarmActive(farm, !farm.is_active)}>{farm.is_active ? 'Deactivate' : 'Activate'}</button> <button type="button" className="ghost-btn small" onClick={() => deleteFarm(farm.id)}>Delete</button></td></tr>
        })}
        {!farms.length ? <tr><td colSpan="10">No farm records.</td></tr> : null}
      </tbody></table></div>
    </section>
  )
}

export default FarmerDetailsPage
