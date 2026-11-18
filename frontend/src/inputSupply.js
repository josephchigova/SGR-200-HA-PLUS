// Shared labels for a lead farmer's input submission and Admin's review of it.

export const STATUS_TONE = {
  DRAFT: '',
  SUBMITTED: 'warn',
  LIMITS_SET: 'info',
  CONFIRMATION: 'warn',
  APPROVED: 'good',
  RETURNED: 'warn',
  REJECTED: 'bad',
}

export const OPEN_STATUSES = ['DRAFT', 'SUBMITTED', 'RETURNED', 'LIMITS_SET', 'CONFIRMATION']

export const when = (value) => (value ? new Date(value).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '—')

// What the lead farmer should do next, in plain words.
export function nextStep(submission) {
  if (!submission) return 'Add your first allocation to start this season’s request.'
  const limitsIssued = submission.stage === 'DISTRIBUTION'
  switch (submission.status) {
    case 'DRAFT': return 'Add or change allocations, then submit the request to Admin.'
    case 'SUBMITTED': return 'Admin is reviewing these hectares. To send more farmers, start a new submission.'
    case 'LIMITS_SET': return 'Admin has issued your maximum hectares. Share them among your farmers, then submit the final distribution.'
    case 'RETURNED': return limitsIssued ? 'Admin returned the distribution. Correct it within the approved hectares and submit it again.' : 'Admin returned the request. Correct it and submit it again.'
    case 'CONFIRMATION': return 'Admin is reviewing your final distribution.'
    case 'APPROVED': return 'Approved. These allocations are official and the farmers’ input debts were created.'
    case 'REJECTED': return 'Rejected. It stays in your history; you can start a new request.'
    default: return ''
  }
}

export const submitLabel = (submission) => (submission?.stage === 'DISTRIBUTION' ? 'Submit final distribution' : 'Submit request to Admin')

// Quantity and cost the server will calculate, shown while typing. The server's figures are what is saved.
export function estimate(variety, hectares) {
  const area = Number(hectares) || 0
  const quantity = area * Number(variety?.rate_per_hectare || 0)
  const packSize = Number(variety?.pack_size || 0)
  const cost = packSize > 0 && variety?.pack_price ? (quantity / packSize) * Number(variety.pack_price) : quantity * Number(variety?.unit_price || 0)
  return { quantity, cost }
}
