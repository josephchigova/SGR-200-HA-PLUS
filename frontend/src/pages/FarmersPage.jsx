import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import FarmLocationFields from '../components/FarmLocationFields'
import TabSearch from '../components/TabSearch'
import { coordinateError } from '../coordinates'

const PAGE_SIZE = 25

const emptyForm = {
  first_name: '',
  middle_name: '',
  surname: '',
  national_id: '',
  phone_primary: '',
  phone_secondary: '',
  email: '',
  gender: '',
  date_of_birth: '',
  address: '',
  province: '',
  district: '',
  ward: '',
  cluster: '',
  farm_name: '',
  total_hectares: '',
  arable_hectares: '',
  irrigated_hectares: '0',
  latitude: '',
  longitude: '',
}

const namePattern = "[A-Za-zÀ-ÖØ-öø-ÿ]+([ '-][A-Za-zÀ-ÖØ-öø-ÿ]+)*"
const nationalIdPattern = "[A-Za-z0-9/-]{5,30}"
const today = new Date()
const maxBirthDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`

const getListData = (data) => {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.results)) return data.results
  return []
}

const getAllPages = async (path, params = {}) => {
  const records = []
  let response = await apiClient.get(path, { params })
  records.push(...getListData(response.data))
  while (response.data?.next) {
    response = await apiClient.get(response.data.next)
    records.push(...getListData(response.data))
  }
  return records
}

function FarmersPage() {
  const [farmers, setFarmers] = useState([])
  const [provinces, setProvinces] = useState([])
  const [districts, setDistricts] = useState([])
  const [wards, setWards] = useState([])
  const [clusters, setClusters] = useState([])
  const [districtsLoading, setDistrictsLoading] = useState(false)
  const [clustersLoading, setClustersLoading] = useState(false)
  const [geographyError, setGeographyError] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form, setForm] = useState(emptyForm)
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const hasInitializedSearch = useRef(false)

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const isFirstPage = currentPage <= 1
  const isLastPage = currentPage >= totalPages

  const loadFarmers = async (query = '', page = 1) => {
    try {
      setLoading(true)
      const params = {
        page,
        page_size: PAGE_SIZE,
      }
      if (query.trim()) {
        params.search = query.trim()
      }
      const response = await apiClient.get('/farmers/', { params })

      if (Array.isArray(response.data)) {
        setFarmers(response.data)
        setTotalCount(response.data.length)
      } else {
        setFarmers(getListData(response.data))
        setTotalCount(Number(response.data?.count || 0))
      }
      setError('')
    } catch (requestError) {
      const message = requestError.response?.status === 401
        ? 'Your session is expired or invalid. Please log in again.'
        : 'Unable to load farmers right now.'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const loadGeography = async () => {
      try {
        setProvinces(await getAllPages('/provinces/', { official: 'true' }))
      } catch {
        setGeographyError('Unable to load provinces. Refresh the page and try again.')
      }
    }

    Promise.resolve().then(loadGeography)
  }, [])

  useEffect(() => {
    if (!hasInitializedSearch.current) {
      hasInitializedSearch.current = true
      return undefined
    }

    const timer = setTimeout(() => {
      setCurrentPage(1)
      setAppliedSearch(search)
    }, 250)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadFarmers(appliedSearch, currentPage)
    }, 0)
    return () => clearTimeout(timer)
  }, [appliedSearch, currentPage])

  useEffect(() => {
    const provinceId = form.province
    if (!provinceId) return

    let active = true
    getAllPages('/districts/', { province: provinceId })
      .then((records) => {
        if (active) setDistricts(records)
      })
      .catch(() => {
        if (active) setGeographyError('Unable to load districts for this province.')
      })
      .finally(() => {
        if (active) setDistrictsLoading(false)
      })

    return () => { active = false }
  }, [form.province])

  useEffect(() => {
    const districtId = form.district
    if (!districtId) return

    let active = true
    Promise.all([
      getAllPages('/wards/', { district: districtId }),
      getAllPages('/clusters/', { district: districtId }),
    ])
      .then(([wardRecords, clusterRecords]) => {
        if (!active) return
        setWards(wardRecords)
        setClusters(clusterRecords)
      })
      .catch(() => {
        if (active) setGeographyError('Unable to load wards or clusters for this district.')
      })
      .finally(() => {
        if (active) setClustersLoading(false)
      })

    return () => { active = false }
  }, [form.district])

  const handleChange = (event) => {
    const { name, value } = event.target
    const safeValue = name === 'phone_primary' || name === 'phone_secondary'
      ? value.replace(/\D/g, '').slice(0, 12)
      : value
    setForm((previous) => ({ ...previous, [name]: safeValue }))
  }

  const handleSubmit = async (event) => {
    event.preventDefault()

    const token = localStorage.getItem('sgr_access_token')
    if (!token) {
      setError('Please sign in before creating a farmer.')
      return
    }

    const locationError = coordinateError(form.latitude, form.longitude)
    if (locationError) {
      setError(locationError)
      return
    }

    setSubmitting(true)
    setError('')

    try {
      const payload = {
        ...form,
        gender: form.gender,
        phone_secondary: form.phone_secondary || '',
        latitude: form.latitude.trim() || null,
        longitude: form.longitude.trim() || null,
      }

      await apiClient.post('/farmers/', payload, {
        headers: { Authorization: `Bearer ${token}` },
      })

      setForm(emptyForm)
      setShowForm(false)
      setCurrentPage(1)
      await loadFarmers(appliedSearch, 1)
    } catch (requestError) {
      const message = requestError.response?.data
        ? Object.values(requestError.response.data).flat().join(' ')
        : 'Unable to create farmer.'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page-card">
      <div className="section-head">
        <h3>Farmer Register</h3>
        <TabSearch value={search} onChange={setSearch} placeholder="Filter farmers..." />
        <button type="button" className="primary-btn small" onClick={() => setShowForm((previous) => !previous)}>
          {showForm ? 'Close Form' : 'Add Farmer'}
        </button>
      </div>

      {showForm ? (
        <form className="farmer-form" onSubmit={handleSubmit}>
          <div className="form-grid">
            <label className="form-field">
              First name
              <input name="first_name" value={form.first_name} onChange={handleChange} required maxLength={100} pattern={namePattern} title="Use letters, spaces, apostrophes, or hyphens only." />
            </label>
            <label className="form-field">
              Middle name
              <input name="middle_name" value={form.middle_name} onChange={handleChange} maxLength={100} pattern={namePattern} title="Use letters, spaces, apostrophes, or hyphens only." />
            </label>
            <label className="form-field">
              Surname
              <input name="surname" value={form.surname} onChange={handleChange} required maxLength={120} pattern={namePattern} title="Use letters, spaces, apostrophes, or hyphens only." />
            </label>
            <label className="form-field">
              National ID
              <input name="national_id" value={form.national_id} onChange={handleChange} required minLength={5} maxLength={30} pattern={nationalIdPattern} title="Enter 5-30 letters or digits; hyphens and slashes are allowed." />
            </label>
            <label className="form-field">
              Primary phone
              <input type="tel" inputMode="numeric" name="phone_primary" value={form.phone_primary} onChange={handleChange} required minLength={9} maxLength={12} pattern="[0-9]{9,12}" title="Enter 9-12 digits only." />
            </label>
            <label className="form-field">
              Secondary phone
              <input type="tel" inputMode="numeric" name="phone_secondary" value={form.phone_secondary} onChange={handleChange} maxLength={12} pattern="([0-9]{9,12})?" title="If supplied, enter 9-12 digits only." />
            </label>
            <label className="form-field">
              Email
              <input type="email" name="email" value={form.email} onChange={handleChange} maxLength={254} />
            </label>
            <label className="form-field">
              Gender
              <select name="gender" value={form.gender} onChange={handleChange} required>
                <option value="">Select</option>
                <option value="MALE">Male</option>
                <option value="FEMALE">Female</option>
                <option value="OTHER">Other</option>
              </select>
            </label>
            <label className="form-field">
              Date of birth
              <input type="date" name="date_of_birth" value={form.date_of_birth} onChange={handleChange} max={maxBirthDate} />
            </label>
            <label className="form-field">
              Province
              <select name="province" value={form.province} onChange={(event) => {
                const province = event.target.value
                setDistricts([])
                setWards([])
                setClusters([])
                setDistrictsLoading(Boolean(province))
                setClustersLoading(false)
                setGeographyError('')
                setForm((previous) => ({ ...previous, province, district: '', ward: '', cluster: '' }))
              }}>
                <option value="">Select</option>
                
                {
                  provinces.map((province) => (
                  <option key={province.id} value={province.id}>{province.name}</option>
                ))}
              </select>
            </label>
            <label className="form-field">
              District
              <select name="district" value={form.district} onChange={(event) => {
                const district = event.target.value
                setWards([])
                setClusters([])
                setClustersLoading(Boolean(district))
                setGeographyError('')
                setForm((previous) => ({ ...previous, district, ward: '', cluster: '' }))
              }} disabled={!form.province}>
                <option value="">{districtsLoading ? 'Loading districts...' : 'Select'}</option>
                {districts.map((district) => (
                  <option key={district.id} value={district.id}>{district.name}</option>
                ))}
              </select>
              {form.province && !districtsLoading && districts.length === 0 && !geographyError ? <small>No districts found for the selected province.</small> : null}
            </label>
            <label className="form-field">
              Ward
              <select name="ward" value={form.ward} onChange={handleChange} disabled={!form.district}>
                <option value="">Select</option>
                {wards.map((ward) => (
                  <option key={ward.id} value={ward.id}>{ward.name}</option>
                ))}
              </select>
            </label>
            <label className="form-field">
              Cluster
              <select name="cluster" value={form.cluster} onChange={handleChange} disabled={!form.district || clustersLoading}>
                <option value="">
                  {clustersLoading ? 'Loading clusters...' : clusters.length ? 'Select cluster' : form.district ? 'No clusters configured for this district' : 'Select a district first'}
                </option>
                {clusters.map((cluster) => (
                  <option key={cluster.id} value={cluster.id}>{cluster.name}</option>
                ))}
              </select>
              {form.district && !clustersLoading && clusters.length === 0 && !geographyError ? <small>Ask an administrator to assign cluster records to this district.</small> : null}
            </label>
            <label className="form-field">
              Farm name
              <input name="farm_name" value={form.farm_name} onChange={handleChange} maxLength={180} />
            </label>
            <label className="form-field">
              Total hectares
              <input type="number" min="0.01" max="9999999999.99" step="0.01" name="total_hectares" value={form.total_hectares} onChange={handleChange} required />
            </label>
            <label className="form-field">
              Arable hectares
              <input type="number" min="0" max={form.total_hectares || undefined} step="0.01" name="arable_hectares" value={form.arable_hectares} onChange={handleChange} required />
            </label>
            <label className="form-field">
              Irrigated arable hectares
              <input type="number" min="0" max={form.arable_hectares || undefined} step="0.01" name="irrigated_hectares" value={form.irrigated_hectares} onChange={handleChange} required />
            </label>
            <label className="form-field full-width">
              Address
              <textarea name="address" value={form.address} onChange={handleChange} rows="3" maxLength={500} />
            </label>
            <FarmLocationFields
              latitude={form.latitude}
              longitude={form.longitude}
              onChange={(name, value) => setForm((previous) => ({ ...previous, [name]: value }))}
            />
          </div>

          <div className="form-actions">
            <button type="button" className="ghost-btn" onClick={() => setShowForm(false)}>
              Cancel
            </button>
            <button type="submit" className="primary-btn" disabled={submitting}>
              {submitting ? 'Saving...' : 'Save Farmer'}
            </button>
          </div>
        </form>
      ) : null}

      {error ? <div className="form-message error">{error}</div> : null}
      {geographyError ? <div className="form-message error" role="alert">{geographyError}</div> : null}

      {loading ? <div className="form-message">Loading farmers...</div> : null}

      {!loading && !error && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Membership No.</th>
                <th>Farmer</th>
                <th>Province</th>
                <th>District</th>
                <th>Cluster</th>
                <th>Hectares</th>
                <th>Status</th>
                <th>Verification</th>
              </tr>
            </thead>
            <tbody>
              {farmers.length > 0 ? (
                farmers.map((farmer) => (
                  <tr key={farmer.id}>
                    <td>{farmer.membership_number || '—'}</td>
                    <td><Link to={`/farmers/${farmer.id}`}>{farmer.full_name || `${farmer.first_name || ''} ${farmer.surname || ''}`.trim() || 'Unknown'}</Link></td>
                    <td>{farmer.province_name || '—'}</td>
                    <td>{farmer.district_name || '—'}</td>
                    <td>{farmer.cluster_name || '—'}</td>
                    <td>{farmer.farm_hectares ?? '—'}</td>
                    <td>
                      <span className={`status-pill ${farmer.membership_status === 'ACTIVE' ? 'active' : 'review'}`}>
                        {farmer.membership_status || '—'}
                      </span>
                    </td>
                    <td>
                      <span className={`status-pill ${farmer.verification_status === 'VERIFIED' ? 'active' : 'review'}`}>
                        {farmer.verification_status || '—'}
                      </span>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan="8">No farmers found.</td>
                </tr>
              )}
            </tbody>
          </table>

          <div className="workflow-form-actions">
            <span>{totalCount} farmers</span>
            {totalPages > 1 ? (
              <>
                <button type="button" className="ghost-btn" disabled={isFirstPage || loading} onClick={() => setCurrentPage((previous) => Math.max(previous - 1, 1))}>
                  Previous
                </button>
                <span>Page {currentPage} of {totalPages}</span>
                <button type="button" className="ghost-btn" disabled={isLastPage || loading} onClick={() => setCurrentPage((previous) => Math.min(previous + 1, totalPages))}>
                  Next
                </button>
              </>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}

export default FarmersPage
