import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import apiClient from '../api/client'
import { errorMessage } from '../components/ui'
import AuthLayout from './AuthLayout'

const FIELDS = [
  ['first_name', 'First name', 'text', 'given-name'],
  ['last_name', 'Last name', 'text', 'family-name'],
  ['email', 'Email address', 'email', 'email'],
  ['phone_number', 'Phone number (optional)', 'tel', 'tel'],
]

function RegisterPage() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ email: '', first_name: '', last_name: '', phone_number: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleChange = (event) => {
    const { name, value } = event.target
    setForm((previous) => ({ ...previous, [name]: value }))
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      await apiClient.post('/auth/register/', { ...form, username: form.email })
      navigate('/login', { state: { message: 'Your request was received. An administrator must approve the account before you can sign in.' } })
    } catch (requestError) {
      setError(errorMessage(requestError, 'The account request could not be sent.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout back={{ to: '/login', label: 'Back to sign in' }}>
      <div className="auth-card">
        <h2>Request access</h2>
        <p>An administrator reviews each request, assigns a role and activates the account.</p>
        <form onSubmit={handleSubmit}>
          {FIELDS.map(([name, label, type, autoComplete]) => (
            <label key={name}>
              {label}
              <input type={type} name={name} autoComplete={autoComplete} value={form[name]} onChange={handleChange} required={name !== 'phone_number'} />
            </label>
          ))}
          <label>
            Password
            <input type="password" name="password" autoComplete="new-password" value={form.password} onChange={handleChange} minLength="8" required />
            <span className="field-hint">At least 8 characters. Avoid common words and your own name.</span>
          </label>
          {error ? <div className="form-message error" role="alert">{error}</div> : null}
          <button type="submit" className="primary-btn block" disabled={loading}>{loading ? 'Sending…' : 'Send request'}</button>
        </form>
        <div className="auth-links">Already approved? <Link to="/login">Sign in</Link></div>
      </div>
    </AuthLayout>
  )
}

export default RegisterPage
