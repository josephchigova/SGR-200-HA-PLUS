import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AppShell } from './App'
import apiClient from './api/client'

vi.mock('./api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

const currentYear = {
  id: 1,
  name: '2026/2027',
  status: 'ACTIVE',
  is_current: true,
  crop_seasons: [
    { code: 'SUMMER', label: 'Summer' },
    { code: 'WINTER', label: 'Winter' },
  ],
}
const olderYear = {
  id: 2,
  name: '2025/2026',
  status: 'CLOSED',
  is_current: false,
  crop_seasons: [{ code: 'SUMMER', label: 'Summer' }],
}

const renderShell = () => render(
  <MemoryRouter initialEntries={['/dashboard']}>
    <AppShell />
  </MemoryRouter>,
)

describe('agricultural year and season selectors', () => {
  beforeEach(() => {
    localStorage.clear()
    apiClient.get.mockImplementation((url) => {
      if (url.startsWith('/seasons/current/')) {
        return Promise.resolve({
          data: {
            agricultural_year: currentYear,
            crop_season: 'WINTER',
            crop_season_label: 'Winter',
          },
        })
      }
      if (url.startsWith('/seasons/')) return Promise.resolve({ data: { results: [currentYear, olderYear], next: null } })
      return Promise.resolve({ data: { results: [], next: null } })
    })
  })

  it('selects the current period from the backend and keeps it across navigation', async () => {
    renderShell()
    const year = await screen.findByLabelText('Agricultural year')
    const season = screen.getByLabelText('Season')
    expect(year.value).toBe('1')
    expect(season.value).toBe('WINTER')
    expect(screen.getByRole('option', { name: '2026/2027' })).toBeTruthy()
    expect(screen.getByRole('option', { name: 'Summer' })).toBeTruthy()

    fireEvent.click(screen.getByRole('link', { name: 'Farmers' }))
    expect(screen.getByLabelText('Agricultural year').value).toBe('1')
    expect(screen.getByLabelText('Season').value).toBe('WINTER')
  })

  it('updates seasons for another year, then restores the manual choice after refresh', async () => {
    const { unmount } = renderShell()
    const year = await screen.findByLabelText('Agricultural year')
    fireEvent.change(year, { target: { value: '2' } })
    expect(screen.getByLabelText('Season').value).toBe('SUMMER')
    expect(screen.queryByRole('option', { name: 'Winter' })).toBeNull()
    expect(screen.getByRole('status').textContent).toContain('2025/2026')

    fireEvent.click(screen.getByRole('button', { name: 'Current period' }))
    expect(screen.getByLabelText('Agricultural year').value).toBe('1')
    expect(screen.getByLabelText('Season').value).toBe('WINTER')

    fireEvent.change(screen.getByLabelText('Season'), { target: { value: 'SUMMER' } })
    expect(screen.getByRole('status').textContent).toContain('Historical period')
    unmount()
    renderShell()
    expect((await screen.findByLabelText('Agricultural year')).value).toBe('1')
    expect(screen.getByLabelText('Season').value).toBe('SUMMER')
  })
})