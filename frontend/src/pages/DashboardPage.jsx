import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import { ColumnChart, DoughnutChart, ExpenseAnalysis, GroupedBarChart, HorizontalBarChart, TrendChart } from '../components/Charts'
import ClusterPerformance from './ClusterPerformance'
import Icon from '../components/Icon'
import { EmptyState, PageHead, Pill, Skeleton, StatCard } from '../components/ui'

const count = (value) => Number(value || 0).toLocaleString('en-US')
const quantity = (value) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })
const amount = (value) => Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const listOf = (data) => (Array.isArray(data) ? data : Array.isArray(data?.results) ? data.results : [])

const VERIFICATION = {
  VERIFIED: ['Verified', 'good'], APPROVED: ['Approved', 'good'], SUBMITTED: ['Submitted', 'warn'], UNDER_REVIEW: ['In review', 'warn'],
  PENDING: ['Pending', 'warn'], REJECTED: ['Rejected', 'bad'], DRAFT: ['Draft', ''], SUSPENDED: ['Suspended', 'bad'], ARCHIVED: ['Archived', ''],
}

function DashboardCharts({ charts = {}, scoped }) {
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
  // The server leaves out spending for roles without finance access.
  const showExpenses = 'expenses_by_category' in charts || 'expenses_by_month' in charts
  return (
    <section className="analytics-grid" aria-label="Charts">
      <TrendChart title="Farmer registration trends" rows={charts.registrations || []} xKey="month" yKey="count" unit="farmers" note={registrationNote} />
      <TrendChart title={scoped ? 'Subscription payments received' : 'Subscription revenue'} rows={charts.subscription_receipts || []} xKey="month" yKey="amount" unit="USD" area note={revenueNote} />
      <DoughnutChart
        title="Subscription payment status"
        note="Paid, partially paid and unpaid farmers for this year."
        slices={[
          { label: 'Paid', value: status.paid, color: 'var(--chart-1)' },
          { label: 'Partially paid', value: status.partial, color: 'var(--chart-3)' },
          { label: 'Unpaid', value: status.unpaid, color: 'var(--chart-4)' },
        ]}
      />
      {scoped ? null : (
        <GroupedBarChart
          title="Input request hectares"
          unit="ha"
          note="Requested and allocated hectares for the selected agricultural year and season."
          series={[
            { label: 'Requested', value: arda.requested, color: 'var(--chart-1)' },
            { label: 'Allocated', value: arda.allocated, color: 'var(--chart-2)' },
          ]}
        />
      )}
      <ColumnChart title="Agricultural production by crop" rows={charts.production_by_crop || []} labelKey="label" valueKey="tonnes" unit="t" note="Actual production in tonnes." />
      <ColumnChart title="GMB deliveries" rows={charts.deliveries || []} labelKey="month" valueKey="tonnes" unit="t" color="var(--chart-2)" note={deliveryNote} />
      <HorizontalBarChart
        title="Farmer receivables"
        note="Subscription balances and input debt are kept separate."
        rows={[
          { label: 'Subscription receivables', amount: receivables.subscription_outstanding, color: 'var(--chart-1)' },
          { label: 'Input-related debt', amount: receivables.input_debt, color: 'var(--chart-3)' },
        ]}
        labelKey="label"
        valueKey="amount"
        unit="USD"
      />
      {showExpenses ? <ExpenseAnalysis categories={charts.expenses_by_category || []} months={charts.expenses_by_month || []} /> : null}
    </section>
  )
}

function RecentActivity({ rows = [] }) {
  if (!rows.length) return null
  return (
    <section className="activity-card">
      <div className="card-head"><h3>Recent activity</h3></div>
      <div className="table-wrap">
        <table className="data-table">
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
      </div>
    </section>
  )
}

function PendingTasks({ items }) {
  return (
    <section className="card">
      <div className="card-head"><h3>Waiting for you</h3></div>
      {items.length ? (
        <div className="task-list">
          {items.map((item) => (
            <Link className="task-item" key={item.key} to={item.url}>
              <span><strong>{item.title}</strong><small>{item.detail}</small></span>
              <Icon name="chevronRight" />
            </Link>
          ))}
        </div>
      ) : <EmptyState icon="check" title="Nothing is waiting">New work appears here as records change.</EmptyState>}
    </section>
  )
}

