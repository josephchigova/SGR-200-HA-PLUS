import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import WorkflowPage from './WorkflowPage'
import { workflowPages } from './workflowConfig'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

describe('WorkflowPage', () => {
  it('submits an ARDA batch using the selected global season without asking for a request number', async () => {
    apiClient.get.mockImplementation((url) => Promise.resolve({
      data: url.startsWith('/programmes/') ? [{ id: 17, name: 'SGR Programme' }] : [],
    }))
    apiClient.post.mockResolvedValue({ data: { id: 12 } })
    const arda = workflowPages.arda

    render(
      <WorkflowPage
        title={arda.title}
        endpoint={arda.endpoint}
        columns={arda.columns}
        forms={[arda.forms[0]]}
        selectedSeason={{ id: 8, name: '2026/2027' }}
        seasonScoped
      />,
    )

    expect(screen.queryByLabelText('Request number')).toBeNull()
    expect(screen.queryByLabelText('Season')).toBeNull()
    expect(await screen.findByRole('option', { name: 'SGR Programme' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Requested hectares'), { target: { value: '125.50' } })
    fireEvent.change(screen.getByLabelText('Programme'), { target: { value: '17' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Create batch' }).closest('form'))

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/arda-request-batches/', {
      programme: '17',
      requested_hectares: '125.50',
      season: 8,
    }))
  })

  it('shows the season-specific paid subscription roster without a manual add-farmer form', async () => {
    apiClient.get.mockImplementation((url) => {
      if (url.startsWith('/farmers/eligible/')) {
        return Promise.resolve({ data: { results: [{
          id: 52,
          full_name: 'Tariro Moyo',
          membership_number: 'SGR-000052',
          national_id: '63-7654321-X-11',
          phone_primary: '0777654321',
          district_name: 'Gweru',
          subscription_status: 'PAID',
        }, {
          id: 53,
          full_name: 'Rudo Dube',
          membership_number: 'SGR-000053',
          national_id: '63-7654322-X-11',
          phone_primary: '0777654322',
          district_name: 'Gweru',
          subscription_status: 'PARTIALLY_PAID',
        }], next: null } })
      }
      return Promise.resolve({ data: [] })
    })
    const arda = workflowPages.arda

    render(
      <WorkflowPage
        title={arda.title}
        endpoint={arda.endpoint}
        columns={arda.columns}
        forms={arda.forms}
        eligibleEndpoint={arda.eligibleEndpoint}
        eligibleTitle={arda.eligibleTitle}
        eligibleColumns={arda.eligibleColumns}
        selectedSeason={{ id: 8, name: '2026/2027' }}
        seasonScoped
      />,
    )

    expect(await screen.findByRole('cell', { name: 'Tariro Moyo' })).toBeTruthy()
    expect(screen.getByRole('cell', { name: 'PAID' })).toBeTruthy()
    expect(screen.getByRole('cell', { name: 'PARTIALLY_PAID' })).toBeTruthy()
    expect(screen.getByText('2 farmers')).toBeTruthy()
    expect(document.querySelector('.eligible-farmers-scroll')).toBeTruthy()
    expect(screen.queryByText('Add subscription-eligible farmer')).toBeNull()
    expect(screen.queryByRole('combobox', { name: 'Eligible farmer' })).toBeNull()
    expect(apiClient.get).toHaveBeenCalledWith(expect.stringContaining('/farmers/eligible/?season=8&season_name=2026%2F2027'))
  })

  it('does not let a slow previous season replace the newly selected season', async () => {
    const columns = [{ key: 'farmer_name', label: 'Farmer' }]
    const forms = []
    let resolveSummer
    apiClient.get.mockImplementation((url) => {
      if (url.includes('crop_season=WINTER')) return Promise.resolve({ data: [{ id: 2, farmer_name: 'Winter Farmer' }] })
      if (url.includes('crop_season=SUMMER')) {
        return new Promise((resolve) => {
          resolveSummer = () => resolve({ data: [{ id: 1, farmer_name: 'Summer Farmer' }] })
        })
      }
      return Promise.resolve({ data: [] })
    })
    const season = { id: 8, name: '2026/2027', status: 'ACTIVE' }
    const { rerender } = render(
      <WorkflowPage title="Production" endpoint="/farmer-productions/" columns={columns} forms={forms} selectedSeason={season} cropSeason="SUMMER" seasonScoped />,
    )
    rerender(
      <WorkflowPage title="Production" endpoint="/farmer-productions/" columns={columns} forms={forms} selectedSeason={season} cropSeason="WINTER" seasonScoped />,
    )

    expect(await screen.findByRole('cell', { name: 'Winter Farmer' })).toBeTruthy()
    resolveSummer()
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith(expect.stringContaining('crop_season=SUMMER')))
    expect(screen.queryByRole('cell', { name: 'Summer Farmer' })).toBeNull()
    expect(screen.getByRole('cell', { name: 'Winter Farmer' })).toBeTruthy()
  })
})