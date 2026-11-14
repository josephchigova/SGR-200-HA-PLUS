import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

import { formatDraftTime } from '../drafts'
import Icon from './Icon'

export function PageHead({ title, subtitle, children }) {
  return (
    <header className="page-head">
      <div>
        <h2>{title}</h2>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {children ? <div className="page-actions no-print">{children}</div> : null}
    </header>
  )
}

export function EmptyState({ icon = 'database', title, children }) {
  return (
    <div className="empty-state">
      <Icon name={icon} />
      <strong>{title}</strong>
      {children ? <span>{children}</span> : null}
    </div>
  )
}

export function Skeleton({ kind = 'block', count = 1 }) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => <div key={index} className={`skeleton ${kind}`} aria-hidden="true" />)}
      <span className="sr-only">Loading</span>
    </>
  )
}

export function StatCard({ label, value, hint, icon, tone = '' }) {
  return (
    <article className={`stat-card ${tone}`.trim()}>
      <div className="stat-top">
        <span>{label}</span>
        {icon ? <i className="stat-icon"><Icon name={icon} /></i> : null}
      </div>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </article>
  )
}

export function Pill({ tone = '', children }) {
  return <span className={`pill ${tone}`.trim()}>{children}</span>
}

export function Modal({ title, subtitle, wide = false, onClose, children, footer }) {
  const box = useRef(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    const previous = document.activeElement
    box.current?.focus()
    const onKey = (event) => {
      if (event.key === 'Escape') onCloseRef.current()
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    document.body.classList.add('has-modal')
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      document.body.classList.remove('has-modal')
      if (previous && typeof previous.focus === 'function') previous.focus()
    }
  }, [])

  // Rendered on the body so the dialog sits above the app and prints on its own.
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className={wide ? 'modal wide' : 'modal'} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={box}>
        <header className="modal-head">
          <div>
            <h3>{title}</h3>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          <button type="button" className="icon-btn no-print" aria-label="Close" onClick={onClose}><Icon name="close" /></button>
        </header>
        <div className="modal-body">{children}</div>
        {footer ? <footer className="modal-foot no-print">{footer}</footer> : null}
      </section>
    </div>,
    document.body,
  )
}

export function AccessDenied({ title = 'You do not have access to this page' }) {
  return (
    <div className="card">
      <EmptyState icon="lock" title={title}>
        Your role does not include this part of the system. Ask an administrator if you need it.
      </EmptyState>
    </div>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function errorMessage(requestError, fallback) {
  const data = requestError?.response?.data
  if (!requestError?.response) return 'The server could not be reached. Check your connection and try again.'
  if (requestError.response.status === 403) return 'Your role is not allowed to do this.'
  if (typeof data?.detail === 'string') return data.detail
  if (data && typeof data === 'object') {
    const parts = Object.entries(data).map(([field, messages]) => {
      const text = Array.isArray(messages) ? messages.join(' ') : String(messages)
      return field === 'non_field_errors' ? text : `${field.replace(/_/g, ' ')}: ${text}`
    })
    if (parts.length) return parts.join(' ')
  }
  return fallback
}

// Shows that a saved draft was put back into the form, with a way to throw it away.
export function DraftNotice({ draft, children }) {
  if (!draft?.restoredAt) return null
  return (
    <div className="form-message draft-notice" role="status">
      <Icon name="history" />
      <span>{children || 'Your unfinished draft was restored'}{formatDraftTime(draft.restoredAt) ? ` (saved ${formatDraftTime(draft.restoredAt)})` : ''}.</span>
      <button type="button" className="ghost-btn small" onClick={draft.discard}>Discard draft</button>
    </div>
  )
}

// A quiet line under a form saying the draft is kept.
export function DraftStatus({ draft }) {
  if (!draft?.savedAt) return null
  return <small className="draft-status">Draft saved {formatDraftTime(draft.savedAt)}</small>
}
