import { describe, expect, it } from 'vitest'

import { coordinateError, googleMapsUrl, parseCoordinates } from './coordinates'

describe('farm coordinate parsing', () => {
  it('parses Google Maps decimal coordinates, including negative values', () => {
    expect(parseCoordinates('-17.8252, 31.0335')).toEqual({ latitude: '-17.8252', longitude: '31.0335' })
    expect(parseCoordinates('17.8252 31.0335')).toEqual({ latitude: '17.8252', longitude: '31.0335' })
  })

  it('parses degrees, minutes and seconds without reversing the values', () => {
    const parsed = parseCoordinates(`17°49'30.7"S 31°02'00.6"E`)
    expect(parsed.latitude.startsWith('-17.825')).toBe(true)
    expect(parsed.longitude.startsWith('31.033')).toBe(true)
  })

  it('parses supported Google Maps links', () => {
    expect(parseCoordinates('https://www.google.com/maps/@-17.8252,31.0335,15z')).toEqual({
      latitude: '-17.8252',
      longitude: '31.0335',
    })
    expect(parseCoordinates('https://maps.google.com/maps?q=-17.8252,31.0335')).toEqual({
      latitude: '-17.8252',
      longitude: '31.0335',
    })
  })

  it('rejects ambiguous, incomplete and out-of-range coordinates', () => {
    expect(parseCoordinates('not coordinates').error).toBeTruthy()
    expect(parseCoordinates('-17.8252').error).toBeTruthy()
    expect(parseCoordinates('10, 20, 30').error).toBeTruthy()
    expect(parseCoordinates('91, 31').error).toMatch(/Latitude/)
    expect(coordinateError('-17.8', '')).toMatch(/both/)
    expect(coordinateError('', '')).toBe('')
    expect(coordinateError('91', '31')).toMatch(/Latitude/)
    expect(coordinateError('-17', '181')).toMatch(/Longitude/)
  })

  it('builds a maps link from the numeric coordinates only', () => {
    expect(googleMapsUrl('-17.8252', '31.0335')).toBe('https://www.google.com/maps/search/?api=1&query=-17.8252,31.0335')
    expect(googleMapsUrl('', '31')).toBe('')
    expect(googleMapsUrl('javascript:alert(1)', '31')).toBe('')
  })
})
