import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import InputAllocationsPage from './InputAllocationsPage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), put: vi.fn() } }))
vi.mock('../auth', () => ({ useAuth: () => ({ can: () => true, profile: { id: 1, role: 'super_admin' } }) }))
vi.mock('../components/FarmerAutocomplete', () => ({
  default: ({ onChange }) => <button type="button" onClick={() => onChange({ id: 7 })}>Pick farmer</button>,
}))

const season = { id: 3, name: '2026/2027' }
const options = {
  crop_hectares: '10.00',
  covered: { SEED: { programme_name: 'Seed Co', allocation: 4 } },
  options: [{
    programme: 2, programme_name: 'ARDA', input_categories: ['SEED', 'FERTILIZER'],
    catalogue: { SEED: [{ input_product: 11, name: 'Mbizi' }], FERTILIZER: [{ input_product: 12, name: 'Compound D' }] },
    batches: [{ id: 20, request_number: 'SGR1000', input_category: '', input_category_label: "All of the programme's inputs", approved_hectares: '200.00', allocated_hectares: '10.00', remaining_hectares: '190.00' }],
  }],
}
const plan = {
  farmer_name: 'Tendai Moyo', programme_name: 'ARDA', crop_name: 'Maize', crop_season: 'Summer', season_name: '2026/2027', request_number: 'SGR1000',
  hectares: '10', crop_hectares_limit: '10.00', remaining_hectares: '190.00', remaining_after: '180.00', total_cost: '2560.00', problems: [], can_confirm: true,
  categories: [{ category: 'FERTILIZER', label: 'Fertilizer', total_cost: '2560.00', lines: [{ input_product: 12, product_name: 'Compound D', unit: 'kg', rate_per_hectare: '400', required_quantity: '4000', packs: '80', pack_label: '50 kg bag', unit_price: '0.64', cost: '2560.00' }] }],
}

beforeEach(() => {
  vi.clearAllMocks()
  apiClient.get.mockImplementation((url) => {
    if (url === '/crops/') return Promise.resolve({ data: { results: [{ id: 5, name: 'Maize', category: 'SUMMER' }] } })
    if (url === '/farms/') return Promise.resolve({ data: { results: [{ id: 9, farm_name: 'Moyo Farm', arable_hectares: '30' }] } })
    if (url === '/input-allocations/programme-options/') return Promise.resolve({ data: options })
    return Promise.resolve({ data: { results: [] } })
  })
  apiClient.post.mockResolvedValue({ data: plan })
  apiClient.put.mockResolvedValue({})
  apiClient.delete.mockResolvedValue({})
})

describe('InputAllocationsPage', () => {
  it('allocates from one programme and one approved request, leaving out input types the farmer already has', async () => {
    render(<InputAllocationsPage selectedSeason={season} periodStatus="ready" />)
    fireEvent.click(await screen.findByText('Pick farmer'))
    fireEvent.change(await screen.findByRole('combobox', { name: 'Crop' }), { target: { value: '5' } })
    expect(await screen.findByDisplayValue('10')).toBeTruthy()
    fireEvent.change(await screen.findByRole('combobox', { name: 'Programme' }), { target: { value: '2' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Approved input request' }), { target: { value: '20' } })
    // Seed already came from Seed Co, so only fertilizer can come from ARDA.
    expect((await screen.findByRole('button', { name: /Seed · from Seed Co/ })).disabled).toBe(true)
    expect(screen.getByRole('button', { name: /Fertilizer/ }).disabled).toBe(false)
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-allocations/programme-preview/', expect.objectContaining({
      farmer: 7, crop: 5, programme: 2, request_batch: 20, hectares: '10',
    })), { timeout: 3000 })
    expect(await screen.findByText('80 × 50 kg bag')).toBeTruthy()
    expect(screen.getByText('190 ha → 180 ha after')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Review and confirm/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm allocation' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-allocations/programme-allocate/', expect.objectContaining({ programme: 2, request_batch: 20 })))
  })

  it('allocates the exact varieties approved in the request', async () => {
    const withProducts = {
      ...options,
      covered: {},
      options: [{
        ...options.options[0],
        batches: [{
          ...options.options[0].batches[0],
          products: [
            { id: 31, input_category: 'SEED', name: 'Mbizi', approved_hectares: '8000.00', remaining_hectares: '7990.00' },
            { id: 32, input_category: 'SEED', name: 'Shumba', approved_hectares: '7000.00', remaining_hectares: '7000.00' },
            { id: 33, input_category: 'FERTILIZER', name: 'Compound D', approved_hectares: '20000.00', remaining_hectares: '19990.00' },
          ],
        }],
      }],
    }
    apiClient.get.mockImplementation((url) => {
      if (url === '/crops/') return Promise.resolve({ data: { results: [{ id: 5, name: 'Maize', category: 'SUMMER' }] } })
      if (url === '/input-allocations/programme-options/') return Promise.resolve({ data: withProducts })
      return Promise.resolve({ data: { results: [] } })
    })
    render(<InputAllocationsPage selectedSeason={season} periodStatus="ready" />)
    fireEvent.click(await screen.findByText('Pick farmer'))
    fireEvent.change(await screen.findByRole('combobox', { name: 'Crop' }), { target: { value: '5' } })
    fireEvent.change(await screen.findByRole('combobox', { name: 'Programme' }), { target: { value: '2' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Approved input request' }), { target: { value: '20' } })
    // Fertilizer is ticked; with two seed varieties approved, one must be chosen.
    expect((await screen.findByRole('button', { name: /Compound D/ })).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: /Mbizi/ }).getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(screen.getByRole('button', { name: /Shumba/ }))
    fireEvent.click(screen.getByRole('button', { name: /Mbizi/ }))
    expect(screen.getByRole('button', { name: /Shumba/ }).getAttribute('aria-pressed')).toBe('false')
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-allocations/programme-preview/', expect.objectContaining({
      programme: 2, request_batch: 20, request_lines: [33, 31],
    })), { timeout: 3000 })
  })
})
