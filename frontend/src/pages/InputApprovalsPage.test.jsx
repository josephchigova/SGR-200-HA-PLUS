import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import InputApprovalsPage from './InputApprovalsPage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('../auth', () => ({ useAuth: () => ({ can: () => true, profile: { role: 'super_admin' } }) }))

const crops = [{
  crop: 5, crop_name: 'Maize', hectares: '12.00',
  categories: [{ input_category: 'SEED', input_category_label: 'Seed', hectares: '12.00' }],
  varieties: [{ requirement: 11, input_category: 'SEED', input_category_label: 'Seed', product_name: 'Mbizi', hectares: '12.00', quantity: '300.00', unit: 'kg', estimated_cost: '600.00', farmers: 2, approved_hectares: null }],
}]

const submission = (changes = {}) => ({
  id: 4, reference: 'LF00004', lead_farmer_name: 'Lead One', programme: 2, programme_name: 'ARDA', season_name: '2026/2027', crop_season_label: 'Summer',
  stage: 'REQUEST', status: 'SUBMITTED', status_label: 'Submitted', farmer_count: 2, allocation_count: 2, hectares_total: '12.00',
  requested_hectares: '12.00', approved_hectares: null, remaining_hectares: null, estimated_cost: '600.00', submitted_at: '2026-11-01T08:00:00Z',
  limits: [], crops, events: [], allocations: [], decision_notes: '', ...changes,
})

const summary = {
  counts: { SUBMITTED: 1, LIMITS_SET: 0, CONFIRMATION: 0, APPROVED: 0 },
  lead_farmers: [{ id: 4, lead_farmer_name: 'Lead One', programme_name: 'ARDA', farmer_count: 2, requested_hectares: '12.00', approved_hectares: null, difference_hectares: null, distributed_hectares: '12.00', status_label: 'Submitted' }],
  varieties: [],
}

let rows = []
beforeEach(() => {
  vi.clearAllMocks()
  rows = [submission()]
  apiClient.get.mockImplementation((url) => Promise.resolve({ data: url.includes('consolidated') ? summary : rows }))
})

const renderPage = () => render(<InputApprovalsPage selectedSeason={{ id: 3, name: '2026/2027' }} cropSeason="SUMMER" periodStatus="ready" />)

describe('InputApprovalsPage', () => {
  it('sets a maximum below the requested hectares at crop, input type and variety level', async () => {
    apiClient.post.mockResolvedValue({ data: submission({ stage: 'DISTRIBUTION', status: 'LIMITS_SET', status_label: 'Approved limits issued', approved_hectares: '10.00' }) })
    renderPage()
    expect(await screen.findByText(/1 awaiting hectare decisions/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))
    fireEvent.click(screen.getByRole('button', { name: 'Set maximum hectares' }))
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Approved hectares for Maize' }), { target: { value: '10' } })
    // Lowering the crop brings the input type and variety under it down too.
    expect(screen.getByRole('spinbutton', { name: 'Approved hectares for Maize seed' }).value).toBe('10')
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Approved hectares for Mbizi' }), { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Issue maximum hectares' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-supply-requests/4/set-hectares/', {
      mode: 'distribute',
      limits: [
        { scope: 'CROP', crop: 5, input_category: undefined, requirement: undefined, approved_hectares: '10' },
        { scope: 'CATEGORY', crop: 5, input_category: 'SEED', requirement: undefined, approved_hectares: '10' },
        { scope: 'VARIETY', crop: 5, input_category: undefined, requirement: 11, approved_hectares: '9' },
      ],
    }))
    expect(await screen.findByText('Maximum hectares issued to Lead One.')).toBeTruthy()
  })

  it('approves a submission as it is in one step', async () => {
    apiClient.post.mockResolvedValue({ data: submission({ status: 'APPROVED', status_label: 'Approved', approved_hectares: '12.00' }) })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Review' }))
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(screen.getByText(/Lead One can keep sending new submissions/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-supply-requests/4/approve/', { remarks: '' }))
    expect(await screen.findByText('LF00004 approved. 2 farmer allocations are official.')).toBeTruthy()
  })

  it('needs a reason to return or reject, and gives the final approval to a distribution', async () => {
    rows = [submission({ stage: 'DISTRIBUTION', status: 'CONFIRMATION', status_label: 'Final distribution submitted', approved_hectares: '12.00' })]
    apiClient.post.mockResolvedValue({ data: { ...rows[0], status: 'RETURNED', status_label: 'Returned for corrections' } })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Review' }))
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Final approval' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Return for corrections' }))
    const confirm = screen.getByRole('button', { name: 'Confirm' })
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Split Mbizi more evenly' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-supply-requests/4/return-for-corrections/', { remarks: 'Split Mbizi more evenly' }))
    expect(await screen.findByText('LF00004 returned to Lead One.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Final approval' })).toBeNull()
  })
})
