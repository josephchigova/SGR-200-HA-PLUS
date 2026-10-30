import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import './App.css'
import apiClient from './api/client'
import {
  cropSeasonAfterYearChange,
  cropSeasonLabel,
  mergeCurrentYear,
  readStoredPeriod,
  resolvePeriodSelection,
  selectionIsHistorical,
  writeStoredPeriod,
} from './period'
import DashboardPage from './pages/DashboardPage'
import FinancePage from './pages/FinancePage'
import CropCataloguePage from './pages/CropCataloguePage'
import FarmerDetailsPage from './pages/FarmerDetailsPage'
import FarmersPage from './pages/FarmersPage'
import InputAllocationsPage from './pages/InputAllocationsPage'
import InputDebtPage from './pages/InputDebtPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import SearchPage from './pages/SearchPage'
import SubscriptionsPage from './pages/SubscriptionsPage'
import VerificationPage from './pages/VerificationPage'
import WorkflowPage from './pages/WorkflowPage'
import { workflowPages } from './pages/workflowConfig'
import { watchMobileTables } from './components/labelMobileTables'

const navGroups = [
  { title: 'Overview', items: [{ label: 'Dashboard', to: '/dashboard' }] },
  {
    title: 'Farmers',
    items: [
      { label: 'Farmers Register', to: '/farmers' },
      { label: 'Verification', to: '/verification' },
      { label: 'Subscriptions', to: '/subscriptions' },
    ],
  },
  {
    title: 'Programmes',
    items: [
      { label: 'Crop Catalogue', to: '/crops' },
      { label: 'Programmes', to: '/programmes' },
      { label: 'ARDA Requests', to: '/arda-requests' },
    ],
  },
  {
    title: 'Inputs and production',
    items: [
      { label: 'Input Allocations', to: '/input-allocations' },
      { label: 'Production', to: '/production' },
      { label: 'Seasonal Planting', to: '/seasonal-planting' },
      { label: 'GMB Deliveries', to: '/deliveries' },
      { label: 'Recovery', to: '/recovery' },
    ],
  },
  { title: 'Finance', items: [{ label: 'Finance', to: '/finance' }] },
  { title: 'Account', items: [{ label: 'Sign in', to: '/login' }] },
]

const bottomNav = [
  { label: 'Dashboard', to: '/dashboard' },
  { label: 'Farmers', to: '/farmers' },
  { label: 'Verification', to: '/verification' },
  { label: 'Finance', to: '/finance' },
]

const roleLabels = {
  super_admin: 'Administrator',
  sgr_executive: 'SGR Executive',
  verification_officer: 'Verification Officer',
  finance_officer: 'Finance Officer',
  programme_officer: 'Programme Officer',
  recovery_officer: 'Recovery Officer',
  provincial_coordinator: 'Provincial Coordinator',
  district_coordinator: 'District Coordinator',
  lead_farmer: 'Lead Farmer',
  auditor: 'Auditor',
  viewer: 'Viewer',
}

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

