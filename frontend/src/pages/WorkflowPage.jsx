import { useEffect, useRef, useState } from 'react'

import apiClient from '../api/client'
import FarmerAutocomplete from '../components/FarmerAutocomplete'

const listData = (data) => (Array.isArray(data) ? data : data?.results || [])

const optionPathsFor = (forms) => [...new Set(forms.flatMap((form) => form.fields
  .filter((field) => field.optionsPath && field.type !== 'farmer' && !(field.dependsOn === 'farmer' && field.optionsPath === '/farms/'))
  .map((field) => field.optionsPath)))]

const withQueryParams = (path, params) => {
  const [basePath, hashFragment = ''] = path.split('#')
  const separator = basePath.includes('?') ? '&' : '?'
  const query = new URLSearchParams(params).toString()
  return `${basePath}${separator}${query}${hashFragment ? `#${hashFragment}` : ''}`
}

const seasonScopedPath = (path, selectedSeason, seasonScoped, cropSeason) => {
  if (!seasonScoped || !selectedSeason) return path
  const params = { season: selectedSeason.id, season_name: selectedSeason.name }
  const keepsFullCatalogue = path.startsWith('/seasons') || path.startsWith('/crops') || path.startsWith('/farmers/eligible')
  if (cropSeason && !keepsFullCatalogue) params.crop_season = cropSeason
  return withQueryParams(path, params)
}

const getAllPages = async (path) => {
  const records = []
  let response = await apiClient.get(path)
  records.push(...listData(response.data))
  while (response.data?.next) {
    response = await apiClient.get(response.data.next)
    records.push(...listData(response.data))
  }
  return records
}

