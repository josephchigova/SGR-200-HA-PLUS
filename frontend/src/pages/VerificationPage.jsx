import { useEffect, useRef, useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import RegistrationReview from '../components/RegistrationReview'
import TabSearch from '../components/TabSearch'
import { EmptyState, Pill } from '../components/ui'
import { statusOf } from '../registration'

const PAGE_SIZE = 25
const VERIFICATION_QUEUE_FILTER = 'DRAFT,SUBMITTED,UNDER_REVIEW'
const QUEUES = [
  [VERIFICATION_QUEUE_FILTER, 'Awaiting approval'],
  ['CORRECTIONS_REQUESTED', 'Corrections requested'],
  ['REJECTED', 'Rejected'],
  ['VERIFIED,APPROVED', 'Approved'],
]

function VerificationPage() {
  const { can } = useAuth()
  const canDecide = can('farmers', 'approve')
  const [farmers, setFarmers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [queue, setQueue] = useState(VERIFICATION_QUEUE_FILTER)
  const [reviewing, setReviewing] = useState(null)
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const hasInitializedSearch = useRef(false)

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const isFirstPage = currentPage <= 1
  const isLastPage = currentPage >= totalPages

  const loadQueue = async (query = '', page = 1, statuses = queue) => {
    try {
      setLoading(true)
      const params = {
        verification_status: statuses,
        // Registrations still being captured are not shown to the reviewer.
        submitted_only: 1,
        page,
        page_size: PAGE_SIZE,
      }
      if (query.trim()) {
        params.search = query.trim()
      }
      const response = await apiClient.get('/farmers/', { params })

      if (Array.isArray(response.data)) {
        setFarmers(response.data)
        setTotalCount(response.data.length)
      } else {
        setFarmers(response.data?.results || [])
        setTotalCount(Number(response.data?.count || 0))
      }
      setError('')
    } catch {
      setError('Unable to load verification queue.')
    } finally {
      setLoading(false)
    }
  }

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
    const timer = setTimeout(() => {
      loadQueue(appliedSearch, currentPage, queue)
    }, 0)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedSearch, currentPage, queue])

  const decided = async (status) => {
    setReviewing(null)
    setNotice(status === 'VERIFIED' ? 'The registration was approved. The farmer is now an active member.' : status === 'REJECTED' ? 'The registration was rejected. The lead farmer can see the reason.' : 'Corrections were requested. The lead farmer can see your remarks.')
    const targetPage = currentPage > 1 && farmers.length === 1 ? currentPage - 1 : currentPage
    setCurrentPage(targetPage)
    await loadQueue(appliedSearch, targetPage, queue)
  }

  return (
    <div className="page-card">
      <div className="section-head">
        <div>
          <h3>Registration approvals</h3>
          <p>Check each submitted registration and its KYC documents, then approve it, reject it or ask for corrections.{canDecide ? '' : ' Your role can view the queue but not decide.'}</p>
        </div>
        <TabSearch value={search} onChange={setSearch} placeholder="Filter verification queue..." />
      </div>

      <div className="chip-row" role="group" aria-label="Queue">
        {QUEUES.map(([value, label]) => (
          <button key={value} type="button" className={queue === value ? 'chip active' : 'chip'} aria-pressed={queue === value} onClick={() => { setCurrentPage(1); setQueue(value) }}>{label}</button>
        ))}
      </div>

      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message success" role="status">{notice}</div> : null}
      {loading ? <div className="form-message">Loading verification queue...</div> : null}

      {!loading && !error ? (
        <div className="table-wrap">
          {farmers.length ? (
            <table className="data-table">
              <thead>
                <tr><th>Farmer</th><th>National ID</th><th>Province</th><th>District</th><th>Cluster</th><th>Registered by</th><th>Documents</th><th>Status</th><th>Action</th></tr>
              </thead>
              <tbody>
                {farmers.map((farmer) => {
                  const [label, tone] = statusOf(farmer.verification_status)
                  const summary = farmer.documents_summary
                  return (
                    <tr key={farmer.id}>
                      <td>{farmer.full_name || `${farmer.first_name || ''} ${farmer.surname || ''}`.trim()}</td>
                      <td>{farmer.national_id || '—'}</td>
                      <td>{farmer.province_name || '—'}</td>
                      <td>{farmer.district_name || '—'}</td>
                      <td>{farmer.cluster_name || '—'}</td>
                      <td>{farmer.registered_by_name || '—'}</td>
                      <td>{summary ? `${summary.verified} of ${summary.uploaded} verified` : '—'}</td>
                      <td><Pill tone={tone}>{label}</Pill></td>
                      <td><button type="button" className="primary-btn small" onClick={() => { setNotice(''); setReviewing(farmer.id) }}><Icon name="eye" />Review</button></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : <EmptyState icon="check" title="Nothing in this queue">Registrations appear here when a lead farmer or officer submits them.</EmptyState>}
          <div className="table-foot">
            <span>{totalCount} farmers in queue</span>
            {totalPages > 1 ? (
              <span className="table-actions">
                <button type="button" className="ghost-btn small" disabled={isFirstPage || loading} onClick={() => setCurrentPage((previous) => Math.max(previous - 1, 1))}>Previous</button>
                <span style={{ alignSelf: 'center' }}>Page {currentPage} of {totalPages}</span>
                <button type="button" className="ghost-btn small" disabled={isLastPage || loading} onClick={() => setCurrentPage((previous) => Math.min(previous + 1, totalPages))}>Next</button>
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

      {reviewing ? <RegistrationReview farmerId={reviewing} canDecide={canDecide} onClose={() => setReviewing(null)} onDecided={decided} /> : null}
    </div>
  )
}

export default VerificationPage
