import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import UsersPage from './UsersPage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}))

const rudo = {
  id: 7,
  first_name: 'Rudo',
  surname: 'Chikafu',
  full_name: 'Rudo Chikafu',
  province: 10,
  province_name: 'Mashonaland West',
  registered_province_ids: [10],
  email: 'rudo@example.com',
  phone_primary: '0771111111',
  national_id: '11-111111-A-11',
  membership_number: 'SGR-MW-000001',
}

describe('UsersPage lead farmer accounts', () => {
  beforeEach(() => {
    apiClient.get.mockImplementation((url) => {
      if (String(url).startsWith('/auth/users/')) return Promise.resolve({ data: { results: [], count: 0 } })
      if (String(url).startsWith('/auth/roles/')) {
        return Promise.resolve({
          data: {
            roles: [
              { role: 'viewer', label: 'Viewer', modules: {} },
              { role: 'lead_farmer', label: 'Lead Farmer / Cluster Leader', modules: {} },
              { role: 'membership_officer', label: 'Membership Officer', modules: {} },
            ],
            actions: [],
            modules: [],
          },
        })
      }
      if (String(url).startsWith('/clusters/')) {
        return Promise.resolve({
          data: [
            { id: 1, name: 'Chinhoyi Cluster', province: 10, province_name: 'Mashonaland West', lead_member: null },
            { id: 2, name: 'Mutare Cluster', province: 20, province_name: 'Manicaland', lead_member: null },
          ],
        })
      }
      if (String(url).startsWith('/farmers/7')) return Promise.resolve({ data: rudo })
      if (String(url).startsWith('/farmers/')) return Promise.resolve({ data: { results: [rudo], next: null } })
      return Promise.resolve({ data: [] })
    })
  })

  it('asks for a registered farmer and only offers clusters in that province', async () => {
    render(<UsersPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add account' }))
    expect(screen.getByRole('textbox', { name: 'First name' })).toBeTruthy()
    expect(screen.queryByRole('combobox', { name: 'Registered farmer' })).toBeNull()

    fireEvent.change(screen.getByRole('combobox', { name: 'Role' }), { target: { value: 'lead_farmer' } })

    expect(screen.queryByRole('textbox', { name: 'First name' })).toBeNull()
    expect(screen.getByText(/only for someone already on the farmer register/)).toBeTruthy()
    const cluster = screen.getByRole('combobox', { name: 'Cluster' })
    expect(cluster.disabled).toBe(true)
    expect(screen.queryByRole('option', { name: /Chinhoyi Cluster/ })).toBeNull()
    expect(screen.queryByRole('option', { name: /Mutare Cluster/ })).toBeNull()

    const farmer = screen.getByRole('combobox', { name: 'Registered farmer' })
    fireEvent.change(farmer, { target: { value: 'Rudo' } })
    fireEvent.click(await screen.findByRole('option', { name: /Rudo Chikafu/ }))

    expect(screen.getByRole('textbox', { name: 'Email address' }).value).toBe('rudo@example.com')
    expect(screen.getByRole('option', { name: /Chinhoyi Cluster/ })).toBeTruthy()
    expect(screen.queryByRole('option', { name: /Mutare Cluster/ })).toBeNull()

    fireEvent.change(screen.getByRole('combobox', { name: 'Role' }), { target: { value: 'membership_officer' } })
    expect(screen.queryByRole('combobox', { name: 'Registered farmer' })).toBeNull()
    expect(screen.getByRole('textbox', { name: 'First name' })).toBeTruthy()
  })
})