function WorkflowPage({ title, endpoint, columns, forms, approveAction = false, editAction = false, deleteAction = false, summaryEndpoint = '', summaryColumns = [], eligibleEndpoint = '', eligibleTitle = '', eligibleColumns = [], selectedSeason = null, seasonScoped = false, activeSeasonOnly = false, cropSeason = '', periodStatus = 'ready' }) {
  const [rows, setRows] = useState([])
  const [summaryRows, setSummaryRows] = useState([])
  const [eligibleData, setEligibleData] = useState({ key: '', rows: [] })
  const [options, setOptions] = useState({})
  const [dependentOptions, setDependentOptions] = useState({})
  const [values, setValues] = useState({})
  const [loadedKey, setLoadedKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [pendingDelete, setPendingDelete] = useState(null)
  const farmerOptionRequests = useRef({})

  const waitingForPeriod = seasonScoped && periodStatus === 'loading'
  const periodUnavailable = seasonScoped && periodStatus === 'error'
  const missingSeason = seasonScoped && periodStatus === 'ready' && !selectedSeason
  const scopedEndpoint = seasonScopedPath(endpoint, selectedSeason, seasonScoped, cropSeason)
  const scopedSummaryEndpoint = summaryEndpoint ? seasonScopedPath(summaryEndpoint, selectedSeason, seasonScoped, cropSeason) : ''
  const eligibleRequestKey = JSON.stringify([eligibleEndpoint, selectedSeason?.id, selectedSeason?.name])
  const eligibleRows = eligibleData.key === eligibleRequestKey ? eligibleData.rows : []
  const eligibleLoading = Boolean(eligibleEndpoint && selectedSeason && eligibleData.key !== eligibleRequestKey)
  const seasonReadOnly = Boolean(activeSeasonOnly && seasonScoped && selectedSeason && selectedSeason.status && selectedSeason.status !== 'ACTIVE')
  const periodBlocked = waitingForPeriod || periodUnavailable || missingSeason
  const rowsReady = !periodBlocked && loadedKey === scopedEndpoint
  const visibleRows = rowsReady ? rows : []
  const visibleSummaryRows = rowsReady ? summaryRows : []
  const loading = waitingForPeriod || (!periodUnavailable && !missingSeason && !rowsReady)

  const refresh = async () => {
    try {
      const response = await apiClient.get(scopedEndpoint)
      setRows(listData(response.data))
      setLoadedKey(scopedEndpoint)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.status === 401 ? 'Sign in to access this workflow.' : 'Unable to load records.')
      setLoadedKey(scopedEndpoint)
    }
    if (scopedSummaryEndpoint) {
      try {
        const response = await apiClient.get(scopedSummaryEndpoint)
        setSummaryRows(listData(response.data))
      } catch {
        setSummaryRows([])
      }
    }
  }

  const refreshOptions = async () => {
    const optionPaths = optionPathsFor(forms)
    const entries = await Promise.all(optionPaths.map(async (path) => {
      try {
        const scopedPath = seasonScopedPath(path, selectedSeason, seasonScoped, cropSeason)
        return [path, await getAllPages(scopedPath)]
      } catch {
        return [path, []]
      }
    }))
    setOptions(Object.fromEntries(entries))
  }

  useEffect(() => {
    if (waitingForPeriod || periodUnavailable || missingSeason) return undefined
    let mounted = true
    const load = async () => {
      try {
        const response = await apiClient.get(scopedEndpoint)
        if (!mounted) return
        setRows(listData(response.data))
        setError('')
        setLoadedKey(scopedEndpoint)
      } catch (requestError) {
        if (!mounted) return
        setRows([])
        setError(requestError.response?.status === 401 ? 'Sign in to access this workflow.' : 'Unable to load records.')
        setLoadedKey(scopedEndpoint)
      }
      if (scopedSummaryEndpoint) {
        try {
          const response = await apiClient.get(scopedSummaryEndpoint)
          if (mounted) setSummaryRows(listData(response.data))
        } catch {
          if (mounted) setSummaryRows([])
        }
      }
      const optionPaths = optionPathsFor(forms)
      const entries = await Promise.all(optionPaths.map(async (path) => {
        try {
          const scopedPath = seasonScopedPath(path, selectedSeason, seasonScoped, cropSeason)
          return [path, await getAllPages(scopedPath)]
        } catch {
          return [path, []]
        }
      }))
      if (mounted) setOptions(Object.fromEntries(entries))
    }
    load()
    return () => { mounted = false }
  }, [forms, scopedEndpoint, scopedSummaryEndpoint, selectedSeason, seasonScoped, cropSeason, waitingForPeriod, periodUnavailable, missingSeason])

  useEffect(() => () => {
    Object.values(farmerOptionRequests.current).forEach((controller) => controller?.abort())
  }, [])

  useEffect(() => {
    if (!eligibleEndpoint || !selectedSeason) return undefined

    let mounted = true
    const eligiblePath = withQueryParams(eligibleEndpoint, {
      season: selectedSeason.id,
      season_name: selectedSeason.name,
      page_size: 100,
    })
    getAllPages(eligiblePath)
      .then((eligibleFarmers) => {
        if (mounted) setEligibleData({ key: eligibleRequestKey, rows: eligibleFarmers })
      })
      .catch(() => {
        if (mounted) setEligibleData({ key: eligibleRequestKey, rows: [] })
      })

    return () => { mounted = false }
  }, [eligibleEndpoint, eligibleRequestKey, selectedSeason])

  const changeValue = (formKey, name, value) => {
    const form = forms.find((candidate) => candidate.key === formKey)
    const dependentFields = form?.fields.filter((field) => field.dependsOn === name) || []
    const dependentValues = Object.fromEntries(dependentFields.map((field) => {
      const matchingOptions = (options[field.optionsPath] || []).filter(
        (option) => String(option[field.dependsOnId || name]) === String(value),
      )
      const selectedValue = field.autoSelectSingle && matchingOptions.length === 1
        ? String(matchingOptions[0].id)
        : ''
      return [field.name, selectedValue]
    }))
    setValues((current) => ({
      ...current,
      [formKey]: { ...current[formKey], [name]: value, ...dependentValues },
    }))

    if (name === 'farmer') {
      dependentFields.filter((field) => field.optionsPath).forEach((field) => {
        const requestKey = `${formKey}:${field.name}`
        farmerOptionRequests.current[requestKey]?.abort()
        setDependentOptions((current) => ({ ...current, [requestKey]: [] }))
        if (!value || field.optionsPath !== '/farms/') return

        const controller = new AbortController()
        farmerOptionRequests.current[requestKey] = controller
        const params = new URLSearchParams({ farmer: String(value), page_size: '100' })
        apiClient.get(`${field.optionsPath}?${params.toString()}`, { signal: controller.signal })
          .then((response) => {
            if (controller.signal.aborted) return
            const matchingOptions = listData(response.data)
            setDependentOptions((current) => ({ ...current, [requestKey]: matchingOptions }))
            if (field.autoSelectSingle && matchingOptions.length === 1) {
              setValues((current) => {
                if (String(current[formKey]?.[name]) !== String(value)) return current
                return {
                  ...current,
                  [formKey]: { ...current[formKey], [field.name]: String(matchingOptions[0].id) },
                }
              })
            }
          })
          .catch(() => {
            if (!controller.signal.aborted) setDependentOptions((current) => ({ ...current, [requestKey]: [] }))
          })
      })
    }
  }

  const submit = async (event, form) => {
    event.preventDefault()
    if (seasonReadOnly) {
      setError('This season is read-only. ARDA requests can only be created or edited for the active season.')
      return
    }
    const formValues = values[form.key] || {}
    const missingFarmer = form.fields.find((field) => field.type === 'farmer' && field.required !== false && !formValues[field.name])
    if (missingFarmer) {
      setError(`Select ${missingFarmer.label.toLowerCase()} from the suggestions.`)
      return
    }
    if (!editingId && form.preventDuplicateBy?.length) {
      const comparableStatuses = form.duplicateStatuses || []
      const duplicate = visibleRows.find((row) => {
        if (comparableStatuses.length && !comparableStatuses.includes(String(row.status || '').toUpperCase())) return false
        return form.preventDuplicateBy.every((fieldName) => {
          const formValue = String(formValues[fieldName] || '').trim().toLowerCase()
          const rowValue = String(row[fieldName] || '').trim().toLowerCase()
          return formValue && formValue === rowValue
        })
      })
      if (duplicate) {
        setError(form.duplicateMessage || 'A matching active record already exists. Edit the existing one instead.')
        return
      }
    }
    if (form.globalSeasonField && !selectedSeason?.id) {
      setError('Select a global season before creating this record.')
      return
    }
    setSaving(true)
    setError('')
    setMessage('')
    const payload = Object.fromEntries(Object.entries(formValues).filter(([, value]) => value !== '' && value !== undefined))
    if (form.globalSeasonField) payload[form.globalSeasonField] = selectedSeason.id
    try {
      const requestUrl = editingId && form.editable ? `${endpoint}${editingId}/` : form.endpoint || endpoint
      const scopedRequestUrl = cropSeason ? withQueryParams(requestUrl, { crop_season: cropSeason }) : requestUrl
      const response = editingId && form.editable
        ? await apiClient.patch(scopedRequestUrl, payload)
        : await apiClient.post(scopedRequestUrl, payload)
      setMessage(`${form.submitLabel || 'Record'} saved.`)
      setValues((current) => ({ ...current, [form.key]: {} }))
      setEditingId(null)
      if (form.afterCreate) await form.afterCreate(response.data)
      await Promise.all([refresh(), refreshOptions()])
    } catch (requestError) {
      const data = requestError.response?.data
      setError(data ? Object.values(data).flat().join(' ') : 'Unable to save this record.')
    } finally {
      setSaving(false)
    }
  }

  const approve = async (row) => {
    setError('')
    try {
      await apiClient.post(`${endpoint}${row.id}/approve/`, { approved_hectares: row.requested_hectares })
      setMessage('ARDA request approved.')
      await refresh()
    } catch (requestError) {
      setError(requestError.response?.data ? Object.values(requestError.response.data).flat().join(' ') : 'Unable to approve this request.')
    }
  }

  const startEditing = (row) => {
    if (seasonReadOnly) {
      setError('This season is read-only. ARDA requests can only be created or edited for the active season.')
      return
    }
    const form = forms.find((candidate) => candidate.editable)
    if (!form) return
    const editableValues = Object.fromEntries(form.fields.map((field) => [field.name, row[field.name] ?? '']))
    setValues((current) => ({ ...current, [form.key]: editableValues }))
    setEditingId(row.id)
    setMessage(form.editStartMessage || `Editing ${row.request_number || row.farmer_name || 'record'}.`)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const removeRecord = async () => {
    if (!pendingDelete) return
    setError('')
    setMessage('')
    try {
      await apiClient.delete(`${endpoint}${pendingDelete.id}/`)
      setMessage('Record deleted.')
      setPendingDelete(null)
      if (editingId === pendingDelete.id) setEditingId(null)
      await refresh()
    } catch (requestError) {
      const data = requestError.response?.data
      const text = data ? Object.values(data).flat().join(' ') : 'This record could not be deleted.'
      setError(text)
      setPendingDelete(null)
    }
  }

  const editForm = forms.find((candidate) => candidate.editable)
  const editButtonLabel = editForm?.editButtonLabel || 'Edit'
  const showActions = approveAction || editAction || deleteAction

  return (
    <section className="workflow-page">
      <div className="workflow-heading">
        <div><p className="eyebrow">Golden Path</p><h3>{title}</h3></div>
        <button type="button" className="ghost-btn" onClick={refresh}>Refresh</button>
      </div>
      {waitingForPeriod ? <div className="form-message">Loading the selected period...</div> : null}
      {periodUnavailable ? <div className="form-message error">The agricultural year and season could not be loaded.</div> : null}
      {missingSeason ? <div className="form-message">Choose an agricultural year and season to view records.</div> : null}
      {seasonReadOnly ? <div className="form-message">This season is read-only. Switch to the active season to create or edit requests.</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {message ? <div className="form-message" role="status">{message}</div> : null}

      {forms.map((form) => (
        <form className="workflow-form" key={form.key} onSubmit={(event) => submit(event, form)}>
          <h4>{form.title}</h4>
          <div className="workflow-fields">
            {form.fields.map((field) => {
              if (field.type === 'farmer') {
                return (
                  <FarmerAutocomplete
                    key={field.name}
                    label={field.label}
                    value={values[form.key]?.[field.name] || ''}
                    endpoint={field.searchEndpoint || '/farmers/'}
                    seasonId={field.seasonScoped ? selectedSeason?.id : undefined}
                    seasonName={field.seasonScoped ? selectedSeason?.name : undefined}
                    required={field.required !== false}
                    disabled={seasonReadOnly}
                    onChange={(farmer) => changeValue(form.key, field.name, farmer ? String(farmer.id) : '')}
                  />
                )
              }

              const fieldOptions = field.dependsOn === 'farmer'
                ? dependentOptions[`${form.key}:${field.name}`] || []
                : options[field.optionsPath] || []

              return (
                <label className="form-field" key={field.name}>
                  {field.label}
                  {field.optionsPath || field.choices ? (
                    <select
                      required={field.required !== false}
                      disabled={(field.disabledWithout && !values[form.key]?.[field.disabledWithout]) || seasonReadOnly}
                      value={values[form.key]?.[field.name] || ''}
                      onChange={(event) => changeValue(form.key, field.name, event.target.value)}
                    >
                      <option value="">Select</option>
                      {field.choices
                        ? field.choices.map(([value, label]) => <option key={value} value={value}>{label}</option>)
                        : fieldOptions
                          .filter((option) => !field.category || option.category === field.category)
                          .filter((option) => !field.categoryFromSeason || !cropSeason || option.category === cropSeason)
                          .filter((option) => !field.selectableOnly || option.selectable !== false)
                          .filter((option) => !field.dependsOn || String(option[field.dependsOnId || field.dependsOn]) === String(values[form.key]?.[field.dependsOn] || ''))
                          .map((option) => (
                            <option key={option.id} value={field.optionValue ? option[field.optionValue] : option.id}>{option[field.optionLabel || 'name'] || option.full_name || option.id}</option>
                          ))}
                    </select>
                  ) : (
                    <input
                      type={field.type || 'text'}
                      min={field.min}
                      step={field.step}
                      disabled={seasonReadOnly}
                      required={field.required !== false}
                      value={field.type === 'checkbox' ? undefined : values[form.key]?.[field.name] || ''}
                      checked={field.type === 'checkbox' ? Boolean(values[form.key]?.[field.name]) : undefined}
                      onChange={(event) => changeValue(form.key, field.name, field.type === 'checkbox' ? event.target.checked : event.target.value)}
                    />
                  )}
                </label>
              )
            })}
          </div>
          <div className="workflow-form-actions">
            <button type="submit" className="primary-btn small" disabled={saving || seasonReadOnly}>{saving ? 'Saving…' : editingId && form.editable ? form.editSubmitLabel || 'Update' : form.submitLabel || 'Save'}</button>
            {editingId && form.editable ? <button type="button" className="ghost-btn" onClick={() => { setEditingId(null); setValues((current) => ({ ...current, [form.key]: {} })) }}>Cancel</button> : null}
          </div>
        </form>
      ))}

      {summaryEndpoint ? <>
        <div className="workflow-list-heading"><h4>Request batches and capacity</h4><span>{visibleSummaryRows.length} batches</span></div>
        <div className="table-wrap"><table className="data-table"><thead><tr>{summaryColumns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>
          {visibleSummaryRows.map((row) => <tr key={row.id}>{summaryColumns.map((column) => <td key={column.key}>{column.render ? column.render(row) : row[column.key] ?? '—'}</td>)}</tr>)}
          {!loading && !visibleSummaryRows.length ? <tr><td colSpan={summaryColumns.length}>No request batches yet.</td></tr> : null}
        </tbody></table></div>
      </> : null}
            {eligibleEndpoint ? <>
              <div className="workflow-list-heading">
                <h4>{eligibleTitle || 'Eligible farmers'}</h4>
                <span>{eligibleLoading ? 'Loading…' : `${eligibleRows.length} farmers`}</span>
              </div>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr>{eligibleColumns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
                  <tbody>
                    {eligibleRows.map((row) => (
                      <tr key={row.id}>
                        {eligibleColumns.map((column) => <td key={column.key}>{column.render ? column.render(row) : row[column.key] || '—'}</td>)}
                      </tr>
                    ))}
                    {!eligibleLoading && eligibleRows.length === 0 ? (
                      <tr><td colSpan={eligibleColumns.length}>No farmers have a paid subscription for this season.</td></tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </> : null}
      {pendingDelete ? (
        <div className="form-message error" role="alert">
          Delete {pendingDelete.request_number || pendingDelete.name || 'this record'}? This cannot be undone.
          <button type="button" className="ghost-btn small" onClick={removeRecord}>Confirm delete</button>
          <button type="button" className="ghost-btn small" onClick={() => setPendingDelete(null)}>Cancel</button>
        </div>
      ) : null}
      <div className="workflow-list-heading"><h4>Records</h4><span>{loading ? 'Loading…' : `${visibleRows.length} records`}</span></div>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}{showActions ? <th>Action</th> : null}</tr></thead>
          <tbody>
            {visibleRows.map((row) => (
              <tr key={row.id}>
                {columns.map((column) => <td key={column.key}>{column.render ? column.render(row) : row[column.key] ?? '—'}</td>)}
                {showActions ? <td>
                  {approveAction && row.status === 'PENDING' ? <button className="primary-btn small" type="button" onClick={() => approve(row)}>Approve</button> : null}
                  {editAction && !seasonReadOnly ? <button className="ghost-btn small" type="button" onClick={() => startEditing(row)}>{editButtonLabel}</button> : null}
                  {deleteAction && !seasonReadOnly ? <button className="ghost-btn small" type="button" onClick={() => setPendingDelete(row)}>Delete</button> : null}
                  {approveAction && row.status !== 'PENDING' ? row.status : null}
                  {editAction && seasonReadOnly ? 'Read-only' : null}
                </td> : null}
              </tr>
            ))}
            {!loading && visibleRows.length === 0 ? <tr><td colSpan={columns.length + (showActions ? 1 : 0)}>{seasonScoped ? 'No records for the selected period.' : 'No records yet.'}</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default WorkflowPage
