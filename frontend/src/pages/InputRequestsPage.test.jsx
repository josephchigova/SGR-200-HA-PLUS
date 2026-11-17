import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import InputRequestsPage from './InputRequestsPage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
vi.mock('../auth', () => ({ useAuth: () => ({ can: () => true, profile: { role: 'super_admin' } }) }))

const season = { id: 3, name: '2026/2027', status: 'ACTIVE' }
const product = (id, name, category, requested, approved = '0.00') => ({
  id, requirement: id + 100, product_name: name, input_category: category, unit: 'kg', rate_per_hectare: '25.0000', unit_price: '2.0000',
  catalogue_active: true, requested_hectares: requested, approved_hectares: approved, allocated_hectares: '0.00', remaining_hectares: approved, farmers: 0,
})
const requests = [
  { id: 1, request_number: 'SGR1000', programme: 2, programme_name: 'SEEDCO', crop: 'Maize', season_name: '2026/2027', crop_season: 'Summer', input_category: '', requested_hectares: '300.00', approved_hectares: '200.00', allocated_hectares: '75.00', remaining_hectares: '125.00', status: 'APPROVED', status_label: 'Approved', products: [product(11, 'Mbizi', 'SEED', '120.00', '120.00')] },
  { id: 2, request_number: 'SGR1001', programme: 2, programme_name: 'SEEDCO', crop: 'Sorghum', season_name: '2026/2027', crop_season: 'Summer', input_category: 'SEED', requested_hectares: '40.00', approved_hectares: '0.00', allocated_hectares: '0.00', remaining_hectares: '0.00', status: 'SUBMITTED', status_label: 'Submitted', products: [product(21, 'Mbizi', 'SEED', '25.00'), product(22, 'Shumba', 'SEED', '15.00')] },
]

beforeEach(() => {
  vi.clearAllMocks()
  apiClient.get.mockImplementation((url) => {
    if (url === '/programmes/') return Promise.resolve({ data: { results: [{ id: 2, name: 'SEEDCO', capacity_status: 'ACTIVE', crops: [5, 6], crop_names: ['Maize', 'Sorghum'], input_categories: ['SEED', 'FERTILIZER'] }] } })
    if (url === '/arda-request-batches/') return Promise.resolve({ data: { results: requests } })
    if (url === '/crop-input-requirements/') {
      return Promise.resolve({ data: { results: [
        { id: 101, input_category: 'SEED', input_product_name: 'Mbizi', rate_per_hectare: '25.0000', unit: 'kg', cost_per_unit: '2.0000', active: true },
        { id: 102, input_category: 'SEED', input_product_name: 'Shumba', rate_per_hectare: '20.0000', unit: 'kg', cost_per_unit: '3.0000', active: true },
      ] } })
    }
    return Promise.resolve({ data: { results: [] } })
  })
  apiClient.post.mockResolvedValue({ data: { request_number: 'SGR1002' } })
})

describe('InputRequestsPage', () => {
  it('shows requested, approved, allocated and remaining hectares and each product in a request', async () => {
    render(<InputRequestsPage selectedSeason={season} periodStatus="ready" />)
    expect(await screen.findByText('SGR1000')).toBeTruthy()
    expect(screen.getAllByText('125 ha').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Show products in SGR1000' }))
    expect(await screen.findByText('120 ha', { selector: 'strong' })).toBeTruthy()
  })

  it('requests hectares for specific varieties from the programme catalogue', async () => {
    render(<InputRequestsPage selectedSeason={season} periodStatus="ready" />)
    await screen.findByText('SGR1000')
    fireEvent.change(screen.getAllByRole('combobox', { name: 'Programme' })[0], { target: { value: '2' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Crop' }), { target: { value: 'Maize' } })
    expect(screen.queryByRole('option', { name: 'Chemicals only' })).toBeNull()
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Requested hectares' }), { target: { value: '20000' } })
    fireEvent.change(await screen.findByRole('spinbutton', { name: 'Hectares for Mbizi' }), { target: { value: '8000' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares for Shumba' }), { target: { value: '7000' } })
    expect(screen.getByText('Seed varieties: 15,000 ha of 20,000 ha.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Save as draft' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/arda-request-batches/', expect.objectContaining({
      programme: 2, crop: 'Maize', requested_hectares: '20000',
      lines: [{ requirement: 101, requested_hectares: '8000' }, { requirement: 102, requested_hectares: '7000' }],
    })))
  })

  it('approves each product within the approved hectares', async () => {
    render(<InputRequestsPage selectedSeason={season} periodStatus="ready" />)
    await screen.findByText('SGR1001')
    fireEvent.click(screen.getByRole('button', { name: 'Approve or reject' }))
    fireEvent.change(await screen.findByRole('spinbutton', { name: /^Approved hectares At most/ }), { target: { value: '30' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Approved hectares for Shumba' }), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Approve 30 ha' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/arda-request-batches/2/approve/', { approved_hectares: '30', notes: '', lines: { 21: '25', 22: '5' } }))
  })
})
