import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Modal } from './ui'

function TypingDialog() {
  const [value, setValue] = useState('')
  return (
    <Modal title="Add account" onClose={() => {}}>
      <label>
        First name
        <input value={value} onChange={(event) => setValue(event.target.value)} />
      </label>
    </Modal>
  )
}

describe('Modal', () => {
  it('keeps the caret in a text field while typing', async () => {
    const user = userEvent.setup()
    render(<TypingDialog />)

    const field = screen.getByRole('textbox', { name: 'First name' })
    await user.click(field)
    await user.keyboard('Joseph')

    expect(document.activeElement).toBe(field)
    expect(field.value).toBe('Joseph')
  })

  it('still closes on Escape after the parent re-renders', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()

    function Dialog() {
      const [value, setValue] = useState('')
      return (
        <Modal title="Add account" onClose={onClose}>
          <label>
            First name
            <input value={value} onChange={(event) => setValue(event.target.value)} />
          </label>
        </Modal>
      )
    }

    render(<Dialog />)
    await user.type(screen.getByRole('textbox', { name: 'First name' }), 'Jo')
    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalled()
  })
})
