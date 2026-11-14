import { useEffect, useRef, useState } from 'react'
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import './App.css'
import './theme.css'
import apiClient from './api/client'
import { AuthProvider, useAuth } from './auth'
import Icon from './components/Icon'
import { AccessDenied, Skeleton } from './components/ui'
import {
  cropSeasonAfterYearChange,
  cropSeasonLabel,
  mergeCurrentYear,
  readStoredPeriod,
  resolvePeriodSelection,
  selectionIsHistorical,
  writeStoredPeriod,
} from './period'
import { IDLE_LIMIT_MS, clearSession, isSignedIn } from './session'
import { useTheme } from './theme'
import AccountPage from './pages/AccountPage'
import AuditLogPage from './pages/AuditLogPage'
import DashboardPage from './pages/DashboardPage'
import FinancePage from './pages/FinancePage'
import CropCataloguePage from './pages/CropCataloguePage'
import ClusterDashboard from './pages/ClusterDashboard'
import LeadFarmersPage from './pages/LeadFarmersPage'
import FarmerDetailsPage from './pages/FarmerDetailsPage'
import FarmersPage from './pages/FarmersPage'
import InputAllocationsPage from './pages/InputAllocationsPage'
import InputDebtPage from './pages/InputDebtPage'
import LoginPage from './pages/LoginPage'
import { ForgotPasswordPage, ResetPasswordPage } from './pages/PasswordPages'
import RegisterFarmerPage from './pages/RegisterFarmerPage'
import RegisterPage from './pages/RegisterPage'
import ReportsPage from './pages/ReportsPage'
import SearchPage from './pages/SearchPage'
import SubscriptionsPage from './pages/SubscriptionsPage'
import UsersPage from './pages/UsersPage'
import VerificationPage from './pages/VerificationPage'
import WorkflowPage from './pages/WorkflowPage'
import { workflowPages } from './pages/workflowConfig'
import { watchMobileTables } from './components/labelMobileTables'

// Each item names the permission module that decides whether it is shown.
const navGroups = [
  {
    title: 'Your work',
    items: [
      { label: 'Overview', to: '/dashboard', icon: 'grid', module: 'dashboard' },
      { label: 'Farmers', to: '/farmers', icon: 'users', module: 'farmers', end: true },
      { label: 'Register farmer', to: '/farmers/register', icon: 'plus', module: 'farmers', action: 'create' },
      { label: 'Approvals', to: '/verification', icon: 'shield', module: 'verification' },
      { label: 'Lead farmers', to: '/clusters', icon: 'layers', module: 'clusters' },
      { label: 'Subscriptions', to: '/subscriptions', icon: 'dollar', module: 'subscriptions' },
    ],
  },
  {
    title: 'Programmes and inputs',
    items: [
      { label: 'Crop catalogue', to: '/crops', icon: 'book', module: 'crops' },
      { label: 'Programmes', to: '/programmes', icon: 'clipboard', module: 'programmes' },
      { label: 'Input requests', to: '/arda-requests', icon: 'send', module: 'arda' },
      { label: 'Input allocations', to: '/input-allocations', icon: 'box', module: 'allocations' },
    ],
  },
  {
    title: 'Production and recovery',
    items: [
      { label: 'Production', to: '/production', icon: 'tractor', module: 'production' },
      { label: 'Seasonal planting', to: '/seasonal-planting', icon: 'sprout', module: 'planting' },
      { label: 'GMB deliveries', to: '/deliveries', icon: 'truck', module: 'deliveries' },
      { label: 'Grain recovery', to: '/recovery', icon: 'wheat', module: 'recovery' },
    ],
  },
  {
    title: 'Administration',
    items: [
      { label: 'Finance', to: '/finance', icon: 'wallet', module: 'finance' },
      { label: 'Reports', to: '/reports', icon: 'chart', module: 'reports' },
      { label: 'Team & access', to: '/users', icon: 'userCheck', module: 'users' },
      { label: 'Audit log', to: '/audit-log', icon: 'history', module: 'audit' },
    ],
  },
]

const allItems = navGroups.flatMap((group) => group.items)
const bottomCandidates = ['/dashboard', '/farmers', '/subscriptions', '/recovery', '/finance', '/reports']
const extraTitles = { '/search': 'Search', '/account': 'My account' }
const SIDEBAR_KEY = 'sgr_sidebar_collapsed'

