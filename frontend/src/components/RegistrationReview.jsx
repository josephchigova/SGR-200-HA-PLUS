import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../api/client'
import { openDocument, saveDocument } from '../documents'
import { statusOf } from '../registration'
import Icon from './Icon'
import { EmptyState, Modal, Pill, Skeleton, errorMessage } from './ui'

const EVENT_TONES = { APPROVED: 'good', DOCUMENT_VERIFIED: 'good', REJECTED: 'bad', DOCUMENT_REJECTED: 'bad', CORRECTIONS_REQUESTED: 'info' }
const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])
const when = (value) => (value ? new Date(value).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '—')

export function DocumentList({ documents, canReview = false, onReview, busy = '' }) {
  const [rejecting, setRejecting] = useState(null)
  const [reason, setReason] = useState('')
  if (!documents.length) return <EmptyState icon="clipboard" title="No documents uploaded">The registration has no KYC files yet.</EmptyState>
  return (
    <div>
      {documents.map((document) => {
        const tone = document.review_status === 'VERIFIED' ? 'good' : document.review_status === 'REJECTED' ? 'bad' : 'warn'
        const label = document.review_status === 'VERIFIED' ? 'Verified' : document.review_status === 'REJECTED' ? 'Rejected' : 'To check'
        return (
          <div className="doc-row" key={document.id}>
            <div>
              <strong>{document.label}</strong> {document.required ? <Pill>Required</Pill> : null} <Pill tone={tone}>{label}</Pill>
              <small>{document.file_name} · uploaded {when(document.upload_date)}{document.uploaded_by_name ? ` by ${document.uploaded_by_name}` : ''}</small>
              {document.review_remarks ? <small>Reviewer: {document.review_remarks}</small> : null}
              {rejecting === document.id ? (
                <form
                  className="form-actions"
                  style={{ marginTop: 8 }}
                  onSubmit={(event) => {
                    event.preventDefault()
                    onReview(document, 'REJECTED', reason)
                    setRejecting(null)
                    setReason('')
                  }}
                >
                  <input aria-label={`Reason for rejecting ${document.label}`} placeholder="What is wrong with this document?" required value={reason} onChange={(event) => setReason(event.target.value)} style={{ flex: '1 1 220px' }} />
                  <button type="submit" className="ghost-btn small danger">Reject document</button>
                  <button type="button" className="ghost-btn small" onClick={() => setRejecting(null)}>Cancel</button>
                </form>
              ) : null}
            </div>
            <div className="table-actions">
              <button type="button" className="ghost-btn small" onClick={() => openDocument(document)}><Icon name="eye" />Preview</button>
              <button type="button" className="ghost-btn small" aria-label={`Download ${document.label}`} onClick={() => saveDocument(document)}><Icon name="download" /></button>
              {canReview ? (
                <>
                  <button type="button" className="primary-btn small" disabled={busy === document.id || document.review_status === 'VERIFIED'} onClick={() => onReview(document, 'VERIFIED', '')}><Icon name="check" />Verify</button>
                  <button type="button" className="ghost-btn small danger" disabled={busy === document.id} onClick={() => { setRejecting(document.id); setReason('') }}>Reject</button>
                </>
              ) : null}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function HistoryList({ events }) {
  if (!events.length) return <p className="card-sub">No history is recorded yet.</p>
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.id} className={EVENT_TONES[event.action] || ''}>
          <span>
            <strong>{event.label}</strong>
            {event.remarks ? ` · ${event.remarks}` : ''}
            <small>{event.actor} · {when(event.created_at)}</small>
          </span>
        </li>
      ))}
    </ol>
  )
}

// Loads one registration with its documents and history.
// eslint-disable-next-line react-refresh/only-export-components
export function useRegistration(farmerId) {
  const [state, setState] = useState({ farmer: null, documents: [], events: [], loading: true, error: '' })
  const [token, setToken] = useState(0)
  useEffect(() => {
    if (!farmerId) return undefined
    let active = true
    Promise.all([
      apiClient.get(`/farmers/${farmerId}/`),
      apiClient.get(`/farmer-documents/?farmer=${farmerId}&page_size=100`),
      apiClient.get(`/farmers/${farmerId}/history/`),
    ]).then(([farmer, documents, events]) => {
      if (active) setState({ farmer: farmer.data, documents: listOf(documents.data), events: listOf(events.data), loading: false, error: '' })
    }).catch((requestError) => {
      if (active) setState((current) => ({ ...current, loading: false, error: errorMessage(requestError, 'The registration could not be loaded.') }))
    })
    return () => { active = false }
  }, [farmerId, token])
  const reload = useCallback(() => setToken((value) => value + 1), [])
  return { ...state, reload }
}

function RegistrationReview({ farmerId, canDecide, onClose, onDecided }) {
  const { farmer, documents, events, loading, error, reload } = useRegistration(farmerId)
  const [remarks, setRemarks] = useState('')
  const [busy, setBusy] = useState('')
  const [problem, setProblem] = useState('')

  const reviewDocument = async (document, decision, reason) => {
    setBusy(document.id)
    setProblem('')
    try {
      await apiClient.post(`/farmer-documents/${document.id}/review/`, { review_status: decision, remarks: reason })
      reload()
    } catch (requestError) {
      setProblem(errorMessage(requestError, 'The document could not be updated.'))
    } finally {
      setBusy('')
    }
  }

  const decide = async (status) => {
    if (status !== 'VERIFIED' && !remarks.trim()) {
      setProblem(status === 'REJECTED' ? 'Give the reason for rejecting this registration.' : 'Say what must be corrected.')
      return
    }
    setBusy(status)
    setProblem('')
    try {
      await apiClient.post(`/farmers/${farmerId}/verify/`, { verification_status: status, remarks: remarks.trim(), rejection_reason: remarks.trim() })
      onDecided(status)
    } catch (requestError) {
      setProblem(errorMessage(requestError, 'The decision could not be saved.'))
    } finally {
      setBusy('')
    }
  }

  const farm = farmer?.primary_farm
  const [label, tone] = statusOf(farmer?.verification_status)
  const unchecked = documents.filter((document) => document.review_status !== 'VERIFIED').length
  const decidable = farmer && ['SUBMITTED', 'UNDER_REVIEW', 'PENDING', 'DRAFT'].includes(farmer.verification_status) && !(farmer.verification_status === 'DRAFT' && farmer.registered_by)

  return (
    <Modal
      wide
      title={farmer ? farmer.full_name : 'Registration'}
      subtitle={farmer ? `${farmer.membership_number || 'No membership number'} · registered ${farmer.registered_by_name ? `by ${farmer.registered_by_name}` : 'by an officer'}${farmer.submitted_at ? ` · submitted ${when(farmer.submitted_at)}` : ''}` : ''}
      onClose={onClose}
      footer={canDecide && decidable ? (
        <>
          <button type="button" className="ghost-btn danger" disabled={Boolean(busy)} onClick={() => decide('REJECTED')}>Reject registration</button>
          <button type="button" className="ghost-btn" disabled={Boolean(busy)} onClick={() => decide('CORRECTIONS_REQUESTED')}>Request corrections</button>
          <button type="button" className="primary-btn" disabled={Boolean(busy) || unchecked > 0} title={unchecked ? 'Verify every document first' : undefined} onClick={() => decide('VERIFIED')}><Icon name="check" />Approve registration</button>
        </>
      ) : <button type="button" className="ghost-btn" onClick={onClose}>Close</button>}
    >
      {loading ? <Skeleton kind="block" /> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {farmer ? (
        <>
          <div className="table-actions" style={{ alignItems: 'center' }}>
            <Pill tone={tone}>{label}</Pill>
            <Pill tone={farmer.membership_status === 'ACTIVE' ? 'good' : ''}>{farmer.membership_status === 'ACTIVE' ? 'Active member' : 'Not yet a member'}</Pill>
            <Link to={`/farmers/${farmer.id}`} onClick={onClose}>Open full profile</Link>
          </div>
          {farmer.review_remarks ? <div className="form-message warning"><strong>Latest remarks:</strong> {farmer.review_remarks}</div> : null}
          <div className="split">
            <section className="review-block">
              <header><h4>Farmer</h4></header>
              <dl>
                <div><dt>National ID</dt><dd>{farmer.national_id || '—'}</dd></div>
                <div><dt>Phone</dt><dd>{farmer.phone_primary || '—'}</dd></div>
                <div><dt>Email</dt><dd>{farmer.email || '—'}</dd></div>
                <div><dt>Cluster</dt><dd>{farmer.cluster_name || 'No cluster'}</dd></div>
              </dl>
            </section>
            <section className="review-block">
              <header><h4>Farm</h4></header>
              <dl>
                <div><dt>Farm name</dt><dd>{farm?.farm_name || '—'}</dd></div>
                <div><dt>Location</dt><dd>{[farmer.province_name, farmer.district_name, farmer.ward_name].filter(Boolean).join(' · ') || '—'}</dd></div>
                <div><dt>Farm size</dt><dd>{farm ? `${Number(farm.total_hectares)} ha` : '—'}</dd></div>
                <div><dt>Arable</dt><dd>{farm ? `${Number(farm.arable_hectares)} ha (${Number(farm.irrigated_hectares)} ha irrigated)` : '—'}</dd></div>
                <div><dt>Coordinates</dt><dd>{farm?.latitude ? `${farm.latitude}, ${farm.longitude}` : 'Not recorded'}</dd></div>
              </dl>
            </section>
          </div>
          <section>
            <h4 className="group-title">KYC documents</h4>
            {farmer.kyc_upload_required === false && !documents.length
              ? <p className="card-sub">An administrator registered this farmer and checked the KYC documents in person. No files were uploaded.</p>
              : <DocumentList documents={documents} canReview={canDecide && decidable} onReview={reviewDocument} busy={busy} />}
          </section>
          {canDecide && decidable ? (
            <label className="form-field">
              Remarks for the lead farmer
              <textarea value={remarks} onChange={(event) => setRemarks(event.target.value)} placeholder="Required when rejecting or requesting corrections. Shown to the person who registered the farmer." />
              {unchecked ? <span className="field-hint">{unchecked} document{unchecked === 1 ? '' : 's'} still to verify before approval.</span> : null}
            </label>
          ) : null}
          {problem ? <div className="form-message error" role="alert">{problem}</div> : null}
          <section>
            <h4 className="group-title">Registration history</h4>
            <HistoryList events={events} />
          </section>
        </>
      ) : null}
    </Modal>
  )
}

export default RegistrationReview
