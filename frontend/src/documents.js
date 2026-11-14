import apiClient from './api/client'

// KYC files are fetched with the user's sign-in and shown from memory. They are
// never reachable through a plain link.
export async function fetchDocument(document) {
  const response = await apiClient.get(document.download_url, { responseType: 'blob', timeout: 120000 })
  return response.data
}

export async function openDocument(document) {
  const tab = window.open('', '_blank')
  try {
    const blob = await fetchDocument(document)
    const url = URL.createObjectURL(blob)
    if (tab) tab.location = url
    else window.location.assign(url)
    window.setTimeout(() => URL.revokeObjectURL(url), 5 * 60 * 1000)
  } catch {
    if (tab) tab.close()
    window.alert('The document could not be opened. Check your connection and try again.')
  }
}

export async function saveDocument(document) {
  const blob = await fetchDocument(document)
  const url = URL.createObjectURL(blob)
  const link = window.document.createElement('a')
  link.href = url
  link.download = document.file_name || 'document'
  link.click()
  URL.revokeObjectURL(url)
}
