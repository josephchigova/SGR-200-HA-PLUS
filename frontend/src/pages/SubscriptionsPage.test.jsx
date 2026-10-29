import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import SubscriptionsPage from './SubscriptionsPage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('../components/FarmerAutocomplete', () => ({
  default: ({ value, onChange, disabled }) => (
    <label>
      Farmer
      <select
        aria-label="Farmer"
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value ? { id: Number(event.target.value) } : null)}
      >
        <option value="">Select farmer</option>
        <option value="7">Tariro Moyo</option>
      </select>
    </label>
  ),
}))

const unpaidFarmer = {
  id: null,
  farmer: 7,
  farmer_name: 'Tariro Moyo',
  membership_number: 'SGR-000007',
  national_id: '63-7654321-X-11',
  phone_primary: '0777654321',
  farmer_arable_hectares: '10.00',
  category: 'UNDER_200HA',
  expected_amount: '500.00',
  paid_amount: '0.00',
  outstanding_amount: '500.00',
  payment_status: 'UNPAID',
  payment_date: null,
  season: '2026/2027',
}

const paginated = (results) => ({ data: { count: results.length, next: null, previous: null, results } })

describe('SubscriptionsPage', () => {
  it('shows derived liability and records a dated cumulative payment', async () => {
    apiClient.get.mockImplementation((url) => {
      if (url.includes('/summary/')) {
        return Promise.resolve({ data: { total_farmers: 546, paid: 301, partial: 20, unpaid: 225 } })
      }
      const params = new URL(url, 'http://localhost').searchParams
      return Promise.resolve(paginated(params.has('farmer') ? [unpaidFarmer] : [unpaidFarmer]))
    })
    apiClient.post.mockResolvedValue({
      data: {
        ...unpaidFarmer,
        id: 19,
        paid_amount: '120.00',
        outstanding_amount: '380.00',
        payment_status: 'PARTIAL',
        payment_date: '2026-08-10',
      },
    })

    render(<SubscriptionsPage selectedSeason={{ id: 3, name: '2026/2027' }} />)

    expect(await screen.findByText('UNPAID')).toBeTruthy()
    expect(await screen.findByText('546')).toBeTruthy()
    expect(screen.getByText('301')).toBeTruthy()
    expect(screen.getByText('20')).toBeTruthy()
    expect(screen.getByText('225')).toBeTruthy()
    expect(screen.getByText('Total Farmers')).toBeTruthy()
    expect(screen.getByLabelText('Expected amount').value).toBe('')
    expect(screen.getByRole('cell', { name: /Tariro Moyo/ })).toBeTruthy()
    expect(screen.getAllByText('$500.00')).toHaveLength(2)
    expect(screen.getByLabelText('Expected amount').readOnly).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(screen.getByLabelText('Amount received').disabled).toBe(false))
    expect(screen.getByLabelText('Expected amount').value).toBe('$500.00')
    expect(screen.getByLabelText('Outstanding subscription balance').value).toBe('$500.00')
    fireEvent.change(screen.getByLabelText('Amount received'), { target: { value: '120.00' } })
    fireEvent.change(screen.getByLabelText('Payment method'), { target: { value: 'BANK' } })
    fireEvent.change(screen.getByLabelText('Payment date'), { target: { value: '2026-08-10' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Record payment' }).closest('form'))

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/farmer-subscriptions/receive/', expect.objectContaining({
      farmer: 7,
      amount: '120.00',
      payment_date: '2026-08-10',
      method: 'BANK',
      season: '2026/2027',
    })))
    expect(await screen.findByText('Received $120.00. Status is PARTIAL. Outstanding $380.00.')).toBeTruthy()
  })
})