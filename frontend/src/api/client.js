import axios from 'axios'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '/api' : 'http://localhost:8000/api'),
  timeout: 15000,
})

apiClient.interceptors.request.use((config) => {
  const url = config.url || ''
  const isCredentialRequest = url.includes('/auth/login') || url.includes('/auth/register')
  const token = localStorage.getItem('sgr_access_token')
  if (token && !isCredentialRequest) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export default apiClient
