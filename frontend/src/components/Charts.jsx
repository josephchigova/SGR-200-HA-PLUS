import { useEffect, useRef, useState } from 'react'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const PLOT_TOP = 56
const PLOT_HEIGHT = 196
const RIGHT_PAD = 24

function monthLabel(value) {
  const [year, month] = String(value || '').split('-')
  const index = Number(month) - 1
  if (!year || Number.isNaN(index) || index < 0 || index > 11) return String(value || '')
  return `${MONTHS[index]} ${year.slice(2)}`
}

function formatMeasure(value, unit) {
  const number = Number(value) || 0
  const digits = unit === 'USD' || unit === 'ha' || unit === 't' ? 2 : 0
  const text = number.toLocaleString('en-US', { minimumFractionDigits: unit === 'USD' ? 2 : 0, maximumFractionDigits: digits })
  if (unit === 'USD') return `USD ${text}`
  if (unit === 'ha') return `${text} ha`
  if (unit === 't') return `${text} t`
  if (unit === 'farmers') return `${text}`
  return `${text} ${unit || ''}`.trim()
}

function axisTitleFor(unit) {
  if (unit === 'farmers') return 'Farmers'
  if (unit === 'USD') return 'USD'
  if (unit === 'ha') return 'Hectares (ha)'
  if (unit === 't') return 'Tonnes (t)'
  return String(unit || '')
}

