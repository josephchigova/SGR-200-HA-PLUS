import { describe, expect, it } from 'vitest'

import { NATIONAL_ID_PATTERN, farmErrors, fileError, formatNationalId, nationalIdError, personalErrors, registrationFormKey, statusOf, submitBlockReason } from './registration'

describe('national ID formatting', () => {
  it('inserts the hyphen and capital letter as the user types', () => {
    expect(formatNationalId('63')).toBe('63')
    expect(formatNationalId('632')).toBe('63-2')
    expect(formatNationalId('632330173e58')).toBe('63-2330173E58')
    expect(NATIONAL_ID_PATTERN.test(formatNationalId('632330173E58'))).toBe(true)
    expect(formatNationalId('63-2330173E58')).toBe('63-2330173E58')
  })

  it('drops characters that do not belong and never completes an invalid ID', () => {
    expect(formatNationalId('6A3')).toBe('63')
    expect(formatNationalId('63233017358')).toBe('63-2330173')
    expect(formatNationalId('632330173E5899')).toBe('63-2330173E58')
    expect(nationalIdError('63-2330173')).toMatch(/one letter/)
    expect(nationalIdError('63-23301')).toMatch(/more digit/)
    expect(nationalIdError('63-2330173E5')).toMatch(/1 more digit/)
    expect(nationalIdError('63-2330173E58')).toBe('')
  })
})

describe('step validation', () => {
  const person = { first_name: 'PANASHE', surname: 'CHITIMA', national_id: '63-2330173E58', farm_name: 'CHITIYO', phone_primary: '0771234567' }

  it('requires the personal details', () => {
    expect(personalErrors(person)).toEqual({})
    expect(Object.keys(personalErrors({ ...person, first_name: 'P4', phone_primary: '12', email: 'x' })).sort()).toEqual(['email', 'first_name', 'phone_primary'])
  })

  it('requires location and land that fits inside the farm', () => {
    const farm = { province: '1', district: '2', ward: '3', total_hectares: '200', irrigated_hectares: '80', dryland_hectares: '100' }
    expect(farmErrors(farm)).toEqual({})
    expect(farmErrors({ ...farm, ward: '' }).ward).toBeTruthy()
    expect(farmErrors({ ...farm, ward: '287' }).ward).toBeUndefined()
    expect(farmErrors({ ...farm, ward: '0' }).ward).toBeTruthy()
    expect(farmErrors({ ...farm, ward: '1000' }).ward).toBeTruthy()
    expect(farmErrors({ ...farm, dryland_hectares: '200' }).dryland_hectares).toMatch(/cannot be more/)
    expect(farmErrors({ ...farm, latitude: '-17.8' }).latitude).toBeTruthy()
  })

  it('checks upload type and size', () => {
    expect(fileError({ name: 'id.pdf', type: 'application/pdf', size: 1000 })).toBe('')
    expect(fileError({ name: 'id.docx', type: '', size: 1000 })).toMatch(/PDF/)
    expect(fileError({ name: 'id.png', type: 'image/png', size: 11 * 1024 * 1024 })).toMatch(/larger/)
  })
})

describe('submitting a finished registration', () => {
  const ready = { personal: {}, farm: {}, crops: [] }

  it('stays available when the details are complete, including when KYC files are not required', () => {
    expect(submitBlockReason(ready)).toBe('')
    expect(submitBlockReason({ ...ready, uploadsKyc: false, missingLabels: ['National ID copy'] })).toBe('')
    expect(statusOf('DRAFT')[0]).toBe('Incomplete')
    expect(statusOf('VERIFIED')[0]).toBe('Approved')
  })

  it('blocks a lead farmer only while a required document is still missing', () => {
    expect(submitBlockReason({ ...ready, uploadsKyc: true, missingLabels: ['Proof of land'] })).toMatch(/Proof of land/)
    expect(submitBlockReason({ ...ready, uploadsKyc: true, missingLabels: [] })).toBe('')
    expect(submitBlockReason({ ...ready, personal: { phone_primary: 'Enter the phone number.' } })).toMatch(/Personal details/)
  })

  it('does not treat field order or numeric text as an unsaved change', () => {
    expect(registrationFormKey({ b: '1', a: 2, login_password: 'secret' })).toBe(registrationFormKey({ a: '2', b: '1' }))
  })
})
