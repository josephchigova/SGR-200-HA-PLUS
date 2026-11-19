// Sharing out a maximum Admin set, in the same submission.
//
// The lead farmer changes the hectares of the farmers already in the submission, sees the totals
// and every limit update as they type, saves all the changes together, and sends the submission
// back to Admin. The figures shown while typing are estimates; the server recalculates and
// checks every limit when the changes are saved and sent.

import { useState } from 'react'

import Icon from './Icon'
import { hectares, money, qty } from '../programmeData'

const keyOf = (allocation, line) => `${allocation.id}:${line.requirement}`

// Land hectares of one farmer's crop: the largest input type, because seed and fertilizer
// usually cover the same land. This matches how the server counts it.
function landOf(lines) {
  const byCategory = {}
  lines.forEach((line) => { byCategory[line.input_category] = (byCategory[line.input_category] || 0) + line.hectares })
  return Math.max(0, ...Object.values(byCategory))
}

function measure(allocations, values) {
  const crops = {}
  const categories = {}
  const varieties = {}
  let land = 0
  let cost = 0
  allocations.forEach((allocation) => {
    const lines = allocation.lines.map((line) => {
      const area = Math.max(0, Number(values[keyOf(allocation, line)]) || 0)
      const perHectare = Number(line.hectares) ? Number(line.estimated_cost || 0) / Number(line.hectares) : 0
      cost += area * perHectare
      categories[`${allocation.crop}:${line.input_category}`] = (categories[`${allocation.crop}:${line.input_category}`] || 0) + area
      varieties[line.requirement] = (varieties[line.requirement] || 0) + area
      return { input_category: line.input_category, hectares: area }
    })
    const area = landOf(lines)
    crops[allocation.crop] = (crops[allocation.crop] || 0) + area
    land += area
  })
  return { crops, categories, varieties, land, cost }
}

function usedFor(limit, measured) {
  if (limit.scope === 'VARIETY') return measured.varieties[limit.requirement] || 0
  if (limit.scope === 'CATEGORY') return measured.categories[`${limit.crop}:${limit.input_category}`] || 0
  return measured.crops[limit.crop] || 0
}

