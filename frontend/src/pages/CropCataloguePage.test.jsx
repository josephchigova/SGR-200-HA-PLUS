import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import CropCataloguePage from './CropCataloguePage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

describe('Crop catalogue money display', () => {
  it('shows monetary values with two decimal places and keeps the rate precision', async () => {
    apiClient.get.mockImplementation((url) => {
      if (url.startsWith('/crops/')) {
        return Promise.resolve({ data: [{ id: 5, name: 'Maize', active: true, input_cost_per_hectare: '31.9000', inputs_count: 2 }] })
      }
      if (url.startsWith('/seasons/')) {
        return Promise.resolve({ data: [{ id: 1, name: '2026/2027', selectable: true }] })
      }
      if (url.startsWith('/crop-input-requirements/')) {
        return Promise.resolve({ data: [
          { id: 1, group_name: 'Chemicals', item_name: 'Glyphosate (Roundup)', rate_per_hectare: '2.0000', unit: 'L', cost_per_unit: '7.7000', cost_per_hectare: '15.4000', active: true, include_in_input_cost: true },
          { id: 2, group_name: 'Chemicals', item_name: 'Metolachlor', rate_per_hectare: '1.5000', unit: 'L', cost_per_unit: '11.0000', cost_per_hectare: '16.5000', active: true, include_in_input_cost: true },
        ] })
      }
      if (url.startsWith('/crop-selling-prices/')) {
        return Promise.resolve({ data: [{ id: 8, season: 1, season_name: '2026/2027', price_per_tonne: '400.0000', currency: 'USD', active: true }] })
      }
      return Promise.resolve({ data: [] })
    })

    const user = userEvent.setup()
    render(<CropCataloguePage />)
    await user.selectOptions(await screen.findByLabelText('Crop'), '5')

    expect(await screen.findByText('7.70')).toBeTruthy()
    expect(screen.getByText('15.40')).toBeTruthy()
    expect(screen.getByText('16.50')).toBeTruthy()
    expect(screen.getByText('11.00')).toBeTruthy()
    expect(screen.getByText('2.0000')).toBeTruthy()
    expect(screen.getByText('1.5000')).toBeTruthy()
    expect(screen.getByText('TOTAL INPUT COST / HA: 31.90')).toBeTruthy()
    expect(screen.getByText('31.90')).toBeTruthy()
    expect(screen.getByText('400.00')).toBeTruthy()
    expect(screen.queryByText('7.7000')).toBeNull()
    expect(screen.queryByText('15.4000')).toBeNull()
    expect(screen.queryByText('31.9000')).toBeNull()

    await user.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    await waitFor(() => expect(screen.getByLabelText('Cost / Unit').value).toBe('7.70'))
    expect(screen.getByLabelText('Cost / Ha').value).toBe('15.40')
  })
})
