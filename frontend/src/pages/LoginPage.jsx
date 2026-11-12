import { useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import apiClient from '../api/client'
import Icon from '../components/Icon'
import { storeTokens, takeSessionNotice } from '../session'
import AuthLayout from './AuthLayout'

function loginErrorMessage(requestError) {
  if (!requestError.response) {
    if (requestError.code === 'ECONNABORTED') {
      return 'The server took too long to respond. Wait a moment and try again. Your password was not rejected.'
    }
    return 'The server could not be reached. Check your connection and try again.'
  }
  const status = requestError.response.status
  const detail = requestError.response.data?.detail
  const message = typeof detail === 'string' ? detail : ''
  if (status === 429) return 'Too many sign-in attempts. Wait a minute and try again.'
  if (status === 400 || status === 401) {
    return message || 'The email or password is incorrect.'
  }
  return 'The server could not complete sign-in. Try again in a moment.'
}

function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [remember, setRemember] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [notice] = useState(() => location.state?.message || takeSessionNotice())
  const submitting = useRef(false)

  const handleChange = (event) => {
    const { name, value } = event.target
    setForm((previous) => ({ ...previous, [name]: value }))
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (submitting.current) return
    submitting.current = true
    setError('')
    setLoading(true)

    try {
      const response = await apiClient.post('/auth/login/', {
        email: form.email.trim(),
        password: form.password,
      }, { timeout: 60000 })

      const { access, refresh } = response.data || {}
      if (!access || !refresh) {
        setError('The server responded, but sign-in did not return a session. Try again.')
        return
      }

      storeTokens({ access, refresh, remember })
      const target = typeof location.state?.from === 'string' && location.state.from.startsWith('/') ? location.state.from : '/dashboard'
      navigate(target, { replace: true })
    } catch (requestError) {
      setError(loginErrorMessage(requestError))
    } finally {
      submitting.current = false
      setLoading(false)
    }
  }

  return (
    <AuthLayout>
      <div className="auth-card">
        <h2>Sign in to SGR</h2>
        <p>Use your staff account to open the operations workspace.</p>

        {notice ? <div className="form-message" role="status">{notice}</div> : null}

        <form onSubmit={handleSubmit} noValidate={false}>
          <label>
            Email address
            <input
              type="email"
              name="email"
              autoComplete="username"
              value={form.email}
              onChange={handleChange}
              placeholder="name@arda.gov.zw"
              required
            />
          </label>

          <div className="form-field">
            <div className="label-row">
              <label htmlFor="login-password">Password</label>
              <Link to="/forgot-password">Forgot password?</Link>
            </div>
            <div className="password-field">
              <input
                id="login-password"
                type={showPassword ? 'text' : 'password'}
                name="password"
                autoComplete="current-password"
                value={form.password}
                onChange={handleChange}
                placeholder="Enter your password"
                required
              />
              <button type="button" className="icon-btn" aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} onClick={() => setShowPassword((value) => !value)}>
                <Icon name={showPassword ? 'eyeOff' : 'eye'} />
              </button>
            </div>
          </div>

          <label className="check-row">
            <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
            Keep me signed in on this device
          </label>

          {error ? <div className="form-message error" role="alert">{error}</div> : null}

          <button type="submit" className="primary-btn block" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <div className="auth-links">
          Need an account? <Link to="/register">Request access</Link>
        </div>
      </div>
    </AuthLayout>
  )
}

export default LoginPage
