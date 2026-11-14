import { useEffect, useId, useMemo, useRef, useState } from 'react'

import Icon from './Icon'

// A dropdown with a search box. The value can only be one of the options, so a
// province, district or ward is always chosen from the list and never typed in.
function SearchSelect({ label, value, options, onChange, placeholder = 'Choose', disabled = false, loading = false, error = '', hint = '', required = false, emptyText = 'Nothing to choose from.' }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const root = useRef(null)
  const search = useRef(null)
  const id = useId()
  const selected = options.find((option) => String(option.value) === String(value))
  const visible = useMemo(() => {
    const term = query.trim().toLowerCase()
    return term ? options.filter((option) => option.label.toLowerCase().includes(term)) : options
  }, [options, query])

  useEffect(() => {
    if (!open) return undefined
    search.current?.focus()
    const close = (event) => {
      if (!root.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const choose = (option) => {
    onChange(String(option.value), option)
    setOpen(false)
    setQuery('')
  }

  const onKeyDown = (event) => {
    if (event.key === 'Escape') {
      setOpen(false)
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => Math.min(index + 1, visible.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (visible[active]) choose(visible[active])
    }
  }

  return (
    <div className="form-field search-select" ref={root}>
      <span id={`${id}-label`}>{label}{required ? <span className="req" aria-hidden="true"> *</span> : null}</span>
      <button
        type="button"
        className={`search-select-button${error ? ' invalid' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-label ${id}-value`}
        disabled={disabled || loading}
        onClick={() => { setOpen((current) => !current); setActive(0) }}
      >
        <span id={`${id}-value`} className={selected ? '' : 'placeholder'}>{loading ? 'Loading…' : selected ? selected.label : placeholder}</span>
        <Icon name="chevrons" />
      </button>
      {open ? (
        <div className="search-select-panel">
          {options.length > 7 ? (
            <input ref={search} type="search" value={query} placeholder={`Search ${label.toLowerCase()}`} aria-label={`Search ${label}`} onChange={(event) => { setQuery(event.target.value); setActive(0) }} onKeyDown={onKeyDown} />
          ) : <input ref={search} className="sr-only" aria-label={`${label} options`} readOnly onKeyDown={onKeyDown} />}
          <ul role="listbox" aria-labelledby={`${id}-label`}>
            {visible.map((option, index) => (
              <li
                key={option.value}
                role="option"
                aria-selected={String(option.value) === String(value)}
                className={index === active ? 'active' : ''}
                onMouseEnter={() => setActive(index)}
                onMouseDown={(event) => { event.preventDefault(); choose(option) }}
              >
                {option.label}
                {String(option.value) === String(value) ? <Icon name="check" /> : null}
              </li>
            ))}
            {!visible.length ? <li className="empty">{options.length ? 'No match.' : emptyText}</li> : null}
          </ul>
        </div>
      ) : null}
      {error ? <span className="field-error" role="alert">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  )
}

export default SearchSelect
