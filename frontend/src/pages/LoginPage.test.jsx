import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import apiClient from '../api/client'
import LoginPage from './LoginPage'

vi.mock('../api/client', () => ({
  default: { post: vi.fn() },
}))

function renderLogin() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    apiClient.post.mockReset()
    localStorage.clear()
  })

  it('stores the session when the server accepts the credentials', async () => {
    apiClient.post.mockResolvedValue({ data: { access: 'access-token', refresh: 'refresh-token' } })
    renderLogin()
    fireEvent.change(screen.getByPlaceholderText('name@arda.gov.zw'), { target: { value: 'officer@arda.gov.zw' } })
    fireEvent.change(screen.getByPlaceholderText('Enter your password'), { target: { value: 'correct-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Login' }))
    await waitFor(() => expect(localStorage.getItem('sgr_access_token')).toBe('access-token'))
    expect(apiClient.post).toHaveBeenCalledTimes(1)
    expect(apiClient.post.mock.calls[0][2]).toEqual({ timeout: 60000 })
  })

  it('shows a credential error only for a rejected login', async () => {
    apiClient.post.mockRejectedValue({ response: { status: 401, data: { detail: 'The email or password is incorrect.' } } })
    renderLogin()
    fireEvent.change(screen.getByPlaceholderText('name@arda.gov.zw'), { target: { value: 'officer@arda.gov.zw' } })
    fireEvent.change(screen.getByPlaceholderText('Enter your password'), { target: { value: 'wrong-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Login' }))
    expect(await screen.findByText('The email or password is incorrect.')).toBeTruthy()
    expect(localStorage.getItem('sgr_access_token')).toBeNull()
  })

  it('does not describe a timeout as a wrong password', async () => {
    apiClient.post.mockRejectedValue({ code: 'ECONNABORTED' })
    renderLogin()
    fireEvent.change(screen.getByPlaceholderText('name@arda.gov.zw'), { target: { value: 'officer@arda.gov.zw' } })
    fireEvent.change(screen.getByPlaceholderText('Enter your password'), { target: { value: 'correct-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Login' }))
    expect(await screen.findByText(/took too long to respond/i)).toBeTruthy()
    expect(screen.queryByText(/check your credentials/i)).toBeNull()
  })
})
