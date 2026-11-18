// Shared labels for a lead farmer's input submission and Admin's review of it.

export const STATUS_TONE = {
  DRAFT: '',
  SUBMITTED: 'warn',
  LIMITS_SET: 'good',
  CONFIRMATION: 'warn',
  APPROVED: 'good',
  RETURNED: 'warn',
  REJECTED: 'bad',
  LIMITS_APPROVED: 'good',
  LIMITS_DISTRIBUTED: 'good',
  LIMITS_ADJUSTED: 'warn',
  FINAL_SUBMITTED: 'warn',
  FINAL_RESUBMITTED: 'warn',
}

export const when = (value) => (value ? new Date(value).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '—')

export const canEditSubmission = (request) => {
  if (!request) return true
  if (request.stage === 'DISTRIBUTION') return request.status === 'LIMITS_SET' || request.status === 'RETURNED'
  return request.status === 'DRAFT' || request.status === 'SUBMITTED' || request.status === 'RETURNED'
}
