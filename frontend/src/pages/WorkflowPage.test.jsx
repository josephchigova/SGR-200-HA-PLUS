import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
    expect(screen.queryByRole('columnheader', { name: 'Status' })).toBeNull()
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

  it('fetches the crop price and recalculates expected tonnes without mixing debts', async () => {
    apiClient.post.mockResolvedValue({ data: { id: 1 } })
    apiClient.get.mockImplementation((url) => {
      if (url.startsWith('/deliveries/recovery-preview/')) {
        const params = new URL(url, 'http://local').searchParams
        if (params.get('crop') === 'Wheat') {
          return Promise.reject({ response: { data: { price: ['Wheat has no configured price per tonne for 2026/2027. Configure the price in the Crop Catalogue before recording this delivery.'] } } })
        }
        if (params.get('farmer') === '4') {
          return Promise.resolve({ data: { crop: 'Maize', price_per_tonne: '400.00', outstanding_input_debt: '100.00', expected_recovery_tonnes: '0.250' } })
        }
        return Promise.resolve({ data: { crop: 'Maize', price_per_tonne: '400.00', outstanding_input_debt: '2000.00', expected_recovery_tonnes: '5.000' } })
      }
      if (url.startsWith('/farmers/?')) {
        const farmer = decodeURIComponent(url).toLowerCase().includes('rudo')
          ? { id: 4, full_name: 'Rudo Dube' }
          : { id: 9, full_name: 'Yusufu Banda' }
        return Promise.resolve({ data: { results: [farmer] } })
      }
      if (url.startsWith('/farmers/')) return Promise.resolve({ data: { id: 9, full_name: 'Yusufu Banda' } })
      if (url.startsWith('/farms/')) {
        const farmer = new URL(url, 'http://local').searchParams.get('farmer')
        return Promise.resolve({ data: farmer === '4' ? [] : [{ id: 3, farm_name: 'Victoria', farmer: 9 }] })
      }
      if (url.startsWith('/crops/')) {
        return Promise.resolve({ data: [
          { id: 1, name: 'Maize', category: 'SUMMER', active: true },
          { id: 2, name: 'Wheat', category: 'SUMMER', active: true },
        ] })
      }
      return Promise.resolve({ data: [] })
    })

    apiClient.post.mockClear()
    const user = userEvent.setup()
    render(<WorkflowPage title="GMB Deliveries" endpoint="/deliveries/" columns={[]} forms={workflowPages.deliveries.forms} selectedSeason={{ id: 1, name: '2026/2027' }} cropSeason="" />)

    await user.type(screen.getByLabelText('Farmer'), 'Yusufu')
    await user.click(await screen.findByRole('option', { name: /Yusufu Banda/ }))
    await user.selectOptions(await screen.findByLabelText('Farm'), '3')
    await user.selectOptions(screen.getByLabelText('Crop'), 'Maize')

    const price = await screen.findByLabelText('Price per tonne')
    expect(price.value).toBe('400.00')
    expect(price.readOnly).toBe(true)
    const debt = screen.getByLabelText('Outstanding input debt')
    expect(debt.value).toBe('2000.00')
    expect(debt.readOnly).toBe(true)
    const expected = screen.getByLabelText('Expected tonnes to recover')
    expect(expected.value).toBe('5.000')
    expect(expected.readOnly).toBe(true)
    expect(screen.getByLabelText('Season').value).toBe('2026/2027')

    fireEvent.change(screen.getByLabelText('Delivery date'), { target: { value: '2027-04-20' } })
    fireEvent.change(screen.getByLabelText('GMB depot'), { target: { value: 'GMB Gweru' } })
    fireEvent.change(screen.getByLabelText('Ticket number'), { target: { value: 'GMB-20' } })
    fireEvent.change(screen.getByLabelText('Tonnes delivered'), { target: { value: '2' } })

    await user.selectOptions(screen.getByLabelText('Crop'), 'Wheat')
    expect((await screen.findByRole('alert')).textContent).toMatch(/no configured price per tonne/i)
    expect(screen.getByLabelText('Price per tonne').value).toBe('')
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }).closest('form'))
    expect(apiClient.post).not.toHaveBeenCalled()

    await user.selectOptions(screen.getByLabelText('Crop'), 'Maize')
    expect((await screen.findByLabelText('Outstanding input debt')).value).toBe('2000.00')
    await user.selectOptions(screen.getByLabelText('Farm'), '3')
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }).closest('form'))
    await waitFor(() => expect(apiClient.post).toHaveBeenCalled())
    const payload = apiClient.post.mock.calls.at(-1)[1]
    expect(payload.price).toBeUndefined()
    expect(payload.outstanding_input_debt).toBeUndefined()
    expect(payload.expected_recovery_tonnes).toBeUndefined()
    expect(payload.tonnes).toBe('2')
    expect(payload.recovery_tonnes).toBe('0')
    expect(payload.crop).toBe('Maize')
    expect(payload.farmer).toBe('9')
    expect(payload.farm).toBe('3')
    expect(payload.season).toBe(1)
    expect(payload.ticket_number).toBe('GMB-20')

    await user.click(screen.getByRole('button', { name: 'Clear selected farmer' }))
    await user.type(screen.getByLabelText('Farmer'), 'Rudo')
    await user.click(await screen.findByRole('option', { name: /Rudo Dube/ }))
    await user.selectOptions(screen.getByLabelText('Crop'), 'Maize')
    expect((await screen.findByLabelText('Outstanding input debt')).value).toBe('100.00')
    expect(screen.getByLabelText('Expected tonnes to recover').value).toBe('0.250')
    expect(screen.getByLabelText('Price per tonne').value).toBe('400.00')
  })
})