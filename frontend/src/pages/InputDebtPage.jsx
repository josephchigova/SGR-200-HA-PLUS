import { useEffect, useMemo, useState } from 'react'

import apiClient from '../api/client'

const toList = (data) => (Array.isArray(data) ? data : data?.results || [])

function InputDebtPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const [rows, setRows] = useState([])
  const [error, setError] = useState('')
  const [loadedKey, setLoadedKey] = useState('')

  const query = useMemo(() => {
    if (!selectedSeason) return ''
    const params = new URLSearchParams({
      season: String(selectedSeason.id),
      season_name: selectedSeason.name,
    })
    if (cropSeason) params.set('crop_season', cropSeason)
    return `?${params.toString()}`
  }, [cropSeason, selectedSeason])
  const requestKey = `${periodStatus}:${query}`
  const periodBlocked = periodStatus !== 'ready' || !selectedSeason
  const rowsReady = !periodBlocked && loadedKey === requestKey
  const visibleRows = rowsReady ? rows : []
  const loading = periodStatus === 'loading' || (!periodBlocked && !rowsReady)

  useEffect(() => {
    if (!selectedSeason || periodStatus !== 'ready') return undefined
    let mounted = true
    const load = async () => {
      try {
        const response = await apiClient.get(`/input-debts/${query}`)
        if (!mounted) return
        setRows(toList(response.data))
        setError('')
        setLoadedKey(requestKey)
      } catch {
        if (!mounted) return
        setRows([])
        setError('Unable to load input debts.')
        setLoadedKey(requestKey)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [periodStatus, query, requestKey, selectedSeason])

  const refresh = async () => {
    try {
      const response = await apiClient.get(`/input-debts/${query}`)
      setRows(toList(response.data))
      setError('')
      setLoadedKey(requestKey)
    } catch {
      setError('Unable to load input debts.')
      setLoadedKey(requestKey)
    }
  }

  return (
    <section className="workflow-page">
      <div className="workflow-heading">
        <button type="button" className="ghost-btn" onClick={refresh}>Refresh</button>
      </div>
      {error ? <div className="form-message error">{error}</div> : null}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Farmer</th>
              <th>Province</th>
              <th>District</th>
              <th>Crop</th>
              <th>Programme</th>
              <th>Contracted Ha</th>
              <th>Input Cost</th>
              <th>Price/Tonne</th>
              <th>Required t</th>
              <th>Delivered t</th>
              <th>Outstanding t</th>
              <th>Amount Recovered</th>
              <th>Outstanding Balance</th>
              <th>Recovery %</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row) => (
              <tr key={row.id}>
                <td>{row.farmer_name}</td>
                <td>{row.province_name || '—'}</td>
                <td>{row.district_name || '—'}</td>
                <td>{row.crop}</td>
                <td>{row.programme_name}</td>
                <td>{row.contracted_hectares}</td>
                <td>{row.input_value}</td>
                <td>{row.selling_price_per_tonne}</td>
                <td>{row.required_recovery_tonnes}</td>
                <td>{row.recovered_tonnes}</td>
                <td>{row.outstanding_tonnes}</td>
                <td>{row.amount_recovered}</td>
                <td>{row.outstanding_monetary_balance}</td>
                <td>{row.recovery_percentage}</td>
                <td>{row.status}</td>
              </tr>
            ))}
            {!loading && visibleRows.length === 0 ? <tr><td colSpan={15}>No input debts for the selected period.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default InputDebtPage
