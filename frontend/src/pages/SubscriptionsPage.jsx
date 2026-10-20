import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import FarmerAutocomplete from '../components/FarmerAutocomplete'

const PAGE_SIZE = 25

const toList = (data) => (Array.isArray(data) ? data : data?.results || [])

const today = () => {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

const formatMoney = (amount) => `$${Number(amount || 0).toLocaleString('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})}`

const errorMessage = (error) => {
  const data = error.response?.data
  if (typeof data === 'string') return data
  if (data && typeof data === 'object') return Object.values(data).flat().join(' ')
  return 'Unable to complete the subscription request.'
}

function SubscriptionsPage({ selectedSeason }) {
  const seasonName = selectedSeason?.name || ''
  const [rows, setRows] = useState([])
  const [summary, setSummary] = useState(null)
  const [loadedSummaryKey, setLoadedSummaryKey] = useState('')
  const [count, setCount] = useState(0)
  const [hasNextPage, setHasNextPage] = useState(false)
  const [hasPreviousPage, setHasPreviousPage] = useState(false)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [loadedRequestKey, setLoadedRequestKey] = useState('')
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [farmerId, setFarmerId] = useState('')
  const [farmerStatus, setFarmerStatus] = useState(null)
  const [loadedFarmerStatusKey, setLoadedFarmerStatusKey] = useState('')
  const [paidAmount, setPaidAmount] = useState('0.00')
  const [paymentDate, setPaymentDate] = useState(today)
  const [saving, setSaving] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const requestKey = JSON.stringify([seasonName, page, debouncedSearch, reloadKey])
  const summaryRequestKey = JSON.stringify([seasonName, reloadKey])
  const farmerStatusKey = farmerId && seasonName ? `${seasonName}:${farmerId}` : ''
  const loading = Boolean(seasonName && loadedRequestKey !== requestKey)
  const summaryLoading = Boolean(seasonName && loadedSummaryKey !== summaryRequestKey)
  const currentSummary = seasonName && !summaryLoading ? summary : null
  const farmerStatusLoading = Boolean(farmerStatusKey && loadedFarmerStatusKey !== farmerStatusKey)
  const visibleRows = seasonName && !loading ? rows : []
  const visibleCount = seasonName ? count : 0
  const currentFarmerStatus = farmerStatusLoading ? null : farmerStatus

  const [pageSeason, setPageSeason] = useState(seasonName)
  if (pageSeason !== seasonName) {
    setPageSeason(seasonName)
    setPage(1)
  }

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    if (!seasonName) return undefined

    let active = true
    const params = new URLSearchParams({ season: seasonName })
    apiClient.get(`/farmer-subscriptions/summary/?${params.toString()}`)
      .then((response) => {
        if (!active) return
        setSummary(response.data)
        setLoadedSummaryKey(summaryRequestKey)
      })
      .catch((requestError) => {
        if (!active) return
        setSummary(null)
        setLoadedSummaryKey(summaryRequestKey)
        setError(errorMessage(requestError))
      })

    return () => {
      active = false
    }
  }, [reloadKey, seasonName, summaryRequestKey])

  useEffect(() => {
    if (!seasonName) {
      return undefined
    }

    let active = true
    const params = new URLSearchParams({
      season: seasonName,
      page: String(page),
      page_size: String(PAGE_SIZE),
    })
    if (debouncedSearch) params.set('search', debouncedSearch)

    apiClient.get(`/farmer-subscriptions/?${params.toString()}`)
      .then((response) => {
        if (!active) return
        setRows(toList(response.data))
        setCount(response.data?.count ?? toList(response.data).length)
        setHasNextPage(Boolean(response.data?.next))
        setHasPreviousPage(Boolean(response.data?.previous))
        setLoadedRequestKey(requestKey)
        setError('')
      })
      .catch((requestError) => {
        if (!active) return
        setRows([])
        setCount(0)
        setLoadedRequestKey(requestKey)
        setError(errorMessage(requestError))
      })

    return () => {
      active = false
    }
  }, [debouncedSearch, page, reloadKey, requestKey, seasonName])

  useEffect(() => {
    if (!farmerId || !seasonName) {
      return undefined
    }

    let active = true
    const params = new URLSearchParams({ season: seasonName, farmer: farmerId, page_size: '1' })
    apiClient.get(`/farmer-subscriptions/?${params.toString()}`)
      .then((response) => {
        if (!active) return
        const statusRow = toList(response.data)[0] || null
        setFarmerStatus(statusRow)
        setLoadedFarmerStatusKey(farmerStatusKey)
        if (statusRow) {
          setPaidAmount(statusRow.paid_amount || '0.00')
          setPaymentDate(statusRow.payment_date || today())
        } else {
          setPaidAmount('0.00')
          setPaymentDate(today())
        }
      })
      .catch((requestError) => {
        if (active) {
          setLoadedFarmerStatusKey(farmerStatusKey)
          setError(errorMessage(requestError))
        }
      })

    return () => {
      active = false
    }
  }, [farmerId, farmerStatusKey, seasonName])

  const submitPayment = async (event) => {
    event.preventDefault()
    setError('')
    setFeedback('')
    if (!seasonName) {
      setError('Select a season before recording a payment.')
      return
    }
    if (!farmerId || !currentFarmerStatus) {
      setError('Select a farmer and wait for the subscription amount to load.')
      return
    }

    setSaving(true)
    try {
      const response = await apiClient.post('/farmer-subscriptions/', {
        farmer: Number(farmerId),
        paid_amount: paidAmount,
        payment_date: Number(paidAmount) > 0 ? paymentDate : null,
        season: seasonName,
      })
      setFarmerStatus((current) => ({ ...current, ...response.data }))
      setPaidAmount(response.data.paid_amount || '0.00')
      setPaymentDate(response.data.payment_date || today())
      setFeedback(`Payment status saved as ${response.data.payment_status}.`)
      setReloadKey((current) => current + 1)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="workflow-page subscription-page">
      <header className="subscription-page-heading">
        <div>
          <p className="eyebrow">{seasonName || 'Season unavailable'}</p>
          <h3>Farmer subscriptions</h3>
          <p className="period-note">Payments belong to the agricultural year and are shared by Summer and Winter.</p>
        </div>
        <span className="subscription-record-count">{visibleCount.toLocaleString()} farmers</span>
      </header>

      {!seasonName ? <div className="form-message">Choose a season to view payment statuses.</div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {feedback ? <div className="form-message" role="status">{feedback}</div> : null}

      <section className="subscription-summary" aria-label="Global season payment summary">
        <div><span>Total Farmers</span><strong>{currentSummary ? currentSummary.total_farmers.toLocaleString() : '—'}</strong></div>
        <div><span>Paid</span><strong>{currentSummary ? currentSummary.paid.toLocaleString() : '—'}</strong></div>
        <div><span>Partial</span><strong>{currentSummary ? currentSummary.partial.toLocaleString() : '—'}</strong></div>
        <div><span>Unpaid</span><strong>{currentSummary ? currentSummary.unpaid.toLocaleString() : '—'}</strong></div>
      </section>

      <form className="workflow-form subscription-payment-form" onSubmit={submitPayment}>
        <div className="workflow-heading">
          <h4>Record or update payment</h4>
          <span className="subscription-season-label">{seasonName || 'No season selected'}</span>
        </div>
        <div className="workflow-fields">
          <FarmerAutocomplete
            label="Farmer"
            value={farmerId}
            required
            disabled={!seasonName || saving}
            onChange={(farmer) => {
              setFarmerId(farmer ? String(farmer.id) : '')
              setFarmerStatus(null)
              setPaidAmount('0.00')
              setPaymentDate(today())
              setError('')
              setFeedback('')
            }}
          />
          <label className="form-field">
            Subscription category
            <input
              aria-label="Subscription category"
              value={farmerStatusLoading ? 'Calculating...' : currentFarmerStatus?.category || 'Select a farmer'}
              readOnly
            />
          </label>
          <label className="form-field">
            Registered arable hectares
            <input
              aria-label="Registered arable hectares"
              value={farmerStatusLoading ? '' : currentFarmerStatus?.farmer_arable_hectares || ''}
              readOnly
            />
          </label>
          <label className="form-field">
            Expected amount
            <input
              aria-label="Expected amount"
              value={farmerStatusLoading ? '' : currentFarmerStatus ? formatMoney(currentFarmerStatus.expected_amount) : ''}
              readOnly
            />
          </label>
          <label className="form-field">
            Total paid to date
            <input
              type="number"
              min="0"
              max={currentFarmerStatus?.expected_amount || undefined}
              step="0.01"
              required
              value={paidAmount}
              disabled={!currentFarmerStatus || saving}
              onChange={(event) => setPaidAmount(event.target.value)}
            />
          </label>
          <label className="form-field">
            Latest payment date
            <input
              type="date"
              required={Number(paidAmount) > 0}
              value={paymentDate}
              disabled={!currentFarmerStatus || saving}
              onChange={(event) => setPaymentDate(event.target.value)}
            />
          </label>
        </div>
        <button className="primary-btn" type="submit" disabled={saving || farmerStatusLoading || !currentFarmerStatus || !seasonName}>
          {saving ? 'Saving...' : 'Save payment status'}
        </button>
      </form>

      <section className="subscription-status-section" aria-labelledby="subscription-status-heading">
        <div className="workflow-list-heading">
          <h4 id="subscription-status-heading">Season payment status</h4>
          <input
            className="tab-search subscription-search"
            type="search"
            value={search}
            placeholder="Search name, ID, membership or phone"
            aria-label="Search subscription statuses"
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(1)
            }}
            disabled={!seasonName}
          />
        </div>

        {seasonName && loading ? <div className="form-message">Loading farmer statuses...</div> : null}
        {!loading && !error && visibleRows.length === 0 && seasonName ? <div className="form-message">No farmers match this search.</div> : null}

        {!loading && seasonName && visibleRows.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table subscription-table">
              <thead>
                <tr>
                  <th>Farmer</th>
                  <th>Arable ha</th>
                  <th>Category</th>
                  <th>Expected</th>
                  <th>Paid to date</th>
                  <th>Balance</th>
                  <th>Status</th>
                  <th>Payment date</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={row.farmer}>
                    <td>
                      <strong>{row.farmer_name}</strong>
                      <small>{row.national_id || row.membership_number || row.phone_primary || 'No identifier'}</small>
                    </td>
                    <td>{row.farmer_arable_hectares}</td>
                    <td>{row.category}</td>
                    <td>{formatMoney(row.expected_amount)}</td>
                    <td>{formatMoney(row.paid_amount)}</td>
                    <td>{formatMoney(row.outstanding_amount)}</td>
                    <td><span className={`status-pill subscription-status ${row.payment_status.toLowerCase()}`}>{row.payment_status}</span></td>
                    <td>{row.payment_date || '—'}</td>
                    <td>
                      <button
                        type="button"
                        className="ghost-btn small"
                        onClick={() => {
                          setFarmerId(String(row.farmer))
                          setFarmerStatus(row)
                          setPaidAmount(row.paid_amount || '0.00')
                          setPaymentDate(row.payment_date || today())
                          setError('')
                          setFeedback('')
                        }}
                      >
                        Update
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="subscription-pagination">
          <span>{visibleCount ? `Showing ${(page - 1) * PAGE_SIZE + 1}-${Math.min(page * PAGE_SIZE, visibleCount)} of ${visibleCount}` : 'No results'}</span>
          <div>
            <button type="button" className="ghost-btn small" disabled={!hasPreviousPage || loading} onClick={() => setPage((current) => Math.max(current - 1, 1))}>
              Previous
            </button>
            <button type="button" className="ghost-btn small" disabled={!hasNextPage || loading} onClick={() => setPage((current) => current + 1)}>
              Next
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}

export default SubscriptionsPage
