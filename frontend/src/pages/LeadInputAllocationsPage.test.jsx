import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import LeadInputAllocationsPage from './LeadInputAllocationsPage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))

const mbizi = {
  requirement: 11, input_category: 'SEED', input_category_label: 'Seed', product_name: 'Mbizi',
  unit: 'kg', rate_per_hectare: '25', unit_price: '2.00', pack_size: null, pack_price: null,
}

const catalogue = {
  farmers: [
    { id: 7, name: 'Tendai Moyo', membership_number: 'F-007', farms: [{ id: 9, name: 'Moyo Farm' }], crops: [{ crop: 5, hectares: '10.00' }] },
    { id: 8, name: 'Rudo Ncube', membership_number: 'F-008', farms: [{ id: 12, name: 'Ncube Farm' }], crops: [{ crop: 5, hectares: '6.00' }] },
  ],
  programmes: [{ programme: 2, programme_name: 'ARDA', crops: [{ crop: 5, crop_name: 'Maize', varieties: [mbizi] }] }],
}

const allocation = {
  id: 31, version: 2, farmer: 7, farmer_name: 'Tendai Moyo', membership_number: 'F-007', crop: 5, crop_name: 'Maize',
  hectares: '8.00', estimated_cost: '400.00',
  lines: [{ id: 1, requirement: 11, input_category: 'SEED', input_category_label: 'Seed', product_name: 'Mbizi', hectares: '8.00', quantity: '200.00', unit: 'kg', rate_per_hectare: '25', estimated_cost: '400.00' }],
}

const submission = (changes = {}) => ({
  id: 4, reference: 'LF00004', programme: 2, programme_name: 'ARDA', stage: 'REQUEST', status: 'DRAFT', status_label: 'Draft',
  editable: true, farmer_count: 1, allocation_count: 1, hectares_total: '8.00', requested_hectares: '8.00', approved_hectares: null,
  remaining_hectares: null, estimated_cost: '400.00', limits: [], crops: [], events: [], allocations: [allocation], ...changes,
})

const season = { id: 3, name: '2026/2027', status: 'ACTIVE' }
let open = []

beforeEach(() => {
  vi.clearAllMocks()
  open = []
  apiClient.get.mockImplementation((url) => Promise.resolve({ data: url.includes('catalogue') ? catalogue : open }))
})

const renderPage = () => render(<LeadInputAllocationsPage selectedSeason={season} cropSeason="SUMMER" periodStatus="ready" />)

