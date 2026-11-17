import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import CropCataloguePage from './CropCataloguePage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
vi.mock('../auth', () => ({ useAuth: () => ({ can: () => true, profile: { role: 'super_admin' } }) }))

const programmes = [
  { id: 1, name: 'ARDA', season_name: '2026/2027', crops: [5, 6], input_categories: ['SEED', 'FERTILIZER'], input_category_labels: ['Seed', 'Fertilizer'], capacity_status: 'ACTIVE' },
  { id: 2, name: 'Seed Co', season_name: '2026/2027', crops: [5], input_categories: ['SEED'], input_category_labels: ['Seed'], capacity_status: 'ACTIVE' },
]
const crops = [{ id: 5, name: 'Maize' }, { id: 6, name: 'Sorghum' }, { id: 7, name: 'Wheat' }]

beforeEach(() => {
  vi.clearAllMocks()
  apiClient.get.mockImplementation((url, config = {}) => {
    const params = config.params || {}
    if (url === '/programmes/') return Promise.resolve({ data: { results: programmes } })
    if (url === '/crops/') return Promise.resolve({ data: { results: crops } })
    if (url === '/inputs/') return Promise.resolve({ data: { results: [{ id: 30, name: 'Compound D', category: 'FERTILIZER', unit: 'kg' }] } })
    if (url === '/seasons/') return Promise.resolve({ data: { results: [{ id: 1, name: '2026/2027', selectable: true }] } })
    if (url === '/crop-input-requirements/' && params.programme === 'none') return Promise.resolve({ data: { results: [] } })
    if (url === '/crop-input-requirements/') {
      return Promise.resolve({ data: { results: [
        { id: 11, input_category: 'FERTILIZER', input_product: 30, input_product_name: 'Compound D', rate_per_hectare: '400.0000', unit: 'kg', cost_per_unit: '0.6400', pack_label: '50 kg bag', pack_size: '50.0000', pack_price: '32.0000', cost_per_hectare: '256.0000', active: true },
      ] } })
    }
    if (url.startsWith('/crop-selling-prices/')) return Promise.resolve({ data: [{ id: 8, season: 1, season_name: '2026/2027', price_per_tonne: '400.0000', currency: 'USD', active: true }] })
    return Promise.resolve({ data: { results: [] } })
  })
})

describe('Crop catalogue', () => {
  it('starts from a programme and shows only its crops and input types, with pack prices', async () => {
    render(<CropCataloguePage />)
    expect(await screen.findByText('Choose a programme')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Programme/ }))
    fireEvent.mouseDown(await screen.findByRole('option', { name: 'ARDA · 2026/2027' }))
    expect(await screen.findByRole('tab', { name: 'Maize' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Sorghum' })).toBeTruthy()
    expect(screen.queryByRole('tab', { name: 'Wheat' })).toBeNull()
    expect(await screen.findByText('Editing ARDA · Maize')).toBeTruthy()
    // ARDA supplies seed and fertilizer only.
    expect(await screen.findByRole('heading', { name: 'Fertilizer' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Chemicals' })).toBeNull()
    expect(await screen.findByText('$0.64 / kg')).toBeTruthy()
    expect(screen.getByText('$32.00 per 50 kg bag')).toBeTruthy()
    expect(screen.getAllByText('$256.00').length).toBeGreaterThan(0)
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/crop-input-requirements/', expect.objectContaining({ params: expect.objectContaining({ crop: 5, programme: 1 }) })))
    // The selling price per tonne stays at the bottom of the page.
    expect(await screen.findByText('400.00')).toBeTruthy()
  })
})
