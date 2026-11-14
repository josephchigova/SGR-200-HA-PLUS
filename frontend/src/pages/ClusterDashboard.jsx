import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import { EmptyState, PageHead, Pill, Skeleton, StatCard, errorMessage } from '../components/ui'
import { statusOf } from '../registration'

const FILTERS = [
  ['all', 'All farmers'],
  ['approved', 'Approved'],
  ['awaiting', 'Awaiting approval'],
  ['action', 'Needs your action'],
]
const AWAITING = ['SUBMITTED', 'UNDER_REVIEW', 'PENDING']
const APPROVED = ['VERIFIED', 'APPROVED']
const ACTION = ['DRAFT', 'CORRECTIONS_REQUESTED', 'REJECTED']

export function PlaceTable({ title, rows }) {
  return (
    <div className="table-wrap" style={{ marginTop: 12 }}>
      <table className="data-table">
        <thead><tr><th>{title}</th><th>Farmers</th><th>Approved</th><th>Pending</th><th>Subscription</th><th>Participation</th><th>Crop allocation</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td><td>{row.farmers}</td><td>{row.approved}</td><td>{row.pending}</td>
              <td>{row.subscription_compliance}%</td><td>{row.agricultural_participation}%</td><td>{row.crop_allocation}%</td>
            </tr>
          ))}
          {!rows.length ? <tr><td colSpan={7}>No farmers in this breakdown yet.</td></tr> : null}
        </tbody>
      </table>
    </div>
  )
}

export function Meter({ value, label }) {
  const percent = Math.max(0, Math.min(100, Number(value) || 0))
  const tone = percent >= 100 ? 'good' : percent > 0 ? 'warn' : 'none'
  return (
    <div className="meter" role="img" aria-label={`${label || 'Progress'} ${percent}%`}>
      <div className="progress-track"><i className={tone} style={{ width: `${percent}%` }} /></div>
      <b>{percent}%</b>
    </div>
  )
}

function Progress({ label, value, detail }) {
  return (
    <div className="progress-row">
      <header><span>{label}</span><span>{value}%</span></header>
      <div className="progress-track"><i style={{ width: `${Math.min(value, 100)}%` }} /></div>
      {detail ? <small className="card-sub">{detail}</small> : null}
    </div>
  )
}

