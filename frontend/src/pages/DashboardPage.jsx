import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import { ColumnChart, DoughnutChart, ExpenseAnalysis, GroupedBarChart, HorizontalBarChart, TrendChart } from '../components/Charts'

const count = (value) => Number(value || 0).toLocaleString('en-US')

function DashboardCharts({ charts = {} }) {
  const arda = charts.arda_hectares || {}
  const status = charts.subscription_status || {}
  const receivables = charts.receivables || {}
  const undated = Number(charts.subscription_receipts_undated || 0)
  const undatedLabel = `USD ${undated.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const undatedFarmers = Number(charts.registrations_undated || 0)
  const undatedTonnes = Number(charts.deliveries_undated_tonnes || 0)
  const revenueNote = undated > 0
    ? `${undatedLabel} was collected without a payment date, so it is not placed on a month. Outstanding balances are not cash.`
    : 'Payments actually received. Outstanding balances are not included.'
  const registrationNote = undatedFarmers > 0
    ? `Farmers registered during the selected agricultural year. ${undatedFarmers.toLocaleString('en-US')} farmers have no registration date, so they are not placed on a month.`
    : 'Farmers registered during the selected agricultural year.'
  const deliveryNote = undatedTonnes > 0
    ? `${undatedTonnes.toLocaleString('en-US', { maximumFractionDigits: 2 })} tonnes have no delivery date, so they are not placed on a month.`
    : 'Delivered tonnes by month.'
  return (
    <section className="analytics-grid">
      <TrendChart title="Farmer registration trends" rows={charts.registrations || []} xKey="month" yKey="count" unit="farmers" note={registrationNote} />
      <TrendChart title="Subscription revenue" rows={charts.subscription_receipts || []} xKey="month" yKey="amount" unit="USD" area note={revenueNote} />
      <DoughnutChart
        title="Subscription payment status"
        note="Paid, partially paid and unpaid farmers for this year."
        slices={[
          { label: 'Paid', value: status.paid, color: '#1f6b45' },
          { label: 'Partially paid', value: status.partial, color: '#b8860b' },
          { label: 'Unpaid', value: status.unpaid, color: '#64748b' },
        ]}
      />
      <GroupedBarChart
        title="ARDA hectares"
        unit="ha"
        note="Requested and allocated hectares for the selected agricultural year and season."
        series={[
          { label: 'Requested', value: arda.requested, color: '#1f6b45' },
          { label: 'Allocated', value: arda.allocated, color: '#0f766e' },
        ]}
      />
      <ColumnChart title="Agricultural production by crop" rows={charts.production_by_crop || []} labelKey="label" valueKey="tonnes" unit="t" note="Actual production in tonnes." />
      <ColumnChart title="GMB deliveries" rows={charts.deliveries || []} labelKey="month" valueKey="tonnes" unit="t" color="#0f766e" note={deliveryNote} />
      <HorizontalBarChart
        title="Farmer receivables"
        note="Subscription balances and input debt are kept separate."
        rows={[
          { label: 'Subscription receivables', amount: receivables.subscription_outstanding, color: '#1f6b45' },
          { label: 'Input-related debt', amount: receivables.input_debt, color: '#b8860b' },
        ]}
        labelKey="label"
        valueKey="amount"
        unit="USD"
      />
      <ExpenseAnalysis categories={charts.expenses_by_category || []} months={charts.expenses_by_month || []} />
    </section>
  )
}

function RecentActivity({ rows = [] }) {
  if (!rows.length) return null
  return (
    <section className="activity-card">
      <h3>Recent activity</h3>
      <table>
        <thead><tr><th>Date</th><th>Activity</th><th>Detail</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.kind}-${row.when}-${row.detail}`}>
              <td>{row.when || '—'}</td>
              <td>{row.kind}</td>
              <td>{row.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function DashboardPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const [summary, setSummary] = useState({
    registered_farmers: 0,
    verified_farmers: 0,
    total_hectares: 0,
    arda_requested_hectares: 0,
    arda_request_count: 0,
    input_allocated_hectares: 0,
    production: 0,
    grain_delivered_tonnes: 0,
  })
  const [error, setError] = useState('')
  const [loadedKey, setLoadedKey] = useState('')
  const [reloadToken, setReloadToken] = useState(0)
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
    const refresh = () => {
      if (document.visibilityState === 'visible') setReloadToken((value) => value + 1)
    }
    document.addEventListener('visibilitychange', refresh)
    window.addEventListener('focus', refresh)
    return () => {
      document.removeEventListener('visibilitychange', refresh)
      window.removeEventListener('focus', refresh)
    }
  }, [])

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
        setSummary(response.data || {})
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
  }, [cropSeason, periodStatus, reloadToken, requestKey, selectedSeason])

  const receivables = summary.charts?.receivables || {}
  const outstanding = (Number(receivables.subscription_outstanding) || 0) + (Number(receivables.input_debt) || 0)
  const quantity = (value) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })
  const amount = (value) => Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const cards = [
    ['Total Farmers', count(summary.registered_farmers), ''],
    ['Verified Farmers', count(summary.verified_farmers), ''],
    ['Total Hectares', quantity(summary.total_hectares), 'ha'],
    ['ARDA Requests', count(summary.arda_request_count), ''],
    ['ARDA Requested', quantity(summary.arda_requested_hectares), 'ha'],
    ['Inputs Allocated', quantity(summary.input_allocated_hectares), 'ha'],
    ['Production', quantity(summary.production), 'tonnes'],
    ['Grain Delivered', quantity(summary.grain_delivered_tonnes), 'tonnes'],
    ['Outstanding Farmer Receivables', amount(outstanding), 'USD'],
  ]

  return (
    <div className="dashboard-page">
      {periodMessage || error ? <div className="form-message error">{periodMessage || error}</div> : null}
      {loading ? <div className="form-message">Loading dashboard...</div> : null}

      {!loading && !error && !periodMessage ? (
        <>
          <section className="kpi-grid" aria-label="Summary">
            {cards.map(([label, value, unit]) => (
              <article className="kpi-card" key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
                <small>{unit || '\u00a0'}</small>
              </article>
            ))}
          </section>
          <DashboardCharts charts={summary.charts} />
          <RecentActivity rows={summary.charts?.recent || []} />
        </>
      ) : null}
    </div>
  )
}

export default DashboardPage
