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
    expect(screen.getAllByText('No data available for the selected period.').length).toBeGreaterThan(0)
  })

  it('draws chart axes from returned aggregates and leaves an empty production chart blank of fake points', async () => {
    apiClient.get.mockResolvedValue({
      data: {
        registered_farmers: 6,
        production: 0,
        charts: {
          registrations: [{ month: '2026-10', count: 6 }],
          subscription_receipts: [{ month: '2026-10', amount: '700.00' }],
          subscription_receipts_undated: '0.00',
          subscription_status: { paid: 2, partial: 1, unpaid: 3 },
          arda_hectares: { requested: '10.00', allocated: '6.00' },
          production_by_crop: [],
          deliveries: [],
          receivables: { subscription_outstanding: '300.00', input_debt: '50.00' },
          expenses_by_category: [],
          expenses_by_month: [],
          recent: [{ kind: 'Registration', when: '2026-10-04', detail: 'Tariro Moyo' }],
        },
      },
    })

    render(<DashboardPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />)

    expect((await screen.findAllByText('Oct 26')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Requested: 10 ha').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Allocated: 6 ha').length).toBeGreaterThan(0)
    expect(screen.queryByText('ARDA Approved')).toBeNull()
    expect(screen.queryByText(/Approved:/)).toBeNull()
    expect(screen.getAllByText('Paid: 2').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Partially paid: 1').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Unpaid: 3').length).toBeGreaterThan(0)
    expect(screen.getByText('Subscription receivables')).toBeTruthy()
    expect(screen.getByText('USD 300.00')).toBeTruthy()
    expect(screen.getByText('Input-related debt')).toBeTruthy()
    expect(screen.getByText('Tariro Moyo')).toBeTruthy()
    expect(screen.getAllByText('No data available for the selected period.').length).toBeGreaterThan(0)
    expect(screen.queryByText('Maize')).toBeNull()
  })

  it('shows the same saved request total to a second view and after a fresh load', async () => {
    apiClient.get.mockResolvedValue({
      data: {
        arda_requested_hectares: '20000.00',
        arda_request_count: 1,
        charts: { arda_hectares: { requested: '20000.00', allocated: '0.00' } },
      },
    })

    const first = render(<DashboardPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />)
    const requested = await screen.findByText('ARDA Requested')
    await waitFor(() => expect(requested.closest('article').textContent).toContain('20,000'))
    expect(screen.queryByText('ARDA Approved')).toBeNull()
    expect(localStorage.getItem('sgr_dashboard_summary')).toBeNull()
    first.unmount()

    apiClient.get.mockResolvedValue({
      data: {
        arda_requested_hectares: '15000.00',
        arda_request_count: 1,
        charts: { arda_hectares: { requested: '15000.00', allocated: '0.00' } },
      },
    })
    const reloadedView = render(<DashboardPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />)
    const reloaded = await screen.findByText('ARDA Requested')
    await waitFor(() => expect(reloaded.closest('article').textContent).toContain('15,000'))
    expect(reloaded.closest('article').textContent).not.toContain('20,000')
    reloadedView.unmount()

    render(
      <>
        <DashboardPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />
        <DashboardPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />
      </>,
    )
    await waitFor(() => expect(screen.getAllByText('ARDA Requested')).toHaveLength(2))
    screen.getAllByText('ARDA Requested').forEach((card) => {
      expect(card.closest('article').textContent).toContain('15,000')
    })
  })
})