function tickText(value, unit) {
  const number = Number(value) || 0
  if (unit === 'USD') return `$${number.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
  if (unit === 'farmers') return Math.round(number).toLocaleString('en-US')
  const whole = Math.abs(number - Math.round(number)) < 0.05
  return (whole ? Math.round(number) : number).toLocaleString('en-US', { maximumFractionDigits: whole ? 0 : 1 })
}

function niceMax(value, unit) {
  const number = Number(value) || 0
  if (number <= 0) return unit === 'farmers' ? 4 : 1
  if (unit === 'farmers') {
    const padded = Math.ceil(number * 1.25)
    return Math.max(4, padded + (padded % 2))
  }
  const power = 10 ** Math.floor(Math.log10(number))
  const fraction = number / power
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10
  return nice * power
}

function axisTicks(max, unit) {
  const values = Array.from({ length: 5 }, (_, index) => (max / 4) * index)
  const seen = new Set()
  return values.flatMap((value) => {
    const plotted = unit === 'farmers' ? Math.round(value) : value
    const label = tickText(plotted, unit)
    if (seen.has(label)) return []
    seen.add(label)
    return [{ value: plotted, label }]
  })
}

function gutterFor(ticks) {
  const widest = ticks.reduce((width, tick) => Math.max(width, String(tick.label).length), 1)
  return Math.max(48, widest * 8 + 18)
}

function useChartWidth(fallback = 640) {
  const ref = useRef(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const node = ref.current
    if (!node || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver((entries) => {
      const next = Math.floor(entries[0].contentRect.width)
      if (next > 0) setWidth((current) => (current === next ? current : next))
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

function singleReadingNote(rows, labelOf) {
  if (rows.length !== 1) return ''
  const label = labelOf(rows[0])
  return `Only ${label} has a recorded value in this period, so this is one reading rather than a trend.`
}

export function EmptyChart({ title, note }) {
  return (
    <figure className="chart-card">
      <figcaption>
        <strong>{title}</strong>
        {note ? <small>{note}</small> : null}
      </figcaption>
      <div className="chart-empty">
        <p>No data available for the selected period.</p>
      </div>
    </figure>
  )
}

function ChartCard({ title, note, children, legend, wide = false }) {
  return (
    <figure className={wide ? 'chart-card chart-card-wide' : 'chart-card'}>
      <figcaption>
        <strong>{title}</strong>
        {note ? <small>{note}</small> : null}
      </figcaption>
      <div className="chart-plot">{children}</div>
      {legend ? <div className="chart-legend">{legend}</div> : null}
    </figure>
  )
}

function ChartSvg({ width, height, label, children }) {
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      {children}
    </svg>
  )
}

function YAxis({ ticks, gutter, plotRight, plotTop, plotBottom, title }) {
  const max = ticks[ticks.length - 1]?.value || 1
  const plotHeight = plotBottom - plotTop
  return (
    <g>
      <text x={8} y={18} className="chart-axis-title">{title}</text>
      {ticks.map((tick) => {
        const y = plotTop + (1 - tick.value / max) * plotHeight
        return (
          <g key={tick.label}>
            <line x1={gutter} x2={plotRight} y1={y} y2={y} className="chart-gridline" />
            <text x={gutter - 12} y={y + 4} textAnchor="end" className="chart-axis">{tick.label}</text>
          </g>
        )
      })}
    </g>
  )
}

function valueLabelPlacement(barTop, barHeight, plotTop, label, barWidth) {
  const labelWidth = String(label).length * 8
  const fitsInside = barHeight >= 24 && labelWidth <= barWidth - 6
  if (fitsInside) return { y: Math.min(barTop + 16, barTop + barHeight - 8), onBar: true }
  return { y: Math.max(barTop - 10, plotTop + 14), onBar: false }
}

export function TrendChart({ title, rows = [], xKey, yKey, unit, area = false, note }) {
  const [plotRef, width] = useChartWidth()
  if (!rows.length) return <EmptyChart title={title} note={note} />
  const max = niceMax(Math.max(...rows.map((row) => Number(row[yKey]) || 0)), unit)
  const ticks = axisTicks(max, unit)
  const gutter = gutterFor(ticks)
  const plotBottom = PLOT_TOP + PLOT_HEIGHT
  const height = plotBottom + 36
  const plotRight = width - RIGHT_PAD
  const plotWidth = Math.max(plotRight - gutter, 40)
  const single = rows.length === 1
  const points = rows.map((row, index) => {
    const ratio = single ? 0.5 : index / (rows.length - 1)
    const x = gutter + 28 + (plotWidth - 56) * ratio
    const y = PLOT_TOP + (1 - (Number(row[yKey]) || 0) / max) * PLOT_HEIGHT
    return { x, y, row }
  })
  const line = points.map((point) => `${point.x},${point.y}`).join(' ')
  const areaPath = `${line} ${points[points.length - 1].x},${plotBottom} ${points[0].x},${plotBottom}`
  const caption = [note, singleReadingNote(rows, (row) => monthLabel(row[xKey]))].filter(Boolean).join(' ')
  return (
    <ChartCard title={title} note={caption}>
      <div ref={plotRef}>
        <ChartSvg width={width} height={height} label={`${title}. ${axisTitleFor(unit)}`}>
          <YAxis ticks={ticks} gutter={gutter} plotRight={plotRight} plotTop={PLOT_TOP} plotBottom={plotBottom} title={axisTitleFor(unit)} />
          {!single && area ? <polygon points={areaPath} className="chart-area" /> : null}
          {!single ? <polyline points={line} className="chart-line" /> : null}
          {points.map((point) => {
            const value = Number(point.row[yKey]) || 0
            const barHeight = plotBottom - point.y
            const placement = valueLabelPlacement(point.y, barHeight, PLOT_TOP, tickText(value, unit), single ? 36 : 28)
            const label = monthLabel(point.row[xKey])
            return (
              <g key={point.row[xKey]}>
                {single ? (
                  <rect x={point.x - 18} y={point.y} width={36} height={Math.max(barHeight, 0)} className="chart-column" rx="3">
                    <title>{label}: {formatMeasure(value, unit)}</title>
                  </rect>
                ) : (
                  <circle cx={point.x} cy={point.y} r="5" className="chart-point">
                    <title>{label}: {formatMeasure(value, unit)}</title>
                  </circle>
                )}
                <text x={point.x} y={placement.y} textAnchor="middle" className={placement.onBar ? 'chart-onbar' : 'chart-axis'}>{tickText(value, unit)}</text>
                <text x={point.x} y={height - 14} textAnchor="middle" className="chart-axis">{label}</text>
              </g>
            )
          })}
        </ChartSvg>
      </div>
    </ChartCard>
  )
}

export function DoughnutChart({ title, slices = [], unit = 'farmers', note }) {
  const [plotRef, width] = useChartWidth()
  const rows = slices.map((slice) => ({ ...slice, value: Number(slice.value) || 0 }))
  const total = rows.reduce((sum, slice) => sum + slice.value, 0)
  if (!total) return <EmptyChart title={title} note={note} />
  const height = 240
  const radius = Math.min(78, Math.max(64, width / 8))
  const centerY = 112
  const circumference = 2 * Math.PI * radius
  const arcs = rows.reduce((state, slice) => {
    const length = (slice.value / total) * circumference
    return {
      cursor: state.cursor + length,
      pieces: [...state.pieces, { ...slice, length, offset: state.cursor }],
    }
  }, { cursor: 0, pieces: [] }).pieces
  return (
    <ChartCard title={title} note={note} legend={rows.map((slice) => (
      <span key={slice.label}><i style={{ background: slice.color }} />{slice.label}: {formatMeasure(slice.value, unit)}</span>
    ))}>
      <div ref={plotRef}>
        <ChartSvg width={width} height={height} label={title}>
          <circle cx={width / 2} cy={centerY} r={radius} className="chart-ring-track" />
          {arcs.filter((arc) => arc.length > 0).map((arc) => (
            <circle
              key={arc.label}
              cx={width / 2}
              cy={centerY}
              r={radius}
              className="chart-ring"
              stroke={arc.color}
              strokeDasharray={`${arc.length} ${Math.max(circumference - arc.length, 0.01)}`}
              strokeDashoffset={-arc.offset}
              style={{ transform: 'rotate(-90deg)', transformOrigin: `${width / 2}px ${centerY}px` }}
            >
              <title>{arc.label}: {formatMeasure(arc.value, unit)}</title>
            </circle>
          ))}
          <text x={width / 2} y={centerY - 4} textAnchor="middle" className="chart-center">{total.toLocaleString('en-US')}</text>
          <text x={width / 2} y={centerY + 16} textAnchor="middle" className="chart-axis">{axisTitleFor(unit)}</text>
        </ChartSvg>
      </div>
    </ChartCard>
  )
}

export function GroupedBarChart({ title, series = [], unit = 'ha', note }) {
  const [plotRef, width] = useChartWidth()
  const rows = series.map((item) => ({ ...item, value: Number(item.value) || 0 }))
  const max = niceMax(Math.max(...rows.map((item) => item.value), 0), unit)
  const ticks = axisTicks(max, unit)
  const gutter = gutterFor(ticks)
  const plotBottom = PLOT_TOP + PLOT_HEIGHT
  const height = plotBottom + 36
  const plotRight = width - RIGHT_PAD
  const plotWidth = Math.max(plotRight - gutter, 40)
  const band = plotWidth / Math.max(rows.length, 1)
  const barWidth = Math.min(56, band * 0.5)
  return (
    <ChartCard title={title} note={note} legend={rows.map((item) => (
      <span key={item.label}><i style={{ background: item.color }} />{item.label}: {formatMeasure(item.value, unit)}</span>
    ))}>
      <div ref={plotRef}>
        <ChartSvg width={width} height={height} label={`${title}. ${axisTitleFor(unit)}`}>
          <YAxis ticks={ticks} gutter={gutter} plotRight={plotRight} plotTop={PLOT_TOP} plotBottom={plotBottom} title={axisTitleFor(unit)} />
          {rows.map((item, index) => {
            const barHeight = (item.value / max) * PLOT_HEIGHT
            const x = gutter + band * index + (band - barWidth) / 2
            const y = plotBottom - barHeight
            const drawn = item.value === 0 ? 2 : Math.max(barHeight, 3)
            const top = item.value === 0 ? plotBottom - 2 : y
            const placement = valueLabelPlacement(top, drawn, PLOT_TOP, tickText(item.value, unit), barWidth)
            return (
              <g key={item.label}>
                <rect x={x} y={top} width={barWidth} height={drawn} fill={item.color} rx="3">
                  <title>{item.label}: {formatMeasure(item.value, unit)}</title>
                </rect>
                <text x={x + barWidth / 2} y={placement.y} textAnchor="middle" className={placement.onBar ? 'chart-onbar' : 'chart-axis'}>{tickText(item.value, unit)}</text>
                <text x={x + barWidth / 2} y={height - 14} textAnchor="middle" className="chart-axis">{item.label}</text>
              </g>
            )
          })}
        </ChartSvg>
      </div>
    </ChartCard>
  )
}

export function ColumnChart({ title, rows = [], labelKey, valueKey, unit, note, color = '#1f6b45' }) {
  const [plotRef, width] = useChartWidth()
  if (!rows.length) return <EmptyChart title={title} note={note} />
  const max = niceMax(Math.max(...rows.map((row) => Number(row[valueKey]) || 0)), unit)
  const ticks = axisTicks(max, unit)
  const gutter = gutterFor(ticks)
  const plotBottom = PLOT_TOP + PLOT_HEIGHT
  const height = plotBottom + (rows.length > 6 ? 56 : 40)
  const plotRight = width - RIGHT_PAD
  const plotWidth = Math.max(plotRight - gutter, 40)
  const band = plotWidth / rows.length
  const barWidth = Math.min(42, band * 0.62)
  const timeSeries = labelKey === 'month'
  const caption = [note, timeSeries ? singleReadingNote(rows, (row) => monthLabel(row[labelKey])) : ''].filter(Boolean).join(' ')
  return (
    <ChartCard title={title} note={caption}>
      <div ref={plotRef}>
        <ChartSvg width={width} height={height} label={`${title}. ${axisTitleFor(unit)}`}>
          <YAxis ticks={ticks} gutter={gutter} plotRight={plotRight} plotTop={PLOT_TOP} plotBottom={plotBottom} title={axisTitleFor(unit)} />
          {rows.map((row, index) => {
            const value = Number(row[valueKey]) || 0
            const barHeight = (value / max) * PLOT_HEIGHT
            const x = gutter + band * index + (band - barWidth) / 2
            const y = plotBottom - barHeight
            const label = timeSeries ? monthLabel(row[labelKey]) : row[labelKey]
            const placement = valueLabelPlacement(y, barHeight, PLOT_TOP, tickText(value, unit), barWidth)
            const rotate = rows.length > 6
            return (
              <g key={`${row[labelKey]}-${index}`}>
                <rect x={x} y={y} width={barWidth} height={Math.max(barHeight, 0)} fill={color} rx="3">
                  <title>{label}: {formatMeasure(value, unit)}</title>
                </rect>
                <text x={x + barWidth / 2} y={placement.y} textAnchor="middle" className={placement.onBar ? 'chart-onbar' : 'chart-axis'}>{tickText(value, unit)}</text>
                <text
                  x={x + barWidth / 2}
                  y={height - (rotate ? 28 : 14)}
                  textAnchor={rotate ? 'end' : 'middle'}
                  className="chart-axis"
                  transform={rotate ? `rotate(-35 ${x + barWidth / 2} ${height - 28})` : undefined}
                >
                  {label}
                </text>
              </g>
            )
          })}
        </ChartSvg>
      </div>
    </ChartCard>
  )
}

const EXPENSE_COLORS = ['#1f6b45', '#0f766e', '#b8860b', '#1d4e89', '#64748b', '#9a3412']

export function ExpenseAnalysis({ categories = [], months = [] }) {
  const categoryRows = categories.filter((row) => Number(row.amount) > 0)
  const monthRows = months.filter((row) => row.month)
  const total = categories.reduce((sum, row) => sum + (Number(row.amount) || 0), 0)
  if (!categoryRows.length && !monthRows.length) {
    return <EmptyChart title="Expenses analysis" note="No expenses have been recorded for the selected period." />
  }
  return (
    <figure className="chart-card chart-card-wide">
      <figcaption>
        <strong>Expenses analysis</strong>
        <small>Total {formatMeasure(total, 'USD')}</small>
      </figcaption>
      <div className="expense-split">
        <div>
          <p className="chart-subhead">By category</p>
          {categoryRows.length ? <DoughnutBody slices={categoryRows.map((row, index) => ({ label: row.label, value: row.amount, color: EXPENSE_COLORS[index % EXPENSE_COLORS.length] }))} unit="USD" /> : <p className="chart-empty-inline">No data available for the selected period.</p>}
        </div>
        <div>
          <p className="chart-subhead">By month</p>
          {monthRows.length ? <ColumnBody rows={monthRows} labelKey="month" valueKey="amount" unit="USD" color="#0f766e" /> : <p className="chart-empty-inline">No data available for the selected period.</p>}
        </div>
      </div>
    </figure>
  )
}

function DoughnutBody({ slices, unit }) {
  const rows = slices.map((slice) => ({ ...slice, value: Number(slice.value) || 0 }))
  const total = rows.reduce((sum, slice) => sum + slice.value, 0)
  const [plotRef, width] = useChartWidth(420)
  const height = 220
  const radius = 62
  const centerY = 96
  const circumference = 2 * Math.PI * radius
  const arcs = rows.reduce((state, slice) => {
    const length = total ? (slice.value / total) * circumference : 0
    return { cursor: state.cursor + length, pieces: [...state.pieces, { ...slice, length, offset: state.cursor }] }
  }, { cursor: 0, pieces: [] }).pieces
  return (
    <>
      <div ref={plotRef}>
        <ChartSvg width={width} height={height} label="Expenses by category">
          <circle cx={width / 2} cy={centerY} r={radius} className="chart-ring-track" />
          {arcs.filter((arc) => arc.length > 0).map((arc) => (
            <circle key={arc.label} cx={width / 2} cy={centerY} r={radius} className="chart-ring" stroke={arc.color} strokeDasharray={`${arc.length} ${Math.max(circumference - arc.length, 0.01)}`} strokeDashoffset={-arc.offset} style={{ transform: 'rotate(-90deg)', transformOrigin: `${width / 2}px ${centerY}px` }}>
              <title>{arc.label}: {formatMeasure(arc.value, unit)}</title>
            </circle>
          ))}
          <text x={width / 2} y={centerY - 2} textAnchor="middle" className="chart-center">{formatMeasure(total, unit)}</text>
          <text x={width / 2} y={centerY + 16} textAnchor="middle" className="chart-axis">{axisTitleFor(unit)}</text>
        </ChartSvg>
      </div>
      <div className="chart-legend">{rows.map((slice) => <span key={slice.label}><i style={{ background: slice.color }} />{slice.label}: {formatMeasure(slice.value, unit)}</span>)}</div>
    </>
  )
}

function ColumnBody({ rows, valueKey, unit, color }) {
  const [plotRef, width] = useChartWidth(420)
  const max = niceMax(Math.max(...rows.map((row) => Number(row[valueKey]) || 0)), unit)
  const ticks = axisTicks(max, unit)
  const gutter = gutterFor(ticks)
  const plotBottom = PLOT_TOP + 150
  const height = plotBottom + 36
  const plotRight = width - 16
  const plotWidth = Math.max(plotRight - gutter, 40)
  const band = plotWidth / rows.length
  const barWidth = Math.min(32, band * 0.62)
  return (
    <div ref={plotRef}>
      <ChartSvg width={width} height={height} label={`Expenses by month. ${axisTitleFor(unit)}`}>
        <YAxis ticks={ticks} gutter={gutter} plotRight={plotRight} plotTop={PLOT_TOP} plotBottom={plotBottom} title={axisTitleFor(unit)} />
        {rows.map((row, index) => {
          const value = Number(row[valueKey]) || 0
          const barHeight = (value / max) * (plotBottom - PLOT_TOP)
          const x = gutter + band * index + (band - barWidth) / 2
          const y = plotBottom - barHeight
          const label = monthLabel(row.month)
          const placement = valueLabelPlacement(y, barHeight, PLOT_TOP, tickText(value, unit), barWidth)
          return (
            <g key={`${label}-${index}`}>
              <rect x={x} y={y} width={barWidth} height={Math.max(barHeight, 0)} fill={color} rx="3">
                <title>{label}: {formatMeasure(value, unit)}</title>
              </rect>
              <text x={x + barWidth / 2} y={placement.y} textAnchor="middle" className={placement.onBar ? 'chart-onbar' : 'chart-axis'}>{tickText(value, unit)}</text>
              <text x={x + barWidth / 2} y={height - 12} textAnchor="middle" className="chart-axis">{label}</text>
            </g>
          )
        })}
      </ChartSvg>
    </div>
  )
}

export function HorizontalBarChart({ title, rows = [], labelKey, valueKey, unit = 'USD', note }) {
  if (!rows.length) return <EmptyChart title={title} note={note} />
  const max = Math.max(...rows.map((row) => Number(row[valueKey]) || 0), 1)
  return (
    <ChartCard title={title} note={note}>
      <div className="hbar-list">
        <p className="chart-subhead">{axisTitleFor(unit)}</p>
        {rows.map((row) => {
          const value = Number(row[valueKey]) || 0
          return (
            <div key={row[labelKey]} className="hbar-row">
              <span>{row[labelKey]}</span>
              <div className="hbar-track" title={`${row[labelKey]}: ${formatMeasure(value, unit)}`}>
                <i style={{ width: `${(value / max) * 100}%`, background: row.color || '#1f6b45' }} />
              </div>
              <strong>{formatMeasure(value, unit)}</strong>
            </div>
          )
        })}
      </div>
    </ChartCard>
  )
}
