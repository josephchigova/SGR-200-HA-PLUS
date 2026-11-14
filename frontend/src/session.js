// Sign-in session storage.
//
// Tokens stay in localStorage, where the rest of the app already reads them. When the
// user does not tick "Keep me signed in", a marker in sessionStorage ties the tokens to
// the open browser session: after the browser is closed the marker is gone and the
// tokens are dropped on the next visit.

const ACCESS = 'sgr_access_token'
const REFRESH = 'sgr_refresh_token'
const REMEMBER = 'sgr_remember'
const SESSION_MARK = 'sgr_session_open'
const NOTICE = 'sgr_session_notice'

export const IDLE_LIMIT_MS = 30 * 60 * 1000

export function getRefreshToken() {
  return localStorage.getItem(REFRESH)
}

export function isSignedIn() {
  return Boolean(localStorage.getItem(ACCESS))
}

export function storeTokens({ access, refresh, remember }) {
  if (access) localStorage.setItem(ACCESS, access)
  if (refresh) localStorage.setItem(REFRESH, refresh)
  if (remember !== undefined) localStorage.setItem(REMEMBER, remember ? '1' : '0')
  try {
    sessionStorage.setItem(SESSION_MARK, '1')
  } catch { /* Storage can be blocked. The session then behaves as remembered. */ }
  window.dispatchEvent(new Event('sgr-auth-changed'))
}

// Drafts of unfinished forms (see drafts.js). On sign-out, drafts already kept on the
// server leave this browser; drafts that never reached the server stay, so nothing is lost.
function forgetSyncedDrafts() {
  try {
    for (let index = localStorage.length - 1; index >= 0; index -= 1) {
      const name = localStorage.key(index)
      if (!name?.startsWith('sgr_draft:')) continue
      try {
        if (JSON.parse(localStorage.getItem(name))?.synced) localStorage.removeItem(name)
      } catch { localStorage.removeItem(name) }
    }
  } catch { /* ignore */ }
}

export function clearSession(reason = '') {
  const hadSession = isSignedIn()
  forgetSyncedDrafts()
  localStorage.removeItem(ACCESS)
  localStorage.removeItem(REFRESH)
  try {
    sessionStorage.removeItem(SESSION_MARK)
    if (reason && hadSession) sessionStorage.setItem(NOTICE, reason)
  } catch { /* ignore */ }
  window.dispatchEvent(new Event('sgr-auth-changed'))
}

export function takeSessionNotice() {
  try {
    const reason = sessionStorage.getItem(NOTICE)
    sessionStorage.removeItem(NOTICE)
    if (reason === 'expired') return 'Your session has ended. Sign in again to continue.'
    if (reason === 'idle') return 'You were signed out after 30 minutes without activity.'
  } catch { /* ignore */ }
  return ''
}

// Called once when the app starts.
export function dropSessionIfBrowserWasClosed() {
  try {
    if (localStorage.getItem(REMEMBER) === '0' && isSignedIn() && !sessionStorage.getItem(SESSION_MARK)) {
      localStorage.removeItem(ACCESS)
      localStorage.removeItem(REFRESH)
    }
  } catch { /* ignore */ }
}
