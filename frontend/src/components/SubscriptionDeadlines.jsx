// The subscription due date for an agricultural year, who has not paid, and the reminders sent.
//
// Reminders are created by a daily job: before the due date, on it, the day after it and every
// 30 days while a subscription stays unpaid. Lead farmers see payment status, never amounts.

import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from './Icon'
import { EmptyState, Pill, errorMessage } from './ui'

const STATUS = { UNPAID: ['Not paid', 'bad'], PARTIAL: ['Partly paid', 'warn'] }
const money = (value) => Number(value || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export default function SubscriptionDeadlines({ seasonName }) {
  const { can, profile } = useAuth()
  const canSet = can('subscriptions', 'edit')
  const showMoney = profile?.role !== 'lead_farmer'
  const [data, setData] = useState(null)
  const [due, setDue] = useState('')
  const [reminders, setReminders] = useState([])
  const [tab, setTab] = useState('overdue')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [token, setToken] = useState(0)
  const load = () => setToken((value) => value + 1)

  useEffect(() => {
    if (!seasonName) return undefined
    let active = true
    Promise.all([
      apiClient.get('/farmer-subscriptions/overdue/', { params: { season_name: seasonName } }),
      apiClient.get('/notifications/inbox/', { params: { kind: 'SUBSCRIPTION', limit: 100 } }),
    ]).then(([overdue, inbox]) => {
      if (!active) return
      setData(overdue.data)
      setDue(overdue.data.due_date || '')
      setReminders((inbox.data.results || []).filter((row) => row.season === seasonName))
      setError('')
    }).catch((requestError) => {
      if (active) setError(errorMessage(requestError, 'Overdue subscriptions could not be loaded.'))
    })
    return () => { active = false }
  }, [seasonName, token])

  const saveDue = async (event) => {
    event.preventDefault()
    try {
      await apiClient.post('/farmer-subscriptions/deadline/', { season: seasonName, due_date: due || null })
      setNotice(due ? `Subscriptions for ${seasonName} are due on ${new Date(due).toLocaleDateString()}. Reminders follow that date.` : 'Due date cleared. No reminders are sent until a date is set.')
      load()
    } catch (requestError) {
      setError(errorMessage(requestError, 'The due date could not be saved.'))
    }
  }

  if (!seasonName) return null
  const rows = data?.results || []
  return (
    <section className="card subscription-deadlines">
      <div className="card-head">
        <div>
          <h3><Icon name="calendar" />Payment deadline and overdue subscriptions</h3>
          <p className="card-sub">
            {data?.due_date
              ? `Subscriptions for ${seasonName} are due on ${new Date(data.due_date).toLocaleDateString()}. ${data.is_overdue ? `${rows.length} approved farmer${rows.length === 1 ? ' has' : 's have'} not fully paid and ${rows.length === 1 ? 'is' : 'are'} overdue.` : 'Reminders start 7 days before.'}`
              : `No due date is set for ${seasonName}, so no reminders are sent.`}
          </p>
        </div>
        {canSet ? (
          <form className="due-date-form" onSubmit={saveDue}>
            <label className="form-field">Due date<input type="date" value={due} onChange={(event) => setDue(event.target.value)} /></label>
            <button type="submit" className="primary-btn small">Save</button>
          </form>
        ) : null}
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      <div className="tabs" role="tablist" aria-label="Deadline views">
        <button type="button" role="tab" aria-selected={tab === 'overdue'} onClick={() => setTab('overdue')}>Not fully paid ({rows.length})</button>
        <button type="button" role="tab" aria-selected={tab === 'reminders'} onClick={() => setTab('reminders')}>Reminders sent to you ({reminders.length})</button>
      </div>
      {tab === 'overdue' ? (
        rows.length ? (
          <div className="table-wrap">
            <table className="data-table compact">
              <thead><tr><th>Farmer</th><th>Membership No.</th><th>Category</th><th>Status</th><th className="num">Paid (%)</th>{showMoney ? <th className="num">Amount due</th> : null}<th className="num">Days overdue</th></tr></thead>
              <tbody>
                {rows.map((row) => {
                  const [label, tone] = STATUS[row.payment_status] || [row.payment_status, '']
                  return (
                    <tr key={row.farmer}>
                      <td>{row.farmer_name}</td>
                      <td>{row.membership_number || '—'}</td>
                      <td>{row.category}</td>
                      <td><Pill tone={tone}>{label}</Pill></td>
                      <td className="num">{row.compliance_percent}%</td>
                      {showMoney ? <td className="num">{money(row.amount_due)}</td> : null}
                      <td className="num">{row.days_overdue ? row.days_overdue : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : <EmptyState icon="check" title="Everyone has paid">All approved farmers have fully paid their {seasonName} subscription.</EmptyState>
      ) : (
        reminders.length ? (
          <div className="table-wrap">
            <table className="data-table compact">
              <thead><tr><th>Sent</th><th>Reminder</th><th>Detail</th><th>Status</th></tr></thead>
              <tbody>
                {reminders.map((row) => (
                  <tr key={row.id}>
                    <td>{new Date(row.created_at).toLocaleString()}</td>
                    <td>{row.kind_label}</td>
                    <td>{row.body}</td>
                    <td>{row.read_at ? `Read ${new Date(row.read_at).toLocaleDateString()}` : row.delivered_at ? 'Shown' : 'Not yet shown'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState icon="bell" title="No reminders yet">Reminders appear once the due date approaches.</EmptyState>
      )}
    </section>
  )
}
