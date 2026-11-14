import { act, render, screen, fireEvent } from '@testing-library/react'
import { StrictMode, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DraftNotice } from './components/ui'
import { stripSecrets, useFormDraft } from './drafts'

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('./api/client', () => ({ default: api }))
vi.mock('./auth', () => ({ useAuth: () => ({ profile: { id: 7 } }) }))

function Form({ start = { name: '', password: '' } }) {
  const [form, setForm] = useState(start)
  const draft = useFormDraft({ key: 'test:form', value: form, onRestore: (data) => setForm((current) => ({ ...current, ...data })) })
  return (
    <div>
      <DraftNotice draft={draft} />
      <input aria-label="Name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
      <input aria-label="Password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />
      <button type="button" onClick={() => { draft.clear(start); setForm(start) }}>Save</button>
    </div>
  )
}

const stored = () => JSON.parse(localStorage.getItem('sgr_draft:7:test:form'))

describe('useFormDraft', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    api.get.mockRejectedValue({ response: { status: 404 } })
    api.put.mockResolvedValue({ data: {} })
    api.delete.mockResolvedValue({})
  })
  afterEach(() => vi.useRealTimers())

  it('keeps typing in the browser at once, without passwords, and restores it after a reload', async () => {
    const first = render(<Form />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'TENDAI' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret123' } })
    expect(stored().data).toEqual({ name: 'TENDAI' })
    first.unmount()

    render(<Form />)
    expect(screen.getByLabelText('Name').value).toBe('TENDAI')
    expect(screen.getByLabelText('Password').value).toBe('')
    expect(screen.getByRole('status').textContent).toContain('draft was restored')
  })

  it('sends the draft to the server after a pause', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<Form />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'RUDO' } })
    expect(api.put).not.toHaveBeenCalled()
    await act(async () => { vi.advanceTimersByTime(1500) })
    expect(api.put).toHaveBeenCalledWith('/drafts/', { key: 'test:form', data: { name: 'RUDO' } })
    vi.useRealTimers()
  })

  it('restores a server draft when this browser has none', async () => {
    api.get.mockResolvedValue({ data: { key: 'test:form', data: { name: 'FROM SERVER' }, updated_at: new Date().toISOString() } })
    render(<Form />)
    expect(await screen.findByDisplayValue('FROM SERVER')).toBeTruthy()
  })

  it('clears the draft after saving and on discard', async () => {
    render(<Form />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'TAKUNDA' } })
    fireEvent.click(screen.getByText('Save'))
    expect(localStorage.getItem('sgr_draft:7:test:form')).toBeNull()
    expect(api.delete).toHaveBeenCalledWith('/drafts/', { params: { key: 'test:form' } })

    localStorage.setItem('sgr_draft:7:test:form', JSON.stringify({ data: { name: 'OLD' }, savedAt: new Date().toISOString() }))
    const again = render(<Form />)
    fireEvent.click(again.getByText('Discard draft'))
    expect(again.getAllByLabelText('Name').at(-1).value).toBe('')
    expect(localStorage.getItem('sgr_draft:7:test:form')).toBeNull()
  })

  it('keeps the draft and shows the notice when effects run twice', () => {
    localStorage.setItem('sgr_draft:7:test:form', JSON.stringify({ data: { name: 'KEPT' }, savedAt: new Date().toISOString(), synced: true }))
    render(<StrictMode><Form /></StrictMode>)
    expect(screen.getByLabelText('Name').value).toBe('KEPT')
    expect(screen.getByRole('status').textContent).toContain('draft was restored')
    expect(stored().data).toEqual({ name: 'KEPT' })
    expect(api.delete).not.toHaveBeenCalled()
  })

  it('drops anything that looks like a secret', () => {
    expect(stripSecrets({ email: 'a', login_password: 'x', nested: [{ token: 1, ok: 2 }] })).toEqual({ email: 'a', nested: [{ ok: 2 }] })
  })
})
