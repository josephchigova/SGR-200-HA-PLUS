import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import MapLocationPicker from '../components/MapLocationPicker'
import SearchSelect from '../components/SearchSelect'
import { EmptyState, PageHead, Pill, Skeleton, errorMessage } from '../components/ui'
import { openDocument } from '../documents'
import {
  farmErrors,
  fileError,
  formatNationalId,
  personalErrors,
  phoneDigits,
  statusOf,
  upper,
} from '../registration'

const STEPS = [
  { key: 'farmer', label: 'Personal details', hint: 'Who is being registered' },
  { key: 'farm', label: 'Farm details', hint: 'Location and land' },
  { key: 'crops', label: 'Crop allocation', hint: 'Planned crops' },
  { key: 'kyc', label: 'KYC documents', hint: 'Upload and submit' },
]

const EMPTY = {
  first_name: '', middle_name: '', surname: '', national_id: '', farm_name: '', phone_primary: '', email: '', gender: '',
  farmer_type: 'EXISTING',
  province: '', district: '', ward: '', cluster: '',
  total_hectares: '', irrigated_hectares: '0', dryland_hectares: '0', irrigation_type: 'CENTRE_PIVOT', latitude: '', longitude: '',
}
// The codes the farm record stores.
const IRRIGATION = [['CENTRE_PIVOT', 'Centre pivot'], ['DRIP', 'Drip'], ['SPRINKLER', 'Sprinkler'], ['FLOOD', 'Flood'], ['OTHER', 'Other']]
const EDITABLE = ['DRAFT', 'CORRECTIONS_REQUESTED', 'REJECTED']

const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])

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

const arableLater = (form) => (Number(form.irrigated_hectares) || 0) + (Number(form.dryland_hectares) || 0)

function cropProblemsFor(rows, limit) {
  const problems = []
  const seen = new Set()
  const totals = {}
  rows.forEach((row, index) => {
    const hectares = Number(row.hectares)
    if (!row.crop || !row.season || !(hectares > 0)) problems.push(`Row ${index + 1} needs a crop, a season and hectares.`)
    const key = `${row.crop}:${row.season}`
    if (row.crop && row.season) {
      if (seen.has(key)) problems.push('Each crop can be entered once for a season.')
      seen.add(key)
      totals[row.season] = (totals[row.season] || 0) + (hectares > 0 ? hectares : 0)
    }
  })
  Object.values(totals).forEach((total) => {
    if (total > limit) problems.push(`Allocated hectares (${total} ha) exceed the ${limit} ha of arable land.`)
  })
  return problems
}