async function fetchAllSeasons() {
  const records = []
  let nextUrl = '/seasons/'
  while (nextUrl) {
    const response = await apiClient.get(nextUrl)
    const data = response.data
    records.push(...(Array.isArray(data) ? data : data?.results || []))
    nextUrl = Array.isArray(data) ? '' : data?.next || ''
  }
  return records
}

function pageTitle(pathname, search = '') {
  if (pathname === '/farmers/register') {
    return new URLSearchParams(search).get('as') === 'lead' ? 'Register a lead farmer' : 'Register a farmer'
  }
  if (pathname.endsWith('/edit')) return 'Continue registration'
  if (pathname.startsWith('/farmers/')) return 'Farmer profile'
  const item = allItems.find((entry) => pathname === entry.to)
  return item?.label || extraTitles[pathname] || 'SGR 200HA+'
}

function initialsOf(name) {
  return name.split(/\s+/).slice(0, 2).map((part) => part.charAt(0).toUpperCase()).join('') || 'SGR'
}

function usePopover() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const close = (event) => {
      if (event.type === 'keydown' ? event.key === 'Escape' : !ref.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])
  return [open, setOpen, ref]
}

function useIdleSignOut(active) {
  useEffect(() => {
    if (!active) return undefined
    let last = Date.now()
    const touch = () => { last = Date.now() }
    const events = ['mousedown', 'keydown', 'touchstart', 'scroll']
    events.forEach((name) => window.addEventListener(name, touch, { passive: true }))
    const timer = window.setInterval(() => {
      if (Date.now() - last > IDLE_LIMIT_MS) clearSession('idle')
    }, 30000)
    return () => {
      events.forEach((name) => window.removeEventListener(name, touch))
      window.clearInterval(timer)
    }
  }, [active])
}

function Guard({ module, action = 'view', children }) {
  const { loading, profile, can, error } = useAuth()
  if (loading) return <Skeleton kind="block" />
  if (!profile && error) return <div className="form-message error" role="alert">{error}</div>
  if (!can(module, action)) return <AccessDenied />
  return children
}

function RegisterRoute() {
  const { loading, profile, can, error } = useAuth()
  const [params] = useSearchParams()
  if (loading) return <Skeleton kind="block" />
  if (!profile && error) return <div className="form-message error" role="alert">{error}</div>
  const asLead = params.get('as') === 'lead'
  const lead = can('lead_registration', 'create')
  const member = can('farmers', 'create')
  // Lead farmers are registered in one step on the Lead farmers page, with their cluster and login.
  if (asLead && lead) return <Navigate to="/clusters?register=1" replace />
  if (!asLead && member) return <RegisterFarmerPage key="member" />
  if (lead) return <Navigate to="/clusters?register=1" replace />
  if (member) return <Navigate to="/farmers/register" replace />
  return <AccessDenied />
}

function sideLinkActive(item, isActive, location) {
  if (!item.to.startsWith('/farmers/register')) return isActive
  const wantsLead = item.to.includes('as=lead')
  const onRegister = location.pathname === '/farmers/register'
  const isLead = new URLSearchParams(location.search).get('as') === 'lead'
  return onRegister && wantsLead === isLead
}

