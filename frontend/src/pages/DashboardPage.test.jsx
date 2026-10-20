import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import DashboardPage from './DashboardPage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn() },
}))

const season = { id: 4, name: '2026/2027', status: 'ACTIVE', is_current: true }

describe('DashboardPage period requests', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('sgr_access_token', 'test-token')
  })

  it('requests the selected period and ignores a stale response', async () => {
    let resolveSummer
    apiClient.get.mockImplementation((url) => {
      if (url.includes('crop_season=WINTER')) {
        return Promise.resolve({ data: { production: 9, registered_farmers: 2 } })
      }
      if (url.includes('crop_season=SUMMER')) {
        return new Promise((resolve) => {
          resolveSummer = () => resolve({ data: { production: 1, registered_farmers: 2 } })
        })
      }
      return Promise.resolve({ data: {} })
    })

    const { rerender } = render(<DashboardPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />)
    rerender(<DashboardPage selectedSeason={season} cropSeason="WINTER" periodStatus="ready" />)

    const production = await screen.findByText('Production')
    await waitFor(() => expect(production.closest('article').textContent).toContain('9'))
    resolveSummer()
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith(expect.stringContaining('crop_season=SUMMER')))
    expect(production.closest('article').textContent).toContain('9')
    expect(production.closest('article').textContent).not.toContain('1')
  })
})
