export const YEAR_STORAGE_KEY = 'sgr_selected_season_id'
export const CROP_STORAGE_KEY = 'sgr_selected_crop_season'
export const PERIOD_MODE_KEY = 'sgr_period_mode'

const KNOWN_CROP_SEASONS = ['SUMMER', 'WINTER']

export function readStoredPeriod() {
  const mode = localStorage.getItem(PERIOD_MODE_KEY) === 'manual' ? 'manual' : 'auto'
  return {
    mode,
    yearId: localStorage.getItem(YEAR_STORAGE_KEY) || '',
    cropSeason: localStorage.getItem(CROP_STORAGE_KEY) || '',
  }
}

export function writeStoredPeriod({ mode, yearId, cropSeason }) {
  localStorage.setItem(PERIOD_MODE_KEY, mode === 'manual' ? 'manual' : 'auto')
  if (yearId) localStorage.setItem(YEAR_STORAGE_KEY, String(yearId))
  else localStorage.removeItem(YEAR_STORAGE_KEY)
  if (cropSeason) localStorage.setItem(CROP_STORAGE_KEY, cropSeason)
  else localStorage.removeItem(CROP_STORAGE_KEY)
}

export function mergeCurrentYear(seasons, currentYear) {
  if (!currentYear?.id) return seasons
  if (seasons.some((season) => String(season.id) === String(currentYear.id))) return seasons
  return [currentYear, ...seasons]
}

export function cropSeasonCodes(season) {
  return (season?.crop_seasons || [])
    .map((item) => item.code)
    .filter((code) => KNOWN_CROP_SEASONS.includes(code))
}

export function cropSeasonLabel(season, cropSeason) {
  const match = (season?.crop_seasons || []).find((item) => item.code === cropSeason)
  if (match?.label) return match.label
  if (cropSeason === 'SUMMER') return 'Summer'
  if (cropSeason === 'WINTER') return 'Winter'
  return ''
}

function chooseCropSeason({ season, preferred, fallback }) {
  const codes = cropSeasonCodes(season)
  const preferredCode = String(preferred || '').toUpperCase()
  if (preferredCode && (codes.length === 0 || codes.includes(preferredCode)) && KNOWN_CROP_SEASONS.includes(preferredCode)) {
    return preferredCode
  }
  const fallbackCode = String(fallback || '').toUpperCase()
  if (fallbackCode && (codes.length === 0 || codes.includes(fallbackCode)) && KNOWN_CROP_SEASONS.includes(fallbackCode)) {
    return fallbackCode
  }
  return codes[0] || ''
}

export function cropSeasonAfterYearChange({ nextSeason, currentCropSeason, previousCropSeason }) {
  if (nextSeason?.is_current) {
    return chooseCropSeason({ season: nextSeason, preferred: currentCropSeason, fallback: previousCropSeason })
  }
  return chooseCropSeason({ season: nextSeason, preferred: previousCropSeason, fallback: currentCropSeason })
}

export function resolvePeriodSelection({ seasons, currentYear, currentCropSeason, stored }) {
  const currentId = currentYear?.id != null ? String(currentYear.id) : ''
  const findSeason = (id) => seasons.find((season) => String(season.id) === String(id)) || null
  const mode = stored?.mode === 'manual' ? 'manual' : 'auto'
  if (mode === 'auto') {
    return { mode, yearId: currentId, cropSeason: currentCropSeason || '' }
  }

  const storedSeason = findSeason(stored?.yearId)
  const season = storedSeason && storedSeason.selectable !== false ? storedSeason : findSeason(currentId)
  return {
    mode,
    yearId: season ? String(season.id) : '',
    cropSeason: chooseCropSeason({
      season,
      preferred: stored?.cropSeason,
      fallback: season?.is_current ? currentCropSeason : '',
    }),
  }
}

export function selectionIsHistorical({ season, cropSeason, currentCropSeason }) {
  if (!season) return false
  if (season.status && season.status !== 'ACTIVE') return true
  if (season.is_current !== true) return true
  return Boolean(currentCropSeason) && cropSeason !== currentCropSeason
}
