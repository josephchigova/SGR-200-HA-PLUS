import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import InputRequestsPage from './InputRequestsPage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
vi.mock('../auth', () => ({ useAuth: () => ({ can: () => true, profile: { role: 'super_admin' } }) }))

const season = { id: 3, name: '2026/2027', status: 'ACTIVE' }
const requests = [
  { id: 1, request_number: 'SGR1000', programme: 2, programme_name: 'ARDA', crop: 'Maize', season_name: '2026/2027', crop_season: 'Summer', input_category: '', requested_hectares: '300.00', approved_hectares: '200.00', allocated_hectares: '75.00', remaining_hectares: '125.00', status: 'APPROVED', status_label: 'Approved' },
  { id: 2, request_number: 'SGR1001', programme: 2, programme_name: 'ARDA', crop: 'Sorghum', season_name: '2026/2027', crop_season: 'Summer', input_category: 'SEED', requested_hectares: '40.00', approved_hectares: '0.00', allocated_hectares: '0.00', remaining_hectares: '0.00', status: 'SUBMITTED', status_label: 'Submitted' },
]

beforeEach(() => {
  vi.clearAllMocks()
  apiClient.get.mockImplementation((url) => {
    if (url === '/programmes/') return Promise.resolve({ data: { results: [{ id: 2, name: 'ARDA', capacity_status: 'ACTIVE', crop_names: ['Maize', 'Sorghum'], input_categories: ['SEED', 'FERTILIZER'] }] } })
    if (url === '/arda-request-batches/') return Promise.resolve({ data: { results: requests } })
    return Promise.resolve({ data: { results: [] } })
  })
  apiClient.post.mockResolvedValue({ data: {} })
})

describe('InputRequestsPage', () => {
  it('shows requested, approved, allocated and remaining hectares and approves part of a request', async () => {
    render(<InputRequestsPage selectedSeason={season} periodStatus="ready" />)
    expect(await screen.findByText('SGR1000')).toBeTruthy()
    expect(screen.getAllByText('125 ha').length).toBeGreaterThan(0)
    expect(screen.getAllByText('200 ha').length).toBeGreaterThan(0)
    // The new-request form offers only the programme's crops and input types.
    fireEvent.change(screen.getAllByRole('combobox', { name: 'Programme' })[0], { target: { value: '2' } })
    expect(screen.getByRole('option', { name: 'Sorghum' })).toBeTruthy()
    expect(screen.getByRole('option', { name: 'Fertilizer only' })).toBeTruthy()
    expect(screen.queryByRole('option', { name: 'Chemicals only' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Approve or reject' }))
    fireEvent.change(await screen.findByRole('spinbutton', { name: /Approved hectares/ }), { target: { value: '30' } })
    fireEvent.click(screen.getByRole('button', { name: 'Approve 30 ha' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/arda-request-batches/2/approve/', { approved_hectares: '30', notes: '' }))
  })
})