function Field({ label, name, form, errors, touched, onChange, onBlur, required = false, hint = '', ...input }) {
  const error = touched[name] ? errors[name] : ''
  return (
    <label className="form-field">
      <span>{label}{required ? <span className="req" aria-hidden="true"> *</span> : null}</span>
      <input
        name={name}
        value={form[name]}
        aria-invalid={Boolean(error)}
        className={error ? 'invalid' : ''}
        onChange={(event) => onChange(name, event.target.value)}
        onBlur={() => onBlur(name)}
        required={required}
        {...input}
      />
      {error ? <span className="field-error" role="alert">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  )
}

function RegisterFarmerPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const asLead = searchParams.get('as') === 'lead'
  const { profile } = useAuth()
  const [context, setContext] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [touched, setTouched] = useState({})
  const [step, setStep] = useState(0)
  const [reviewing, setReviewing] = useState(false)
  const [farmerId, setFarmerId] = useState(id || '')
  const [farmer, setFarmer] = useState(null)
  const [saved, setSaved] = useState('')
  const [options, setOptions] = useState({ provinces: [], districts: [], wards: [], clusters: [], crops: [], seasons: [] })
  const [allocations, setAllocations] = useState([])
  const [loadingOptions, setLoadingOptions] = useState({ districts: false, wards: false })
  const [documents, setDocuments] = useState([])
  const [uploads, setUploads] = useState({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  const locked = Boolean(context?.locked)
  const requirements = useMemo(() => context?.documents || [], [context])
  const required = requirements.filter((item) => item.required || (item.when && item.when === form.farmer_type))

  // Reference data and, when continuing, the saved registration.
  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      try {
        const [contextResponse, provinces, crops, seasons] = await Promise.all([
          apiClient.get('/farmers/registration-context/'),
          loadAll('/provinces/?official=1&page_size=50'),
          loadAll('/crops/?page_size=100').catch(() => []),
          loadAll('/seasons/?page_size=50').catch(() => []),
        ])
        if (!active) return
        const info = contextResponse.data
        setContext(info)
        setOptions((current) => ({ ...current, provinces, crops, seasons }))
        let next = { ...EMPTY }
        if (info.locked) {
          next = { ...next, province: String(info.province?.id || ''), district: String(info.district?.id || ''), cluster: String(info.cluster?.id || '') }
        }
        if (id) {
          const [farmerResponse, documentRows] = await Promise.all([
            apiClient.get(`/farmers/${id}/`),
            loadAll(`/farmer-documents/?farmer=${id}`),
          ])
          if (!active) return
          const record = farmerResponse.data
          const farm = record.primary_farm || {}
          const arable = Number(farm.arable_hectares || 0)
          const irrigated = Number(farm.irrigated_hectares || 0)
          next = {
            ...next,
            first_name: record.first_name || '', middle_name: record.middle_name || '', surname: record.surname || '',
            national_id: record.national_id || '', farm_name: farm.farm_name || '', phone_primary: record.phone_primary || '',
            email: record.email || '', gender: record.gender || '',
            farmer_type: record.farmer_type || 'EXISTING',
            province: String(record.province || next.province || ''), district: String(record.district || next.district || ''),
            ward: String(record.ward || ''), cluster: String(record.cluster || next.cluster || ''),
            total_hectares: farm.total_hectares ? String(Number(farm.total_hectares)) : '',
            irrigated_hectares: String(irrigated), dryland_hectares: String(Math.max(arable - irrigated, 0)),
            irrigation_type: IRRIGATION.some(([code]) => code === farm.irrigation_type) ? farm.irrigation_type : 'CENTRE_PIVOT',
            latitude: farm.latitude ?? '', longitude: farm.longitude ?? '',
          }
          setFarmer(record)
          setDocuments(documentRows)
          setAllocations((record.crop_allocations || []).map((row) => ({ crop: String(row.crop), season: String(row.season), hectares: String(Number(row.hectares)) })))
          setSaved(JSON.stringify(next))
          setStep(3)
        }
        setForm(next)
        setError('')
      } catch (requestError) {
        if (active) setError(errorMessage(requestError, 'The registration form could not be loaded.'))
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [id])

  // Districts follow the province.
  useEffect(() => {
    if (!form.province) return undefined
    let active = true
    setLoadingOptions((current) => ({ ...current, districts: true }))
    loadAll(`/districts/?province=${form.province}&page_size=200`).then((districts) => {
      if (active) setOptions((current) => ({ ...current, districts: districts.sort((a, b) => a.name.localeCompare(b.name)) }))
    }).catch(() => {
      if (active) setError('The districts could not be loaded. Check your connection and choose the province again.')
    }).finally(() => {
      if (active) setLoadingOptions((current) => ({ ...current, districts: false }))
    })
    return () => { active = false }
  }, [form.province, locked])

  // Wards follow the district, from the official ward register.
  useEffect(() => {
    if (!form.district) return undefined
    let active = true
    setLoadingOptions((current) => ({ ...current, wards: true }))
    loadAll(`/wards/?district=${form.district}&page_size=200`).then((wards) => {
      const number = (ward) => Number(String(ward.name).replace(/\D/g, '')) || 0
      if (active) setOptions((current) => ({ ...current, wards: wards.sort((a, b) => number(a) - number(b) || a.name.localeCompare(b.name)) }))
    }).catch(() => {
      if (active) setError('The wards could not be loaded. Check your connection and choose the district again.')
    }).finally(() => {
      if (active) setLoadingOptions((current) => ({ ...current, wards: false }))
    })
    return () => { active = false }
  }, [form.district])

  const errorsOne = useMemo(() => personalErrors(form), [form])
  const errorsTwo = useMemo(() => farmErrors(form), [form])
  const cropProblems = useMemo(() => cropProblemsFor(allocations, arableLater(form)), [allocations, form])
  const uploadedCodes = new Set(documents.map((document) => document.document_type))
  const missing = required.filter((item) => !uploadedCodes.has(item.code))
  const stepValid = [!Object.keys(errorsOne).length, !Object.keys(errorsTwo).length, !cropProblems.length, !missing.length]
  const dirty = saved !== JSON.stringify(form)
  // A step opens only when every step before it is valid and saved.
  const reachable = (index) => index === 0 || (index === 1 && stepValid[0]) || (index === 2 && stepValid[0] && stepValid[1] && Boolean(farmerId) && !dirty) || (index === 3 && reachableCrops())
  function reachableCrops() {
    return stepValid[0] && stepValid[1] && stepValid[2] && Boolean(farmerId) && !dirty
  }
  const editable = !farmer || EDITABLE.includes(farmer.verification_status)
  const arable = (Number(form.irrigated_hectares) || 0) + (Number(form.dryland_hectares) || 0)

  const change = (name, value) => {
    let next = value
    if (['first_name', 'middle_name', 'surname', 'farm_name'].includes(name)) next = upper(value)
    if (name === 'national_id') next = formatNationalId(value)
    if (name === 'phone_primary') next = value.replace(/[^\d+ ]/g, '')
    setTouched((current) => ({ ...current, [name]: true }))
    setForm((current) => ({
      ...current,
      [name]: next,
      // A new province clears the district and ward. A new district clears the ward.
      ...(name === 'province' ? { district: '', ward: '', cluster: locked ? current.cluster : '' } : {}),
      ...(name === 'district' ? { ward: '' } : {}),
    }))
    if (name === 'province') setOptions((current) => ({ ...current, districts: [], wards: [] }))
    if (name === 'district') setOptions((current) => ({ ...current, wards: [] }))
  }
  const blur = (name) => setTouched((current) => ({ ...current, [name]: true }))
  const touchAll = (names) => setTouched((current) => ({ ...current, ...Object.fromEntries(names.map((name) => [name, true])) }))
  const fieldProps = { form, touched, onChange: change, onBlur: blur }

  const payload = () => ({
    first_name: form.first_name.trim(), middle_name: form.middle_name.trim(), surname: form.surname.trim(),
    national_id: form.national_id, farm_name: form.farm_name.trim(), phone_primary: phoneDigits(form.phone_primary),
    email: form.email.trim(), gender: form.gender,
    province: form.province, district: form.district, ward: form.ward,
    farmer_type: form.farmer_type || 'EXISTING',
    ...(asLead ? { as_lead: true } : {}),
    total_hectares: form.total_hectares, arable_hectares: String(arable), irrigated_hectares: form.irrigated_hectares || '0',
    irrigation_type: Number(form.irrigated_hectares) > 0
      ? (IRRIGATION.some(([code]) => code === form.irrigation_type) ? form.irrigation_type : 'CENTRE_PIVOT')
      : Number(form.dryland_hectares) > 0 ? 'RAINFED' : 'NONE',
    latitude: form.latitude === '' ? null : form.latitude, longitude: form.longitude === '' ? null : form.longitude,
    as_draft: true,
  })

  const saveDraft = async () => {
    setBusy(true)
    setError('')
    try {
      const response = farmerId
        ? await apiClient.patch(`/farmers/${farmerId}/`, payload())
        : await apiClient.post('/farmers/', payload())
      setFarmer(response.data)
      setFarmerId(String(response.data.id))
      setSaved(JSON.stringify(form))
      return true
    } catch (requestError) {
      setError(errorMessage(requestError, 'The registration could not be saved.'))
      return false
    } finally {
      setBusy(false)
    }
  }

  const continueFromOne = () => {
    touchAll(Object.keys(EMPTY).slice(0, 8))
    if (stepValid[0]) setStep(1)
  }

  const continueFromTwo = async () => {
    touchAll(['province', 'district', 'ward', 'total_hectares', 'irrigated_hectares', 'dryland_hectares', 'latitude'])
    if (!stepValid[0]) { setStep(0); return }
    if (!stepValid[1]) return
    if ((!farmerId || dirty) && !(await saveDraft())) return
    setStep(2)
  }

  const continueFromCrops = async () => {
    if (!stepValid[2]) return
    setBusy(true)
    setError('')
    try {
      if (farmerId) {
        const response = await apiClient.patch(`/farmers/${farmerId}/`, {
          crop_allocations: allocations.filter((row) => row.crop && row.season).map((row) => ({
            crop: Number(row.crop), season: Number(row.season), hectares: row.hectares,
          })),
        })
        setFarmer(response.data)
      }
      setStep(3)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The crop allocation could not be saved.'))
    } finally {
      setBusy(false)
    }
  }

  const goTo = (index) => {
    if (!reachable(index)) return
    setReviewing(false)
    setStep(index)
  }

  const useCurrentLocation = () => {
    if (!navigator.geolocation) {
      setError('This device cannot give its location. Type the coordinates instead.')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (position) => setForm((current) => ({ ...current, latitude: position.coords.latitude.toFixed(6), longitude: position.coords.longitude.toFixed(6) })),
      () => setError('The location could not be read. Allow location access, or type the coordinates.'),
      { enableHighAccuracy: true, timeout: 15000 },
    )
  }

  const upload = useCallback(async (item, file) => {
    const problem = fileError(file, context?.max_upload_mb)
    if (problem) {
      setUploads((current) => ({ ...current, [item.code]: { error: problem } }))
      return
    }
    setUploads((current) => ({ ...current, [item.code]: { progress: 0, name: file.name } }))
    const body = new FormData()
    body.append('farmer', farmerId)
    body.append('document_type', item.code)
    body.append('file', file)
    try {
      const response = await apiClient.post('/farmer-documents/', body, {
        timeout: 180000,
        onUploadProgress: (event) => {
          const progress = event.total ? Math.round((event.loaded / event.total) * 100) : 50
          setUploads((current) => ({ ...current, [item.code]: { progress, name: file.name } }))
        },
      })
      setDocuments((current) => [...current.filter((document) => document.document_type !== item.code), response.data])
      setUploads((current) => ({ ...current, [item.code]: null }))
    } catch (requestError) {
      setUploads((current) => ({ ...current, [item.code]: { error: errorMessage(requestError, 'The file could not be uploaded.') } }))
    }
  }, [context, farmerId])

  const submit = async () => {
    setBusy(true)
    setError('')
    try {
      const response = await apiClient.post(`/farmers/${farmerId}/submit/`)
      setFarmer(response.data)
      setDone(true)
    } catch (requestError) {
      setError(errorMessage(requestError, 'The registration could not be submitted.'))
    } finally {
      setBusy(false)
    }
  }

  const nameOf = (list, value) => list.find((item) => String(item.id) === String(value))?.name || '—'
  const fullName = [form.first_name, form.middle_name, form.surname].filter(Boolean).join(' ')

  if (loading) return <div className="page-card"><PageHead title="Register a farmer" /><Skeleton kind="block" /></div>

  if (locked && !context.cluster) {
    return (
      <div className="page-card">
        <PageHead title="Register a farmer" />
        <div className="card"><EmptyState icon="alert" title="Your account has no cluster yet">Ask an administrator to assign your cluster. You can register farmers after that.</EmptyState></div>
      </div>
    )
  }

  if (done) {
    return (
      <div className="page-card">
        <PageHead title="Registration submitted" />
        <div className="card">
          <EmptyState icon="check" title={`${fullName} is now awaiting approval`}>
            An administrator will check the documents and approve the registration, or send it back with remarks. You can follow its status on the Farmers page.
          </EmptyState>
          <div className="form-actions" style={{ justifyContent: 'center' }}>
            <Link className="ghost-btn" to={`/farmers/${farmerId}`}>Open the registration</Link>
            <a className="primary-btn" href="/farmers/register"><Icon name="plus" />Register another farmer</a>
          </div>
        </div>
      </div>
    )
  }

  if (!editable) {
    const [label, tone] = statusOf(farmer.verification_status)
    return (
      <div className="page-card">
        <PageHead title="Register a farmer" />
        <div className="card">
          <EmptyState icon="lock" title="This registration cannot be changed now">
            {farmer.full_name} is <Pill tone={tone}>{label}</Pill>. It can be edited only when an administrator asks for corrections.
          </EmptyState>
          <div className="form-actions" style={{ justifyContent: 'center' }}><Link className="primary-btn" to={`/farmers/${farmerId}`}>Open the registration</Link></div>
        </div>
      </div>
    )
  }

  return (
    <div className="page-card">
      <PageHead
        title={id ? 'Continue registration' : asLead ? 'Register a lead farmer' : 'Register a farmer'}
        subtitle={asLead
          ? 'Four steps. The cluster is created from this lead farmer’s name. There is no cluster to choose.'
          : 'Four steps: the farmer, the farm, the crop allocation, then the KYC documents. An administrator approves the registration after you submit it.'}
      >
        <Link className="ghost-btn" to="/farmers"><Icon name="arrowLeft" />Back to farmers</Link>
      </PageHead>

      {context.cluster ? (
        <div className="notice-strip">
          <Icon name="users" />
          <div>
            <strong>{context.cluster.name}</strong>
            <span>
              {context.province?.name}{context.district ? ` · ${context.district.name}` : ''} · Registered by {profile ? `${profile.first_name || ''} ${profile.last_name || ''}`.trim() || profile.email : 'you'}.
              The cluster and region are set automatically.
            </span>
          </div>
        </div>
      ) : null}

      {farmer?.review_remarks && farmer.verification_status !== 'DRAFT' ? (
        <div className="form-message warning" role="status">
          <strong>Administrator remarks:</strong> {farmer.review_remarks}
        </div>
      ) : null}

      <ol className="stepper" aria-label="Registration steps">
        {STEPS.map((item, index) => {
          const state = index === step && !reviewing ? 'current' : stepValid[index] && (index < 3 ? reachable(index + 1) || index < step : true) ? 'done' : 'todo'
          return (
            <li key={item.key} className={state}>
              <button type="button" disabled={!reachable(index)} aria-current={state === 'current' ? 'step' : undefined} onClick={() => goTo(index)}>
                <span className="step-dot">{state === 'done' ? <Icon name="check" /> : index + 1}</span>
                <span className="step-text"><strong>Step {index + 1}: {item.label}</strong><small>{state === 'done' ? 'Completed' : state === 'current' ? 'In progress' : item.hint}</small></span>
              </button>
            </li>
          )
        })}
      </ol>

      {error ? <div className="form-message error" role="alert">{error}</div> : null}

      {step === 0 && !reviewing ? (
        <section className="card">
          <div className="card-head"><div><p className="eyebrow">Step 1 of 4</p><h3>Personal details</h3><p className="card-sub">Names and the farm name are written in capital letters automatically.</p></div></div>
          <div className="form-grid two">
            <Field label="First name" name="first_name" errors={errorsOne} required autoComplete="off" {...fieldProps} />
            <Field label="Middle name (optional)" name="middle_name" errors={errorsOne} autoComplete="off" {...fieldProps} />
            <Field label="Surname" name="surname" errors={errorsOne} required autoComplete="off" {...fieldProps} />
            <Field label="National ID" name="national_id" errors={errorsOne} required autoComplete="off" placeholder="63-2330173E58" maxLength={13} hint="Type the numbers and letter. The hyphen is added for you." {...fieldProps} />
            <Field label="Farm name" name="farm_name" errors={errorsOne} required autoComplete="off" maxLength={180} {...fieldProps} />
            <Field label="Phone number" name="phone_primary" errors={errorsOne} required type="tel" inputMode="tel" placeholder="0771234567" hint="9 to 12 digits." {...fieldProps} />
            <Field label="Email (optional)" name="email" errors={errorsOne} type="email" autoComplete="off" {...fieldProps} />
            <label className="form-field">
              <span>Farmer type<span className="req" aria-hidden="true"> *</span></span>
              <select value={form.farmer_type} onChange={(event) => change('farmer_type', event.target.value)}>
                <option value="EXISTING">Existing farmer</option>
                <option value="NEW">New farmer</option>
              </select>
              <span className="field-hint">{form.farmer_type === 'NEW' ? 'A new farmer must also upload the DAEO letter.' : 'An existing farmer does not upload the DAEO letter.'}</span>
            </label>
            <label className="form-field">
              <span>Gender (optional)</span>
              <select value={form.gender} onChange={(event) => change('gender', event.target.value)}>
                <option value="">Not recorded</option>
                <option value="MALE">Male</option>
                <option value="FEMALE">Female</option>
                <option value="OTHER">Other</option>
              </select>
            </label>
          </div>
          <div className="wizard-actions">
            <span className="card-sub">{stepValid[0] ? 'All required details are complete.' : 'Complete the fields marked * to continue.'}</span>
            <button type="button" className="primary-btn" onClick={continueFromOne}>Continue<Icon name="arrowRight" /></button>
          </div>
        </section>
      ) : null}

      {step === 1 && !reviewing ? (
        <section className="card">
          <div className="card-head"><div><p className="eyebrow">Step 2 of 4</p><h3>Farm details</h3><p className="card-sub">Choose the province, district and ward from the official lists, then record the land.</p></div></div>
          <div className="form-grid three">
            <SearchSelect
              label="Province" required value={form.province} disabled={locked}
              options={options.provinces.map((item) => ({ value: item.id, label: item.name }))}
              onChange={(value) => change('province', value)} placeholder="Choose province"
              error={touched.province ? errorsTwo.province : ''} hint={locked ? 'Set by your cluster.' : ''}
            />
            <SearchSelect
              label="District" required value={form.district} disabled={!form.province || (locked && Boolean(context.district))}
              loading={loadingOptions.districts}
              options={options.districts.map((item) => ({ value: item.id, label: item.name }))}
              onChange={(value) => change('district', value)} placeholder={form.province ? 'Choose district' : 'Choose a province first'}
              error={touched.district ? errorsTwo.district : ''} hint={locked && context.district ? 'Set by your cluster.' : ''}
            />
            <SearchSelect
              label="Ward" required value={form.ward} disabled={!form.district} loading={loadingOptions.wards}
              options={form.district ? options.wards.map((item) => ({ value: item.id, label: item.name })) : []}
              onChange={(value) => change('ward', value)} placeholder={form.district ? 'Choose ward' : 'Choose a district first'}
              error={touched.ward ? errorsTwo.ward : ''}
              emptyText="No wards are recorded for this district. Ask an administrator to load the official ward list."
            />
            <Field label="Total farm size (ha)" name="total_hectares" errors={errorsTwo} required type="number" min="0" step="0.01" inputMode="decimal" {...fieldProps} />
            <Field label="Arable irrigated (ha)" name="irrigated_hectares" errors={errorsTwo} required type="number" min="0" step="0.01" inputMode="decimal" {...fieldProps} />
            <Field label="Arable dryland (ha)" name="dryland_hectares" errors={errorsTwo} required type="number" min="0" step="0.01" inputMode="decimal" {...fieldProps} />
            {Number(form.irrigated_hectares) > 0 ? (
              <label className="form-field">
                <span>Irrigation type</span>
                <select value={form.irrigation_type} onChange={(event) => change('irrigation_type', event.target.value)}>
                  {IRRIGATION.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
            ) : null}
          </div>
          <div className="total-strip"><span>Total arable land</span><strong>{arable.toLocaleString('en-US', { maximumFractionDigits: 2 })} ha</strong></div>

          <div className="card-head" style={{ marginTop: 20 }}><div><h3>Farm coordinates (optional)</h3><p className="card-sub">Stand on the farm and use this device, pick the place on a map, or type the coordinates.</p></div>
            <div className="table-actions">
              <button type="button" className="ghost-btn small" onClick={useCurrentLocation}><Icon name="mapPin" />Use current location</button>
              <MapLocationPicker latitude={form.latitude} longitude={form.longitude} onSelect={({ latitude, longitude }) => setForm((current) => ({ ...current, latitude, longitude }))} />
            </div>
          </div>
          <div className="form-grid two">
            <Field label="Latitude" name="latitude" errors={errorsTwo} inputMode="decimal" placeholder="-17.825200" {...fieldProps} />
            <Field label="Longitude" name="longitude" errors={{}} inputMode="decimal" placeholder="31.033500" {...fieldProps} />
          </div>
          <div className="wizard-actions">
            <button type="button" className="ghost-btn" onClick={() => setStep(0)}><Icon name="arrowLeft" />Back</button>
            <button type="button" className="primary-btn" disabled={busy} onClick={continueFromTwo}>{busy ? 'Saving…' : 'Save and continue'}<Icon name="arrowRight" /></button>
          </div>
        </section>
      ) : null}

      {step === 2 && !reviewing ? (
        <section className="card">
          <div className="card-head">
            <div>
              <p className="eyebrow">Step 3 of 4</p>
              <h3>Crop allocation</h3>
              <p className="card-sub">Add the crops this farmer will grow, or leave the list empty for the administrator. Allocated hectares cannot exceed the {arable.toLocaleString('en-US', { maximumFractionDigits: 2 })} ha of arable land in a season.</p>
            </div>
            <button type="button" className="ghost-btn small" onClick={() => setAllocations((current) => [...current, { crop: options.crops[0] ? String(options.crops[0].id) : '', season: options.seasons[0] ? String(options.seasons[0].id) : '', hectares: '' }])}><Icon name="plus" />Add crop</button>
          </div>
          {allocations.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Crop</th><th>Season</th><th>Allocated hectares</th><th></th></tr></thead>
                <tbody>
                  {allocations.map((row, index) => (
                    <tr key={`${index}-${row.crop}`}>
                      <td>
                        <select aria-label={`Crop ${index + 1}`} value={row.crop} onChange={(event) => setAllocations((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, crop: event.target.value } : item))}>
                          <option value="">Choose crop</option>
                          {options.crops.map((crop) => <option key={crop.id} value={crop.id}>{crop.name}</option>)}
                        </select>
                      </td>
                      <td>
                        <select aria-label={`Season ${index + 1}`} value={row.season} onChange={(event) => setAllocations((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, season: event.target.value } : item))}>
                          <option value="">Choose season</option>
                          {options.seasons.map((season) => <option key={season.id} value={season.id}>{season.name}</option>)}
                        </select>
                      </td>
                      <td><input aria-label={`Hectares ${index + 1}`} type="number" min="0.01" step="0.01" value={row.hectares} onChange={(event) => setAllocations((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, hectares: event.target.value } : item))} /></td>
                      <td><button type="button" className="icon-btn danger" title="Remove crop" aria-label={`Remove crop ${index + 1}`} onClick={() => setAllocations((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Icon name="trash" /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="card-sub">No crops yet. You can continue and add them later.</p>}
          {cropProblems.length ? <div className="form-message error" role="alert">{cropProblems[0]}</div> : null}
          <div className="total-strip"><span>Allocated this step</span><strong>{allocations.reduce((sum, row) => sum + (Number(row.hectares) || 0), 0).toLocaleString('en-US', { maximumFractionDigits: 2 })} ha</strong></div>
          <div className="wizard-actions">
            <button type="button" className="ghost-btn" onClick={() => setStep(1)}><Icon name="arrowLeft" />Back</button>
            <button type="button" className="primary-btn" disabled={busy || Boolean(cropProblems.length)} onClick={continueFromCrops}>{busy ? 'Saving…' : 'Save and continue'}<Icon name="arrowRight" /></button>
          </div>
        </section>
      ) : null}

      {step === 3 && !reviewing ? (
        <section className="card">
          <div className="card-head">
            <div><p className="eyebrow">Step 4 of 4</p><h3>KYC documents</h3><p className="card-sub">Every document is required{form.farmer_type === 'NEW' ? ', including the DAEO letter.' : '. The DAEO letter is not required for an existing farmer.'} PDF, JPG or PNG, up to {context.max_upload_mb} MB each.</p></div>
            <Pill tone={missing.length ? 'warn' : 'good'}>{required.length - missing.length} of {required.length} required uploaded</Pill>
          </div>
          <div className="upload-grid">
            {required.map((item) => <UploadCard key={item.code} item={{ ...item, required: true }} document={documents.find((document) => document.document_type === item.code)} state={uploads[item.code]} onFile={upload} />)}
          </div>
          <div className="wizard-actions">
            <button type="button" className="ghost-btn" onClick={() => setStep(2)}><Icon name="arrowLeft" />Back</button>
            <span className="card-sub">{missing.length ? `Still needed: ${missing.map((item) => item.label).join(', ')}.` : 'All required documents are uploaded.'}</span>
            <button type="button" className="primary-btn" disabled={Boolean(missing.length)} onClick={() => setReviewing(true)}>Review registration<Icon name="arrowRight" /></button>
          </div>
        </section>
      ) : null}

      {reviewing ? (
        <section className="card">
          <div className="card-head"><div><p className="eyebrow">Final review</p><h3>Check the details before submitting</h3><p className="card-sub">After you submit, the registration goes to an administrator and cannot be changed unless corrections are requested.</p></div></div>
          <div className="review-grid">
            <ReviewBlock title="Farmer" onEdit={() => goTo(0)} rows={[
              ['Name', fullName], ['National ID', form.national_id], ['Farmer type', form.farmer_type === 'NEW' ? 'New farmer' : 'Existing farmer'], ['Phone', form.phone_primary], ['Email', form.email || '—'], ['Farm name', form.farm_name],
            ]} />
            <ReviewBlock title="Farm" onEdit={() => goTo(1)} rows={[
              ['Province', nameOf(options.provinces, form.province)], ['District', nameOf(options.districts, form.district)], ['Ward', nameOf(options.wards, form.ward)],
              ['Cluster', context.cluster?.name || (asLead ? 'Created from the lead farmer’s name' : '—')],
              ['Total farm size', `${form.total_hectares} ha`], ['Arable irrigated', `${form.irrigated_hectares} ha`], ['Arable dryland', `${form.dryland_hectares} ha`],
              ['Coordinates', form.latitude !== '' ? `${form.latitude}, ${form.longitude}` : 'Not recorded'],
            ]} />
            <ReviewBlock title="Crops" onEdit={() => goTo(2)} rows={allocations.length ? allocations.map((row) => [nameOf(options.crops, row.crop), `${row.hectares || 0} ha · ${nameOf(options.seasons, row.season)}`]) : [['Crops', 'Left for the administrator']]} />
            <ReviewBlock title="Documents" onEdit={() => goTo(3)} rows={documents.map((document) => [document.label, document.file_name])} />
          </div>
          <div className="wizard-actions">
            <button type="button" className="ghost-btn" onClick={() => setReviewing(false)}><Icon name="arrowLeft" />Back to documents</button>
            <button type="button" className="primary-btn" disabled={busy || !stepValid.every(Boolean) || dirty} onClick={submit}>{busy ? 'Submitting…' : 'Submit for approval'}<Icon name="check" /></button>
          </div>
        </section>
      ) : null}
    </div>
  )
}

function ReviewBlock({ title, rows, onEdit }) {
  return (
    <div className="review-block">
      <header><h4>{title}</h4><button type="button" className="link-btn" onClick={onEdit}>Edit</button></header>
      <dl>
        {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </div>
  )
}

function UploadCard({ item, document, state, onFile }) {
  const inputId = `upload-${item.code}`
  const uploading = state && state.progress !== undefined
  const rejected = document?.review_status === 'REJECTED'
  return (
    <div className={`upload-card${document ? ' has-file' : ''}${rejected ? ' rejected' : ''}`}>
      <header>
        <strong>{item.label}{item.required ? <span className="req" aria-hidden="true"> *</span> : null}</strong>
        {document ? <Pill tone={rejected ? 'bad' : document.review_status === 'VERIFIED' ? 'good' : 'info'}>{rejected ? 'Rejected' : document.review_status === 'VERIFIED' ? 'Verified' : 'Uploaded'}</Pill> : <Pill>{item.required ? 'Required' : 'Optional'}</Pill>}
      </header>
      <p>{item.hint}</p>
      {document ? (
        <div className="upload-file">
          <Icon name="clipboard" />
          <span title={document.file_name}>{document.file_name}</span>
          <button type="button" className="link-btn" onClick={() => openDocument(document)}>Preview</button>
        </div>
      ) : null}
      {rejected && document.review_remarks ? <span className="field-error">Reviewer: {document.review_remarks}</span> : null}
      {uploading ? (
        <div className="upload-progress" role="progressbar" aria-valuenow={state.progress} aria-valuemin={0} aria-valuemax={100} aria-label={`Uploading ${item.label}`}>
          <i style={{ width: `${state.progress}%` }} />
          <span>Uploading {state.name} · {state.progress}%</span>
        </div>
      ) : null}
      {state?.error ? <span className="field-error" role="alert">{state.error}</span> : null}
      <label htmlFor={inputId} className={`ghost-btn small${uploading ? ' disabled' : ''}`}>
        <Icon name="download" className="flip" />{document ? 'Replace file' : 'Choose file'}
      </label>
      <input
        id={inputId}
        className="sr-only"
        type="file"
        accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
        disabled={uploading}
        aria-label={`${document ? 'Replace' : 'Choose'} file for ${item.label}`}
        onChange={(event) => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (file) onFile(item, file)
        }}
      />
    </div>
  )
}

export default RegisterFarmerPage
