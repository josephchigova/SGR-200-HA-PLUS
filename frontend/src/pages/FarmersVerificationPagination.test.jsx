import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import FarmersPage from './FarmersPage'
import VerificationPage from './VerificationPage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

const pageResponse = ({ count, results, page, pageSize }) => ({
  data: {
    count,
    next: page * pageSize < count ? `http://localhost:8000/api/farmers/?page=${page + 1}` : null,
    previous: page > 1 ? `http://localhost:8000/api/farmers/?page=${page - 1}` : null,
    results,
  },
})

const farmerRow = (id, namePrefix = 'Farmer') => ({
  id,
  full_name: `${namePrefix} ${String(id).padStart(2, '0')}`,
  first_name: namePrefix,
  surname: String(id),
  national_id: `63-TEST-${String(id).padStart(4, '0')}-X-10`,
  membership_number: `SGR-MA-${String(id).padStart(6, '0')}`,
  phone_primary: `0775${String(id).padStart(6, '0')}`,
  province_name: 'Manicaland',
  district_name: 'Mutare',
  cluster_name: 'Cluster A',
  farm_hectares: '12.50',
  membership_status: 'ACTIVE',
  verification_status: 'DRAFT',
})

const verificationRow = (id, fullName, status = 'SUBMITTED') => ({
  id,
  full_name: fullName,
  first_name: fullName.split(' ')[0],
  surname: fullName.split(' ').slice(1).join(' ') || 'Farmer',
  national_id: `63-VERIFY-${String(id).padStart(4, '0')}-X-10`,
  membership_number: `SGR-MA-${String(id).padStart(6, '0')}`,
  province: 4,
  province_name: 'Manicaland',
  district_name: 'Mutare',
  phone_primary: '0772000000',
  membership_status: 'ACTIVE',
  verification_status: status,
})

afterEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe('FarmersPage pagination', () => {
  it('supports previous and next pagination and resets to page 1 when searching', async () => {
    apiClient.get.mockImplementation((url, config = {}) => {
      if (url === '/provinces/') {
        return Promise.resolve({ data: { count: 0, next: null, previous: null, results: [] } })
      }

      if (url === '/farmers/') {
        const page = Number(config?.params?.page || 1)
        const pageSize = Number(config?.params?.page_size || 25)
        const search = config?.params?.search || ''

        if (search === 'Needle') {
          return Promise.resolve(
            pageResponse({
              count: 2,
              page,
              pageSize,
              results: [farmerRow(501, 'Needle'), farmerRow(502, 'Needle')],
            }),
          )
        }

        if (page === 1) {
          return Promise.resolve(pageResponse({
            count: 55,
            page,
            pageSize,
            results: Array.from({ length: 25 }, (_, index) => farmerRow(index + 1)),
          }))
        }
        if (page === 2) {
          return Promise.resolve(pageResponse({
            count: 55,
            page,
            pageSize,
            results: Array.from({ length: 25 }, (_, index) => farmerRow(index + 26)),
          }))
        }
        return Promise.resolve(pageResponse({
          count: 55,
          page,
          pageSize,
          results: Array.from({ length: 5 }, (_, index) => farmerRow(index + 51)),
        }))
      }

      return Promise.resolve({ data: { count: 0, next: null, previous: null, results: [] } })
    })

    render(
      <MemoryRouter>
        <FarmersPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('cell', { name: 'Farmer 01' })).toBeTruthy()
    expect(screen.getByText('55 farmers')).toBeTruthy()
    expect(screen.getByText('Page 1 of 3')).toBeTruthy()

    await new Promise((resolve) => { setTimeout(resolve, 300) })

    const previousButton = screen.getByRole('button', { name: 'Previous' })
    const nextButton = screen.getByRole('button', { name: 'Next' })
    expect(previousButton.disabled).toBe(true)
    expect(nextButton.disabled).toBe(false)

    fireEvent.click(nextButton)
    expect(await screen.findByRole('cell', { name: 'Farmer 26' })).toBeTruthy()
    expect(screen.getByText('Page 2 of 3')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByRole('cell', { name: 'Farmer 51' })).toBeTruthy()
    expect(screen.getByText('Page 3 of 3')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Next' }).disabled).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    expect(await screen.findByRole('cell', { name: 'Farmer 26' })).toBeTruthy()

    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter farmers...' }), { target: { value: 'Needle' } })

    expect(await screen.findByRole('cell', { name: 'Needle 501' })).toBeTruthy()
    expect(screen.getByText('2 farmers')).toBeTruthy()
    expect(screen.queryByText('Page 1 of 1')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Previous' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull()

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        '/farmers/',
        expect.objectContaining({
          params: expect.objectContaining({ search: 'Needle', page: 1, page_size: 25 }),
        }),
      )
    })
  })
})

describe('VerificationPage pagination', () => {
  it('paginates queue data, keeps DRAFT farmers visible, and resets to page 1 when searching', async () => {
    apiClient.get.mockImplementation((url, config = {}) => {
      if (url !== '/farmers/') {
        return Promise.resolve({ data: { count: 0, next: null, previous: null, results: [] } })
      }

      const page = Number(config?.params?.page || 1)
      const pageSize = Number(config?.params?.page_size || 25)
      const search = config?.params?.search || ''

      if (search === 'Draft Queue Farmer') {
        return Promise.resolve(pageResponse({
          count: 1,
          page,
          pageSize,
          results: [verificationRow(1, 'Draft Queue Farmer', 'DRAFT')],
        }))
      }

      if (page === 1) {
        return Promise.resolve(pageResponse({
          count: 50,
          page,
          pageSize,
          results: [
            verificationRow(1, 'Draft Queue Farmer', 'DRAFT'),
            ...Array.from({ length: 24 }, (_, index) => verificationRow(index + 2, `Queue Farmer ${index + 2}`)),
          ],
        }))
      }
      return Promise.resolve(pageResponse({
        count: 50,
        page,
        pageSize,
        results: Array.from({ length: 25 }, (_, index) => verificationRow(index + 26, `Queue Farmer ${index + 26}`, 'UNDER_REVIEW')),
      }))
    })

    render(<VerificationPage />)

    expect(await screen.findByText('Draft Queue Farmer')).toBeTruthy()
    expect(screen.getAllByText('Manicaland').length).toBeGreaterThan(0)
    expect(screen.getByText('50 farmers in queue')).toBeTruthy()
    expect(screen.getByText('Page 1 of 2')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Previous' }).disabled).toBe(true)

    await new Promise((resolve) => { setTimeout(resolve, 300) })

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText('Queue Farmer 26')).toBeTruthy()
    expect(screen.getByText('Page 2 of 2')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Next' }).disabled).toBe(true)

    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter verification queue...' }), {
      target: { value: 'Draft Queue Farmer' },
    })

    expect(await screen.findByText('Draft Queue Farmer')).toBeTruthy()
    expect(screen.getByText('1 farmers in queue')).toBeTruthy()
    expect(screen.queryByText('Page 1 of 1')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Previous' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull()

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        '/farmers/',
        expect.objectContaining({
          params: expect.objectContaining({
            verification_status: 'DRAFT,SUBMITTED,UNDER_REVIEW',
            search: 'Draft Queue Farmer',
            page: 1,
            page_size: 25,
          }),
        }),
      )
    })
  })
})
