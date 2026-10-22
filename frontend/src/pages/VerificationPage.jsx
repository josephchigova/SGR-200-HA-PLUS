import { useEffect, useRef, useState } from 'react'

import apiClient from '../api/client'
import TabSearch from '../components/TabSearch'

const PAGE_SIZE = 25
const VERIFICATION_QUEUE_FILTER = 'DRAFT,SUBMITTED,UNDER_REVIEW'

const statusOptions = [
  { value: 'SUBMITTED', label: 'Submitted' },
  { value: 'UNDER_REVIEW', label: 'Under Review' },
  { value: 'VERIFIED', label: 'Verified' },
  { value: 'REJECTED', label: 'Rejected' },
]

function VerificationPage() {
  const [farmers, setFarmers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [pendingDecision, setPendingDecision] = useState({})
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const hasInitializedSearch = useRef(false)

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const isFirstPage = currentPage <= 1
  const isLastPage = currentPage >= totalPages

  const loadQueue = async (query = '', page = 1) => {
    try {
      setLoading(true)
      const params = {
        verification_status: VERIFICATION_QUEUE_FILTER,
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
      loadQueue(appliedSearch, currentPage)
    }, 0)
    return () => clearTimeout(timer)
  }, [appliedSearch, currentPage])

  const handleDecisionChange = (farmerId, field, value) => {
    setPendingDecision((previous) => ({
      ...previous,
      [farmerId]: {
        ...(previous[farmerId] || {}),
        [field]: value,
      },
    }))
  }

  const submitDecision = async (farmerId) => {
    const token = localStorage.getItem('sgr_access_token')
    const payload = pendingDecision[farmerId] || {}

    if (!payload.verification_status) {
      setError('Choose a verification outcome before submitting.')
      return
    }

    try {
      const response = await apiClient.post(`/farmers/${farmerId}/verify/`, payload, {
        headers: { Authorization: `Bearer ${token}` },
      })

      setPendingDecision((previous) => {
        const next = { ...previous }
        delete next[farmerId]
        return next
      })
      setError('')
      const targetPage = currentPage > 1 && farmers.length === 1 ? currentPage - 1 : currentPage
      setCurrentPage(targetPage)
      await loadQueue(appliedSearch, targetPage)
      if (response.data) {
        console.log('Verification updated', response.data)
      }
    } catch (requestError) {
      const message = requestError.response?.data
        ? Object.values(requestError.response.data).flat().join(' ')
        : 'Unable to save verification decision.'
      setError(message)
    }
  }

  return (
    <div className="page-card">
      <div className="section-head">
        <h3>Farmer Verification</h3>
        <TabSearch value={search} onChange={setSearch} placeholder="Filter verification queue..." />
      </div>

      {error ? <div className="form-message error">{error}</div> : null}
      {loading ? <div className="form-message">Loading review queue...</div> : null}

      {!loading && farmers.length === 0 ? (
        <div className="form-message">No farmers are awaiting verification.</div>
      ) : null}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Farmer</th>
              <th>Membership</th>
              <th>National ID</th>
              <th>Phone</th>
              <th>Province</th>
              <th>District</th>
              <th>Membership status</th>
              <th>Decision</th>
              <th>Reason</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {farmers.map((farmer) => {
              const customerDecision = pendingDecision[farmer.id] || {}
              const isRejected = customerDecision.verification_status === 'REJECTED'

              return (
                <tr key={farmer.id}>
                  <td>{farmer.full_name || `${farmer.first_name || ''} ${farmer.surname || ''}`.trim()}</td>
                  <td>{farmer.membership_number || '—'}</td>
                  <td>{farmer.national_id || '—'}</td>
                  <td>{farmer.phone_primary || '—'}</td>
                  <td>{farmer.province_name || '—'}</td>
                  <td>{farmer.district_name || '—'}</td>
                  <td>{farmer.membership_status || '—'}</td>
                  <td>
                    <select
                      value={customerDecision.verification_status || ''}
                      onChange={(event) => handleDecisionChange(farmer.id, 'verification_status', event.target.value)}
                    >
                      <option value="">Select</option>
                      {statusOptions.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="text"
                      value={customerDecision.rejection_reason || ''}
                      onChange={(event) => handleDecisionChange(farmer.id, 'rejection_reason', event.target.value)}
                      placeholder={isRejected ? 'Required for rejection' : 'Optional notes'}
                      disabled={!isRejected}
                    />
                  </td>
                  <td>
                    <button type="button" className="primary-btn small" onClick={() => submitDecision(farmer.id)}>
                      Save
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        <div className="workflow-form-actions">
          <span>{totalCount} farmers in queue</span>
          {totalPages > 1 ? (
            <>
              <button type="button" className="ghost-btn" disabled={isFirstPage || loading} onClick={() => setCurrentPage((previous) => Math.max(previous - 1, 1))}>
                Previous
              </button>
              <span>Page {currentPage} of {totalPages}</span>
              <button type="button" className="ghost-btn" disabled={isLastPage || loading} onClick={() => setCurrentPage((previous) => Math.min(previous + 1, totalPages))}>
                Next
              </button>
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}

export default VerificationPage
