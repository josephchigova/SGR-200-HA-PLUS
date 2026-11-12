import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import apiClient from '../api/client'
import { errorMessage } from '../components/ui'
import AuthLayout from './AuthLayout'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      const response = await apiClient.post('/auth/password-reset/', { email: email.trim() })
      setSent(response.data?.detail || 'If that email belongs to an active account, a reset link has been sent.')
    } catch (requestError) {
      setError(requestError.response?.status === 429 ? 'Too many requests. Wait a minute and try again.' : errorMessage(requestError, 'The reset link could not be requested.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout back={{ to: '/login', label: 'Back to sign in' }}>
      <div className="auth-card">
        <h2>Reset your password</h2>
        <p>Enter your account email. We will send a link for choosing a new password.</p>
        {sent ? (
          <>
            <div className="form-message success" role="status">{sent}</div>
            <div className="auth-links">No email after a few minutes? Ask your administrator to reset the password for you.</div>
          </>
        ) : (
          <form onSubmit={submit}>
            <label>
              Email address
              <input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required />
            </label>
            {error ? <div className="form-message error" role="alert">{error}</div> : null}
            <button type="submit" className="primary-btn block" disabled={loading}>{loading ? 'Sending…' : 'Send reset link'}</button>
          </form>
        )}
      </div>
    </AuthLayout>
  )
}

export function ResetPasswordPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const uid = params.get('uid') || ''
  const token = params.get('token') || ''

  const submit = async (event) => {
    event.preventDefault()
    if (password !== confirm) {
      setError('The two passwords do not match.')
      return
    }
    setError('')
    setLoading(true)
    try {
      const response = await apiClient.post('/auth/password-reset/confirm/', { uid, token, new_password: password })
      navigate('/login', { state: { message: response.data?.detail || 'Your password has been reset.' } })
    } catch (requestError) {
      setError(errorMessage(requestError, 'The password could not be reset.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout back={{ to: '/login', label: 'Back to sign in' }}>
      <div className="auth-card">
        <h2>Choose a new password</h2>
        {!uid || !token ? (
          <>
            <div className="form-message error" role="alert">This reset link is incomplete. Request a new one.</div>
            <div className="auth-links"><Link to="/forgot-password">Request a new link</Link></div>
          </>
        ) : (
          <form onSubmit={submit}>
            <label>
              New password
              <input type="password" autoComplete="new-password" minLength="8" value={password} onChange={(event) => setPassword(event.target.value)} required />
              <span className="field-hint">At least 8 characters. Avoid common words and your own name.</span>
            </label>
            <label>
              Repeat the new password
              <input type="password" autoComplete="new-password" minLength="8" value={confirm} onChange={(event) => setConfirm(event.target.value)} required />
            </label>
            {error ? <div className="form-message error" role="alert">{error}</div> : null}
            <button type="submit" className="primary-btn block" disabled={loading}>{loading ? 'Saving…' : 'Save new password'}</button>
          </form>
        )}
      </div>
    </AuthLayout>
  )
}