function Workspace() {
  const navigate = useNavigate()
  const location = useLocation()
  const { profile, can } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const [searchQuery, setSearchQuery] = useState('')
  const [seasons, setSeasons] = useState([])
  const [selectedSeasonId, setSelectedSeasonId] = useState('')
  const [cropSeason, setCropSeason] = useState('')
  const [currentPeriod, setCurrentPeriod] = useState(null)
  const [periodLoading, setPeriodLoading] = useState(true)
  const [periodError, setPeriodError] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(SIDEBAR_KEY) === '1')
  const [notices, setNotices] = useState({ count: 0, items: [] })
  const [userOpen, setUserOpen, userRef] = usePopover()
  const [noticeOpen, setNoticeOpen, noticeRef] = usePopover()

  useIdleSignOut(true)
  useEffect(() => watchMobileTables(), [location.pathname])

  useEffect(() => {
    if (!navOpen) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') setNavOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navOpen])

  useEffect(() => {
    let cancelled = false
    const load = () => {
      apiClient.get('/notifications/').then((response) => {
        if (!cancelled && response.data?.items) setNotices(response.data)
      }).catch(() => {})
    }
    load()
    const timer = window.setInterval(load, 120000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [location.pathname])

  useEffect(() => {
    let cancelled = false
    const loadPeriod = async () => {
      setPeriodLoading(true)
      setPeriodError('')
      try {
        const currentResponse = await apiClient.get('/seasons/current/')
        if (cancelled) return
        const seasonRecords = mergeCurrentYear(await fetchAllSeasons(), currentResponse.data?.agricultural_year)
        if (cancelled) return
        const selection = resolvePeriodSelection({
          seasons: seasonRecords,
          currentYear: currentResponse.data?.agricultural_year,
          currentCropSeason: currentResponse.data?.crop_season,
          stored: readStoredPeriod(),
        })
        setSeasons(seasonRecords)
        setCurrentPeriod(currentResponse.data)
        setSelectedSeasonId(selection.yearId)
        setCropSeason(selection.cropSeason)
        writeStoredPeriod(selection)
      } catch {
        if (!cancelled) setPeriodError('Unable to load the agricultural year and season.')
      } finally {
        if (!cancelled) setPeriodLoading(false)
      }
    }
    loadPeriod()
    return () => { cancelled = true }
  }, [])

  const selectedSeason = seasons.find((season) => String(season.id) === String(selectedSeasonId)) || null
  const currentCropSeason = currentPeriod?.crop_season || ''
  const periodStatus = periodLoading ? 'loading' : periodError ? 'error' : 'ready'
  const historical = selectionIsHistorical({ season: selectedSeason, cropSeason, currentCropSeason })
  const selectedCropLabel = cropSeasonLabel(selectedSeason, cropSeason)
  const historicalMessage = !selectedSeason || !historical
    ? ''
    : selectedSeason.status !== 'ACTIVE'
      ? `${selectedSeason.name} is not the active season. Records stay available to view. Input requests can only be created or edited for an active season.`
      : `Historical period. Viewing ${selectedSeason.name}${selectedCropLabel ? ` · ${selectedCropLabel}` : ''}. Selecting this period does not change saved records.`

  const applySelection = (selection) => {
    setSelectedSeasonId(selection.yearId)
    setCropSeason(selection.cropSeason)
    writeStoredPeriod(selection)
  }

  const returnToCurrentPeriod = () => {
    const currentYear = currentPeriod?.agricultural_year
    if (!currentYear?.id) return
    applySelection({ mode: 'auto', yearId: String(currentYear.id), cropSeason: currentCropSeason })
  }

  const toggleCollapsed = () => {
    setCollapsed((value) => {
      localStorage.setItem(SIDEBAR_KEY, value ? '0' : '1')
      return !value
    })
  }

  const logout = () => {
    clearSession()
    navigate('/login', { replace: true })
  }

  const profileName = profile
    ? (`${profile.first_name || ''} ${profile.last_name || ''}`.trim() || profile.username || profile.email)
    : ''
  const groups = navGroups
    .map((group) => ({ ...group, items: group.items.filter((item) => can(item.module, item.action || 'view')) }))
    .filter((group) => group.items.length)
  const bottomItems = bottomCandidates
    .map((to) => allItems.find((item) => item.to === to))
    .filter((item) => item && can(item.module))
    .slice(0, 4)
  const period = { selectedSeason, cropSeason, periodStatus }
  const usesPeriod = !['/users', '/audit-log', '/account'].includes(location.pathname)

  return (
    <div className={collapsed ? 'shell is-collapsed' : 'shell'}>
      {navOpen ? <button type="button" className="side-backdrop" aria-label="Close navigation" onClick={() => setNavOpen(false)} /> : null}
      <aside id="primary-navigation" className={navOpen ? 'side is-open' : 'side'}>
        <div className="side-brand">
          <img className="brand-logo-image" src={`${import.meta.env.BASE_URL}sgr-mark.png`} alt="" width="40" height="40" />
          <div>
            <strong>SGR 200HA+</strong>
            <small>Farmer &amp; Input Management</small>
          </div>
        </div>
        <nav className="side-nav" aria-label="Primary navigation">
          {groups.map((group) => (
            <div key={group.title}>
              <p className="side-title">{group.title}</p>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={Boolean(item.end)}
                  title={collapsed ? item.label : undefined}
                  className={({ isActive }) => (sideLinkActive(item, isActive, location) ? 'side-link active' : 'side-link')}
                  onClick={() => setNavOpen(false)}
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-foot" ref={userRef}>
          {userOpen ? (
            <div className="popover" role="menu">
              <div className="popover-head">
                <strong>{profileName || 'Signed in'}</strong>
                <small>{profile?.email}</small>
              </div>
              <Link className="menu-item" role="menuitem" to="/account" onClick={() => { setUserOpen(false); setNavOpen(false) }}><Icon name="settings" />My account</Link>
              <button type="button" className="menu-item" role="menuitem" onClick={toggleTheme}>
                <Icon name={theme === 'dark' ? 'sun' : 'moon'} />{theme === 'dark' ? 'Light theme' : 'Dark theme'}
              </button>
              <button type="button" className="menu-item danger" role="menuitem" onClick={logout}><Icon name="logout" />Sign out</button>
            </div>
          ) : null}
          <button type="button" className="side-user" aria-haspopup="menu" aria-expanded={userOpen} onClick={() => setUserOpen((open) => !open)}>
            <span className="avatar" aria-hidden="true">{initialsOf(profileName)}</span>
            <span className="side-user-text">
              <strong>{profileName || 'Loading…'}</strong>
              <small>{(profile?.role_label || '').split(' / ')[0]}{profile?.cluster_name ? ` · ${profile.cluster_name}` : ''}</small>
            </span>
            <Icon name="chevrons" />
          </button>
        </div>
      </aside>

      <div className="shell-main">
        <header className="topbar">
          <button type="button" className="icon-btn mobile-only" aria-label="Open navigation" aria-expanded={navOpen} aria-controls="primary-navigation" onClick={() => setNavOpen(true)}>
            <Icon name="menu" />
          </button>
          <button type="button" className="icon-btn desktop-only" aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-pressed={collapsed} onClick={toggleCollapsed}>
            <Icon name="panel" />
          </button>
          <span className="topbar-title">{pageTitle(location.pathname, location.search)}</span>

          {usesPeriod ? (
            <div className="topbar-period" aria-label="Reporting period">
              <select
                aria-label="Agricultural year"
                value={selectedSeasonId}
                disabled={periodLoading || !seasons.length}
                onChange={(event) => {
                  const nextSeason = seasons.find((season) => String(season.id) === event.target.value) || null
                  applySelection({
                    mode: 'manual',
                    yearId: event.target.value,
                    cropSeason: cropSeasonAfterYearChange({ nextSeason, currentCropSeason, previousCropSeason: cropSeason }),
                  })
                }}
              >
                {!seasons.some((season) => season.selectable !== false) ? <option value="">{periodLoading ? 'Loading' : 'No years'}</option> : null}
                {seasons.filter((season) => season.selectable !== false).map((season) => (
                  <option key={season.id} value={season.id}>{season.name}</option>
                ))}
              </select>
              <select
                aria-label="Season"
                value={cropSeason}
                disabled={periodLoading || !(selectedSeason?.crop_seasons || []).length}
                onChange={(event) => applySelection({ mode: 'manual', yearId: selectedSeasonId, cropSeason: event.target.value })}
              >
                {(selectedSeason?.crop_seasons || []).length ? (selectedSeason.crop_seasons || []).map((item) => (
                  <option key={item.code} value={item.code}>{item.label}</option>
                )) : <option value="">{periodLoading ? 'Loading' : 'No season'}</option>}
              </select>
              <button type="button" className="ghost-btn" onClick={returnToCurrentPeriod} disabled={!currentPeriod?.agricultural_year?.id}>
                Current period
              </button>
            </div>
          ) : null}

          <form
            className="topbar-search"
            role="search"
            onSubmit={(event) => {
              event.preventDefault()
              if (searchQuery.trim()) navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`)
            }}
          >
            <Icon name="search" />
            <input aria-label="Search the system" type="search" placeholder="Search records" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} />
          </form>

          <div className="popover-anchor" ref={noticeRef}>
            <button type="button" className="icon-btn" aria-label={`Notifications, ${notices.items.length} waiting`} aria-haspopup="true" aria-expanded={noticeOpen} onClick={() => setNoticeOpen((open) => !open)}>
              <Icon name="bell" />
              {notices.items.length ? <span className="badge-dot">{notices.items.length}</span> : null}
            </button>
            {noticeOpen ? (
              <div className="popover notice-list">
                <div className="popover-head"><strong>Notifications</strong><small>Work waiting for you, from live records.</small></div>
                {notices.items.length ? notices.items.map((item) => (
                  <Link key={item.key} to={item.url} className={`notice-item ${item.tone}`} onClick={() => setNoticeOpen(false)}>
                    <i aria-hidden="true" />
                    <span><strong>{item.title}</strong><small>{item.detail}</small></span>
                  </Link>
                )) : <p className="card-sub" style={{ padding: '10px 12px' }}>Nothing is waiting for you.</p>}
              </div>
            ) : null}
          </div>
          <button type="button" className="icon-btn" aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} onClick={toggleTheme}>
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
          </button>
        </header>

        <main className="content">
          {periodError && usesPeriod ? <p className="form-message error shell-banner" role="alert">{periodError}</p> : null}
          {historicalMessage && usesPeriod ? <p className="form-message period-banner shell-banner" role="status">{historicalMessage}</p> : null}
          {profile?.must_change_password && location.pathname !== '/account' ? (
            <p className="form-message warning shell-banner" role="status">
              You are using a temporary password. <Link to="/account">Choose your own password</Link>.
            </p>
          ) : null}
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Guard module="dashboard">{profile?.role === 'lead_farmer' ? <ClusterDashboard {...period} /> : <DashboardPage {...period} />}</Guard>} />
            <Route path="/farmers" element={<Guard module="farmers"><FarmersPage /></Guard>} />
            <Route path="/farmers/register" element={<RegisterRoute />} />
            <Route path="/farmers/:id/edit" element={<Guard module="farmers" action="edit"><RegisterFarmerPage /></Guard>} />
            <Route path="/farmers/:id" element={<Guard module="farmers"><FarmerDetailsPage /></Guard>} />
            <Route path="/clusters" element={<Guard module="clusters"><LeadFarmersPage selectedSeason={selectedSeason} /></Guard>} />
            <Route path="/lead-farmers" element={<Navigate to="/clusters" replace />} />
            <Route path="/verification" element={<Guard module="verification"><VerificationPage /></Guard>} />
            <Route path="/subscriptions" element={<Guard module="subscriptions"><SubscriptionsPage selectedSeason={selectedSeason} /></Guard>} />
            <Route path="/crops" element={<Guard module="crops"><CropCataloguePage /></Guard>} />
            <Route path="/programmes" element={<Guard module="programmes"><WorkflowPage {...workflowPages.programmes} {...period} module="programmes" /></Guard>} />
            <Route path="/arda-requests" element={<Guard module="arda"><WorkflowPage {...workflowPages.arda} {...period} module="arda" /></Guard>} />
            <Route path="/input-allocations" element={<Guard module="allocations"><InputAllocationsPage {...period} /></Guard>} />
            <Route path="/production" element={<Guard module="production"><WorkflowPage {...workflowPages.production} {...period} module="production" /></Guard>} />
            <Route path="/seasonal-planting" element={<Guard module="planting"><WorkflowPage {...workflowPages.seasonalPlanting} {...period} module="planting" /></Guard>} />
            <Route path="/deliveries" element={<Guard module="deliveries"><WorkflowPage {...workflowPages.deliveries} {...period} module="deliveries" /></Guard>} />
            <Route path="/recovery" element={<Guard module="recovery"><InputDebtPage {...period} /></Guard>} />
            <Route path="/finance" element={<Guard module="finance"><FinancePage selectedSeason={selectedSeason} /></Guard>} />
            <Route path="/reports" element={<Guard module="reports"><ReportsPage selectedSeason={selectedSeason} cropSeason={cropSeason} /></Guard>} />
            <Route path="/users" element={<Guard module="users"><UsersPage /></Guard>} />
            <Route path="/audit-log" element={<Guard module="audit"><AuditLogPage /></Guard>} />
            <Route path="/account" element={<AccountPage />} />
            <Route path="/inputs" element={<Navigate to="/input-allocations" replace />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </main>
      </div>

      <nav className="bottom-tabs" aria-label="Frequent sections">
        {bottomItems.map((item) => (
          <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? 'active' : '')}>
            <Icon name={item.icon} />
            {item.label.split(' ')[0]}
          </NavLink>
        ))}
        <button type="button" aria-expanded={navOpen} aria-controls="primary-navigation" onClick={() => setNavOpen(true)}>
          <Icon name="menu" />
          Menu
        </button>
      </nav>
    </div>
  )
}

const PUBLIC_PATHS = ['/login', '/register', '/forgot-password', '/reset-password']

export function AppShell() {
  const location = useLocation()
  const auth = useAuth()
  const signedIn = auth.signedIn ?? isSignedIn()
  // The theme applies on public pages too.
  useTheme()

  if (PUBLIC_PATHS.includes(location.pathname)) {
    if (signedIn && location.pathname === '/login') return <Navigate to="/dashboard" replace />
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
      </Routes>
    )
  }
  if (!signedIn) {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />
  }
  return <Workspace />
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppShell />
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
