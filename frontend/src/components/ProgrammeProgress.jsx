// How far a programme's hectares have got: requested by lead farmers, approved by Admin,
// distributed to farmers and finally approved. Every figure comes from the server, which works
// it out from the saved submissions, so it changes as soon as anything is saved or decided.
// This is for monitoring only; decisions are made under Input approvals.

import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import { errorMessage } from './ui'
import { CATEGORY_LABEL, hectares } from '../programmeData'

const EMPTY = { crop: '', input_category: '', requirement: '', lead_farmer: '' }

function ProgrammeProgress({ programme, cropSeason = '' }) {
  const [filters, setFilters] = useState(EMPTY)
  const [data, setData] = useState(null)
  const [loadedKey, setLoadedKey] = useState('')
  const [error, setError] = useState('')
  const requestKey = JSON.stringify([programme.id, cropSeason, filters])

  useEffect(() => {
    let active = true
    const params = { programme: programme.id }
    if (cropSeason) params.crop_season = cropSeason
    Object.entries(filters).forEach(([key, value]) => { if (value) params[key] = value })
    apiClient.get('/input-supply-requests/progress/', { params })
      .then((response) => { if (active) { setData(response.data); setError('') } })
      .catch((requestError) => { if (active) setError(errorMessage(requestError, 'Progress could not be loaded.')) })
      .finally(() => { if (active) setLoadedKey(requestKey) })
    return () => { active = false }
  }, [programme.id, cropSeason, filters, requestKey])

  const options = data?.options
  const varieties = (options?.varieties || []).filter((item) => (!filters.crop || String(item.crop) === filters.crop) && (!filters.input_category || item.input_category === filters.input_category))
  const set = (name, value) => setFilters((current) => {
    const next = { ...current, [name]: value }
    if (name !== 'requirement' && name !== 'lead_farmer') next.requirement = ''
    return next
  })
  const totals = data?.totals
  const percent = totals?.progress_percent === null || totals?.progress_percent === undefined ? null : Math.min(100, Number(totals.progress_percent))

  return (
    <div className="programme-progress">
      <div className="filter-row">
        <label className="form-field">Crop
          <select value={filters.crop} onChange={(event) => set('crop', event.target.value)}>
            <option value="">All crops</option>
            {(options?.crops || []).map((crop) => <option key={crop.id} value={crop.id}>{crop.name}</option>)}
          </select>
        </label>
        <label className="form-field">Input type
          <select value={filters.input_category} onChange={(event) => set('input_category', event.target.value)}>
            <option value="">All input types</option>
            {(options?.categories || []).map((code) => <option key={code} value={code}>{CATEGORY_LABEL[code] || code}</option>)}
          </select>
        </label>
        <label className="form-field">Variety or product
          <select value={filters.requirement} onChange={(event) => set('requirement', event.target.value)}>
            <option value="">All varieties</option>
            {varieties.map((item) => <option key={item.requirement} value={item.requirement}>{item.name}</option>)}
          </select>
        </label>
        <label className="form-field">Lead farmer
          <select value={filters.lead_farmer} onChange={(event) => set('lead_farmer', event.target.value)}>
            <option value="">All lead farmers</option>
            {(options?.lead_farmers || []).map((lead) => <option key={lead.id} value={lead.id}>{lead.name}</option>)}
          </select>
        </label>
      </div>

      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {!data && loadedKey !== requestKey ? <div className="form-message">Loading progress…</div> : null}

      {totals ? (
        totals.submissions ? (
          <>
            <div className="progress-head">
              <strong>{percent === null ? 'Nothing approved yet' : `${totals.progress_percent}% of approved hectares distributed`}</strong>
              <span>{totals.submissions} submission{totals.submissions === 1 ? '' : 's'} from {data.lead_farmers.length} lead farmer{data.lead_farmers.length === 1 ? '' : 's'}</span>
            </div>
            <div className="progress-bar" role="progressbar" aria-label="Approved hectares distributed" aria-valuemin="0" aria-valuemax="100" aria-valuenow={percent ?? 0}>
              <span style={{ width: `${percent ?? 0}%` }} />
            </div>
            <div className="hectare-strip" aria-label="Programme progress">
              <span><small>Requested</small><strong>{hectares(totals.requested_hectares)}</strong></span>
              <span><small>Approved maximum</small><strong>{hectares(totals.approved_hectares)}</strong></span>
              <span><small>Distributed to farmers</small><strong>{hectares(totals.distributed_hectares)}</strong></span>
              <span><small>Remaining approved</small><strong>{hectares(totals.remaining_hectares)}</strong></span>
              <span><small>Finally approved</small><strong>{hectares(totals.final_hectares)}</strong></span>
              {Number(totals.awaiting_hectares) ? <span><small>Awaiting Admin’s decision</small><strong>{hectares(totals.awaiting_hectares)}</strong></span> : null}
            </div>
            <p className="field-hint">
              Distributed includes {hectares(totals.provisional_hectares)} still provisional (waiting for the lead farmer or Admin’s final approval).
              Only finally approved hectares are official and have farmer debts.
            </p>
            <div className="table-wrap">
              <table className="data-table compact">
                <thead><tr><th>Lead farmer</th><th className="num">Requested</th><th className="num">Approved limit</th><th className="num">Distributed</th><th className="num">Remaining</th><th className="num">Finally approved</th><th className="num">Awaiting decision</th></tr></thead>
                <tbody>
                  {data.lead_farmers.map((row) => (
                    <tr key={row.lead_farmer}>
                      <td>{row.lead_farmer_name}</td>
                      <td className="num">{hectares(row.requested_hectares)}</td>
                      <td className="num">{hectares(row.approved_hectares)}</td>
                      <td className="num">{hectares(row.distributed_hectares)}</td>
                      <td className="num">{Number(row.remaining_hectares) < 0 ? <span className="field-error">{hectares(-Number(row.remaining_hectares))} over</span> : hectares(row.remaining_hectares)}</td>
                      <td className="num">{hectares(row.final_hectares)}</td>
                      <td className="num">{Number(row.awaiting_hectares) ? hectares(row.awaiting_hectares) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : <div className="form-message">No lead farmer has sent a submission for this {filters.crop || filters.input_category || filters.requirement || filters.lead_farmer ? 'selection' : 'programme'} yet.</div>
      ) : null}
    </div>
  )
}

export default ProgrammeProgress
