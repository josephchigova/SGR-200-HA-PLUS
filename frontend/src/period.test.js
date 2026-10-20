import { beforeEach, describe, expect, it } from 'vitest'

import { cropSeasonAfterYearChange, resolvePeriodSelection, selectionIsHistorical } from './period'

const currentYear = {
  id: 1,
  name: '2026/2027',
  status: 'ACTIVE',
  is_current: true,
  crop_seasons: [
    { code: 'SUMMER', label: 'Summer' },
    { code: 'WINTER', label: 'Winter' },
  ],
}
const olderYear = {
  id: 2,
  name: '2025/2026',
  status: 'CLOSED',
  is_current: false,
  crop_seasons: [
    { code: 'SUMMER', label: 'Summer' },
    { code: 'WINTER', label: 'Winter' },
  ],
}

describe('period selection', () => {
  beforeEach(() => localStorage.clear())

  it('uses the backend current period until the user chooses one', () => {
    const selection = resolvePeriodSelection({
      seasons: [olderYear, currentYear],
      currentYear,
      currentCropSeason: 'SUMMER',
      stored: { mode: 'auto', yearId: '2', cropSeason: 'WINTER' },
    })
    expect(selection).toEqual({ mode: 'auto', yearId: '1', cropSeason: 'SUMMER' })
  })

  it('restores a manual year and season after refresh', () => {
    const selection = resolvePeriodSelection({
      seasons: [olderYear, currentYear],
      currentYear,
      currentCropSeason: 'SUMMER',
      stored: { mode: 'manual', yearId: '2', cropSeason: 'WINTER' },
    })
    expect(selection).toEqual({ mode: 'manual', yearId: '2', cropSeason: 'WINTER' })
  })

  it('selects the current crop season when the user returns to the current year', () => {
    expect(cropSeasonAfterYearChange({
      nextSeason: currentYear,
      currentCropSeason: 'SUMMER',
      previousCropSeason: 'WINTER',
    })).toBe('SUMMER')
    expect(cropSeasonAfterYearChange({
      nextSeason: olderYear,
      currentCropSeason: 'SUMMER',
      previousCropSeason: 'WINTER',
    })).toBe('WINTER')
  })

  it('marks closed years and the non-current crop season as historical', () => {
    expect(selectionIsHistorical({ season: currentYear, cropSeason: 'SUMMER', currentCropSeason: 'SUMMER' })).toBe(false)
    expect(selectionIsHistorical({ season: currentYear, cropSeason: 'WINTER', currentCropSeason: 'SUMMER' })).toBe(true)
    expect(selectionIsHistorical({ season: olderYear, cropSeason: 'SUMMER', currentCropSeason: 'SUMMER' })).toBe(true)
  })
})
