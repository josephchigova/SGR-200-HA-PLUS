import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import ReportsPage from './ReportsPage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn() },
}))

const catalogue = {
  categories: [{ code: 'farmers', label: 'Farmer management', count: 1 }, { code: 'finance', label: 'Finance', count: 1 }],
  filters: { province: 'Province', agricultural_year: 'Agricultural year', season: 'Season' },
  limitations: ['Asset quantity is not stored.'],
  reports: [
    { code: 'farmers-register', category: 'farmers', title: 'Complete farmer register', description: 'Every farmer record.', filters: ['province', 'agricultural_year'], status_options: [], gap: '' },
    { code: 'finance-assets', category: 'finance', title: 'Asset register', description: 'Assets stored on the register.', filters: [], status_options: [], gap: 'Quantity is not stored.' },
  ],
}

describe('Reports centre', () => {
  it('previews a filtered report and downloads pdf and csv', async () => {
    apiClient.get.mockImplementation((url) => {
      if (url.startsWith('/reports/catalogue')) return Promise.resolve({ data: catalogue })
      if (url.startsWith('/reports/analytics')) {
        return Promise.resolve({ data: { cards: [{ label: 'Registered farmers', value: '2' }], charts: [{ title: 'Farmers by province', rows: [{ label: 'Midlands', value: '2', display: '2' }] }], limitations: [] } })
      }
      if (url.startsWith('/reports/farmers-register/preview')) {
        return Promise.resolve({ data: {
          code: 'farmers-register', title: 'Complete farmer register', filters: ['Province: 4'], gap: '',
          count: 1, page: 1, pages: 1, columns: [{ key: 'surname', label: 'Surname' }],
          summaries: [{ label: 'Records', value: '1' }], chart: [], rows: [{ surname: 'Banda' }],
        } })
      }
      if (url.includes('/export/')) return Promise.resolve({ data: new Blob(['report']), headers: { 'content-type': 'text/csv' } })
      return Promise.resolve({ data: [] })
    })

    render(<ReportsPage selectedSeason={{ id: 1, name: '2026/2027' }} cropSeason="SUMMER" />)
    expect(await screen.findByText('Registered farmers')).toBeTruthy()
    fireEvent.click(await screen.findByRole('button', { name: /Complete farmer register/ }))
    expect(await screen.findByText('Banda')).toBeTruthy()
    expect(screen.getByText('Records')).toBeTruthy()
    expect(apiClient.get).toHaveBeenCalledWith('/reports/farmers-register/preview/', expect.objectContaining({
      params: expect.objectContaining({ agricultural_year: '1', page: 1 }),
    }))

    fireEvent.click(screen.getByRole('button', { name: 'Download CSV' }))
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/reports/farmers-register/export/', expect.objectContaining({
      params: expect.objectContaining({ file_format: 'csv' }),
      responseType: 'blob',
    })))
    fireEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/reports/farmers-register/export/', expect.objectContaining({
      params: expect.objectContaining({ file_format: 'pdf' }),
    })))
    expect(screen.getByText('Asset quantity is not stored.')).toBeTruthy()
  })
})
