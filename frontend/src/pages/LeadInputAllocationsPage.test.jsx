import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import LeadInputAllocationsPage from './LeadInputAllocationsPage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

const catalogue = {
  farmers: [{ id: 7, name: 'Tendai Moyo', farms: [{ id: 9, name: 'Moyo Farm' }], crops: [{ crop: 5, hectares: '10.00' }] }],
  programmes: [{
    programme: 2,
    programme_name: 'ARDA',
    crops: [{
      crop: 5,
      crop_name: 'Maize',
      crop_season: 'SUMMER',
      crop_season_label: 'Summer',
      varieties: [{
        requirement: 11,
        input_category: 'SEED',
        input_category_label: 'Seed',
        product_name: 'Mbizi',
        unit: 'kg',
        rate_per_hectare: '25',
        unit_price: '2.00',
        pack_size: null,
        pack_price: null,
      }],
    }],
  }],
  open_requests: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  apiClient.get.mockResolvedValue({ data: catalogue })
  apiClient.post.mockResolvedValue({
    data: {
      id: 4, reference: 'LF00004', status: 'DRAFT', status_label: 'Draft', stage: 'REQUEST',
      hectares_total: '8.00', estimated_cost: '400.00', farmers: [], events: [], limits: [],
    },
  })
})

describe('LeadInputAllocationsPage', () => {
  it('calculates the quantity locally and sends only the hectares to the server', async () => {
    render(<LeadInputAllocationsPage selectedSeason={{ id: 3, name: '2026/2027', status: 'ACTIVE' }} cropSeason="SUMMER" periodStatus="ready" />)
    fireEvent.change(await screen.findByRole('combobox', { name: 'Programme' }), { target: { value: '2' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Crop' }), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add farmer' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Farmer 1' }), { target: { value: '7' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares of Mbizi for farmer 1' }), { target: { value: '8' } })
    expect(screen.getAllByText('200 kg')).toHaveLength(2)
    expect(screen.getAllByText('$400.00')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-supply-requests/', {
      programme: 2,
      season: 3,
      crop: 5,
      crop_season: 'SUMMER',
      farmers: [{ farmer: 7, farm: 9, lines: [{ requirement: 11, hectares: '8' }] }],
    }))
  })
})
