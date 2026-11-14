import { Link } from 'react-router-dom'

import Icon from '../components/Icon'
import { useTheme } from '../theme'

// The two-panel frame shared by sign-in, account request and password pages.
function AuthLayout({ children, back = null }) {
  const { theme, toggleTheme } = useTheme()
  return (
    <div className="auth-page">
      <section className="auth-brand" aria-label="SGR 200HA+">
        <div className="auth-brand-top">
          <img className="auth-logo" src={`${import.meta.env.BASE_URL}sgr-logo.jpg`} alt="Strategic Grain Reserve, 200ha+ Club Zimbabwe" width="120" height="120" />
        </div>
        <div>
          <span className="eyebrow">200HA+ Club Zimbabwe</span>
          <h1>Farmer &amp; input management</h1>
          <p>One workspace for farmer membership, seasonal production, subscriptions, input allocation, grain recovery and finance.</p>
        </div>
        <div className="auth-brand-foot"><Icon name="shield" />Authorised staff access</div>
      </section>
      <section className="auth-panel">
        <button type="button" className="icon-btn auth-theme" aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} onClick={toggleTheme}>
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
        </button>
        <div className="auth-box">
          {back ? <Link className="auth-back" to={back.to}><Icon name="arrowLeft" />{back.label}</Link> : null}
          {children}
        </div>
      </section>
    </div>
  )
}

export default AuthLayout
