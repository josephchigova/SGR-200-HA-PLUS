// Drafts of unfinished forms.
//
// useFormDraft keeps a copy of a form while the user types, so a refresh, a closed tab
// or a click on another page loses nothing. The copy is written to the browser at once
// and to the server a moment later, so it also follows the user to another device.
// Opening the form again restores the newest copy. Saving the form clears it.
//
// Passwords and similar secrets are never part of a draft.

import { useCallback, useEffect, useRef, useState } from 'react'

import apiClient from './api/client'
import { useAuth } from './auth'

const PREFIX = 'sgr_draft:'
const SERVER_DELAY_MS = 1200
const SECRET = /password|secret|token/i

export function stripSecrets(value) {
  if (Array.isArray(value)) return value.map(stripSecrets)
  if (value && typeof value === 'object' && !(value instanceof Date)) {
    const result = {}
    for (const [key, item] of Object.entries(value)) {
      if (SECRET.test(key)) continue
      // Files cannot be kept in a draft. They are picked again before saving.
      if (typeof File !== 'undefined' && item instanceof File) continue
      result[key] = stripSecrets(item)
    }
    return result
  }
  return value
}

function cleaned(value, exclude) {
  const data = stripSecrets(value ?? {})
  if (exclude?.length && data && typeof data === 'object' && !Array.isArray(data)) {
    for (const name of exclude) delete data[name]
  }
  return data
}

const storageKey = (userId, key) => `${PREFIX}${userId}:${key}`

function readLocal(name) {
  try {
    const raw = localStorage.getItem(name)
    if (!raw) return null
    const entry = JSON.parse(raw)
    return entry && typeof entry === 'object' && 'data' in entry ? entry : null
  } catch {
    return null
  }
}

function writeLocal(name, entry) {
  try {
    localStorage.setItem(name, JSON.stringify(entry))
  } catch { /* Storage full or blocked: the server copy still works. */ }
}

function removeLocal(name) {
  try {
    localStorage.removeItem(name)
  } catch { /* ignore */ }
}

