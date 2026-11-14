import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import UsersPage from './UsersPage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}))

const leadAccount = {
  id: 9, email: 'john@example.com', first_name: 'JOHN', last_name: 'MOYO', role: 'lead_farmer', role_label: 'Lead Farmer / Cluster Leader',
  is_active: true, assigned_cluster: 3, cluster_name: 'JOHN MOYO', farmer: 7, last_login: null,
}

const renderPage = () => render(<UsersPage />, { wrapper: MemoryRouter })

describe('UsersPage and lead farmer logins', () => {
  beforeEach(() => {
    apiClient.patch.mockReset()
    apiClient.get.mockImplementation((url) => {
      if (String(url).startsWith('/auth/users/')) return Promise.resolve({ data: { results: [leadAccount], count: 1 } })
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
      return Promise.resolve({ data: [] })
    })
  })

  it('does not offer the lead farmer role for a new account and points to the Lead farmers page', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Add account' }))
    const role = screen.getByRole('combobox', { name: 'Role' })
    expect(within(role).queryByRole('option', { name: 'Lead Farmer / Cluster Leader' })).toBeNull()
    expect(within(role).getByRole('option', { name: 'Membership Officer' })).toBeTruthy()
    expect(role.disabled).toBe(false)
    expect(screen.getByRole('link', { name: 'Lead farmers' }).getAttribute('href')).toBe('/clusters')
    expect(screen.queryByRole('combobox', { name: 'Cluster' })).toBeNull()
  })

  it('keeps a lead farmer login tied to its cluster and never sends the cluster', async () => {
    apiClient.patch.mockResolvedValue({ data: leadAccount })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit john@example.com' }))
    expect(screen.getByRole('combobox', { name: 'Role' }).disabled).toBe(true)
    expect(screen.getByText(/Cluster: JOHN MOYO/)).toBeTruthy()
    expect(screen.queryByRole('combobox', { name: 'Cluster' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled())
    const [, payload] = apiClient.patch.mock.calls[0]
    expect(payload).not.toHaveProperty('assigned_cluster')
    expect(payload).not.toHaveProperty('farmer')
    expect(payload).not.toHaveProperty('role')
  })
})
