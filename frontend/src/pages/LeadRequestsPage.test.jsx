import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import LeadRequestsPage from './LeadRequestsPage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), put: vi.fn() } }))
const auth = { role: 'lead_farmer', approve: false }
vi.mock('../auth', () => ({ useAuth: () => ({ can: (module, action) => action !== 'approve' || auth.approve, profile: { role: auth.role } }) }))

const season = { id: 3, name: '2026/2027', status: 'ACTIVE' }
const request = {
  id: 9, cluster_name: 'Moyo Cluster', lead_farmer_name: 'John Moyo', programme_name: 'SEEDCO', season_name: '2026/2027', crop_season: 'SUMMER', crop_season_label: 'Summer',
  status: 'DRAFT', status_label: 'Draft', farmers: 1, total_hectares: '5', decision_notes: '',
  lines: [{ id: 1, farmer: 4, farmer_name: 'John Moyo', membership_number: 'SGR-1', crop: 5, crop_name: 'Maize', hectares: '5.00', request_number: 'SGR1000', allocation: null, items: [{ request_line: 31, input_category: 'SEED', input_category_label: 'Seed', product_name: 'Mbizi', unit: 'kg', quantity: '125', cost: null }] }],
  totals: { farmers: 1, rows: [{ crop: 'Maize', input_category: 'SEED', input_category_label: 'Seed', product_name: 'Mbizi', unit: 'kg', hectares: '5', farmers: 1, quantity: '125', cost: null }] },
}
const choices = {
  farmers: [{ id: 4, name: 'John Moyo', membership_number: 'SGR-1' }, { id: 6, name: 'Rudo Moyo', membership_number: 'SGR-2' }],
  crops: [{ id: 5, name: 'Maize', request_number: 'SGR1000', products: [
    { id: 31, input_category: 'SEED', name: 'Mbizi', unit: 'kg', rate_per_hectare: '25' },
    { id: 32, input_category: 'SEED', name: 'Shumba', unit: 'kg', rate_per_hectare: '20' },
    { id: 33, input_category: 'FERTILIZER', name: 'Compound D', unit: 'kg', rate_per_hectare: '400' },
  ] }],
}

beforeEach(() => {
  vi.clearAllMocks()
  auth.role = 'lead_farmer'
  auth.approve = false
  apiClient.get.mockImplementation((url) => {
    if (url === '/lead-requests/') return Promise.resolve({ data: { results: [{ ...request, lines: undefined, totals: undefined }] } })
    if (url === '/lead-requests/summary/') return Promise.resolve({ data: { totals: request.totals, requests: [{ request: 9, lead_farmer_name: 'John Moyo', programme_name: 'SEEDCO', totals: request.totals }] } })
    if (url === '/lead-requests/9/') return Promise.resolve({ data: request })
    if (url === '/lead-requests/9/choices/') return Promise.resolve({ data: choices })
    if (url === '/programmes/') return Promise.resolve({ data: { results: [{ id: 2, name: 'SEEDCO' }] } })
    return Promise.resolve({ data: { results: [] } })
  })
  apiClient.post.mockResolvedValue({ data: {} })
})

describe('LeadRequestsPage', () => {
  it('lets a lead farmer add farmers with one seed variety and submit the whole request', async () => {
    render(<LeadRequestsPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />)
    expect(await screen.findByText('Start a request for 2026/2027 Summer')).toBeTruthy()
    fireEvent.click(await screen.findByRole('button', { name: 'Open and edit' }))
    expect(await screen.findByText('John Moyo · SEEDCO · 2026/2027 Summer')).toBeTruthy()
    expect(screen.getAllByText('125 kg').length).toBeGreaterThan(0)

    fireEvent.change(screen.getByRole('combobox', { name: 'Farmer' }), { target: { value: '6' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Crop' }), { target: { value: '5' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares' }), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: /Mbizi/ }))
    fireEvent.click(screen.getByRole('button', { name: /Shumba/ }))
    fireEvent.click(screen.getByRole('button', { name: /Compound D/ }))
    // Picking Shumba replaced Mbizi: one variety per hectare.
    expect(screen.getByRole('button', { name: /Mbizi/ }).getAttribute('aria-pressed')).toBe('false')
    expect(screen.getByRole('button', { name: /Shumba/ }).textContent).toContain('80 kg')
    fireEvent.click(screen.getByRole('button', { name: 'Add farmer' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/lead-request-lines/', { request: 9, farmer: 6, crop: 5, hectares: '4', products: [32, 33] }))

    fireEvent.click(await screen.findByRole('button', { name: /Submit to Admin/ }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/lead-requests/9/submit/', {}))
    expect(screen.queryByRole('button', { name: 'Approve or reject' })).toBeNull()
  })

  it('shows Admin the consolidated totals and approves a submitted request', async () => {
    auth.role = 'super_admin'
    auth.approve = true
    request.status = 'SUBMITTED'
    render(<LeadRequestsPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />)
    expect(await screen.findByText('Consolidated totals · 2026/2027 Summer')).toBeTruthy()
    fireEvent.click(await screen.findByRole('button', { name: 'Open' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Approve or reject' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Approve request' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/lead-requests/9/approve/', { notes: '' }))
    request.status = 'DRAFT'
  })
})
