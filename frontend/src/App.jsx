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

const navItems = [
  { label: 'Dashboard', to: '/dashboard' },
  { label: 'Farmers', to: '/farmers' },
  { label: 'Verification', to: '/verification' },
  { label: 'Subscriptions', to: '/subscriptions' },
  { label: 'Crop Catalogue', to: '/crops' },
  { label: 'Programmes', to: '/programmes' },
  { label: 'ARDA Requests', to: '/arda-requests' },
  { label: 'Input Allocations', to: '/input-allocations' },
  { label: 'Production', to: '/production' },
  { label: 'Seasonal Planting', to: '/seasonal-planting' },
  { label: 'GMB Deliveries', to: '/deliveries' },
  { label: 'Recovery', to: '/recovery' },
  { label: 'Sign in', to: '/login' },
]

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
      {!isLoginPage ? <aside className="sidebar golden-nav">
          <div className="brand-block">
            <div className="brand-mark">SGR</div>
            <div>
              <h1>SGR 200HA+</h1>
              <p>Farmer &amp; Input Management System</p>
            </div>
          </div>

          <nav className="nav-section" aria-label="Primary navigation">
            <p className="nav-title">Navigation</p>
            <ul>
              {navItems.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </aside> : null}

        <main className={isLoginPage ? 'login-main' : 'main-panel'}>
          {!isLoginPage ? <header className="topbar">
            <div className="period-block">
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
                    {!seasons.length ? <option value="">No years</option> : null}
                    {seasons.map((season) => (
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
                    {(selectedSeason?.crop_seasons || []).map((item) => (
                      <option key={item.code} value={item.code}>{item.label}</option>
                    ))}
                  </select>
                </label>
                <button type="button" className="ghost-btn" onClick={returnToCurrentPeriod} disabled={!currentPeriod?.agricultural_year?.id}>
                  Current period
                </button>
              </div>
              {periodLoading ? <p className="form-message">Loading agricultural year and season...</p> : null}
              {periodError ? <p className="form-message error" role="alert">{periodError}</p> : null}
              {historicalMessage ? <p className="form-message period-banner" role="status">{historicalMessage}</p> : null}
            </div>
            <div className="topbar-actions">
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
              <button type="button" className="ghost-btn">Notifications</button>
              {authenticated ? (
                <button
                  type="button"
                  className="primary-btn"
                  onClick={() => {
                    localStorage.removeItem('sgr_access_token')
                    localStorage.removeItem('sgr_refresh_token')
                    setAuthenticated(false)
                    window.location.href = '/login'
                  }}
                >
                  Logout
                </button>
              ) : (
                <NavLink to="/login" className="primary-btn">Sign in</NavLink>
              )}
            </div>
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
            <Route path="/inputs" element={<Navigate to="/input-allocations" replace />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
        </main>
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
