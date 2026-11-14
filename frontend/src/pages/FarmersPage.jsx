import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import TabSearch from '../components/TabSearch'
import { EmptyState, Pill } from '../components/ui'
import { formatDisplay } from '../formatNumbers'
import { statusOf } from '../registration'

const PAGE_SIZE = 25
// Each filter is a set of registration states.
const FILTERS = [
  ['', 'All'],
  ['VERIFIED,APPROVED', 'Approved'],
  ['SUBMITTED,UNDER_REVIEW,PENDING', 'Awaiting approval'],
  ['DRAFT', 'Incomplete'],
  ['CORRECTIONS_REQUESTED', 'Corrections needed'],
  ['REJECTED', 'Rejected'],
]
const EDITABLE = ['DRAFT', 'CORRECTIONS_REQUESTED', 'REJECTED']

const getListData = (data) => (Array.isArray(data) ? data : data?.results || [])

function FarmersPage() {
  const { can, profile } = useAuth()
  const canCreate = can('farmers', 'create')
  const leadFarmer = profile?.role === 'lead_farmer'
  const [farmers, setFarmers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [status, setStatus] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const hasInitializedSearch = useRef(false)

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const isFirstPage = currentPage <= 1
  const isLastPage = currentPage >= totalPages

  useEffect(() => {
    if (!hasInitializedSearch.current) {
      hasInitializedSearch.current = true
      return undefined
    }
    const timer = setTimeout(() => {
      setCurrentPage(1)
      setAppliedSearch(search)
    }, 250)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    let active = true
    const timer = setTimeout(async () => {
      try {
        setLoading(true)
        const params = { page: currentPage, page_size: PAGE_SIZE }
        if (appliedSearch.trim()) params.search = appliedSearch.trim()
        if (status) params.verification_status = status
        const response = await apiClient.get('/farmers/', { params })
        if (!active) return
        setFarmers(getListData(response.data))
        setTotalCount(Array.isArray(response.data) ? response.data.length : Number(response.data?.count || 0))
        setError('')
      } catch (requestError) {
        if (!active) return
        setError(requestError.response?.status === 401
          ? 'Your session is expired or invalid. Please log in again.'
          : 'Unable to load farmers right now.')
      } finally {
        if (active) setLoading(false)
      }
    }, 0)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [appliedSearch, currentPage, status])

  return (
    <div className="page-card">
      <div className="section-head">
        <div>
          <h3>Farmers</h3>
          <p>
            {leadFarmer
              ? `The farmers in ${profile?.cluster_name || 'your cluster'}. Register a farmer, then follow the registration until an administrator approves it.`
              : 'The permanent register of members and applicants. Open a farmer to see farms, documents and history.'}
          </p>
        </div>
        <div className="page-actions">
          <TabSearch value={search} onChange={setSearch} placeholder="Filter farmers..." />
          {canCreate ? <Link className="primary-btn" to="/farmers/register"><Icon name="plus" />Register farmer</Link> : null}
        </div>
      </div>

      <div className="chip-row" role="group" aria-label="Registration status">
        {FILTERS.map(([value, label]) => (
          <button key={label} type="button" className={status === value ? 'chip active' : 'chip'} aria-pressed={status === value} onClick={() => { setCurrentPage(1); setStatus(value) }}>{label}</button>
        ))}
      </div>

      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {loading ? <div className="form-message">Loading farmers...</div> : null}

      {!loading && !error && (
        <div className="table-wrap">
          {farmers.length > 0 ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Membership No.</th>
                  <th>Farmer</th>
                  <th>Province</th>
                  <th>District</th>
                  <th>Ward</th>
                  <th>Cluster</th>
                  <th>Hectares</th>
                  <th>Registration</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {farmers.map((farmer) => {
                  const [label, tone] = statusOf(farmer.verification_status)
                  const canContinue = canCreate && EDITABLE.includes(farmer.verification_status) && Boolean(farmer.registered_by)
                  return (
                    <tr key={farmer.id}>
                      <td>{farmer.membership_number || '—'}</td>
                      <td><Link to={`/farmers/${farmer.id}`}>{farmer.full_name || `${farmer.first_name || ''} ${farmer.surname || ''}`.trim() || 'Unknown'}</Link></td>
                      <td>{farmer.province_name || '—'}</td>
                      <td>{farmer.district_name || '—'}</td>
                      <td>{farmer.ward_name || '—'}</td>
                      <td>{farmer.cluster_name || '—'}</td>
                      <td>{formatDisplay('farm_hectares', farmer.farm_hectares) ?? '—'}</td>
                      <td>
                        <Pill tone={tone}>{label}</Pill>
                        {farmer.review_remarks && EDITABLE.includes(farmer.verification_status) ? <small>{farmer.review_remarks}</small> : null}
                      </td>
                      <td>
                        {canContinue
                          ? <Link className="ghost-btn small" to={`/farmers/${farmer.id}/edit`}>{farmer.verification_status === 'DRAFT' ? 'Continue' : 'Correct'}</Link>
                          : <Link className="ghost-btn small" to={`/farmers/${farmer.id}`}>Open</Link>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <EmptyState icon="users" title="No farmers found">
              {status || appliedSearch ? 'Change the filter or search.' : canCreate ? 'Register the first farmer to get started.' : 'Farmers appear here once they are registered.'}
            </EmptyState>
          )}

          <div className="table-foot">
            <span>{totalCount} farmers</span>
            {totalPages > 1 ? (
              <span className="table-actions">
                <button type="button" className="ghost-btn small" disabled={isFirstPage || loading} onClick={() => setCurrentPage((previous) => Math.max(previous - 1, 1))}>Previous</button>
                <span style={{ alignSelf: 'center' }}>Page {currentPage} of {totalPages}</span>
                <button type="button" className="ghost-btn small" disabled={isLastPage || loading} onClick={() => setCurrentPage((previous) => Math.min(previous + 1, totalPages))}>Next</button>
              </span>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}

export default FarmersPage
