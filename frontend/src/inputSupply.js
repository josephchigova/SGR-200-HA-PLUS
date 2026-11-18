// Shared labels for the lead-farmer input request and the admin approval queue.

export const STATUS_TONE = {
  DRAFT: '',
  SUBMITTED: 'warn',
  APPROVED: 'good',
  RETURNED: 'warn',
  REJECTED: 'bad',
}

export const when = (value) => (value ? new Date(value).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '—')