function Portfolio({ rows, total }) {
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>Farmer portfolio</h3>
          <p className="card-sub">{total} record{total === 1 ? '' : 's'} · Select a farmer for the details</p>
        </div>
        <Link className="ghost-btn small" to="/farmers">View all</Link>
      </div>
      {rows.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Farmer</th><th>Membership number</th><th>District</th><th>Registration</th></tr></thead>
            <tbody>
              {rows.map((farmer) => {
                const [label, tone] = VERIFICATION[farmer.verification_status] || [farmer.verification_status || '—', '']
                return (
                  <tr key={farmer.id}>
                    <td><Link to={`/farmers/${farmer.id}`}>{farmer.full_name || `${farmer.first_name || ''} ${farmer.surname || ''}`}</Link></td>
                    <td>{farmer.membership_number || '—'}</td>
                    <td>{farmer.district_name || '—'}</td>
                    <td><Pill tone={tone}>{label}</Pill></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : <EmptyState icon="users" title="No farmers registered yet">Register a farmer to start your portfolio.</EmptyState>}
    </section>
  )
}

function DashboardPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const { profile, can } = useAuth()
  const [summary, setSummary] = useState({})
  const [tasks, setTasks] = useState([])
  const [portfolio, setPortfolio] = useState({ rows: [], total: 0 })
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
  const scoped = ['cluster', 'district', 'province'].includes(summary.scope?.kind)
  const leadFarmer = profile?.role === 'lead_farmer'

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

  useEffect(() => {
    if (!profile) return undefined
    let active = true
    apiClient.get('/notifications/').then((response) => {
      if (active) setTasks(Array.isArray(response.data?.items) ? response.data.items : [])
    }).catch(() => {})
    if (leadFarmer) {
      apiClient.get('/farmers/?page_size=8&ordering=-registration_date').then((response) => {
        if (active) setPortfolio({ rows: listOf(response.data), total: response.data?.count ?? listOf(response.data).length })
      }).catch(() => {})
    }
    return () => { active = false }
  }, [profile, leadFarmer, reloadToken])

  const receivables = summary.charts?.receivables || {}
  const outstanding = (Number(receivables.subscription_outstanding) || 0) + (Number(receivables.input_debt) || 0)
  const farmerCards = [
    [scoped ? 'My Farmers' : 'Total Farmers', count(summary.registered_farmers), scoped ? summary.scope?.label : 'Registered farmers', 'users'],
    ['Verified Farmers', count(summary.verified_farmers), `${count(summary.pending_verifications)} awaiting verification`, 'shield'],
    ['Total Hectares', quantity(summary.total_hectares), 'ha registered', 'mapPin'],
  ]
  const requestCards = scoped ? [] : [
    ['Input Requests', count(summary.arda_request_count), 'Request batches this period', 'send'],
    ['Input Requested', quantity(summary.arda_requested_hectares), 'ha', 'clipboard'],
  ]
  const cards = [
    ...farmerCards,
    ...requestCards,
    ['Inputs Allocated', quantity(summary.input_allocated_hectares), 'ha', 'box'],
    ['Production', quantity(summary.production), 'tonnes', 'tractor'],
    ['Grain Delivered', quantity(summary.grain_delivered_tonnes), 'tonnes', 'truck'],
    ['Outstanding Farmer Receivables', amount(outstanding), 'USD · subscriptions and input debt', 'dollar'],
  ]
  const firstName = profile?.first_name || ''
  const title = leadFarmer ? 'My fieldwork' : 'Overview'
  const subtitle = leadFarmer
    ? `${summary.scope?.label || profile?.cluster_name || 'Your cluster'} · Register farmers and follow their progress from submission to recovery.`
    : scoped
      ? `${summary.scope?.label} · Farmer registration, production and recovery in your area.`
      : 'Farmer registration, agricultural production and financial performance for the selected period.'

  return (
    <div className="dashboard-page">
      <PageHead title={title} subtitle={`${firstName ? `Welcome, ${firstName}. ` : ''}${subtitle}`}>
        <button type="button" className="ghost-btn" onClick={() => setReloadToken((value) => value + 1)}><Icon name="refresh" />Refresh</button>
        {can('farmers', 'create') && profile ? <Link className="primary-btn" to="/farmers"><Icon name="plus" />Register farmer</Link> : null}
      </PageHead>

      {periodMessage || error ? <div className="form-message error" role="alert">{periodMessage || error}</div> : null}
      {loading ? (
        <>
          <section className="kpi-grid"><Skeleton kind="stat" count={6} /></section>
          <Skeleton kind="block" />
        </>
      ) : null}

      {!loading && !error && !periodMessage ? (
        <>
          <section className="kpi-grid" aria-label="Summary">
            {cards.map(([label, value, hint, icon]) => <StatCard key={label} label={label} value={value} hint={hint} icon={icon} />)}
          </section>
          {leadFarmer ? <Portfolio rows={portfolio.rows} total={portfolio.total} /> : <ClusterPerformance seasonName={selectedSeason?.name || ''} />}
          <DashboardCharts charts={summary.charts} scoped={scoped} />
          {profile ? <PendingTasks items={tasks} /> : null}
          <RecentActivity rows={summary.charts?.recent || []} />
        </>
      ) : null}
    </div>
  )
}

export default DashboardPage
