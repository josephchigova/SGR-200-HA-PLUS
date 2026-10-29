import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import FarmerAutocomplete from './FarmerAutocomplete'

vi.mock('../api/client', () => ({
  default: { get: vi.fn() },
}))

const farmer = {
  id: 42,
  full_name: 'Tariro Moyo',
  national_id: '63-1234567-X-11',
  membership_number: 'SGR-000042',
  phone_primary: '0771234567',
  district_name: 'Gweru',
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('FarmerAutocomplete', () => {
  it('searches the selected endpoint and returns the chosen farmer', async () => {
    apiClient.get.mockResolvedValue({ data: { results: [farmer], next: null } })
    const onChange = vi.fn()
    render(<FarmerAutocomplete label="Eligible farmer" endpoint="/farmers/eligible/" onChange={onChange} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'Eligible farmer' }), { target: { value: 'Tariro' } })
    expect(await screen.findByRole('option', { name: /Tariro Moyo/ })).toBeTruthy()

    expect(apiClient.get).toHaveBeenCalledWith(
      expect.stringContaining('/farmers/eligible/?search=Tariro&page_size=20'),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    fireEvent.click(screen.getByRole('option', { name: /Tariro Moyo/ }))

    expect(onChange).toHaveBeenCalledWith(farmer)
    expect(screen.getByRole('combobox', { name: /Eligible farmer/ }).value).toBe('Tariro Moyo')
  })

  it('includes the global season when searching eligible farmers', async () => {
    apiClient.get.mockResolvedValue({ data: { results: [farmer], next: null } })
    render(
      <FarmerAutocomplete
        label="Eligible farmer"
        endpoint="/farmers/eligible/"
        seasonId={3}
        seasonName="2026/2027"
        onChange={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByRole('combobox', { name: 'Eligible farmer' }), { target: { value: 'Tariro' } })
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled())

    expect(apiClient.get).toHaveBeenCalledWith(
      expect.stringContaining('season=3&season_name=2026%2F2027'),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('does not fetch the entire farmer list before a search term is entered', () => {
    render(<FarmerAutocomplete onChange={vi.fn()} />)
    fireEvent.focus(screen.getByRole('combobox', { name: 'Farmer' }))

    expect(apiClient.get).not.toHaveBeenCalled()
    expect(screen.getByText('Type at least one character to search.')).toBeTruthy()
  })
})