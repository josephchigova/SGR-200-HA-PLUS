// Formatting and validation for farmer registration.

export const NATIONAL_ID_PATTERN = /^[0-9]{2}-[0-9]{7}[A-Z][0-9]{2}$/
const NAME_PATTERN = /^[\p{L}]+(?:[ '-][\p{L}]+)*$/u

// Builds 63-2330173E58 as the user types. A character that cannot belong at its
// position is dropped, so the value never holds anything the format forbids. An
// incomplete ID stays incomplete: nothing is invented to make it pass.
export function formatNationalId(raw) {
  const characters = String(raw || '').toUpperCase().replace(/[^0-9A-Z]/g, '')
  let digitsBefore = ''
  let letter = ''
  let digitsAfter = ''
  for (const character of characters) {
    const isDigit = character >= '0' && character <= '9'
    if (digitsBefore.length < 9) {
      if (isDigit) digitsBefore += character
    } else if (!letter) {
      if (!isDigit) letter = character
    } else if (digitsAfter.length < 2 && isDigit) {
      digitsAfter += character
    }
  }
  const head = digitsBefore.slice(0, 2)
  const body = digitsBefore.slice(2)
  return `${head}${digitsBefore.length > 2 ? '-' : ''}${body}${letter}${digitsAfter}`
}

export function nationalIdError(value) {
  if (!value) return 'Enter the national ID.'
  if (NATIONAL_ID_PATTERN.test(value)) return ''
  const plain = value.replace('-', '')
  if (plain.length < 9) return `Enter ${9 - plain.length} more digit${9 - plain.length === 1 ? '' : 's'}, then a letter and two digits.`
  if (plain.length === 9) return 'Next comes one letter, for example E.'
  return `Enter ${12 - plain.length} more digit${12 - plain.length === 1 ? '' : 's'} to finish the ID.`
}

export const upper = (value) => String(value || '').toUpperCase()

export function nameError(value, label, required = true) {
  const text = String(value || '').trim()
  if (!text) return required ? `Enter the ${label}.` : ''
  if (!NAME_PATTERN.test(text)) return 'Use letters, spaces, apostrophes or hyphens only.'
  return ''
}

export const phoneDigits = (value) => String(value || '').replace(/\D/g, '')

export function phoneError(value) {
  const digits = phoneDigits(value)
  if (!digits) return 'Enter the phone number.'
  if (digits.length < 9 || digits.length > 12) return 'Enter 9 to 12 digits, for example 0771234567.'
  return ''
}

export function emailError(value) {
  if (!value) return ''
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? '' : 'Enter a valid email address, or leave it empty.'
}

export function personalErrors(form) {
  return clean({
    first_name: nameError(form.first_name, 'first name'),
    middle_name: nameError(form.middle_name, 'middle name', false),
    surname: nameError(form.surname, 'surname'),
    national_id: nationalIdError(form.national_id),
    farm_name: String(form.farm_name || '').trim() ? '' : 'Enter the farm name.',
    phone_primary: phoneError(form.phone_primary),
    email: emailError(form.email),
  })
}

const number = (value) => (value === '' || value === null || value === undefined ? NaN : Number(value))

export function farmErrors(form) {
  const total = number(form.total_hectares)
  const irrigated = number(form.irrigated_hectares)
  const dryland = number(form.dryland_hectares)
  const errors = {
    province: form.province ? '' : 'Choose the province.',
    district: form.district ? '' : 'Choose the district.',
    ward: String(form.ward || '').trim() ? '' : 'Enter the ward.',
    total_hectares: !(total > 0) ? 'Enter the total farm size in hectares.' : '',
    irrigated_hectares: !(irrigated >= 0) ? 'Enter the irrigated arable hectares. Use 0 if none.' : '',
    dryland_hectares: !(dryland >= 0) ? 'Enter the dryland arable hectares. Use 0 if none.' : '',
  }
  if (!errors.total_hectares && !errors.irrigated_hectares && !errors.dryland_hectares && irrigated + dryland > total) {
    errors.dryland_hectares = `Arable land (${irrigated + dryland} ha) cannot be more than the farm size (${total} ha).`
  }
  const hasLatitude = String(form.latitude || '').trim() !== ''
  const hasLongitude = String(form.longitude || '').trim() !== ''
  if (hasLatitude !== hasLongitude) errors.latitude = 'Enter both latitude and longitude, or leave both empty.'
  else if (hasLatitude) {
    const latitude = Number(form.latitude)
    const longitude = Number(form.longitude)
    if (!(latitude >= -90 && latitude <= 90) || !(longitude >= -180 && longitude <= 180)) errors.latitude = 'These coordinates are not valid.'
  }
  return clean(errors)
}

export const MAX_UPLOAD_MB = 10
const ALLOWED_TYPES = ['application/pdf', 'image/jpeg', 'image/png']

export function fileError(file, maxMb = MAX_UPLOAD_MB) {
  if (!file) return 'Choose a file.'
  const name = file.name.toLowerCase()
  const extensionOk = ['.pdf', '.jpg', '.jpeg', '.png'].some((extension) => name.endsWith(extension))
  if (!extensionOk || (file.type && !ALLOWED_TYPES.includes(file.type))) return 'Use a PDF, JPG or PNG file.'
  if (file.size > maxMb * 1024 * 1024) return `The file is larger than ${maxMb} MB.`
  if (file.size === 0) return 'The file is empty.'
  return ''
}

function clean(errors) {
  return Object.fromEntries(Object.entries(errors).filter(([, message]) => message))
}

export const STATUS_LABELS = {
  DRAFT: ['Incomplete', ''],
  PENDING: ['Awaiting approval', 'warn'],
  SUBMITTED: ['Awaiting approval', 'warn'],
  UNDER_REVIEW: ['In review', 'warn'],
  VERIFIED: ['Approved', 'good'],
  APPROVED: ['Approved', 'good'],
  REJECTED: ['Rejected', 'bad'],
  CORRECTIONS_REQUESTED: ['Corrections needed', 'info'],
  SUSPENDED: ['Suspended', 'bad'],
  ARCHIVED: ['Archived', ''],
}

export const statusOf = (code) => STATUS_LABELS[code] || [code || '—', '']
