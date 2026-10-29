const DECIMAL_PAIR = /^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/
const DMS_PART = /(-?\d+(?:\.\d+)?)(?:\s*[°º]\s*)(\d+(?:\.\d+)?)?(?:\s*[′']\s*)?(\d+(?:\.\d+)?)?(?:\s*[″"]\s*)?\s*([NSEW])/gi
const URL_AT = /@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/
const URL_QUERY = /[?&](?:q|query|ll)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/i

export function formatCoordinate(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  const rounded = Math.round(number * 1000000) / 1000000
  return String(rounded)
}

export function coordinateError(latitude, longitude) {
  const latitudeEmpty = latitude === undefined || latitude === null || String(latitude).trim() === ''
  const longitudeEmpty = longitude === undefined || longitude === null || String(longitude).trim() === ''
  if (latitudeEmpty && longitudeEmpty) return ''
  if (latitudeEmpty || longitudeEmpty) return 'Enter both latitude and longitude, or leave both empty.'
  const latitudeNumber = Number(latitude)
  const longitudeNumber = Number(longitude)
  if (!Number.isFinite(latitudeNumber) || !Number.isFinite(longitudeNumber)) return 'Latitude and longitude must be numbers.'
  if (latitudeNumber < -90 || latitudeNumber > 90) return 'Latitude must be between -90 and 90.'
  if (longitudeNumber < -180 || longitudeNumber > 180) return 'Longitude must be between -180 and 180.'
  return ''
}

export function googleMapsUrl(latitude, longitude) {
  if (coordinateError(latitude, longitude)) return ''
  const latitudeNumber = Number(latitude)
  const longitudeNumber = Number(longitude)
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(latitudeNumber)},${encodeURIComponent(longitudeNumber)}`
}

function fromDms(degrees, minutes = 0, seconds = 0, hemisphere) {
  const absolute = Math.abs(Number(degrees)) + (Number(minutes) / 60) + (Number(seconds) / 3600)
  const negative = hemisphere === 'S' || hemisphere === 'W' || String(degrees).startsWith('-')
  return negative ? -absolute : absolute
}

function parseDms(text) {
  const matches = [...text.matchAll(DMS_PART)]
  if (matches.length !== 2) return null
  const [latitudePart, longitudePart] = matches
  const latitudeHemisphere = latitudePart[4].toUpperCase()
  const longitudeHemisphere = longitudePart[4].toUpperCase()
  if (!'NS'.includes(latitudeHemisphere) || !'EW'.includes(longitudeHemisphere)) return { ambiguous: true }
  return {
    latitude: fromDms(latitudePart[1], latitudePart[2], latitudePart[3], latitudeHemisphere),
    longitude: fromDms(longitudePart[1], longitudePart[2], longitudePart[3], longitudeHemisphere),
  }
}

function parseUrl(text) {
  const looksLikeUrl = /google\.[^\s/]+\/maps|maps\.google\./i.test(text) || URL_AT.test(text) || URL_QUERY.test(text)
  if (!looksLikeUrl) return null
  const atMatch = text.match(URL_AT)
  const queryMatch = text.match(URL_QUERY)
  if (atMatch && queryMatch && (atMatch[1] !== queryMatch[1] || atMatch[2] !== queryMatch[2])) return { ambiguous: true }
  const match = atMatch || queryMatch
  if (!match) return { invalid: true }
  return { latitude: Number(match[1]), longitude: Number(match[2]) }
}

export function parseCoordinates(input) {
  const text = String(input || '').trim()
  if (!text) return { error: 'Paste the coordinates copied from Google Maps.' }
  const url = parseUrl(text)
  const dms = parseDms(text)
  const decimalMatch = text.match(DECIMAL_PAIR)
  const decimal = decimalMatch ? { latitude: Number(decimalMatch[1]), longitude: Number(decimalMatch[2]) } : null
  if (url?.ambiguous || dms?.ambiguous || url?.invalid) {
    return { error: 'These coordinates are ambiguous. Paste one latitude and one longitude.' }
  }
  const found = [url, dms, decimal].filter((item) => item && !item.ambiguous && !item.invalid)
  if (found.length === 0) return { error: 'Use latitude, longitude, degrees and minutes, or a Google Maps link.' }
  const first = found[0]
  const disagrees = found.some((item) => formatCoordinate(item.latitude) !== formatCoordinate(first.latitude) || formatCoordinate(item.longitude) !== formatCoordinate(first.longitude))
  if (disagrees) return { error: 'These coordinates are ambiguous. Paste one latitude and one longitude.' }
  const error = coordinateError(first.latitude, first.longitude)
  if (error) return { error }
  return { latitude: formatCoordinate(first.latitude), longitude: formatCoordinate(first.longitude) }
}
