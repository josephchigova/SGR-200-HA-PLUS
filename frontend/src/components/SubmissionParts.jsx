// Read-only views of a lead farmer's input submission, shared by the lead farmer and Admin screens.
// Every figure comes from the server, which works it out from the saved allocations.

import { Pill } from './ui'
import { STATUS_TONE, when } from '../inputSupply'
import { hectares, money, qty } from '../programmeData'

export function StatusPill({ submission }) {
  return <Pill tone={STATUS_TONE[submission.status] || ''}>{submission.status_label}</Pill>
}

export function HectareSummary({ submission }) {
  const issued = submission.approved_hectares !== null && submission.approved_hectares !== undefined
  return (
    <div className="hectare-strip" aria-label="Hectares">
      <span><small>Requested</small><strong>{hectares(submission.requested_hectares)}</strong></span>
      {issued ? <span><small>Approved maximum</small><strong>{hectares(submission.approved_hectares)}</strong></span> : null}
      <span><small>Distributed to farmers</small><strong>{hectares(submission.hectares_total)}</strong></span>
      {issued ? <span><small>Remaining unallocated</small><strong>{hectares(submission.remaining_hectares)}</strong></span> : null}
      <span><small>Farmers</small><strong>{submission.farmer_count}</strong></span>
      {submission.estimated_cost !== null ? <span><small>Estimated cost</small><strong>{money(submission.estimated_cost)}</strong></span> : null}
    </div>
  )
}

export function LimitsTable({ limits }) {
  if (!limits?.length) return null
  return (
    <div className="table-wrap">
      <table className="data-table compact">
        <thead><tr><th>Approved for</th><th>Level</th><th className="num">Requested</th><th className="num">Approved maximum</th><th className="num">Difference</th><th className="num">Distributed</th><th className="num">Remaining</th></tr></thead>
        <tbody>
          {limits.map((row) => {
            const over = Number(row.remaining_hectares) < 0
            return (
              <tr key={row.id} className={over ? 'shortage-row' : ''}>
                <td>{row.name}</td>
                <td>{row.scope_label}</td>
                <td className="num">{hectares(row.requested_hectares)}</td>
                <td className="num"><strong>{hectares(row.approved_hectares)}</strong></td>
                <td className="num">{Number(row.difference_hectares) === 0 ? '—' : hectares(row.difference_hectares)}</td>
                <td className="num">{hectares(row.distributed_hectares)}</td>
                <td className="num">{over ? <span className="field-error">{hectares(-Number(row.remaining_hectares))} over</span> : hectares(row.remaining_hectares)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function CropBreakdown({ crops, showMoney = true }) {
  if (!crops?.length) return null
  return (
    <div className="table-wrap">
      <table className="data-table compact">
        <thead><tr><th>Crop</th><th>Input</th><th>Variety or product</th><th className="num">Hectares</th><th className="num">Quantity</th>{showMoney ? <th className="num">Estimated cost</th> : null}<th className="num">Farmers</th></tr></thead>
        <tbody>
          {crops.flatMap((crop) => crop.varieties.map((variety, index) => (
            <tr key={`${crop.crop}:${variety.requirement}`}>
              <td>{index === 0 ? <strong>{crop.crop_name} · {hectares(crop.hectares)}</strong> : ''}</td>
              <td>{variety.input_category_label}</td>
              <td>{variety.product_name}</td>
              <td className="num">{hectares(variety.hectares)}{variety.approved_hectares ? <small className="block-hint">max {hectares(variety.approved_hectares)}</small> : null}</td>
              <td className="num"><strong>{qty(variety.quantity)} {variety.unit}</strong></td>
              {showMoney ? <td className="num">{money(variety.estimated_cost)}</td> : null}
              <td className="num">{variety.farmers}</td>
            </tr>
          )))}
        </tbody>
      </table>
    </div>
  )
}

export function AllocationRows({ allocations, actions }) {
  return allocations.map((row) => (
    <tr key={row.id}>
      <td>{row.farmer_name}<small className="block-hint">{row.membership_number}</small></td>
      <td>{row.crop_name}</td>
      <td>{row.lines.map((line) => <div key={line.id}>{line.product_name}: {hectares(line.hectares)} → {qty(line.quantity)} {line.unit}</div>)}</td>
      <td className="num">{hectares(row.hectares)}</td>
      <td className="num">{money(row.estimated_cost)}</td>
      {actions ? <td>{actions(row)}</td> : null}
    </tr>
  ))
}

export function AllocationsTable({ allocations, actions, empty = 'No allocations yet.' }) {
  if (!allocations?.length) return <div className="form-message">{empty}</div>
  return (
    <div className="table-wrap">
      <table className="data-table compact">
        <thead><tr><th>Farmer</th><th>Crop</th><th>Varieties and quantities</th><th className="num">Hectares</th><th className="num">Estimated cost</th>{actions ? <th>Actions</th> : null}</tr></thead>
        <tbody><AllocationRows allocations={allocations} actions={actions} /></tbody>
      </table>
    </div>
  )
}

export function History({ events }) {
  if (!events?.length) return null
  return (
    <ol className="submission-history">
      {[...events].reverse().map((event) => (
        <li key={event.id}>
          <strong>{event.action_label}</strong> · {event.actor_name || 'System'} · {when(event.created_at)}
          {event.remarks ? <div className="history-remarks">“{event.remarks}”</div> : null}
          {event.detail?.farmer ? <div className="block-hint">{event.detail.farmer} · {event.detail.crop}: {(event.detail.varieties || []).map((item) => `${item.name} ${item.hectares} ha`).join(', ')}</div> : null}
        </li>
      ))}
    </ol>
  )
}
