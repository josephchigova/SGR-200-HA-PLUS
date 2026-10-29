function TabSearch({ value, onChange, placeholder = 'Filter this tab...' }) {
  return (
    <input
      className="tab-search"
      type="search"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      aria-label={placeholder}
    />
  )
}

export default TabSearch
