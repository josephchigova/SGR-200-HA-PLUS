// Lead farmer: every input submission, its status, Admin's feedback, limits and history.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import { AllocationsTable, CropBreakdown, HectareSummary, History, LimitsTable, StatusPill } from '../components/SubmissionParts'
import { EmptyState, PageHead, errorMessage } from '../components/ui'
import { nextStep, when } from '../inputSupply'
import { hectares, listOf } from '../programmeData'

function MyInputRequestsPage({ selectedSeason = null, cropSeason = '', periodStatus = 'ready' }) {
  const [rows, setRows] = useState([])
  const [open, setOpen] = useState(null)
  const [loadedKey, setLoadedKey] = useState('')
  const [error, setError] = useState('')
  const blocked = periodStatus !== 'ready' || !selectedSeason
  const requestKey = JSON.stringify([selectedSeason?.id, cropSeason])

  useEffect(() => {
    if (blocked) return undefined
    let active = true
    const params = { season: selectedSeason.id, page_size: 100 }
    if (cropSeason) params.crop_season = cropSeason
    apiClient.get('/input-supply-requests/', { params })
      .then((response) => { if (active) { setRows(listOf(response.data)); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Your requests could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [blocked, selectedSeason, cropSeason, requestKey])

  const loading = !blocked && loadedKey !== requestKey
  const current = rows.find((row) => row.id === open)

  return (
    <div className="page-card">
      <PageHead title="My input requests" subtitle="Your submissions to Admin for each programme and season, with their status, Admin’s feedback and history." />
      {blocked ? <div className="form-message">Choose the agricultural year and season in the header.</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {loading ? <div className="form-message">Loading…</div> : null}
      {!loading && !blocked && !rows.length ? <EmptyState icon="send" title="No requests yet">Add allocations on the Input allocations page to start one.</EmptyState> : null}
      {rows.length ? (
        <section className="card">
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Request</th><th>Programme</th><th>Year and season</th><th className="num">Requested</th><th className="num">Approved maximum</th><th className="num">Distributed</th><th>Status</th><th>Updated</th><th /></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className={open === row.id ? 'selected-row' : ''}>
                    <td><strong>{row.reference}</strong>{row.earlier_workflow ? <small className="block-hint">Earlier one-crop request</small> : null}</td>
                    <td>{row.programme_name}</td>
                    <td>{row.season_name} · {row.crop_season_label}</td>
                    <td className="num">{hectares(row.requested_hectares)}</td>
                    <td className="num">{row.approved_hectares ? hectares(row.approved_hectares) : '—'}</td>
                    <td className="num">{hectares(row.hectares_total)}</td>
                    <td><StatusPill submission={row} />{row.limits_changed ? <small className="block-hint field-error">Limits changed</small> : null}</td>
                    <td>{when(row.reviewed_at || row.submitted_at)}</td>
                    <td><button type="button" className="ghost-btn small" onClick={() => setOpen(open === row.id ? null : row.id)}>{open === row.id ? 'Close' : 'Open'}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      {current ? (
        <section className="card">
          <div className="card-head">
            <div>
              <h3>{current.reference} · {current.programme_name} · {current.season_name} {current.crop_season_label} <StatusPill submission={current} /></h3>
              <p className="card-sub">{nextStep(current)}</p>
              {current.decision_notes ? <p className={['RETURNED', 'REJECTED'].includes(current.status) ? 'field-error' : 'card-sub'}>Admin: {current.decision_notes}</p> : null}
            </div>
            {current.editable ? <Link className="primary-btn small" to={`/input-allocations?submission=${current.id}`}>{current.hectares_capped ? 'Adjust to the maximum' : 'Open in Input allocations'}</Link> : null}
          </div>
          <HectareSummary submission={current} />
          <h4>Farmer allocations</h4>
          <AllocationsTable allocations={current.allocations} />
          {current.limits?.length ? <details className="expandable"><summary>Approved maximum hectares</summary><LimitsTable limits={current.limits} /></details> : null}
          <details className="expandable"><summary>Totals by crop and variety</summary><CropBreakdown crops={current.crops} /></details>
          {current.events?.length ? <details className="expandable"><summary>History and Admin feedback</summary><History events={current.events} /></details> : null}
        </section>
      ) : null}
    </div>
  )
}

export default MyInputRequestsPage