describe('LeadInputAllocationsPage', () => {
  it('saves one allocation straight away and sends only the hectares', async () => {
    const saved = submission()
    apiClient.post.mockImplementation(() => { open = [saved]; return Promise.resolve({ status: 201, data: saved }) })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Farmer/ }))
    fireEvent.mouseDown(screen.getByRole('option', { name: 'Tendai Moyo · F-007' }))
    expect(screen.getByText(/intends to plant 10 ha of Maize/)).toBeTruthy()
    // Varieties are searched, then added as rows with the farmer's planting filled in.
    fireEvent.click(screen.getByRole('button', { name: /Varieties and products/ }))
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search Varieties and products' }), { target: { value: 'mbi' } })
    fireEvent.mouseDown(screen.getByRole('option', { name: 'Mbizi · Seed · 25 kg/ha' }))
    expect(screen.getByRole('spinbutton', { name: 'Hectares of Mbizi' }).value).toBe('10')
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares of Mbizi' }), { target: { value: '8' } })
    expect(screen.getByText('200 kg')).toBeTruthy()
    expect(screen.getAllByText('$400.00').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Save allocation' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-supply-requests/allocations/', {
      programme: 2, season: 3, crop_season: 'SUMMER', farmer: 7, crop: 5, lines: [{ requirement: 11, hectares: '8' }],
    }))
    expect(await screen.findByText(/Tendai Moyo’s Maize allocation was saved/)).toBeTruthy()
    expect(within(screen.getByRole('table')).getByText('Tendai Moyo')).toBeTruthy()
    // A farmer already allocated this crop is not offered again.
    fireEvent.click(screen.getByRole('button', { name: /Farmer/ }))
    expect(screen.queryByRole('option', { name: 'Tendai Moyo · F-007' })).toBeNull()
  })

  it('edits with the saved version and deletes through the server', async () => {
    open = [submission()]
    const edited = submission({ allocations: [{ ...allocation, version: 3, hectares: '6.00' }], hectares_total: '6.00' })
    apiClient.patch.mockImplementation(() => { open = [edited]; return Promise.resolve({ data: edited }) })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit Tendai Moyo Maize' }))
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares of Mbizi' }), { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledWith('/input-supply-requests/allocations/31/', { lines: [{ requirement: 11, hectares: '6' }], version: 2 }))

    await screen.findByText('Tendai Moyo’s allocation was updated.')
    apiClient.delete.mockImplementation(() => { open = []; return Promise.resolve({ data: { deleted: true, submission: null } }) })
    fireEvent.click(await screen.findByRole('button', { name: 'Delete Tendai Moyo Maize' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith('/input-supply-requests/allocations/31/', { params: { version: 3 } }))
    expect(await screen.findByText('No allocations yet. Add a farmer above to start this submission.')).toBeTruthy()
  })

  it('shows a conflict and reloads the saved figures instead of overwriting them', async () => {
    open = [submission()]
    apiClient.delete.mockRejectedValue({ response: { status: 409, data: { detail: 'This allocation was changed by someone else.', conflict: true } } })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete Tendai Moyo Maize' }))
    const callsBefore = apiClient.get.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText(/changed by someone else. The latest figures are shown below/)).toBeTruthy()
    await waitFor(() => expect(apiClient.get.mock.calls.length).toBeGreaterThan(callsBefore))
  })

  it('submits the request and locks editing once Admin is reviewing it', async () => {
    open = [submission()]
    apiClient.post.mockImplementation(() => {
      const sent = submission({ status: 'SUBMITTED', status_label: 'Submitted', editable: false })
      open = [sent]
      return Promise.resolve({ data: sent })
    })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Send to Admin' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-supply-requests/4/submit/'))
    expect(await screen.findByText('LF00004 was sent to Admin.')).toBeTruthy()
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Edit Tendai Moyo Maize' })).toBeNull())
  })

  it('opens the next submission once one is with Admin, and keeps the sent one as it was', async () => {
    open = [submission({ status: 'SUBMITTED', status_label: 'Submitted', editable: false })]
    const second = submission({ id: 5, reference: 'LF00005', allocations: [{ ...allocation, id: 40, farmer: 8, farmer_name: 'Rudo Ncube', membership_number: 'F-008' }] })
    apiClient.post.mockImplementation(() => { open = [second, ...open]; return Promise.resolve({ status: 201, data: second }) })
    renderPage()
    // The page starts the next submission straight away.
    expect(await screen.findByText(/Add the farmers for your next submission/)).toBeTruthy()
    // The submitted one is still there, read-only.
    fireEvent.click(screen.getByRole('button', { name: /LF00004 · Submitted/ }))
    expect(screen.getByText(/Admin is reviewing this submission/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Edit Tendai Moyo Maize' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Save allocation' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /New submission/ }))
    fireEvent.click(screen.getByRole('button', { name: /Farmer/ }))
    // A farmer whose crop is already with Admin is not offered again.
    expect(screen.queryByRole('option', { name: 'Tendai Moyo · F-007' })).toBeNull()
    fireEvent.mouseDown(screen.getByRole('option', { name: 'Rudo Ncube · F-008' }))
    fireEvent.click(screen.getByRole('button', { name: /Varieties and products/ }))
    fireEvent.mouseDown(screen.getByRole('option', { name: 'Mbizi · Seed · 25 kg/ha' }))
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Hectares of Mbizi' }), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save allocation' }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-supply-requests/allocations/', {
      programme: 2, season: 3, crop_season: 'SUMMER', farmer: 8, crop: 5, lines: [{ requirement: 11, hectares: '5' }],
    }))
    expect(await screen.findByRole('button', { name: /LF00005 · Draft/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /New submission/ })).toBeNull()
  })

  it('redistributes a maximum in the same submission and sends it back to Admin', async () => {
    const limits = [
      { id: 1, scope: 'CROP', scope_label: 'Crop', crop: 5, input_category: '', requirement: null, name: 'Maize', requested_hectares: '8.00', approved_hectares: '6.00', difference_hectares: '-2.00', distributed_hectares: '8.00', remaining_hectares: '-2.00' },
      { id: 2, scope: 'VARIETY', scope_label: 'Variety', crop: 5, input_category: 'SEED', requirement: 11, name: 'Mbizi', requested_hectares: '8.00', approved_hectares: '6.00', difference_hectares: '-2.00', distributed_hectares: '8.00', remaining_hectares: '-2.00' },
    ]
    const capped = submission({ stage: 'DISTRIBUTION', status: 'LIMITS_SET', status_label: 'Maximum hectares set', hectares_capped: true, requested_hectares: '8.00', approved_hectares: '6.00', remaining_hectares: '-2.00', limits })
    open = [capped]
    const fixed = submission({ ...capped, allocations: [{ ...allocation, version: 3, hectares: '6.00', lines: [{ ...allocation.lines[0], hectares: '6.00', estimated_cost: '300.00' }] }] })
    apiClient.post.mockImplementation((url) => Promise.resolve({ data: url.endsWith('/submit/') ? { ...fixed, status: 'CONFIRMATION', status_label: 'Final distribution submitted', editable: false } : fixed }))
    renderPage()
    // Opens on the same submission's redistribution screen... unless a new one is chosen.
    fireEvent.click(await screen.findByRole('button', { name: /LF00004 · Maximum hectares set/ }))
    expect(screen.getByText(/Admin has reduced the hectares for this submission/)).toBeTruthy()
    const summary = screen.getByLabelText('Redistribution summary')
    expect(within(summary).getByText('Hectares to reduce')).toBeTruthy()
    expect(within(summary).getByText('2 ha')).toBeTruthy()
    expect(screen.getByLabelText('Still to fix').textContent).toContain('Mbizi: reduce by 2 ha')
    const send = screen.getByRole('button', { name: 'Send back to Admin for approval' })
    expect(send.disabled).toBe(true)
    // Typing updates every figure at once.
    fireEvent.change(screen.getByRole('spinbutton', { name: 'New hectares of Mbizi for Tendai Moyo' }), { target: { value: '6' } })
    expect(within(summary).getByText('Remaining')).toBeTruthy()
    expect(within(summary).getByText('$300.00')).toBeTruthy()
    expect(screen.getByText(/Every maximum is met/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Show quantities and costs' }))
    expect(screen.getByText('150 kg')).toBeTruthy()
    // Sending saves the changes together, then sends the same submission back.
    fireEvent.click(send)
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-supply-requests/4/redistribute/', {
      changes: [{ allocation: 31, version: 2, lines: [{ requirement: 11, hectares: '6' }] }],
    }))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/input-supply-requests/4/submit/'))
    expect(await screen.findByText('LF00004 was sent back to Admin for approval.')).toBeTruthy()
  })

  it('starts a new submission for other farmers even while a maximum is being shared out', async () => {
    open = [submission({ stage: 'DISTRIBUTION', status: 'LIMITS_SET', status_label: 'Maximum hectares set', hectares_capped: true, approved_hectares: '6.00', remaining_hectares: '-2.00' })]
    renderPage()
    expect(await screen.findByText(/Admin set maximum hectares on LF00004/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /New submission/ }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'Save allocation' })).toBeTruthy()
  })
})
