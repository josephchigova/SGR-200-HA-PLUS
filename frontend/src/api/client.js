import axios from 'axios'

import { clearSession, getRefreshToken, storeTokens } from '../session'

const baseURL = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '/api' : 'http://localhost:8000/api')

const apiClient = axios.create({ baseURL, timeout: 15000 })

const isCredentialRequest = (url = '') => ['/auth/login', '/auth/register', '/auth/refresh', '/auth/password-reset'].some((path) => url.includes(path))

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('sgr_access_token')
  if (token && !isCredentialRequest(config.url)) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// One refresh at a time. Requests that fail while it runs wait for the same result.
let refreshing = null

function refreshAccessToken() {
  if (!refreshing) {
    const refresh = getRefreshToken()
    refreshing = (refresh
      ? axios.post(`${baseURL}/auth/refresh/`, { refresh }, { timeout: 15000 })
      : Promise.reject(new Error('No refresh token')))
      .then((response) => {
        storeTokens({ access: response.data.access, refresh: response.data.refresh || refresh })
        return response.data.access
      })
      .finally(() => { refreshing = null })
  }
  return refreshing
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    const expired = error.response?.status === 401 && original && !original.sgrRetried && !isCredentialRequest(original.url)
    if (!expired || !localStorage.getItem('sgr_access_token')) return Promise.reject(error)
    original.sgrRetried = true
    try {
      const access = await refreshAccessToken()
      original.headers = { ...(original.headers || {}), Authorization: `Bearer ${access}` }
      return apiClient(original)
    } catch {
      // The session has ended. Clearing it sends the user back to sign in.
      clearSession('expired')
      return Promise.reject(error)
    }
  },
)

export default apiClient
