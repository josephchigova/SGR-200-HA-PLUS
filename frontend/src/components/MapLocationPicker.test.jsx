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
})
