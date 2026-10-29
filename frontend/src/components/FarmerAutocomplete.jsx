import { useEffect, useId, useRef, useState } from 'react'

import apiClient from '../api/client'

const toList = (data) => (Array.isArray(data) ? data : data?.results || [])

const displayName = (farmer) => farmer?.full_name
  || `${farmer?.first_name || ''} ${farmer?.middle_name || ''} ${farmer?.surname || ''}`.trim()

function FarmerAutocomplete({
  value = '',
  onChange,
  label = 'Farmer',
  endpoint = '/farmers/',
  seasonId,
  seasonName,
  placeholder = 'Search by name, National ID, membership or phone',
  required = false,
  disabled = false,
  pageSize = 20,
  debounceMs = 300,
}) {
  const generatedId = useId()
  const inputId = `farmer-autocomplete-${generatedId}`
  const wrapperRef = useRef(null)
  const selectedRef = useRef(null)
  const [selectedFarmer, setSelectedFarmer] = useState(null)
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const [open, setOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(-1)

  useEffect(() => {
    if (!value) {
      if (selectedRef.current) {
        selectedRef.current = null
        setSelectedFarmer(null)
        setQuery('')
      }
      return undefined
    }

    if (String(selectedRef.current?.id) === String(value)) return undefined

    let active = true
    apiClient.get(`/farmers/${value}/`)
      .then((response) => {
        if (!active) return
        selectedRef.current = response.data
        setSelectedFarmer(response.data)
        setQuery(displayName(response.data))
      })
      .catch(() => {
        if (active) {
          selectedRef.current = null
          setSelectedFarmer(null)
          setQuery('')
        }
      })

    return () => {
      active = false
    }
  }, [value])

  useEffect(() => {
    const handleOutsidePointer = (event) => {
      if (!wrapperRef.current?.contains(event.target)) {
        setOpen(false)
        setLoading(false)
      }
    }

    document.addEventListener('mousedown', handleOutsidePointer)
    return () => document.removeEventListener('mousedown', handleOutsidePointer)
  }, [])

  useEffect(() => {
    const search = query.trim()
    if (!open || selectedRef.current || search.length < 1) return undefined

    let active = true
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({ search, page_size: String(pageSize) })
        if (seasonId) params.set('season', String(seasonId))
        if (seasonName) params.set('season_name', seasonName)
        const response = await apiClient.get(`${endpoint}?${params.toString()}`, { signal: controller.signal })
        if (!active) return
        setSuggestions(toList(response.data))
        setHasMore(Boolean(response.data?.next))
        setHighlightedIndex(-1)
        setError('')
      } catch {
        if (!active || controller.signal.aborted) return
        setSuggestions([])
        setHasMore(false)
        setError('Unable to search farmers.')
      } finally {
        if (active) setLoading(false)
      }
    }, debounceMs)

    return () => {
      active = false
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [debounceMs, endpoint, open, pageSize, query, seasonId, seasonName])

  const selectFarmer = (farmer) => {
    selectedRef.current = farmer
    setSelectedFarmer(farmer)
    setQuery(displayName(farmer))
    setSuggestions([])
    setLoading(false)
    setError('')
    setHasMore(false)
    setOpen(false)
    setHighlightedIndex(-1)
    onChange?.(farmer)
  }

  const clearFarmer = () => {
    selectedRef.current = null
    setSelectedFarmer(null)
    setQuery('')
    setSuggestions([])
    setLoading(false)
    setError('')
    setHasMore(false)
    setOpen(false)
    setHighlightedIndex(-1)
    onChange?.(null)
  }

  const handleKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      if (suggestions.length) {
        setHighlightedIndex((current) => Math.min(current < 0 ? 0 : current + 1, suggestions.length - 1))
      }
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      if (suggestions.length) {
        setHighlightedIndex((current) => Math.max(current < 0 ? suggestions.length - 1 : current - 1, 0))
      }
    } else if (event.key === 'Enter' && open && highlightedIndex >= 0) {
      event.preventDefault()
      selectFarmer(suggestions[highlightedIndex])
    } else if (event.key === 'Escape') {
      setOpen(false)
      setLoading(false)
      setHighlightedIndex(-1)
    }
  }

  return (
    <div className="farmer-autocomplete" ref={wrapperRef}>
      <label className="form-field" htmlFor={inputId}>
        {label}
        <span className="farmer-autocomplete-input-wrap">
          <input
            id={inputId}
            type="search"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={open}
            aria-controls={`${inputId}-suggestions`}
            aria-activedescendant={highlightedIndex >= 0 ? `${inputId}-option-${highlightedIndex}` : undefined}
            aria-required={required}
            autoComplete="off"
            disabled={disabled}
            placeholder={placeholder}
            value={query}
            onFocus={() => {
              if (!selectedRef.current) setOpen(true)
            }}
            onChange={(event) => {
              const nextQuery = event.target.value
              selectedRef.current = null
              setSelectedFarmer(null)
              setQuery(nextQuery)
              setSuggestions([])
              setLoading(Boolean(nextQuery.trim()))
              setError('')
              setHasMore(false)
              setOpen(true)
              setHighlightedIndex(-1)
              onChange?.(null)
            }}
            onKeyDown={handleKeyDown}
          />
          {query ? (
            <button
              type="button"
              className="farmer-autocomplete-clear"
              aria-label={selectedFarmer ? 'Clear selected farmer' : 'Clear farmer search'}
              onClick={clearFarmer}
              disabled={disabled}
            >
              ×
            </button>
          ) : null}
        </span>
      </label>
      {open ? (
        <div id={`${inputId}-suggestions`} className="farmer-suggestion-list" role="listbox" aria-label={`${label} search results`}>
          {loading ? <div className="farmer-suggestion-state" role="status">Searching...</div> : null}
          {!loading && error ? <div className="farmer-suggestion-state" role="status">{error}</div> : null}
          {!loading && !error && !query.trim() ? <div className="farmer-suggestion-state">Type at least one character to search.</div> : null}
          {!loading && !error && query.trim() && suggestions.length === 0 ? <div className="farmer-suggestion-state" role="status">No farmers found</div> : null}
          {suggestions.map((farmer, index) => (
            <button
              id={`${inputId}-option-${index}`}
              key={farmer.id}
              type="button"
              className={`farmer-suggestion${index === highlightedIndex ? ' highlighted' : ''}`}
              role="option"
              aria-selected={index === highlightedIndex}
              onMouseEnter={() => setHighlightedIndex(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectFarmer(farmer)}
            >
              <strong>{displayName(farmer) || `Farmer ${farmer.id}`}</strong>
              <small>
                {[
                  farmer.national_id ? `ID: ${farmer.national_id}` : '',
                  farmer.membership_number ? `Membership: ${farmer.membership_number}` : '',
                  farmer.phone_primary ? `Phone: ${farmer.phone_primary}` : '',
                  farmer.district_name || '',
                ].filter(Boolean).join(' · ')}
              </small>
            </button>
          ))}
          {!loading && !error && suggestions.length > 0 && hasMore ? (
            <div className="farmer-suggestion-state">Showing first {pageSize} results. Refine your search.</div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export default FarmerAutocomplete