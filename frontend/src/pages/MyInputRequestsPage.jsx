// A lead farmer's own input requests, including Admin's decision and the correction history.

import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { EmptyState, PageHead, Pill, errorMessage } from '../components/ui'
import { loadAll, qty } from '../programmeData'
import { STATUS_TONE, when } from '../inputSupply'

function MyInputRequestsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const [rows, setRows] = useState([])
  const [loadedKey, setLoadedKey] = useState('')
  const [error, setError] = useState('')
  const [open, setOpen] = useState(null)
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const requestKey = JSON.stringify([selectedSeason?.id, cropSeason])

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id }
    if (cropSeason) params.crop_season = cropSeason
    loadAll('/input-supply-requests/', params)
      .then((list) => { if (active) { setRows(list); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Your input requests could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, requestKey])

  const loading = !blocked && loadedKey !== requestKey
  const waiting = rows.filter((row) => row.status === 'SUBMITTED').length

  return (
    <div className="page-card">
      <PageHead title="My input requests" subtitle="Every request you have saved or submitted, and what Admin decided. A request returned for corrections can be changed from Input allocations and submitted again." />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      <section className="card">
        <div className="card-head">
          <div>
            <h3>{selectedSeason?.name || 'Agricultural year'}</h3>
            <p className="card-sub">{waiting ? `${waiting} waiting for Admin.` : 'Nothing is waiting for Admin.'}</p>
          </div>
        </div>
        {loading ? <div className="form-message">Loading requests…</div> : null}
        {!loading && !blocked && !rows.length ? <EmptyState icon="send" title="No input requests">Allocate varieties to your farmers, then submit the request.</EmptyState> : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Request</th><th>Programme</th><th>Crop</th><th>Season</th><th>Farmers</th><th>Status</th><th>Submitted</th><th></th></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <Fragment key={row.id}>
                    <tr>
                      <td><strong>{row.reference}</strong></td>
                      <td>{row.programme_name}</td>
                      <td>{row.crop_name}</td>
                      <td>{row.crop_season_label}</td>
                      <td>{row.farmer_count}</td>
                      <td><Pill tone={STATUS_TONE[row.status] || ''}>{row.status_label}</Pill></td>
                      <td>{when(row.submitted_at)}</td>
                      <td>
                        <button type="button" className="ghost-btn" onClick={() => setOpen(open === row.id ? null : row.id)}>{open === row.id ? 'Hide' : 'Details'}</button>
                      </td>
                    </tr>
                    {open === row.id ? (
                      <tr>
                        <td colSpan={8}>
                          {row.decision_notes ? <p><strong>Admin:</strong> {row.decision_notes}</p> : null}
                          {row.reviewed_by_name ? <p className="card-sub">Reviewed by {row.reviewed_by_name} on {when(row.reviewed_at)}.</p> : null}
                          <table className="data-table">
                            <thead><tr><th>Input</th><th>Variety</th><th className="num">Requested</th></tr></thead>
                            <tbody>
                              {(row.totals || []).map((line) => (
                                <tr key={line.requirement}><td>{line.input_category_label}</td><td>{line.product_name}</td><td className="num">{qty(line.quantity)} {line.unit}</td></tr>
                              ))}
                            </tbody>
                          </table>
                          <ol className="timeline">
                            {(row.events || []).map((event) => (
                              <li key={event.id}>
                                <Pill tone={STATUS_TONE[event.action] || ''}>{event.action_label}</Pill>
                                <span>{when(event.created_at)} · {event.actor_name || 'System'}</span>
                                {event.remarks ? <p>{event.remarks}</p> : null}
                              </li>
                            ))}
                          </ol>
                          {row.status === 'DRAFT' || row.status === 'RETURNED' ? <Link to="/input-allocations">Change this request</Link> : null}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  )
}

export default MyInputRequestsPage
