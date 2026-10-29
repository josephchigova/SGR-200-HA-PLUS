import { useState } from 'react'

import { coordinateError, googleMapsUrl, parseCoordinates } from '../coordinates'

function FarmLocationFields({ latitude, longitude, onChange }) {
  const [paste, setPaste] = useState('')
  const [pasteError, setPasteError] = useState('')
  const fieldError = coordinateError(latitude, longitude)
  const mapsUrl = googleMapsUrl(latitude, longitude)

  const applyPaste = () => {
    const result = parseCoordinates(paste)
    if (result.error) {
      setPasteError(result.error)
      return
    }
    setPasteError('')
    onChange('latitude', result.latitude)
    onChange('longitude', result.longitude)
  }

  return (
    <fieldset className="coordinate-fields">
      <legend>Farm Location Coordinates (Google Maps)</legend>
      <p>
        These coordinates identify the farm or chosen location, not necessarily the farmer&apos;s home address.
        Open Google Maps, find the farmer&apos;s farm location, right-click the location or select the location marker, copy the coordinates, and paste them below.
      </p>
      <div className="form-grid">
        <label className="form-field full-width">
          Paste Google Maps Coordinates
          <input
            name="coordinate_paste"
            value={paste}
            onChange={(event) => setPaste(event.target.value)}
            placeholder="-17.8252, 31.0335"
            aria-describedby="coordinate-help"
          />
        </label>
        <div className="full-width">
          <button type="button" className="ghost-btn small" onClick={applyPaste}>Use pasted coordinates</button>
        </div>
        <label className="form-field">
          Latitude
          <input name="latitude" inputMode="decimal" value={latitude} onChange={(event) => onChange('latitude', event.target.value)} placeholder="-17.8252" />
        </label>
        <label className="form-field">
          Longitude
          <input name="longitude" inputMode="decimal" value={longitude} onChange={(event) => onChange('longitude', event.target.value)} placeholder="31.0335" />
        </label>
      </div>
      <p id="coordinate-help">Coordinates are optional. Leave both fields empty when the location is not available.</p>
      {pasteError || fieldError ? <div className="form-message error" role="alert">{pasteError || fieldError}</div> : null}
      {mapsUrl ? <a className="ghost-btn small" href={mapsUrl} target="_blank" rel="noopener noreferrer">View Location on Google Maps</a> : null}
    </fieldset>
  )
}

export default FarmLocationFields
