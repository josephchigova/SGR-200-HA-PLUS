// Small shared helpers for the programme, catalogue, request and allocation pages.

import apiClient from './api/client'
import { CATEGORIES } from './inputCategories'

export const listOf = (data) => (Array.isArray(data) ? data : data?.results || [])

export async function loadAll(path, params = {}) {
  const rows = []
  let response = await apiClient.get(path, { params: { ...params, page_size: 200 } })
  rows.push(...listOf(response.data))
  for (let page = 2; response.data?.next && page < 30; page += 1) {
    response = await apiClient.get(path, { params: { ...params, page_size: 200, page } })
    rows.push(...listOf(response.data))
  }
  return rows
}

export const money = (value) => (value === null || value === undefined || value === '' ? '—' : Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' }))
export const qty = (value, digits = 2) => Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: digits })
export const hectares = (value) => `${qty(value)} ha`
export const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map(([code, label]) => [code, label]))
// Products of one input type cover different land, so their hectares add up; different input
// types go on the same land, so a request's hectares are the largest of those sums.
export function requestTotal(lines) {
  const byType = {}
  lines.forEach(({ input_category: category, hectares: value }) => {
    byType[category] = (byType[category] || 0) + (Number(value) || 0)
  })
  return Math.max(0, ...Object.values(byType))
}
