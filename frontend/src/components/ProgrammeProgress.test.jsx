import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import ProgrammeProgress from './ProgrammeProgress'

vi.mock('../api/client', () => ({ default: { get: vi.fn() } }))

const row = (name, values) => ({
  lead_farmer: name.length, lead_farmer_name: name, submissions: 1, requested_hectares: '0.00', approved_hectares: '0.00', distributed_hectares: '0.00',
  remaining_hectares: '0.00', final_hectares: '0.00', awaiting_hectares: '0.00', provisional_hectares: '0.00', progress_percent: null, ...values,
})

const data = {
  totals: row('', { submissions: 3, requested_hectares: '1520.00', approved_hectares: '850.00', distributed_hectares: '550.00', remaining_hectares: '300.00', final_hectares: '120.00', provisional_hectares: '430.00', progress_percent: '64.7' }),
  lead_farmers: [
    row('John', { requested_hectares: '220.00', approved_hectares: '150.00', distributed_hectares: '120.00', remaining_hectares: '30.00', final_hectares: '120.00' }),
    row('Peter', { requested_hectares: '300.00', approved_hectares: '200.00', distributed_hectares: '180.00', remaining_hectares: '20.00' }),
    row('Panashe', { requested_hectares: '1000.00', approved_hectares: '500.00', distributed_hectares: '250.00', remaining_hectares: '250.00' }),
  ],
  options: {
    crops: [{ id: 5, name: 'Maize' }], categories: ['SEED'],
    varieties: [{ requirement: 11, crop: 5, input_category: 'SEED', name: 'Mbizi · Maize' }],
    lead_farmers: [{ id: 4, name: 'John' }],
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  apiClient.get.mockResolvedValue({ data })
})

describe('ProgrammeProgress', () => {
  it('shows requested, approved, distributed and finally approved hectares from the server', async () => {
    render(<ProgrammeProgress programme={{ id: 2, name: 'ARDA' }} cropSeason="SUMMER" />)
    expect(await screen.findByText('64.7% of approved hectares distributed')).toBeTruthy()
    const strip = screen.getByLabelText('Programme progress')
    expect(within(strip).getByText('1,520 ha')).toBeTruthy()
    expect(within(strip).getByText('850 ha')).toBeTruthy()
    expect(screen.getByText(/430 ha still provisional/)).toBeTruthy()
    expect(screen.getByRole('cell', { name: 'Panashe' })).toBeTruthy()
    expect(apiClient.get).toHaveBeenCalledWith('/input-supply-requests/progress/', { params: { programme: 2, crop_season: 'SUMMER' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Variety or product' }), { target: { value: '11' } })
    await waitFor(() => expect(apiClient.get).toHaveBeenLastCalledWith('/input-supply-requests/progress/', { params: { programme: 2, crop_season: 'SUMMER', requirement: '11' } }))
  })
})