function Redistribution({ submission, busy, onSave, onSend, onAddFarmer }) {
  const allocations = submission.allocations || []
  const [values, setValues] = useState(() => Object.fromEntries(allocations.flatMap((allocation) => allocation.lines.map((line) => [keyOf(allocation, line), String(Number(line.hectares))]))))
  const [details, setDetails] = useState(false)
  const measured = measure(allocations, values)
  const allowed = Number(submission.approved_hectares || 0)
  const toReduce = Math.max(0, measured.land - allowed)
  const overAll = (submission.limits || [])
    .map((limit) => ({ limit, used: usedFor(limit, measured), excess: usedFor(limit, measured) - Number(limit.approved_hectares) }))
    .filter(({ excess }) => excess > 1e-9)
  // Name the most specific thing to change: a crop or input type is left out when a variety
  // under it is over by as much, because reducing that variety fixes both.
  const under = (outer, inner) => inner.limit.crop === outer.limit.crop && (outer.limit.scope === 'CROP'
    ? inner.limit.scope !== 'CROP'
    : inner.limit.scope === 'VARIETY' && inner.limit.input_category === outer.limit.input_category)
  const over = overAll.filter((item) => item.limit.scope === 'VARIETY' || !overAll.some((other) => other !== item && under(item, other) && other.excess >= item.excess - 1e-9))
  const changed = allocations.filter((allocation) => allocation.lines.some((line) => Number(values[keyOf(allocation, line)]) !== Number(line.hectares)))
  const invalid = Object.values(values).some((value) => value === '' || Number(value) < 0 || Number.isNaN(Number(value)))

  const changes = () => changed.map((allocation) => ({
    allocation: allocation.id,
    version: allocation.version,
    lines: allocation.lines.map((line) => ({ requirement: line.requirement, hectares: values[keyOf(allocation, line)] })),
  }))

  return (
    <section className="card redistribution">
      <div className="redistribution-intro" role="note">
        <Icon name="alert" />
        <p>
          Admin has allowed <strong>{hectares(allowed)}</strong> of the {hectares(submission.requested_hectares)} you requested.
          Adjust your farmers’ allocations below so the total does not go over {hectares(allowed)}, then send it back to Admin for approval.
        </p>
      </div>

      <div className="hectare-strip" aria-label="Redistribution summary">
        <span><small>Originally requested</small><strong>{hectares(submission.requested_hectares)}</strong></span>
        <span><small>Admin has allowed</small><strong>{hectares(allowed)}</strong></span>
        <span><small>Currently allocated</small><strong>{hectares(measured.land)}</strong></span>
        {toReduce > 0
          ? <span className="over"><small>Hectares to reduce</small><strong>{hectares(toReduce)}</strong></span>
          : <span><small>Remaining</small><strong>{hectares(allowed - measured.land)}</strong></span>}
        <span><small>Estimated cost</small><strong>{money(measured.cost)}</strong></span>
      </div>

      {over.length ? (
        <ul className="redistribution-problems" aria-label="Still to fix">
          {over.map(({ limit, used }) => (
            <li key={limit.id}><strong>{limit.name}</strong>: reduce by {hectares(used - Number(limit.approved_hectares))} (allowed {hectares(limit.approved_hectares)}, now {hectares(used)})</li>
          ))}
        </ul>
      ) : <p className="form-message success">Every maximum is met. Save your changes and send the submission back to Admin.</p>}

      <div className="table-wrap">
        <table className="data-table compact redistribution-table">
          <thead>
            <tr>
              <th>Farmer</th><th>Crop</th><th>Variety or product</th><th className="num">Current ha</th><th className="num">New ha</th>
              {details ? <><th className="num">Quantity</th><th className="num">Estimated cost</th></> : null}
            </tr>
          </thead>
          <tbody>
            {allocations.flatMap((allocation) => allocation.lines.map((line, index) => {
              const key = keyOf(allocation, line)
              const area = Math.max(0, Number(values[key]) || 0)
              const perHectare = Number(line.hectares) ? Number(line.estimated_cost || 0) / Number(line.hectares) : 0
              return (
                <tr key={key} className={Number(values[key]) !== Number(line.hectares) ? 'changed-row' : ''}>
                  <td>{index === 0 ? <>{allocation.farmer_name}<small className="block-hint">{allocation.membership_number}</small></> : null}</td>
                  <td>{index === 0 ? allocation.crop_name : null}</td>
                  <td>{line.product_name}<small className="block-hint">{line.input_category_label}</small></td>
                  <td className="num">{hectares(line.hectares)}</td>
                  <td className="num">
                    <input className="hectare-input" type="number" min="0" step="any" inputMode="decimal" aria-label={`New hectares of ${line.product_name} for ${allocation.farmer_name}`}
                      value={values[key]} onChange={(event) => setValues({ ...values, [key]: event.target.value })} />
                  </td>
                  {details ? <><td className="num">{qty(area * Number(line.rate_per_hectare || 0))} {line.unit}</td><td className="num">{money(area * perHectare)}</td></> : null}
                </tr>
              )
            }))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan="3">Total land</th>
              <th className="num">{hectares(submission.hectares_total)}</th>
              <th className="num">{hectares(measured.land)}</th>
              {details ? <><th /><th className="num">{money(measured.cost)}</th></> : null}
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="field-hint">Enter 0 to take a variety away from a farmer. A farmer left with nothing is removed from this submission.</p>

      <div className="redistribution-actions">
        <button type="button" className="link-btn" onClick={() => setDetails(!details)} aria-expanded={details}>{details ? 'Hide quantities and costs' : 'Show quantities and costs'}</button>
        <button type="button" className="link-btn" onClick={onAddFarmer}><Icon name="plus" />Add another farmer</button>
        <span className="spacer" />
        <button type="button" className="ghost-btn" disabled={busy || invalid || !changed.length} onClick={() => onSave(changes())}>Save changes</button>
        <button type="button" className="primary-btn" disabled={busy || invalid || over.length > 0} title={over.length ? 'Reduce the hectares listed above first.' : undefined}
          onClick={() => onSend(changed.length ? changes() : null)}>
          <Icon name="send" />Send back to Admin for approval
        </button>
      </div>
    </section>
  )
}

export default Redistribution
