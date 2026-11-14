// Shared helpers for the production page.

import apiClient from './api/client'

export const STATUSES = [
  ['PENDING', 'Planned', 'info'],
  ['PLANTED', 'Growing', 'good'],
  ['HARVESTED', 'Harvested', 'warn'],
  ['COMPLETED', 'Completed', ''],
]
export const STATUS_LABEL = Object.fromEntries(STATUSES.map(([code, label]) => [code, label]))
export const SEASON_LABEL = { SUMMER: 'Summer', WINTER: 'Winter' }
export const hectares = (value) => Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])

function csvCell(value) {
  const text = String(value ?? '')
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function downloadCsv(filename, header, rows) {
  const body = [header, ...rows].map((row) => row.map(csvCell).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([body], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function loadAllRecords(params) {
  const rows = []
  for (let page = 1; page <= 40; page += 1) {
    const response = await apiClient.get('/farmer-productions/', { params: { ...params, page, page_size: 500 } })
    rows.push(...listOf(response.data))
    if (!response.data?.next) break
  }
  return rows
}

export function exportRecords(rows, period) {
  downloadCsv(`production-records-${(period || 'all').replace(/\W+/g, '-')}.csv`,
    ['Farmer', 'Membership No.', 'Cluster', 'Lead farmer', 'Province', 'District', 'Crop', 'Season', 'Agri year', 'Registered ha', 'Planted ha', 'Irrigated ha', 'Estimated t', 'Actual t', 'Status'],
    rows.map((row) => [row.farmer_name, row.membership_number, row.cluster_name, row.lead_farmer_name, row.province_name, row.district_name, row.crop,
      SEASON_LABEL[row.crop_season] || '', row.season_name, row.contracted_hectares, row.planted_hectares, row.irrigated_hectares,
      row.estimated_production, row.actual_production, STATUS_LABEL[row.status] || row.status]))
}