export function AppShell() {
  const navigate = useNavigate()
  const location = useLocation()
  const isLoginPage = location.pathname === '/login'
  const [authenticated, setAuthenticated] = useState(Boolean(localStorage.getItem('sgr_access_token')))
  const [searchQuery, setSearchQuery] = useState('')
  const [seasons, setSeasons] = useState([])
  const [selectedSeasonId, setSelectedSeasonId] = useState('')
  const [cropSeason, setCropSeason] = useState('')
  const [currentPeriod, setCurrentPeriod] = useState(null)
  const [periodLoading, setPeriodLoading] = useState(!isLoginPage)
  const [periodError, setPeriodError] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)
  const [profile, setProfile] = useState(null)

  useEffect(() => watchMobileTables(), [location.pathname])

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const query = window.matchMedia('(max-width: 1023px)')
    const sync = () => setMobileNav(query.matches)
    sync()
    query.addEventListener('change', sync)
    return () => query.removeEventListener('change', sync)
  }, [])

  useEffect(() => {
    if (!navOpen) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') setNavOpen(false)
    }
    document.body.classList.add('nav-lock')
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.classList.remove('nav-lock')
      window.removeEventListener('keydown', onKey)
    }
  }, [navOpen])

  useEffect(() => {
    if (!authenticated || isLoginPage) {
      setProfile(null)
      return undefined
    }
    let cancelled = false
    apiClient.get('/auth/me/').then((response) => {
      if (!cancelled) setProfile(response.data)
    }).catch(() => {
      if (!cancelled) setProfile(null)
    })
    return () => { cancelled = true }
  }, [authenticated, isLoginPage])

  useEffect(() => {
    const syncAuthentication = () => setAuthenticated(Boolean(localStorage.getItem('sgr_access_token')))
    window.addEventListener('storage', syncAuthentication)
    window.addEventListener('sgr-auth-changed', syncAuthentication)
    return () => {
      window.removeEventListener('storage', syncAuthentication)
      window.removeEventListener('sgr-auth-changed', syncAuthentication)
    }
  }, [])

  useEffect(() => {
    if (isLoginPage) return undefined
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
      } catch (requestError) {
        if (!cancelled) {
          const status = requestError.response?.status
          setPeriodError(status === 401
            ? 'Sign in to load the agricultural year and season.'
            : 'Unable to load the agricultural year and season.')
        }
      } finally {
        if (!cancelled) setPeriodLoading(false)
      }
    }
    loadPeriod()
    return () => { cancelled = true }
  }, [isLoginPage])

  const selectedSeason = seasons.find((season) => String(season.id) === String(selectedSeasonId)) || null
  const currentCropSeason = currentPeriod?.crop_season || ''
  const periodStatus = periodLoading ? 'loading' : periodError ? 'error' : 'ready'
  const historical = selectionIsHistorical({ season: selectedSeason, cropSeason, currentCropSeason })
  const selectedCropLabel = cropSeasonLabel(selectedSeason, cropSeason)
  const historicalMessage = !selectedSeason || !historical
    ? ''
    : selectedSeason.status !== 'ACTIVE'
      ? `${selectedSeason.name} is not the active season. Records stay available to view. ARDA requests can only be created or edited for an active season.`
      : `Historical period. Viewing ${selectedSeason.name}${selectedCropLabel ? ` · ${selectedCropLabel}` : ''}. Selecting this period does not change saved records.`

  const applySelection = (selection) => {
    setSelectedSeasonId(selection.yearId)
    setCropSeason(selection.cropSeason)
    writeStoredPeriod(selection)
  }

  const logout = () => {
    localStorage.removeItem('sgr_access_token')
    localStorage.removeItem('sgr_refresh_token')
    setAuthenticated(false)
    setNavOpen(false)
    window.location.href = '/login'
  }

  const profileName = profile
    ? (`${profile.first_name || ''} ${profile.last_name || ''}`.trim() || profile.username || profile.email)
    : ''
  const profileInitials = profileName
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join('') || 'SGR'
  const bottomActive = (to) => (to === '/farmers'
    ? location.pathname === '/farmers' || location.pathname.startsWith('/farmers/')
    : location.pathname === to)

  const returnToCurrentPeriod = () => {
    const currentYear = currentPeriod?.agricultural_year
    if (!currentYear?.id) return
    applySelection({
      mode: 'auto',
      yearId: String(currentYear.id),
      cropSeason: currentCropSeason,
    })
  }

  return (
    <div className={`app-shell${isLoginPage ? ' login-shell' : ''}`}>
      {!isLoginPage && navOpen ? <button type="button" className="nav-backdrop" aria-label="Close navigation" onClick={() => setNavOpen(false)} /> : null}
      {!isLoginPage ? <aside id="primary-navigation" className={`sidebar golden-nav${navOpen ? ' is-open' : ''}`} aria-hidden={mobileNav && !navOpen} inert={mobileNav && !navOpen ? true : undefined}>
          <div className="drawer-toolbar">
            <button type="button" className="drawer-close" onClick={() => setNavOpen(false)}>Close</button>
          </div>
          <div className="brand-block">
            <div className="brand-mark">SGR</div>
            <div>
              <h1>SGR 200HA+</h1>
              <p>Farmer &amp; Input Management System</p>
            </div>
          </div>
          {profile ? (
            <div className="nav-profile">
              <span className="nav-avatar" aria-hidden="true">{profileInitials}</span>
              <div>
                <strong>{profileName}</strong>
                <small>{roleLabels[profile.role] || profile.role}</small>
              </div>
            </div>
          ) : null}

          <nav className="nav-section" aria-label="Primary navigation">
            {navGroups.map((group) => (
              <div key={group.title}>
                <p className="nav-title">{group.title}</p>
                <ul>
                  {group.items.map((item) => (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
                        onClick={() => setNavOpen(false)}
                      >
                        {item.label}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
          {authenticated ? <button type="button" className="ghost-btn nav-logout" onClick={logout}>Logout</button> : null}
        </aside> : null}

        <main className={isLoginPage ? 'login-main' : 'main-panel'}>
          {!isLoginPage ? <header className="app-header">
            <div className="mobile-topbar">
              <button type="button" className="nav-toggle ghost-btn" aria-expanded={navOpen} aria-controls="primary-navigation" onClick={() => setNavOpen((open) => !open)}>
                <span className="hamburger" aria-hidden="true"><span /><span /><span /></span>
                <span>{navOpen ? 'Close' : 'Menu'}</span>
              </button>
              <div className="mobile-brand">
                <span className="brand-mark">SGR</span>
                <div>
                  <strong>SGR 200HA+</strong>
                  <small>Farmer &amp; Input Management</small>
                </div>
              </div>
            </div>
            {location.pathname === '/dashboard' ? (
              <div className="page-heading">
                <h2>Dashboard</h2>
                <p>Monitor farmer registration, agricultural production and financial performance.</p>
              </div>
            ) : null}
            <div className="app-toolbar">
              <div className="toolbar-group" aria-label="Reporting period">
              <div className="period-selectors">
                <label className="period-field">
                  <span className="eyebrow">Agricultural Year</span>
                  <select
                    aria-label="Agricultural year"
                    className="season-selector"
                    value={selectedSeasonId}
                    disabled={periodLoading || !seasons.length}
                    onChange={(event) => {
                      const nextSeason = seasons.find((season) => String(season.id) === event.target.value) || null
                      applySelection({
                        mode: 'manual',
                        yearId: event.target.value,
                        cropSeason: cropSeasonAfterYearChange({
                          nextSeason,
                          currentCropSeason,
                          previousCropSeason: cropSeason,
                        }),
                      })
                    }}
                  >
                    {!seasons.some((season) => season.selectable !== false) ? <option value="">{periodError ? 'Sign in' : 'No years'}</option> : null}
                    {seasons.filter((season) => season.selectable !== false).map((season) => (
                      <option key={season.id} value={season.id}>{season.name}</option>
                    ))}
                  </select>
                </label>
                <label className="period-field">
                  <span className="eyebrow">Season</span>
                  <select
                    aria-label="Season"
                    className="season-selector"
                    value={cropSeason}
                    disabled={periodLoading || !(selectedSeason?.crop_seasons || []).length}
                    onChange={(event) => applySelection({
                      mode: 'manual',
                      yearId: selectedSeasonId,
                      cropSeason: event.target.value,
                    })}
                  >
                    {(selectedSeason?.crop_seasons || []).length ? (selectedSeason.crop_seasons || []).map((item) => (
                      <option key={item.code} value={item.code}>{item.label}</option>
                    )) : <option value="">{periodLoading ? 'Loading' : 'No season'}</option>}
                  </select>
                </label>
                <button type="button" className="ghost-btn period-reset" onClick={returnToCurrentPeriod} disabled={!currentPeriod?.agricultural_year?.id}>
                  Current period
                </button>
              </div>
              </div>
            <div className="toolbar-group toolbar-actions">
              <form
                className="global-search"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (searchQuery.trim()) navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`)
                }}
              >
                <input
                  aria-label="Search the system"
                  placeholder="Search farmers, programmes..."
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                />
                <button type="submit" className="ghost-btn">Search</button>
              </form>
              <div className="header-actions">
                <button type="button" className="ghost-btn">Notifications</button>
                {authenticated ? (
                  <button type="button" className="primary-btn" onClick={logout}>Logout</button>
                ) : (
                  <NavLink to="/login" className="primary-btn">Sign in</NavLink>
                )}
              </div>
            </div>
            </div>
            {periodLoading ? <p className="form-message">Loading agricultural year and season...</p> : null}
            {periodError ? <p className="form-message error" role="alert">{periodError}</p> : null}
            {historicalMessage ? <p className="form-message period-banner" role="status">{historicalMessage}</p> : null}
          </header> : null}

          <Routes>
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="/dashboard" element={<DashboardPage selectedSeason={selectedSeason} cropSeason={cropSeason} periodStatus={periodStatus} />} />
            <Route path="/farmers" element={<FarmersPage />} />
            <Route path="/farmers/:id" element={<FarmerDetailsPage />} />
            <Route path="/verification" element={<VerificationPage />} />
            <Route path="/subscriptions" element={<SubscriptionsPage selectedSeason={selectedSeason} />} />
            <Route path="/crops" element={<CropCataloguePage />} />
            <Route path="/programmes" element={<WorkflowPage {...workflowPages.programmes} selectedSeason={selectedSeason} cropSeason={cropSeason} periodStatus={periodStatus} />} />
            <Route path="/arda-requests" element={<WorkflowPage {...workflowPages.arda} selectedSeason={selectedSeason} cropSeason={cropSeason} periodStatus={periodStatus} />} />
            <Route path="/input-allocations" element={<InputAllocationsPage selectedSeason={selectedSeason} cropSeason={cropSeason} periodStatus={periodStatus} />} />
            <Route path="/production" element={<WorkflowPage {...workflowPages.production} selectedSeason={selectedSeason} cropSeason={cropSeason} periodStatus={periodStatus} />} />
            <Route path="/seasonal-planting" element={<WorkflowPage {...workflowPages.seasonalPlanting} selectedSeason={selectedSeason} cropSeason={cropSeason} periodStatus={periodStatus} />} />
            <Route path="/deliveries" element={<WorkflowPage {...workflowPages.deliveries} selectedSeason={selectedSeason} cropSeason={cropSeason} periodStatus={periodStatus} />} />
            <Route path="/recovery" element={<InputDebtPage selectedSeason={selectedSeason} cropSeason={cropSeason} periodStatus={periodStatus} />} />
            <Route path="/finance" element={<FinancePage selectedSeason={selectedSeason} />} />
            <Route path="/inputs" element={<Navigate to="/input-allocations" replace />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
        </main>
        {!isLoginPage ? (
          <nav className="bottom-nav" aria-label="Frequent sections">
            {bottomNav.map((item) => (
              <button key={item.to} type="button" className={bottomActive(item.to) ? 'active' : ''} onClick={() => { setNavOpen(false); navigate(item.to) }}>
                {item.label}
              </button>
            ))}
            <button type="button" aria-expanded={navOpen} aria-controls="primary-navigation" onClick={() => setNavOpen(true)}>Menu</button>
          </nav>
        ) : null}
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  )
}

export default App
