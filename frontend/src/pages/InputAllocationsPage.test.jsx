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
const option = (programme, name, product) => ({
  programme, programme_name: name, programme_code: name.slice(0, 3).toUpperCase(),
  products: [{ input_product: product, name: `Product ${product}`, unit: 'kg', rate_per_hectare: '10', unit_price: '2.0000' }],
  batches: [{ id: programme * 10, request_number: `B-${programme}`, covers_all_products: true, products: { [product]: { available: '500', unit: 'kg' } } }],
})

beforeEach(() => {
  vi.clearAllMocks()
  apiClient.get.mockImplementation((url) => {
    if (url === '/crops/') return Promise.resolve({ data: { results: [{ id: 5, name: 'Maize' }] } })
    if (url === '/farms/') return Promise.resolve({ data: { results: [{ id: 9, farm_name: 'Moyo Farm', arable_hectares: '30' }] } })
    if (url === '/input-allocations/programme-options/') {
      return Promise.resolve({ data: { crop_hectares: '10.00', categories: { SEED: [option(1, 'Seed Co', 11)], FERTILIZER: [option(2, 'ARDA', 12)], CHEMICALS: [option(3, 'Government', 13)] } } })
    }
    return Promise.resolve({ data: { results: [] } })
  })
  apiClient.put.mockResolvedValue({})
  apiClient.delete.mockResolvedValue({})
  apiClient.post.mockResolvedValue({ data: { hectares: '10', crop_name: 'Maize', season_name: '2026/2027', total_cost: '600.00', problems: [], can_confirm: true, categories: [] } })
})

describe('InputAllocationsPage', () => {
  it('lets each input category come from a different programme', async () => {
    render(<InputAllocationsPage selectedSeason={season} periodStatus="ready" />)
    fireEvent.click(await screen.findByText('Pick farmer'))
    fireEvent.change(await screen.findByRole('combobox', { name: 'Crop' }), { target: { value: '5' } })
    expect(await screen.findByDisplayValue('10')).toBeTruthy()
    for (const [label, programme] of [['Seed programme', 'Seed Co (SEE)'], ['Fertilizer programme', 'ARDA (ARD)'], ['Chemicals programme', 'Government (GOV)']]) {
      fireEvent.click(screen.getByRole('button', { name: new RegExp(label) }))
      fireEvent.mouseDown(await screen.findByRole('option', { name: programme }))
    }
    await waitFor(() => expect(apiClient.post.mock.calls.map((call) => call[0])).toContain('/input-allocations/programme-preview/'), { timeout: 3000 })
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-allocations/programme-preview/', expect.objectContaining({
      farmer: 7, crop: 5, hectares: '10',
      selections: { SEED: { programme: 1, batch: null }, FERTILIZER: { programme: 2, batch: null }, CHEMICALS: { programme: 3, batch: null } },
    })))
  })
})