export function formatDraftTime(savedAt) {
  if (!savedAt) return ''
  const date = new Date(savedAt)
  if (Number.isNaN(date.getTime())) return ''
  const sameDay = date.toDateString() === new Date().toDateString()
  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

/**
 * Keep a draft of a form.
 *
 * key        names the form, for example "register:new" or "farmer:12:changes".
 * value      the form state to keep (anything JSON can hold).
 * onRestore  receives a saved draft, or the starting values when the draft is discarded.
 * enabled    false until the form holds its starting values (for example while an
 *            edit form is still loading the record). Those values are the baseline:
 *            a form that matches its baseline has no draft.
 * exclude    top-level names never kept in the draft.
 *
 * Returns { restoredAt, savedAt, discard, clear }. Call clear() after a successful save.
 */
export function useFormDraft({ key, value, onRestore, enabled = true, exclude }) {
  const { profile } = useAuth()
  const userId = profile?.id
  const active = Boolean(enabled && userId && key)
  const name = active ? storageKey(userId, key) : ''

  const [restoredAt, setRestoredAt] = useState(null)
  const [savedAt, setSavedAt] = useState(null)
  const state = useRef({ name: '', baseline: null, baselineData: null, last: null, stale: null, dirty: false, timer: null, pending: null })
  const restoreRef = useRef(onRestore)
  const excludeRef = useRef(exclude)
  useEffect(() => {
    restoreRef.current = onRestore
    excludeRef.current = exclude
  })

  const serverSave = useCallback((draftKey, data, localName) => {
    apiClient.put('/drafts/', { key: draftKey, data })
      .then(() => {
        const entry = readLocal(localName)
        if (entry && JSON.stringify(entry.data) === JSON.stringify(data)) writeLocal(localName, { ...entry, synced: true })
      })
      .catch(() => { /* The browser copy stays; the next change tries again. */ })
  }, [])

  const flush = useCallback(() => {
    const current = state.current
    if (current.timer) clearTimeout(current.timer)
    current.timer = null
    const pending = current.pending
    current.pending = null
    if (!pending) return
    if (pending.remove) apiClient.delete('/drafts/', { params: { key: pending.key } }).catch(() => {})
    else serverSave(pending.key, pending.data, pending.name)
  }, [serverSave])

  // Take the baseline and restore a saved draft when the form becomes ready.
  useEffect(() => {
    if (!active) return undefined
    const current = state.current
    const data = cleaned(value, excludeRef.current)
    const baseline = JSON.stringify(data)
    current.name = name
    current.baseline = baseline
    current.baselineData = data
    current.last = baseline
    current.stale = null
    current.dirty = false
    let cancelled = false

    const restore = (draftData, when) => {
      const serialized = JSON.stringify(draftData)
      if (serialized === baseline) return
      // Until the restored values reach the form, the form still shows the values it
      // had before. Those are not a change by the user.
      current.stale = JSON.stringify(cleaned(value, excludeRef.current))
      current.last = serialized
      restoreRef.current?.(draftData)
      setRestoredAt(when)
      setSavedAt(when)
    }

    const local = readLocal(name)
    if (local) restore(local.data, local.savedAt)
    const draftKey = key
    apiClient.get('/drafts/', { params: { key: draftKey } })
      .then((response) => {
        if (cancelled || current.dirty || !response.data?.data) return
        const serverTime = Date.parse(response.data.updated_at)
        const localTime = local ? Date.parse(local.savedAt) : 0
        if (serverTime > localTime + 1000) {
          writeLocal(name, { data: response.data.data, savedAt: response.data.updated_at, synced: true })
          restore(response.data.data, response.data.updated_at)
        } else if (local && !local.synced) {
          serverSave(draftKey, local.data, name)
        }
      })
      .catch(() => {
        if (!cancelled && local && !local.synced) serverSave(draftKey, local.data, name)
      })

    return () => {
      cancelled = true
      flush()
      setRestoredAt(null)
      setSavedAt(null)
    }
    // The baseline is taken once per form; later value changes are drafts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, name])

  // Save every change.
  useEffect(() => {
    if (!active) return
    const current = state.current
    if (current.name !== name) return
    const data = cleaned(value, excludeRef.current)
    const serialized = JSON.stringify(data)
    if (serialized === current.last) return
    if (current.stale !== null) {
      if (serialized === current.stale) return
      current.stale = null
    }
    current.last = serialized
    current.dirty = true
    if (current.timer) clearTimeout(current.timer)
    if (serialized === current.baseline) {
      removeLocal(name)
      setSavedAt(null)
      current.pending = { key, remove: true }
    } else {
      const now = new Date().toISOString()
      writeLocal(name, { data, savedAt: now, synced: false })
      setSavedAt(now)
      current.pending = { key, data, name }
    }
    current.timer = setTimeout(flush, SERVER_DELAY_MS)
  }, [active, name, key, value, flush])

  // Send the last change before the page goes away.
  useEffect(() => {
    if (!active) return undefined
    const leave = () => flush()
    window.addEventListener('pagehide', leave)
    return () => window.removeEventListener('pagehide', leave)
  }, [active, flush])

  // The form was saved: drop the draft. The form's current values become the baseline.
  const clear = useCallback((nextValue) => {
    const current = state.current
    if (current.timer) clearTimeout(current.timer)
    current.timer = null
    current.pending = null
    if (current.name) removeLocal(current.name)
    if (key && userId) apiClient.delete('/drafts/', { params: { key } }).catch(() => {})
    const data = cleaned(nextValue === undefined ? value : nextValue, excludeRef.current)
    current.baseline = JSON.stringify(data)
    current.baselineData = data
    current.last = current.baseline
    current.stale = null
    current.dirty = false
    setRestoredAt(null)
    setSavedAt(null)
  }, [key, userId, value])

  // Throw the draft away and go back to the starting values.
  const discard = useCallback(() => {
    const current = state.current
    const startingValues = current.baselineData
    clear(startingValues)
    if (startingValues !== null) restoreRef.current?.(JSON.parse(JSON.stringify(startingValues)))
  }, [clear])

  return { restoredAt, savedAt, discard, clear }
}
