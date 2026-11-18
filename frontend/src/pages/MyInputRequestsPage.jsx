// A lead farmer's submission history: drafts, hectare decisions, distributions and final approvals.

import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { EmptyState, PageHead, Pill, errorMessage } from '../components/ui'
import { canEditSubmission, STATUS_TONE, when } from '../inputSupply'
import { loadAll, money, qty } from '../programmeData'

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
  const waiting = rows.filter((row) => row.status === 'SUBMITTED' || row.status === 'CONFIRMATION').length

  return (
    <div className="page-card">
      <PageHead
        title="My input requests"
        subtitle="Submission history for this agricultural year and season. A draft, a returned submission, or approved hectares can be changed from Input allocations."
      />
      {blocked ? <div className="form-message">Choose an agricultural year in the header.</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      <section className="card">
        <div className="card-head">
          <div>
            <h3>{selectedSeason?.name || 'Agricultural year'}</h3>
            <p className="card-sub">{waiting ? `${waiting} waiting for Admin.` : 'Nothing is waiting for Admin.'}</p>
          </div>
        </div>
        {loading ? <div className="form-message">Loading submissions…</div> : null}
        {!loading && !blocked && !rows.length ? <EmptyState icon="send" title="No input requests">Allocate varieties to your farmers, then submit the request.</EmptyState> : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Submission</th><th>Programme</th><th>Crop</th><th>Season</th><th className="num">Hectares</th><th className="num">Estimated cost</th><th>Status</th><th>Submitted</th><th></th></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <Fragment key={row.id}>
                    <tr>
                      <td><strong>{row.reference}</strong></td>
                      <td>{row.programme_name}</td>
                      <td>{row.crop_name}</td>
                      <td>{row.crop_season_label}</td>
                      <td className="num">{qty(row.hectares_total)} ha</td>
                      <td className="num">{money(row.estimated_cost)}</td>
                      <td><Pill tone={STATUS_TONE[row.status] || ''}>{row.status_label}</Pill></td>
                      <td>{when(row.submitted_at)}</td>
                      <td>
                        <button type="button" className="ghost-btn" onClick={() => setOpen(open === row.id ? null : row.id)}>{open === row.id ? 'Hide' : 'Details'}</button>
                      </td>
                    </tr>
                    {open === row.id ? (
                      <tr>
                        <td colSpan={9}>
                          {row.decision_notes ? <p><strong>Admin:</strong> {row.decision_notes}</p> : null}
                          {row.reviewed_by_name ? <p className="card-sub">Reviewed by {row.reviewed_by_name} on {when(row.reviewed_at)}.</p> : null}
                          {row.limits?.length ? (
                            <div className="table-wrap">
                              <table className="data-table">
                                <thead><tr><th>Level</th><th>Item</th><th className="num">Requested</th><th className="num">Approved</th><th className="num">Allocated</th><th className="num">Still available</th></tr></thead>
                                <tbody>
                                  {row.limits.map((limit) => (
                                    <tr key={limit.id}>
                                      <td>{limit.scope_label}</td>
                                      <td>{limit.name}</td>
                                      <td className="num">{qty(limit.requested_hectares)} ha</td>
                                      <td className="num"><strong>{qty(limit.approved_hectares)} ha</strong></td>
                                      <td className="num">{qty(limit.allocated_hectares)} ha</td>
                                      <td className="num">{qty(limit.remaining_hectares)} ha</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : null}
                          <div className="table-wrap">
                            <table className="data-table">
                              <thead><tr><th>Input</th><th>Variety</th><th className="num">Hectares</th><th className="num">Quantity</th><th className="num">Estimated cost</th></tr></thead>
                              <tbody>
                                {(row.totals || []).map((line) => (
                                  <tr key={line.requirement}>
                                    <td>{line.input_category_label}</td>
                                    <td>{line.product_name}</td>
                                    <td className="num">{qty(line.hectares)} ha</td>
                                    <td className="num">{qty(line.quantity)} {line.unit}</td>
                                    <td className="num">{money(line.estimated_cost)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          <div className="table-wrap">
                            <table className="data-table">
                              <thead><tr><th>Farmer</th><th className="num">Land ha</th><th>Varieties</th></tr></thead>
                              <tbody>
                                {row.farmers.map((farmer) => (
                                  <tr key={farmer.id}>
                                    <td>{farmer.farmer_name}</td>
                                    <td className="num">{qty(farmer.hectares)}</td>
                                    <td>{farmer.lines.map((line) => `${line.product_name} ${qty(line.hectares)} ha`).join(', ')}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          <ol className="timeline">
                            {(row.events || []).map((event) => (
                              <li key={event.id}>
                                <Pill tone={STATUS_TONE[event.action] || ''}>{event.action_label}</Pill>
                                <span>{when(event.created_at)} · {event.actor_name || 'System'}</span>
                                {event.remarks ? <p>{event.remarks}</p> : null}
                              </li>
                            ))}
                          </ol>
                          {canEditSubmission(row) ? <Link to="/input-allocations">Change this submission</Link> : null}
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
