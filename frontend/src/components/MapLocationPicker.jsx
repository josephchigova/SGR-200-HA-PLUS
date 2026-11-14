import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import Icon from './Icon'
import { Modal } from './ui'

const ZIMBABWE = [-19.015438, 29.154857]

const pin = L.divIcon({
  className: 'location-pin-wrap',
  html: '<span class="location-pin"></span>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
})

function pointFrom(latitude, longitude) {
  if (String(latitude ?? '').trim() === '' || String(longitude ?? '').trim() === '') return null
  const lat = Number(latitude)
  const lng = Number(longitude)
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null
  return [lat, lng]
}

function MapDialog({ latitude, longitude, onClose, onSelect }) {
  const node = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)
  const placeRef = useRef(() => {})
  const [point, setPoint] = useState(() => pointFrom(latitude, longitude))
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')

  useEffect(() => {
    const container = node.current
    if (!container) return undefined
    if (container._leaflet_id) container._leaflet_id = undefined
    const start = pointFrom(latitude, longitude)
    const map = L.map(container, { zoomControl: true }).setView(start || ZIMBABWE, start ? 15 : 6)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap',
      maxZoom: 19,
    }).addTo(map)
    mapRef.current = map

    const place = (lat, lng, zoom) => {
      const latlng = L.latLng(lat, lng)
      if (!markerRef.current) {
        markerRef.current = L.marker(latlng, { icon: pin, draggable: true }).addTo(map)
        markerRef.current.on('dragend', () => {
          const next = markerRef.current.getLatLng()
          setPoint([next.lat, next.lng])
        })
      } else {
        markerRef.current.setLatLng(latlng)
      }
      map.setView(latlng, zoom || Math.max(map.getZoom(), 14))
      setPoint([lat, lng])
    }
    placeRef.current = place
    map.on('click', (event) => place(event.latlng.lat, event.latlng.lng))
    if (start) place(start[0], start[1], 15)

    const timer = window.setTimeout(() => map.invalidateSize(), 80)
    return () => {
      window.clearTimeout(timer)
      map.remove()
      mapRef.current = null
      markerRef.current = null
      placeRef.current = () => {}
    }
    // The map is created for the coordinates present when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const searchPlace = async (event) => {
    event.preventDefault()
    const text = query.trim()
    if (text.length < 2) return
    setSearching(true)
    setSearchError('')
    try {
      const response = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&countrycodes=zw&limit=5&q=${encodeURIComponent(text)}`, {
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) throw new Error('search failed')
      const rows = await response.json()
      const list = Array.isArray(rows) ? rows : []
      setResults(list)
      if (!list.length) setSearchError('No matching place in Zimbabwe. Click the map instead.')
    } catch {
      setResults([])
      setSearchError('Place search is unavailable. Click the map to choose the location.')
    } finally {
      setSearching(false)
    }
  }

  return (
    <Modal
      wide
      title="Select the farm on the map"
      subtitle="Search for a place, or click the map to drop a pin. Drag the pin if it needs to move."
      onClose={onClose}
      footer={(
        <>
          <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="primary-btn"
            disabled={!point}
            onClick={() => onSelect({ latitude: point[0].toFixed(6), longitude: point[1].toFixed(6) })}
          >
            Use this location
          </button>
        </>
      )}
    >
      <form className="location-search" onSubmit={searchPlace}>
        <label>
          Search a place
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ward, village or landmark" />
        </label>
        <button type="submit" className="ghost-btn" disabled={searching || query.trim().length < 2}>{searching ? 'Searching…' : 'Search'}</button>
      </form>
      {searchError ? <p className="field-hint" role="status">{searchError}</p> : null}
      {results.length ? (
        <ul className="location-results">
          {results.map((result) => (
            <li key={result.place_id}>
              <button
                type="button"
                onClick={() => {
                  placeRef.current(Number(result.lat), Number(result.lon), 16)
                  setResults([])
                }}
              >
                {result.display_name}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div ref={node} className="location-map" role="application" aria-label="Farm map" />
      <p className="field-hint">{point ? `${point[0].toFixed(6)}, ${point[1].toFixed(6)}` : 'No point chosen yet.'}</p>
    </Modal>
  )
}

function MapLocationPicker({ latitude, longitude, onSelect }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button type="button" className="ghost-btn small" onClick={() => setOpen(true)}>
        <Icon name="map" />Select on map
      </button>
      {open ? (
        <MapDialog
          latitude={latitude}
          longitude={longitude}
          onClose={() => setOpen(false)}
          onSelect={(coords) => {
            onSelect(coords)
            setOpen(false)
          }}
        />
      ) : null}
    </>
  )
}

export default MapLocationPicker
