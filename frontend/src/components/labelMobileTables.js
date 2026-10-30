function labelMobileTables() {
  document.querySelectorAll('table.data-table, table.finance-table').forEach((table) => {
    const headers = [...table.querySelectorAll('thead th')].map((cell) => cell.textContent.replace(/\s+/g, ' ').trim())
    if (!headers.length) return
    table.classList.add('mobile-cards')
    table.querySelectorAll('tbody tr').forEach((row) => {
      const cells = [...row.children]
      if (cells.length === 1 && cells[0].colSpan > 1) {
        cells[0].setAttribute('data-label', '')
        cells[0].classList.add('mobile-span')
        return
      }
      cells.forEach((cell, index) => {
        const header = headers[index]
        const label = header || (cell.querySelector('button, a') ? 'Action' : '')
        if (label) cell.setAttribute('data-label', label)
      })
    })
  })
}

export function watchMobileTables() {
  let frame = 0
  const schedule = () => {
    cancelAnimationFrame(frame)
    frame = requestAnimationFrame(labelMobileTables)
  }
  schedule()
  const root = document.getElementById('root')
  const observer = new MutationObserver(schedule)
  if (root) observer.observe(root, { childList: true, subtree: true })
  return () => {
    cancelAnimationFrame(frame)
    observer.disconnect()
  }
}
