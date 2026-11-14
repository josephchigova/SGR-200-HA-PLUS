import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import RegisterFarmerPage from './RegisterFarmerPage'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

const documents = [
  { code: 'NATIONAL_ID', label: 'National ID copy', required: true, hint: 'Identity' },
  { code: 'PROOF_OF_LAND', label: 'Proof of land', required: true, hint: 'Land' },
]

const farmer = {
  id: 21,
  first_name: 'BLESSED',
  middle_name: 'BINDURA',
  surname: 'GEZA',
  national_id: '63-2330173E58',
  phone_primary: '0771234567',
  email: 'blessed@example.com',
  gender: '',
  farmer_type: 'NEW',
  province: 1,
  district: 2,
  ward_name: 'Ward 1',
  cluster: 4,
  cluster_name: 'TAKUNDA JOSHUA MUTENJE',
  verification_status: 'DRAFT',
  kyc_upload_required: true,
  primary_farm: {
    farm_name: 'GEZA FARMS',
    total_hectares: '100.00',
    arable_hectares: '100.00',
    irrigated_hectares: '100.00',
    irrigation_type: 'CENTRE_PIVOT',
    latitude: '-17.835622',
    longitude: '31.021466',
  },
  crop_allocations: [{ id: 1, crop: 5, season: 8, hectares: '80' }],
}

function uploaded(codes) {
  return codes.map((code) => ({
    id: code,
    document_type: code,
    label: documents.find((item) => item.code === code).label,
    file_name: `${code}.png`,
    review_status: 'PENDING',
  }))
}

function mockGets({ kyc = true, files = ['NATIONAL_ID', 'PROOF_OF_LAND'] } = {}) {
  apiClient.get.mockImplementation((url) => {
    const data = (() => {
      if (String(url).includes('registration-context')) {
        return { locked: false, cluster: { id: 4, name: 'TAKUNDA JOSHUA MUTENJE' }, province: { id: 1, name: 'Midlands' }, documents, max_upload_mb: 10, kyc_upload: kyc }
      }
      if (String(url).startsWith('/provinces')) return [{ id: 1, name: 'Midlands' }]
      if (String(url).startsWith('/crops')) return [{ id: 5, name: 'Maize' }]
      if (String(url).startsWith('/seasons')) return [{ id: 8, name: '2026/2027 Summer' }]
      if (String(url).startsWith('/districts')) return [{ id: 2, name: 'Gweru' }]
      if (String(url).startsWith('/farmer-documents')) return uploaded(files)
      if (String(url).startsWith('/farmers/21')) return { ...farmer, kyc_upload_required: kyc }
      return []
    })()
    return Promise.resolve({ data })
  })
}

function renderWizard() {
  return render(
    <MemoryRouter initialEntries={['/farmers/21/edit']}>
      <Routes>
        <Route path="/farmers/:id/edit" element={<RegisterFarmerPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RegisterFarmerPage submission', () => {
  beforeEach(() => {
    localStorage.clear()
    apiClient.get.mockReset()
    apiClient.post.mockReset()
    apiClient.patch.mockReset()
    apiClient.post.mockResolvedValue({ data: { ...farmer, verification_status: 'SUBMITTED' } })
    apiClient.patch.mockImplementation(() => Promise.resolve({ data: { ...farmer, kyc_upload_required: true, verification_status: 'DRAFT' } }))
  })

  it('submits a complete registration even when farm details were edited after the last save', async () => {
    mockGets()
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: /Review registration/ }))
    const submit = screen.getByRole('button', { name: 'Submit for approval' })
    expect(submit.disabled).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: /Step 2: Farm details/ }))
    fireEvent.change(screen.getByLabelText(/Total farm size/), { target: { value: '120' } })
    fireEvent.click(screen.getByRole('button', { name: /Step 3: Crop allocation/ }))
    fireEvent.click(screen.getByRole('button', { name: /Save and continue/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Review registration/ }))
    const again = screen.getByRole('button', { name: 'Submit for approval' })
    expect(again.disabled).toBe(false)
    fireEvent.click(again)

    await screen.findByText(/awaiting approval/i)
    expect(apiClient.patch).toHaveBeenCalled()
    expect(apiClient.post).toHaveBeenCalledWith('/farmers/21/submit/')
    expect(apiClient.patch.mock.invocationCallOrder[0]).toBeLessThan(apiClient.post.mock.invocationCallOrder[0])
  })

  it('keeps submit unavailable until a lead farmer has uploaded the required documents', async () => {
    mockGets({ files: ['NATIONAL_ID'] })
    renderWizard()
    const review = await screen.findByRole('button', { name: /Review registration/ })
    expect(review.disabled).toBe(true)
    expect(screen.getByText(/Still needed: Proof of land/)).toBeTruthy()
  })

  it('completes an administrator registration without any KYC upload', async () => {
    mockGets({ kyc: false, files: [] })
    apiClient.patch.mockImplementation(() => Promise.resolve({ data: { ...farmer, kyc_upload_required: false, verification_status: 'VERIFIED' } }))
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: /Save and continue/ }))
    const complete = await screen.findByRole('button', { name: 'Complete registration' })
    expect(complete.disabled).toBe(false)
    expect(screen.getByText(/No KYC files are required/)).toBeTruthy()
    expect(screen.queryByText(/Still needed/)).toBeNull()
  })
})
