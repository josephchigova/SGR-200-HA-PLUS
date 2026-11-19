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
    case 'DRAFT': return 'Add your farmers, then send the submission to Admin.'
    case 'SUBMITTED': return 'Admin is reviewing this submission. To send more farmers, start a new submission.'
    case 'LIMITS_SET': return submission.hectares_capped
      ? 'Admin has reduced the hectares for this submission. Adjust your farmers’ allocations below to fit, then send it back to Admin for approval.'
      : 'Its hectares were approved unchanged. Submit it to confirm, or wait for Admin to approve it.'
    case 'RETURNED': return limitsIssued ? 'Admin returned it for corrections. Adjust the allocations within the approved hectares, then send it back.' : 'Admin returned it for corrections. Make the changes Admin asked for, then send it back.'
    case 'CONFIRMATION': return 'Admin is reviewing your final distribution.'
    case 'APPROVED': return 'Approved. These allocations are official and the farmers’ input debts were created. Send more farmers in a new submission.'
    case 'REJECTED': return 'Rejected. It stays in your history; you can start a new request.'
    default: return ''
  }
}

export const submitLabel = (submission) => (submission?.stage === 'DISTRIBUTION' ? 'Send back to Admin for approval' : 'Send to Admin')

// Quantity and cost the server will calculate, shown while typing. The server's figures are what is saved.
export function estimate(variety, hectares) {
  const area = Number(hectares) || 0
  const quantity = area * Number(variety?.rate_per_hectare || 0)
  const packSize = Number(variety?.pack_size || 0)
  const cost = packSize > 0 && variety?.pack_price ? (quantity / packSize) * Number(variety.pack_price) : quantity * Number(variety?.unit_price || 0)
  return { quantity, cost }
}
