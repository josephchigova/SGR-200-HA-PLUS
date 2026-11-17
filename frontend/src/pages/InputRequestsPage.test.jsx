import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import InputRequestsPage from './InputRequestsPage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), put: vi.fn() } }))
vi.mock('../auth', () => ({ useAuth: () => ({ can: () => true, profile: { role: 'super_admin' } }) }))

const season = { id: 3, name: '2026/2027', status: 'ACTIVE' }
const product = (id, name, category, hectares, allocated = '0.00') => ({
  id, requirement: id + 100, product_name: name, input_category: category, unit: 'kg', rate_per_hectare: '25.0000', unit_price: '2.0000',
  catalogue_active: true, requested_hectares: hectares, approved_hectares: hectares, allocated_hectares: allocated,
  remaining_hectares: String(Number(hectares) - Number(allocated)), farmers: Number(allocated) ? 1 : 0,
})
const requests = [
  { id: 1, request_number: 'SGR1000', programme: 2, programme_name: 'SEEDCO', crop: 'Maize', season_name: '2026/2027', crop_season: 'Summer', input_category: 'SEED', requested_hectares: '15000.00', approved_hectares: '15000.00', allocated_hectares: '50.00', remaining_hectares: '14950.00', status: 'APPROVED', products: [product(1, 'Mbizi', 'SEED', '8000.00', '50.00'), product(2, 'Shumba', 'SEED', '7000.00')] },
  { id: 2, request_number: 'SGR1001', programme: 2, programme_name: 'SEEDCO', crop: 'Sorghum', season_name: '2026/2027', crop_season: 'Summer', input_category: '', requested_hectares: '40.00', approved_hectares: '40.00', allocated_hectares: '0.00', remaining_hectares: '40.00', status: 'APPROVED', products: [] },
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
        { id: 103, input_category: 'FERTILIZER', input_product_name: 'Compound D', rate_per_hectare: '400.0000', unit: 'kg', cost_per_unit: '0.6400', active: true },
      ] } })
    }
    return Promise.resolve({ data: { results: [] } })
  })
  apiClient.post.mockResolvedValue({ data: { request_number: 'SGR1002', requested_hectares: '20000.00' } })
  apiClient.patch.mockResolvedValue({ data: { request_number: 'SGR1000' } })
  apiClient.put.mockResolvedValue({})
  apiClient.delete.mockResolvedValue({})
})

describe('InputRequestsPage', () => {
  it('lists requests with no approval step and shows each product', async () => {
    render(<InputRequestsPage selectedSeason={season} periodStatus="ready" />)
    expect(await screen.findByText('SGR1000')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Submit|Approve/ })).toBeNull()
    // A request with allocations cannot be deleted until they are cancelled.
    expect(screen.getByRole('button', { name: 'Delete SGR1000' }).disabled).toBe(true)
    expect(screen.getByRole('button', { name: 'Delete SGR1001' }).disabled).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Show products in SGR1000' }))
    expect(await screen.findByText('7,950 ha', { selector: 'strong' })).toBeTruthy()
  })

  it('works out the total hectares from the varieties and creates the request in one step', async () => {
    render(<InputRequestsPage selectedSeason={season} periodStatus="ready" />)
    await screen.findByText('SGR1000')
    expect(screen.queryByRole('spinbutton', { name: 'Requested hectares' })).toBeNull()
    fireEvent.change(screen.getAllByRole('combobox', { name: 'Programme' })[0], { target: { value: '2' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Crop' }), { target: { value: 'Maize' } })
    fireEvent.change(await screen.findByRole('spinbutton', { name: 'Hectares for Mbizi' }), { target: { value: '8000' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares for Shumba' }), { target: { value: '7000' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares for Compound D' }), { target: { value: '15000' } })
    // Varieties add up (8,000 + 7,000); fertilizer goes on the same 15,000 ha.
    expect(screen.getByLabelText('Total hectares').textContent).toBe('15,000 ha')
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares for Shumba' }), { target: { value: '12000' } })
    expect(screen.getByLabelText('Total hectares').textContent).toBe('20,000 ha')
    fireEvent.click(screen.getByRole('button', { name: 'Create request' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/arda-request-batches/', expect.objectContaining({
      programme: 2, crop: 'Maize',
      lines: [{ requirement: 101, requested_hectares: '8000' }, { requirement: 102, requested_hectares: '12000' }, { requirement: 103, requested_hectares: '15000' }],
    })))
    expect(apiClient.post.mock.calls[0][1]).not.toHaveProperty('requested_hectares')
    expect(await screen.findByText(/SGR1002 created for 20,000 ha/)).toBeTruthy()
  })

  it('edits a request with allocations without letting a product drop below them', async () => {
    render(<InputRequestsPage selectedSeason={season} periodStatus="ready" />)
    await screen.findByText('SGR1000')
    fireEvent.click(screen.getByRole('button', { name: 'Edit SGR1000' }))
    const mbizi = await screen.findByRole('spinbutton', { name: 'Hectares for Mbizi' })
    expect(mbizi.value).toBe('8000')
    expect(mbizi.getAttribute('min')).toBe('50')
    expect(screen.getByText('50 ha allocated')).toBeTruthy()
    // Allocations exist, so the programme and crop stay fixed.
    expect(screen.getAllByRole('combobox', { name: 'Programme' }).some((select) => select.disabled)).toBe(true)
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares for Shumba' }), { target: { value: '5000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledWith('/arda-request-batches/1/', expect.objectContaining({
      lines: [{ requirement: 101, requested_hectares: '8000' }, { requirement: 102, requested_hectares: '5000' }],
    })))
  })
})
