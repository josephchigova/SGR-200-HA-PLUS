function parseDecimal(value) {
  const text = String(value ?? '').trim()
  if (!/^\d+(\.\d+)?$/.test(text)) return null
  const [whole, fraction = ''] = text.split('.')
  const digits = BigInt(whole) * (10n ** BigInt(fraction.length)) + BigInt(fraction || '0')
  return { digits, scale: fraction.length }
}

function formatScaled(digits, places) {
  const negative = digits < 0n
  const absolute = negative ? -digits : digits
  const text = absolute.toString().padStart(places + 1, '0')
  const whole = text.slice(0, text.length - places)
  const fraction = text.slice(text.length - places)
  return `${negative ? '-' : ''}${whole}.${fraction}`
}

function roundHalfEven(digits, scale, places) {
  if (scale <= places) return digits * (10n ** BigInt(places - scale))
  const divisor = 10n ** BigInt(scale - places)
  const base = digits / divisor
  const remainder = digits % divisor
  const half = divisor / 2n
  if (remainder > half || (remainder === half && base % 2n === 1n)) return base + 1n
  return base
}

export function multiplyDecimal(left, right, places = 4) {
  const a = parseDecimal(left)
  const b = parseDecimal(right)
  if (!a || !b) return ''
  const product = a.digits * b.digits
  return formatScaled(roundHalfEven(product, a.scale + b.scale, places), places)
}

export function addDecimal(values, places = 4) {
  let total = 0n
  values.forEach((value) => {
    const parsed = parseDecimal(value)
    if (!parsed) return
    total += roundHalfEven(parsed.digits, parsed.scale, places)
  })
  return formatScaled(total, places)
}