// The lead farmer's home: the cluster in counts and percentages. No money is shown,
// and none is sent by the server for this role.
function ClusterDashboard({ selectedSeason = null, periodStatus = 'ready' }) {
  const { profile } = useAuth()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [token, setToken] = useState(0)
  const seasonName = selectedSeason?.name || ''

  useEffect(() => {
    if (periodStatus === 'loading') return undefined
    let active = true
    apiClient.get('/farmers/cluster-overview/', { params: seasonName ? { season_name: seasonName } : {} }).then((response) => {
      if (!active) return
      setData(response.data)
      setError('')
    }).catch((requestError) => {
      if (active) setError(errorMessage(requestError, 'The cluster overview could not be loaded.'))
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [seasonName, periodStatus, token])

  const farmers = useMemo(() => {
    const rows = data?.farmers || []
    const term = search.trim().toLowerCase()
    return rows.filter((row) => {
      if (filter === 'approved' && !APPROVED.includes(row.verification_status)) return false
      if (filter === 'awaiting' && !AWAITING.includes(row.verification_status)) return false
      if (filter === 'action' && !ACTION.includes(row.verification_status)) return false
      return !term || `${row.name} ${row.membership_number}`.toLowerCase().includes(term)
    })
  }, [data, filter, search])

  const counts = data?.counts || {}
  const performance = data?.performance || {}
  const cluster = data?.cluster
  const needsAction = (counts.incomplete || 0) + (counts.corrections_requested || 0)

  return (
    <div className="dashboard-page">
      <PageHead
        title="My cluster"
        subtitle={`${cluster ? `${cluster.name} · ${[cluster.province, cluster.district].filter(Boolean).join(' · ')}` : profile?.cluster_name || 'No cluster assigned'}. Register farmers and follow their progress${seasonName ? ` for ${seasonName}` : ''}.`}
      >
        <button type="button" className="ghost-btn" onClick={() => { setLoading(true); setToken((value) => value + 1) }}><Icon name="refresh" />Refresh</button>
        <Link className="primary-btn" to="/farmers/register"><Icon name="plus" />Register farmer</Link>
      </PageHead>

      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {loading && !data ? (
        <>
          <section className="kpi-grid"><Skeleton kind="stat" count={5} /></section>
          <Skeleton kind="block" />
        </>
      ) : null}

      {data ? (
        <>
          <section className="kpi-grid" aria-label="Cluster overview">
            <StatCard label="Farmers in cluster" value={counts.total} hint="Every registration you have captured" icon="users" />
            <StatCard label="Approved farmers" value={counts.approved} hint="Active SGR members" icon="shield" tone="good" />
            <StatCard label="Awaiting approval" value={counts.awaiting_approval} hint="With the administrator" icon="history" />
            <StatCard label="Rejected registrations" value={counts.rejected || 0} hint="Open one to see the reason" icon="alert" tone={counts.rejected ? 'bad' : ''} />
            <StatCard label="Incomplete registrations" value={needsAction} hint={counts.corrections_requested ? `${counts.corrections_requested} need corrections` : 'Drafts to finish'} icon="clipboard" tone={needsAction ? 'warn' : ''} />
            <StatCard label="Subscription compliance" value={`${performance.subscription_compliance || 0}%`} hint={`${performance.subscription_complete || 0} of ${counts.approved || 0} approved farmers complete`} icon="chart" />
          </section>

          {needsAction || counts.rejected ? (
            <section className="card">
              <div className="card-head"><h3>Needs your action</h3></div>
              <div className="task-list">
                {(data.farmers || []).filter((row) => ACTION.includes(row.verification_status)).slice(0, 6).map((row) => {
                  const [label, tone] = statusOf(row.verification_status)
                  return (
                    <Link className="task-item" key={row.id} to={`/farmers/${row.id}/edit`}>
                      <span>
                        <strong>{row.name}</strong> <Pill tone={tone}>{label}</Pill>
                        <small>{row.review_remarks || (row.verification_status === 'DRAFT' ? `${row.documents_uploaded} of ${row.documents_required} required documents uploaded. Finish and submit.` : 'Open to correct and resubmit.')}</small>
                      </span>
                      <Icon name="chevronRight" />
                    </Link>
                  )
                })}
              </div>
            </section>
          ) : null}

          <section className="card">
            <div className="card-head">
              <div><h3>Cluster performance</h3><p className="card-sub">Shares of your farmers, shown as percentages.</p></div>
            </div>
            <div className="perf-grid">
              <Progress label="Registration submitted" value={performance.registration_progress || 0} detail="Registrations sent for approval or approved" />
              <Progress label="Approved by administrator" value={performance.approval_progress || 0} detail={`${counts.approved || 0} of ${counts.total || 0} farmers`} />
              <Progress label="KYC documents verified" value={performance.kyc_progress || 0} detail="Farmers with every required document verified" />
              <Progress label="Subscription compliance" value={performance.subscription_compliance || 0} detail={`${performance.subscription_in_progress || 0} in progress · ${performance.subscription_not_started || 0} not started`} />
              <Progress label="Agricultural participation" value={performance.participation || 0} detail="Approved farmers with planting or production this year" />
              <Progress label="Seasonal cropping recorded" value={performance.seasonal_cropping || 0} detail="Approved farmers with a planting plan" />
              <Progress label="Crop allocation recorded" value={performance.crop_allocation || 0} detail="Farmers whose planned crops were captured at registration" />
              <Progress label="Inputs allocated" value={performance.input_allocation || 0} detail="Approved farmers with an input allocation" />
            </div>
          </section>

          <section className="card">
            <div className="card-head"><div><h3>Performance by district and ward</h3><p className="card-sub">Only farmers in your cluster. Subscription figures are percentages.</p></div></div>
            <PlaceTable title="District" rows={data.by_district || []} />
            <PlaceTable title="Ward" rows={data.by_ward || []} />
          </section>

          <section className="card">
            <div className="card-head">
              <div><h3>Farmer performance</h3><p className="card-sub">{farmers.length} of {counts.total} farmers. Subscription progress is a percentage. Amounts are handled by the finance team.</p></div>
              <input className="tab-search" type="search" aria-label="Search farmers" placeholder="Search farmer or membership number" value={search} onChange={(event) => setSearch(event.target.value)} />
            </div>
            <div className="chip-row" role="group" aria-label="Filter farmers" style={{ marginBottom: 12 }}>
              {FILTERS.map(([value, label]) => <button key={value} type="button" className={filter === value ? 'chip active' : 'chip'} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}
            </div>
            {farmers.length ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Farmer</th><th>Registration</th><th>KYC documents</th><th>Subscription compliance</th><th>Status</th><th>Cropping</th><th>Inputs</th></tr></thead>
                  <tbody>
                    {farmers.map((row) => {
                      const [label, tone] = statusOf(row.verification_status)
                      const approved = row.subscription_compliance !== null
                      return (
                        <tr key={row.id}>
                          <td><Link to={`/farmers/${row.id}`}>{row.name}</Link><small>{row.membership_number}{row.ward ? ` · ${row.ward}` : ''}</small></td>
                          <td><Pill tone={tone}>{label}</Pill></td>
                          <td>{row.documents_verified} of {row.documents_required} verified</td>
                          <td>{approved ? <Meter value={row.subscription_compliance} label={`${row.name} subscription compliance`} /> : '—'}</td>
                          <td>{approved ? <Pill tone={row.subscription_compliance >= 100 ? 'good' : row.subscription_compliance > 0 ? 'warn' : ''}>{row.subscription_status}</Pill> : <span className="card-sub">After approval</span>}</td>
                          <td>{row.planting_recorded ? <Pill tone="good">Recorded</Pill> : <Pill>Not yet</Pill>}</td>
                          <td>{row.inputs_allocated ? <Pill tone="good">Allocated</Pill> : <Pill>Not yet</Pill>}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState icon="users" title={counts.total ? 'No farmers match' : 'No farmers in your cluster yet'}>
                {counts.total ? 'Change the filter or search.' : 'Register your first farmer to start building the cluster.'}
              </EmptyState>
            )}
          </section>
        </>
      ) : null}
    </div>
  )
}

export default ClusterDashboard
