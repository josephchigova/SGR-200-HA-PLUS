import { useEffect, useState } from 'react'

import apiClient from '../api/client'

function DashboardPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const [summary, setSummary] = useState({
    registered_farmers: 0,
    verified_farmers: 0,
    total_hectares: 0,
    arda_requested_hectares: 0,
    arda_approved_hectares: 0,
    input_allocated_hectares: 0,
    production: 0,
    grain_delivered_tonnes: 0,
    outstanding_recovery_tonnes: 0,
    recovery_percentage: 0,
  })
  const [error, setError] = useState('')
  const [loadedKey, setLoadedKey] = useState('')
  const requestKey = `${periodStatus}:${selectedSeason?.id || ''}:${selectedSeason?.name || ''}:${cropSeason}`
  const signedOut = periodStatus === 'ready' && Boolean(selectedSeason) && !localStorage.getItem('sgr_access_token')
  const periodMessage = periodStatus === 'error'
    ? 'The agricultural year and season could not be loaded.'
    : periodStatus === 'ready' && !selectedSeason
      ? 'Choose an agricultural year and season to view this period.'
      : signedOut
        ? 'Please sign in to view the dashboard.'
        : ''
  const loading = !periodMessage && (periodStatus === 'loading' || loadedKey !== requestKey)

  useEffect(() => {
    if (periodStatus !== 'ready' || !selectedSeason || !localStorage.getItem('sgr_access_token')) return undefined

    let active = true
    const params = new URLSearchParams({
      season: String(selectedSeason.id),
      season_name: selectedSeason.name,
    })
    if (cropSeason) params.set('crop_season', cropSeason)
    const loadSummary = async () => {
      try {
        const response = await apiClient.get(`/farmers/dashboard-summary/?${params.toString()}`)
        if (!active) return
        setSummary((current) => ({ ...current, ...(response.data || {}) }))
        setError('')
        setLoadedKey(requestKey)
      } catch {
        if (!active) return
        setError('Unable to load dashboard summary.')
        setLoadedKey(requestKey)
      }
    }

    loadSummary()
    return () => { active = false }
  }, [cropSeason, periodStatus, requestKey, selectedSeason])

  const cards = [
    ['Total Farmers', summary.registered_farmers, 'farmer records'],
    ['Verified Farmers', summary.verified_farmers, 'verified records'],
    ['Total Hectares', summary.total_hectares, 'ha'],
    ['ARDA Requested', summary.arda_requested_hectares, 'ha'],
    ['ARDA Approved', summary.arda_approved_hectares, 'ha'],
    ['Inputs Allocated', summary.input_allocated_hectares, 'ha'],
    ['Production', summary.production, 'tonnes'],
    ['Grain Delivered', summary.grain_delivered_tonnes, 'tonnes'],
    ['Outstanding Recovery', summary.outstanding_recovery_tonnes, 'tonnes'],
    ['Recovery', summary.recovery_percentage, '%'],
  ]

  return (
    <>
      {periodMessage || error ? <div className="form-message error">{periodMessage || error}</div> : null}
      {loading ? <div className="form-message">Loading dashboard...</div> : null}

      {!loading && !error && !periodMessage ? (
        <>
          <section className="stats-grid golden-dashboard">
            {cards.map(([label, value, unit]) => (
              <article className="stat-card" key={label}>
                <span>{label}</span>
                <strong>{Number(value || 0).toLocaleString()}</strong>
                <small>{unit}</small>
              </article>
            ))}
          </section>
        </>
      ) : null}
    </>
  )
}

export default DashboardPage
