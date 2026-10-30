import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import AssetsPanel from './AssetsPanel'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}))

const summary = {
  total_assets: 0,
  total_acquisition_value: '0.00',
  total_current_value: '0.00',
  total_net_book_value: '0.00',
  under_maintenance: 0,
  disposed_or_written_off: 0,
  by_category: [],
}

describe('AssetsPanel', () => {
  beforeEach(() => {
    apiClient.get.mockImplementation((url) => {
      if (url === '/auth/me/') return Promise.resolve({ data: { role: 'finance_officer', first_name: 'Ada', last_name: 'Ncube' } })
      if (url === '/assets/summary/') return Promise.resolve({ data: summary })
      if (url === '/asset-categories/') return Promise.resolve({ data: [{ id: 4, name: 'Vehicles', is_active: true }] })
      if (url.startsWith('/assets/')) return Promise.resolve({ data: { count: 0, next: null, previous: null, results: [] } })
      return Promise.resolve({ data: {} })
    })
    apiClient.post.mockReset()
  })

  it('shows an empty register and the asset fields for a finance officer', async () => {
    render(<AssetsPanel />)
    expect(await screen.findByText('No assets have been registered.')).toBeTruthy()
    expect(screen.getByText('Acquisition value')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Register asset' }))
    expect(screen.getByText('Asset name')).toBeTruthy()
    expect(screen.getByText('Purchase cost')).toBeTruthy()
    expect(screen.getByText('Warranty expiry')).toBeTruthy()
    expect(screen.getAllByRole('option', { name: 'Vehicles' }).length).toBeGreaterThan(0)
    expect(screen.getByText(/does not post an operating expense/i)).toBeTruthy()
  })
})