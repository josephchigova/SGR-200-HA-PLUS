import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import Icon from '../components/Icon'
import TabSearch from '../components/TabSearch'
import { EmptyState, Pill } from '../components/ui'
import { formatDisplay } from '../formatNumbers'
import { statusOf } from '../registration'

const PAGE_SIZE = 25
const COLUMNS = 8
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

const farmerName = (farmer) => farmer.full_name || `${farmer.first_name || ''} ${farmer.surname || ''}`.trim() || 'Unknown'

function leadChoices(clusters) {
  const choices = []
  const seen = new Set()
  for (const cluster of clusters) {
    if (!cluster.lead_member || seen.has(cluster.lead_member)) continue
    seen.add(cluster.lead_member)
    choices.push({
      id: String(cluster.lead_member),
      name: cluster.lead_farmer_name || cluster.name,
      cluster: cluster.name || '',
    })
  }
  choices.sort((left, right) => left.name.localeCompare(right.name))
  return choices
}

function groupsOf(farmers) {
  const groups = []
  const byKey = new Map()
  for (const farmer of farmers) {
    const key = farmer.lead_member
      ? `member:${farmer.lead_member}`
      : (farmer.lead_farmer_name ? `name:${farmer.lead_farmer_name}` : 'none')
    let group = byKey.get(key)
    if (!group) {
      group = {
        key,
        label: farmer.lead_farmer_name || 'No lead farmer',
        cluster: farmer.cluster_name || '',
        rows: [],
      }
      byKey.set(key, group)
      groups.push(group)
    }
    if (!group.cluster && farmer.cluster_name) group.cluster = farmer.cluster_name
    group.rows.push(farmer)
  }
  groups.sort((left, right) => {
    if (left.key === 'none') return 1
    if (right.key === 'none') return -1
    return left.label.localeCompare(right.label)
  })
  return groups
}

async function loadClusters() {
  const records = []
  let page = 1
  while (page <= 20) {
    const response = await apiClient.get('/clusters/', { params: { page } })
    records.push(...getListData(response.data))
    if (!response.data?.next) break
    page += 1
  }
  return records
}

function FarmersPage() {
  const { can, profile } = useAuth()
  const canCreate = can('farmers', 'create')
  const canEdit = can('farmers', 'edit')
  const leadFarmer = profile?.role === 'lead_farmer'
  const [farmers, setFarmers] = useState([])
  const [leads, setLeads] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [status, setStatus] = useState('')
  const [lead, setLead] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const hasInitializedSearch = useRef(false)

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const isFirstPage = currentPage <= 1
  const isLastPage = currentPage >= totalPages
  const groups = useMemo(() => groupsOf(farmers), [farmers])

  useEffect(() => {
    if (leadFarmer) return undefined
    let active = true
    loadClusters()
      .then((clusters) => {
        if (active) setLeads(leadChoices(clusters))
      })
      .catch(() => {
        if (active) setLeads([])
      })
    return () => { active = false }
  }, [leadFarmer])

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
        if (lead) params.lead_member = lead
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
  }, [appliedSearch, currentPage, lead, status])

  return (
    <div className="page-card">
      <div className="section-head">
        <div>
          <h3>Farmers</h3>
          <p>
            {leadFarmer
              ? `The farmers in ${profile?.cluster_name || 'your cluster'}. Register a farmer, then follow the registration until an administrator approves it.`
              : 'Farmers are grouped by the lead farmer of their cluster. Open a record to see farms, documents and history.'}
          </p>
        </div>
        <div className="page-actions">
          <TabSearch value={search} onChange={setSearch} placeholder="Filter farmers..." />
          {canCreate ? <Link className="primary-btn" to="/farmers/register"><Icon name="plus" />Register farmer</Link> : null}
        </div>
      </div>

      {leadFarmer ? null : (
        <div className="farmers-filters">
          <label className="form-field">
            Lead farmer
            <select
              value={lead}
              onChange={(event) => {
                setCurrentPage(1)
                setLead(event.target.value)
              }}
            >
              <option value="">All lead farmers</option>
              {leads.map((choice) => (
                <option key={choice.id} value={choice.id}>
                  {choice.cluster ? `${choice.name} · ${choice.cluster}` : choice.name}
                </option>
              ))}
              <option value="none">No lead farmer</option>
            </select>
          </label>
        </div>
      )}

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
                  <th>National ID</th>
                  <th>Province / District</th>
                  <th>Cluster</th>
                  <th>Lead farmer</th>
                  <th>Hectares</th>
                  <th>Registration</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => (
                  <GroupRows
                    key={group.key}
                    group={group}
                    canEdit={canEdit}
                    leadFarmer={leadFarmer}
                  />
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState icon="users" title="No farmers found">
              {status || appliedSearch || lead ? 'Change the filter or search.' : canCreate ? 'Register the first farmer to get started.' : 'Farmers appear here once they are registered.'}
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

function GroupRows({ group, canEdit, leadFarmer }) {
  return (
    <>
      <tr className="lead-group">
        <td colSpan={COLUMNS}>
          {group.label}
          {group.key !== 'none' && group.cluster ? <span>{group.cluster}</span> : null}
        </td>
      </tr>
      {group.rows.map((farmer) => {
        const name = farmerName(farmer)
        const [label, tone] = statusOf(farmer.verification_status)
        const registrationOpen = EDITABLE.includes(farmer.verification_status)
        const showPencil = canEdit && (!leadFarmer || registrationOpen)
        const place = [farmer.province_name, farmer.district_name].filter(Boolean).join(' · ')
        return (
          <tr key={farmer.id}>
            <td>{farmer.membership_number || '—'}</td>
            <td>
              <span className="farmer-row-name">
                <Link to={`/farmers/${farmer.id}`}>{name}</Link>
                <Link className="icon-btn" to={`/farmers/${farmer.id}`} aria-label={`View ${name}`} title="View details">
                  <Icon name="eye" />
                </Link>
                {showPencil ? (
                  <Link
                    className="icon-btn"
                    to={registrationOpen ? `/farmers/${farmer.id}/edit` : `/farmers/${farmer.id}#farms`}
                    aria-label={`Edit ${name}`}
                    title={registrationOpen ? 'Edit registration' : 'Edit farms'}
                  >
                    <Icon name="pencil" />
                  </Link>
                ) : null}
              </span>
            </td>
            <td>{farmer.national_id || '—'}</td>
            <td>{place || '—'}</td>
            <td>{farmer.cluster_name || '—'}</td>
            <td>{farmer.lead_farmer_name || '—'}</td>
            <td>{formatDisplay('farm_hectares', farmer.farm_hectares) ?? '—'}</td>
            <td>
              <Pill tone={tone}>{label}</Pill>
              {farmer.review_remarks && registrationOpen ? <small>{farmer.review_remarks}</small> : null}
            </td>
          </tr>
        )
      })}
    </>
  )
}

export default FarmersPage
