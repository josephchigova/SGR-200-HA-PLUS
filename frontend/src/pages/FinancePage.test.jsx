import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import FinancePage from './FinancePage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

const season = { id: 1, name: '2026/2027', start_date: '2026-10-01', end_date: '2027-09-30', status: 'ACTIVE' }

describe('FinancePage', () => {
  beforeEach(() => {
    apiClient.get.mockReset()
  })

  it('requests the selected agricultural year and shows backend figures', async () => {
    let resolveFirst
    apiClient.get.mockImplementation((url, config) => {
      if (!url.includes('dashboard')) return Promise.resolve({ data: [] })
      if (config?.params?.start === '2026-10-01') {
        return new Promise((resolve) => {
          resolveFirst = () => resolve({
            data: { total_revenue: '10.00', total_expenses: '4.00', net_profit: '6.00', total_assets: '10.00', total_liabilities: '0.00', total_equity: '10.00', cash_on_hand: '10.00', bank_balances: '0.00', accounts_receivable: '0.00', accounts_payable: '0.00' },
          })
        })
      }
      return Promise.resolve({
        data: { total_revenue: '25.00', total_expenses: '5.00', net_profit: '20.00', total_assets: '25.00', total_liabilities: '0.00', total_equity: '25.00', cash_on_hand: '25.00', bank_balances: '0.00', accounts_receivable: '0.00', accounts_payable: '0.00' },
      })
    })

    const { rerender } = render(<FinancePage selectedSeason={season} />)
    rerender(<FinancePage selectedSeason={{ ...season, start_date: '2025-10-01', end_date: '2026-09-30', name: '2025/2026' }} />)
    expect(await screen.findByText('20.00')).toBeTruthy()
    resolveFirst()
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith(
      '/finance-reports/dashboard/',
      expect.objectContaining({ params: expect.objectContaining({ start: '2026-10-01', end: '2027-09-30', season_name: '2026/2027' }) }),
    ))
    expect(screen.getByText('Net profit').closest('article').textContent).toContain('20.00')
    expect(screen.getByText('Subscription Revenue')).toBeTruthy()
  })

  it('shows the operations summary as labeled figures', async () => {
    apiClient.get.mockImplementation((url) => {
      if (url.includes('operations')) {
        return Promise.resolve({
          data: {
            subscriptions: { expected: '255000.00', paid: '16650.00', outstanding: '238350.00', ledger_posted: '0.00', collection_percent: '6.53', note: 'Operational only.' },
            input_allocations: { total_input_cost: '140962.50', hectares: '10.00', programmes: [], note: 'Operational cost.' },
            input_debts: { total_debt: '140962.50', sgr_amount: '0.00', arda_amount: '0.00', amount_recovered: '0.00', outstanding: '140962.50', recognized_receivables: 0, note: 'Not a receivable.' },
            deliveries: { tonnes: '0.00', recorded_value: '0.00', amount_recovered: '0.00', farmer_balance: '0.00', note: 'Stored delivery amounts.' },
          },
        })
      }
      return Promise.resolve({ data: [] })
    })
    render(<FinancePage selectedSeason={season} />)
    fireEvent.click(await screen.findByRole('tab', { name: 'Operations' }))
    expect(await screen.findByText('Expected')).toBeTruthy()
    expect(screen.getByText('255,000.00')).toBeTruthy()
    expect(screen.queryByText(/"subscriptions"/)).toBeNull()
  })
})