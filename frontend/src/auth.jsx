import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import apiClient from './api/client'
import { isSignedIn } from './session'

// Outside a provider (unit tests of a single page) every action is allowed. Inside the
// app the provider answers from the permission matrix the server sends with the profile.
// The server enforces the same matrix on every request, so this only decides what to show.
const AuthContext = createContext({
  profile: null,
  loading: false,
  error: '',
  can: () => true,
  reload: () => {},
})

export function AuthProvider({ children }) {
  const [signedIn, setSignedIn] = useState(isSignedIn)
  // The result of the latest profile request, tagged with the request it answers.
  const [result, setResult] = useState({ key: '', profile: null, error: '' })
  const [token, setToken] = useState(0)
  const requestKey = signedIn ? `in:${token}` : 'out'

  useEffect(() => {
    const sync = () => {
      const now = isSignedIn()
      // Signing out drops the old profile, so the next user never sees its permissions.
      if (!now) setResult({ key: '', profile: null, error: '' })
      setSignedIn(now)
    }
    window.addEventListener('storage', sync)
    window.addEventListener('sgr-auth-changed', sync)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener('sgr-auth-changed', sync)
    }
  }, [])

  useEffect(() => {
    if (!signedIn) return undefined
    let cancelled = false
    apiClient.get('/auth/me/').then((response) => {
      if (!cancelled) setResult({ key: requestKey, profile: response.data, error: '' })
    }).catch((requestError) => {
      if (cancelled) return
      setResult({
        key: requestKey,
        profile: null,
        error: requestError.response ? 'Your account details could not be loaded.' : 'The server could not be reached.',
      })
    })
    return () => { cancelled = true }
  }, [signedIn, requestKey])

  // A reload keeps showing the last profile until the new one arrives.
  const profile = signedIn ? result.profile : null
  const loading = signedIn && result.key !== requestKey && !result.profile
  const error = signedIn && result.key === requestKey ? result.error : ''

  const can = useCallback((module, action = 'view') => Boolean(profile?.permissions?.[module]?.[action]), [profile])
  const reload = useCallback(() => setToken((value) => value + 1), [])

  const value = useMemo(() => ({ profile, loading, error, can, reload, signedIn }), [profile, loading, error, can, reload, signedIn])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  return useContext(AuthContext)
}
