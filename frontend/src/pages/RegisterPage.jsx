import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import apiClient from '../api/client'

function RegisterPage() {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    email: '',
    username: '',
    first_name: '',
    last_name: '',
    phone_number: '',
    password: '',
  })
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
      await apiClient.post('/auth/register/', form)
      navigate('/login', { state: { message: 'Registration complete. Sign in to continue.' } })
    } catch (requestError) {
      const details = requestError.response?.data
      setError(details ? Object.values(details).flat().join(' ') : 'Registration failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-card login-card">
      <div className="section-head">
        <h3>Create ARDA Account</h3>
      </div>

      <form onSubmit={handleSubmit}>
        {['first_name', 'last_name', 'username', 'email', 'phone_number'].map((field) => (
          <label key={field}>
            {field.replace('_', ' ')}
            <input
              type={field === 'email' ? 'email' : 'text'}
              name={field}
              value={form[field]}
              onChange={handleChange}
              required={field !== 'phone_number'}
            />
          </label>
        ))}
        <label>
          Password
          <input type="password" name="password" value={form.password} onChange={handleChange} minLength="8" required />
        </label>

        {error ? <div className="form-message error">{error}</div> : null}
        <div className="login-actions">
          <button type="submit" className="primary-btn" disabled={loading}>
            {loading ? 'Creating account...' : 'Create account'}
          </button>
        </div>
        <div className="form-message">
          Already registered? <Link to="/login">Sign in</Link>
        </div>
      </form>
    </div>
  )
}

export default RegisterPage
