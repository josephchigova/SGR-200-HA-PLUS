import { useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import apiClient from '../api/client'

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
  if (status === 400 || status === 401) {
    return message || 'The email or password is incorrect.'
  }
  return 'The server could not complete sign-in. Try again in a moment.'
}

function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
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

      localStorage.setItem('sgr_access_token', access)
      localStorage.setItem('sgr_refresh_token', refresh)
      window.dispatchEvent(new Event('sgr-auth-changed'))
      navigate('/farmers')
    } catch (requestError) {
      setError(loginErrorMessage(requestError))
    } finally {
      submitting.current = false
      setLoading(false)
    }
  }

  return (
    <div className="login-content">
      <header className="login-brand">
        <span className="brand-mark">SGR</span>
        <h1>SGR 200HA+</h1>
        <p>Farmer &amp; Input Management System</p>
      </header>
      <section className="page-card login-card">
        <div className="section-head">
          <h3>SGR Login</h3>
        </div>

        {location.state?.message ? <div className="form-message">{location.state.message}</div> : null}

        <form onSubmit={handleSubmit}>
          <label>
            Email Address
            <input
              type="email"
              name="email"
              value={form.email}
              onChange={handleChange}
              placeholder="name@arda.gov.zw"
              required
            />
          </label>

          <label>
            Password
            <input
              type="password"
              name="password"
              value={form.password}
              onChange={handleChange}
              placeholder="Enter your password"
              required
            />
          </label>

          {error ? <div className="form-message error">{error}</div> : null}

          <div className="login-actions">
            <button type="submit" className="primary-btn" disabled={loading}>
              {loading ? 'Signing in...' : 'Login'}
            </button>
          </div>
          <div className="form-message">
            Need an account? <Link to="/register">Create one</Link>
          </div>
        </form>
      </section>
    </div>
  )
}

export default LoginPage
