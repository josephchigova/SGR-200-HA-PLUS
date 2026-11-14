import { useState } from 'react'

import apiClient from '../api/client'
import { useAuth } from '../auth'
import { DraftNotice, PageHead, errorMessage } from '../components/ui'
import { useFormDraft } from '../drafts'
import { useTheme } from '../theme'

function AccountPage() {
  const { profile, reload } = useAuth()
  const { theme, setTheme } = useTheme()
  const [edited, setEdited] = useState(null)
  const [passwords, setPasswords] = useState({ current_password: '', new_password: '', confirm: '' })
  const [detailState, setDetailState] = useState({ saving: false, message: '', error: '' })
  const [passwordState, setPasswordState] = useState({ saving: false, message: '', error: '' })
  // Until the user types, the form shows the saved profile.
  const details = edited || { first_name: profile?.first_name || '', last_name: profile?.last_name || '', phone_number: profile?.phone_number || '' }
  const setDetails = setEdited
  // Passwords are never drafted; the contact details are.
  const detailsDraft = useFormDraft({ key: 'account:details', value: details, enabled: Boolean(profile), onRestore: (data) => setEdited((current) => ({ ...(current || details), ...data })) })

  const saveDetails = async (event) => {
    event.preventDefault()
    setDetailState({ saving: true, message: '', error: '' })
    try {
      await apiClient.patch('/auth/me/', details)
      detailsDraft.clear(details)
      reload()
      setDetailState({ saving: false, message: 'Your details were saved.', error: '' })
    } catch (requestError) {
      setDetailState({ saving: false, message: '', error: errorMessage(requestError, 'Your details could not be saved.') })
    }
  }

  const savePassword = async (event) => {
    event.preventDefault()
    if (passwords.new_password !== passwords.confirm) {
      setPasswordState({ saving: false, message: '', error: 'The two new passwords do not match.' })
      return
    }
    setPasswordState({ saving: true, message: '', error: '' })
    try {
      await apiClient.post('/auth/change-password/', { current_password: passwords.current_password, new_password: passwords.new_password })
      setPasswords({ current_password: '', new_password: '', confirm: '' })
      reload()
      setPasswordState({ saving: false, message: 'Your password has been changed.', error: '' })
    } catch (requestError) {
      setPasswordState({ saving: false, message: '', error: errorMessage(requestError, 'The password could not be changed.') })
    }
  }

  return (
    <div className="page-card">
      <PageHead title="My account" subtitle="Your details, password and display preference." />

      <section className="card">
        <div className="card-head"><h3>Access</h3></div>
        <div className="form-grid">
          <div className="form-field">Email<span className="field-hint">{profile?.email || '—'}</span></div>
          <div className="form-field">Role<span className="field-hint">{profile?.role_label || '—'}</span></div>
          {profile?.cluster_name ? <div className="form-field">Cluster<span className="field-hint">{profile.cluster_name}</span></div> : null}
          {profile?.district_name ? <div className="form-field">District<span className="field-hint">{profile.district_name}</span></div> : null}
          {profile?.province_name ? <div className="form-field">Province<span className="field-hint">{profile.province_name}</span></div> : null}
        </div>
        <p className="card-sub" style={{ marginTop: 12 }}>Your role and assignment are set by an administrator.</p>
      </section>

      <form className="card" onSubmit={saveDetails}>
        <DraftNotice draft={detailsDraft} />
        <div className="card-head"><h3>Your details</h3></div>
        <div className="form-grid">
          <label>First name<input value={details.first_name} onChange={(event) => setDetails({ ...details, first_name: event.target.value })} /></label>
          <label>Last name<input value={details.last_name} onChange={(event) => setDetails({ ...details, last_name: event.target.value })} /></label>
          <label>Phone number<input type="tel" value={details.phone_number} onChange={(event) => setDetails({ ...details, phone_number: event.target.value })} /></label>
        </div>
        {detailState.error ? <div className="form-message error" role="alert" style={{ marginTop: 14 }}>{detailState.error}</div> : null}
        {detailState.message ? <div className="form-message success" role="status" style={{ marginTop: 14 }}>{detailState.message}</div> : null}
        <div className="form-actions"><button type="submit" className="primary-btn" disabled={detailState.saving}>{detailState.saving ? 'Saving…' : 'Save details'}</button></div>
      </form>

      <form className="card" onSubmit={savePassword}>
        <div className="card-head"><h3>Change password</h3></div>
        <div className="form-grid">
          <label>Current password<input type="password" autoComplete="current-password" required value={passwords.current_password} onChange={(event) => setPasswords({ ...passwords, current_password: event.target.value })} /></label>
          <label>New password<input type="password" autoComplete="new-password" minLength="8" required value={passwords.new_password} onChange={(event) => setPasswords({ ...passwords, new_password: event.target.value })} /></label>
          <label>Repeat new password<input type="password" autoComplete="new-password" minLength="8" required value={passwords.confirm} onChange={(event) => setPasswords({ ...passwords, confirm: event.target.value })} /></label>
        </div>
        {passwordState.error ? <div className="form-message error" role="alert" style={{ marginTop: 14 }}>{passwordState.error}</div> : null}
        {passwordState.message ? <div className="form-message success" role="status" style={{ marginTop: 14 }}>{passwordState.message}</div> : null}
        <div className="form-actions"><button type="submit" className="primary-btn" disabled={passwordState.saving}>{passwordState.saving ? 'Saving…' : 'Change password'}</button></div>
      </form>

      <section className="card">
        <div className="card-head"><h3>Appearance</h3></div>
        <div className="tabs" role="group" aria-label="Theme" style={{ width: 'fit-content' }}>
          <button type="button" className={theme === 'light' ? 'active' : ''} aria-pressed={theme === 'light'} onClick={() => setTheme('light')}>Light</button>
          <button type="button" className={theme === 'dark' ? 'active' : ''} aria-pressed={theme === 'dark'} onClick={() => setTheme('dark')}>Dark</button>
        </div>
        <p className="card-sub" style={{ marginTop: 12 }}>The choice is remembered on this device.</p>
      </section>
    </div>
  )
}

export default AccountPage
