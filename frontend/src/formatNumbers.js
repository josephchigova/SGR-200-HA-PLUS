const COUNT_KEYS = /^(farmers|farm_count|farmer_count|total_farmers|requests|records|users|deliveries|debts|allocations|subscriptions|programmes|inputs)$|_count$/
const MONEY_KEYS = /cost|amount|price|balance|debit|credit|paid|outstanding|fee|income|value|receipt/i
const MEASURE_KEYS = /hectare|tonne|quantity|yield|qty/i

export function formatDisplay(key, value) {
  if (value === null || value === undefined || value === '') return value
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  const text = String(value)
  if (!/^-?\d+(\.\d+)?$/.test(text)) return value
  const number = Number(text)
  if (!Number.isFinite(number)) return value
  if (COUNT_KEYS.test(key)) return String(Math.round(number))
  if (MONEY_KEYS.test(key) && !MEASURE_KEYS.test(key)) {
    return number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
  if (!MEASURE_KEYS.test(key)) return value
  const places = /yield|expected_tonnes|qty3/.test(key) ? 3 : 2
  return number.toLocaleString('en-US', { maximumFractionDigits: places })
}
