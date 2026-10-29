import { describe, expect, it } from 'vitest'

import { addDecimal, multiplyDecimal } from './decimal'

describe('decimal money', () => {
  it('multiplies rate and unit cost to four decimal places', () => {
    expect(multiplyDecimal('6', '23', 4)).toBe('138.0000')
    expect(multiplyDecimal('0.15', '8', 4)).toBe('1.2000')
    expect(multiplyDecimal('1.005', '1', 2)).toBe('1.00')
    expect(multiplyDecimal('1.015', '1', 2)).toBe('1.02')
  })

  it('adds costs without binary floating-point drift', () => {
    expect(addDecimal(['0.10', '0.20'], 2)).toBe('0.30')
    expect(addDecimal(['10.1250', '0.0001'], 4)).toBe('10.1251')
  })
})