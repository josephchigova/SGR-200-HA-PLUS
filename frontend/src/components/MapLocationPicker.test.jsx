import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import MapLocationPicker from './MapLocationPicker'

const { map } = vi.hoisted(() => {
  const marker = {
    addTo() { return marker },
    on() { return marker },
    setLatLng() { return marker },
    getLatLng() { return { lat: 0, lng: 0 } },
  }
  const map = {
    marker,
    handlers: {},
    setView() { return map },
    on(event, handler) { map.handlers[event] = handler },
    remove() {},
    invalidateSize() {},
    getZoom() { return 6 },
  }
  return { map }
})

vi.mock('leaflet', () => ({
  default: {
    map: () => map,
    tileLayer: () => ({ addTo() {} }),
    marker: () => map.marker,
    latLng: (lat, lng) => ({ lat, lng }),
    circleMarker: () => ({ addTo() { return this }, bindTooltip() { return this }, setLatLng() { return this } }),
    divIcon: () => ({}),
  },
}))

describe('MapLocationPicker', () => {
  it('fills the coordinates from a point chosen on the map', async () => {
    const onSelect = vi.fn()
    render(<MapLocationPicker latitude="" longitude="" onSelect={onSelect} />)

    fireEvent.click(screen.getByRole('button', { name: 'Select on map' }))
    expect(screen.getByRole('dialog', { name: 'Select the farm on the map' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Use this location' }).disabled).toBe(true)

    map.handlers.click({ latlng: { lat: -17.8252, lng: 31.0335 } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Use this location' }).disabled).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: 'Use this location' }))

    expect(onSelect).toHaveBeenCalledWith({ latitude: '-17.825200', longitude: '31.033500' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('replaces the point on a second click, and the device location never overrides it', async () => {
    const onSelect = vi.fn()
    const setView = vi.spyOn(map, 'setView')
    const geolocation = { getCurrentPosition: (success) => success({ coords: { latitude: -20.1, longitude: 28.5 } }) }
    Object.defineProperty(navigator, 'geolocation', { value: geolocation, configurable: true })
    render(<MapLocationPicker latitude="-17.000000" longitude="31.000000" onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Select on map' }))

    map.handlers.click({ latlng: { lat: -18.1, lng: 30.2 } })
    map.handlers.click({ latlng: { lat: -18.25, lng: 30.45 } })
    fireEvent.click(screen.getByRole('button', { name: 'Go to my location' }))
    expect(setView).toHaveBeenCalledWith({ lat: -20.1, lng: 28.5 }, 14)
    await waitFor(() => expect(screen.getByText('Selected point: -18.250000, 30.450000')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Use this location' }))
    expect(onSelect).toHaveBeenCalledWith({ latitude: '-18.250000', longitude: '30.450000' })
  })
})
