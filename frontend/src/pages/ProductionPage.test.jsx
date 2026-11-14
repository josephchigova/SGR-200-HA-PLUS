import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import ProductionPage from './ProductionPage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), patch: vi.fn(), delete: vi.fn(), post: vi.fn(), put: vi.fn() },
}))
vi.mock('../auth', () => ({ useAuth: () => ({ can: () => true, profile: null }) }))

const season = { id: 4, name: '2026/2027' }
const overview = {
  records: 105,
  registered_hectares: '16766.80',
  planted_hectares: '12000.00',
  irrigated_hectares: '15332.30',
  farmers_planted: 39,
  crops: 3,
  estimated_production: '131560.00',
  actual_production: '4200.00',
  by_crop: [
    { crop: 'Maize', farmers: 51, hectares: '10095.00', share: 60, planted_hectares: '9000.00', irrigated_hectares: '8660.50', estimated_production: '90000.00', actual_production: '3000.00', yield_per_hectare: '0.33', planting_progress: 89 },
    { crop: 'Wheat', farmers: 49, hectares: '6155.50', share: 37, planted_hectares: '3000.00', irrigated_hectares: '6155.50', estimated_production: '41560.00', actual_production: '1200.00', yield_per_hectare: '0.40', planting_progress: 49 },
  ],
  by_lead: [
    { lead_farmer: 'ANESU MARUFU', district: 'Marondera', farmers: 18, registered_hectares: '8245.00', planted_hectares: '7820.00', irrigated_hectares: '7820.00', estimated_production: '1.00', actual_production: '0', yield_per_hectare: '0', planting_progress: 95 },
  ],
  by_status: [{ status: 'PLANTED', label: 'Planted', records: 60, hectares: '9000.00' }],
  previous: { season: '2025/2026', registered_hectares: '15757.00', irrigated_hectares: '14100.00', estimated_production: '116600.00' },
}
const record = {
  id: 9, farmer: 3, farmer_name: 'ANESU MARUFU', membership_number: 'SGR-0052', lead_farmer_name: 'ANESU MARUFU', cluster_name: 'ANESU MARUFU',
  crop: 'Maize', crop_season: 'SUMMER', season_name: '2026/2027', contracted_hectares: '123.00', planted_hectares: '93.00', irrigated_hectares: '93.00', status: 'PLANTED',
}

function respond(url) {
  if (url.startsWith('/farmer-productions/overview/')) return Promise.resolve({ data: overview })
  if (url === '/farmer-productions/') return Promise.resolve({ data: { count: 1, next: null, results: [record] } })
  return Promise.resolve({ data: { results: [] } })
}

const renderPage = (path = '/production') => render(
  <MemoryRouter initialEntries={[path]}>
    <ProductionPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />
  </MemoryRouter>,
)

describe('ProductionPage', () => {
  beforeEach(() => {
    apiClient.get.mockReset()
    apiClient.patch.mockReset()
    apiClient.get.mockImplementation(respond)
  })

  it('shows totals with the change since last season, crop share, lead farmers and records', async () => {
    renderPage()
    expect(await screen.findByText('16,766.8 ha')).toBeTruthy()
    expect(screen.getByText('↑ 6.4% vs 2025/2026')).toBeTruthy()
    expect(screen.getAllByText('ANESU MARUFU').length).toBeGreaterThan(0)
    expect(screen.getByText('Marondera')).toBeTruthy()
    expect(apiClient.get).toHaveBeenCalledWith('/farmer-productions/overview/?season=4&season_name=2026%2F2027&crop_season=SUMMER')
    expect(await screen.findByText('SGR-0052')).toBeTruthy()
    expect(screen.getByText('Growing')).toBeTruthy()
  })

  it('moves a record to its next stage', async () => {
    apiClient.patch.mockResolvedValue({ data: {} })
    renderPage('/production?tab=records')
    fireEvent.click(await screen.findByRole('button', { name: 'Move ANESU MARUFU Maize to Harvested' }))
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledWith('/farmer-productions/9/', { status: 'HARVESTED' }))
  })

  it('shows crop performance with yield and planting progress', async () => {
    renderPage('/production?tab=crops')
    expect(await screen.findByText('Crop performance')).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Maize planted 89%' })).toBeTruthy()
  })
})
