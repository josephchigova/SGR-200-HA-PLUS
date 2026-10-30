import { useEffect, useRef, useState } from 'react'

import apiClient from '../api/client'
import AssetsPanel from './AssetsPanel'

const REPORTS = [
  ['dashboard', 'Dashboard'],
  ['assets', 'Assets'],
  ['operations', 'Operations'],
  ['subscription-report', 'Subscriptions'],
  ['debtors', 'Debtors'],
  ['expense-schedule', 'Expenses'],
  ['cash-bank', 'Cash and Bank'],
  ['profit-loss', 'Profit & Loss'],
  ['balance-sheet', 'Balance Sheet'],
]

function money(value) {
  if (value === null || value === undefined || value === '') return 'Not available'
  const amount = Number(value)
  if (Number.isNaN(amount)) return String(value)
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount)
}

function FinancePage({ selectedSeason }) {
  const [reportName, setReportName] = useState('dashboard')
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [manualRange, setManualRange] = useState(false)
  const [schedule, setSchedule] = useState(null)
  const [debtors, setDebtors] = useState(null)
  const [expenseForm, setExpenseForm] = useState({ expense_date: '', description: '', amount: '', method: 'CASH', category: 'OTHER', reference: '', paid: true, notes: '' })
  const [reload, setReload] = useState(0)
  const requestId = useRef(0)

  const seasonStart = selectedSeason?.start_date || ''
  const seasonEnd = selectedSeason?.end_date || ''
  if (!manualRange && seasonStart && seasonEnd && (start !== seasonStart || end !== seasonEnd)) {
    setStart(seasonStart)
    setEnd(seasonEnd)
  }

  useEffect(() => {
    const current = ++requestId.current
    const load = async () => {
      if (reportName === 'assets') {
        setLoading(false)
        setReport(null)
        return
      }
      if (!start || !end) return
      setLoading(true)
      setError('')
      try {
        const params = { start, end, as_of: end }
        if (selectedSeason?.name) params.season_name = selectedSeason.name
        if (reportName === 'debtors') {
          const response = await apiClient.get('/farmer-subscriptions/debtors/', { params: { season_name: selectedSeason?.name || '' } })
          if (current !== requestId.current) return
          setDebtors(response.data)
          setReport(null)
          return
        }
        if (reportName === 'expense-schedule') {
          const response = await apiClient.get('/expense-schedule/', { params: { start, end } })
          if (current !== requestId.current) return
          setSchedule(response.data)
          setReport(null)
          return
        }
        const reportResponse = await apiClient.get(`/finance-reports/${reportName}/`, { params })
        if (current !== requestId.current) return
        setReport(reportResponse.data)
      } catch (requestError) {
        if (current !== requestId.current) return
        const detail = requestError.response?.data?.detail
        setError(typeof detail === 'string' ? detail : 'Unable to load the financial report.')
        setReport(null)
      } finally {
        if (current === requestId.current) setLoading(false)
      }
    }
    load()
  }, [reportName, start, end, selectedSeason?.name, reload])

  const download = async (format) => {
    setNotice('')
    try {
      const response = await apiClient.get(`/finance-reports/${reportName}/`, {
        params: { start, end, as_of: end, format, season_name: selectedSeason?.name || '' },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = `${reportName}.${format}`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('The export could not be downloaded.')
    }
  }

  const saveExpense = async (event) => {
    event.preventDefault()
    setNotice('')
    setError('')
    try {
      await apiClient.post('/expense-schedule/', { ...expenseForm, paid: expenseForm.paid })
      setNotice('Expense recorded.')
      setExpenseForm({ expense_date: end, description: '', amount: '', method: 'CASH', category: 'OTHER', reference: '', paid: true, notes: '' })
      setReload((value) => value + 1)
    } catch (requestError) {
      const detail = requestError.response?.data
      setError(detail ? Object.values(detail).flat().join(' ') : 'The expense was not recorded.')
    }
  }

  return (
    <div className="page-card finance-page">
      <div className="section-head">
        <div>
          <h3>Finance</h3>
          <p className="finance-note">Subscription income is recognized only when it is posted. The balance sheet opening position comes from the workbook calculation.</p>
        </div>
      </div>
      <div className="finance-tabs" role="tablist" aria-label="Finance sections">
        {REPORTS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={reportName === key} className={reportName === key ? 'active' : ''} onClick={() => setReportName(key)}>{label}</button>
        ))}
      </div>
      {reportName === 'assets' ? <AssetsPanel /> : null}
      {reportName !== 'assets' ? <div className="finance-filters">
        <label>From <input type="date" value={start} onChange={(event) => { setManualRange(true); setStart(event.target.value) }} /></label>
        <label>To <input type="date" value={end} onChange={(event) => { setManualRange(true); setEnd(event.target.value) }} /></label>
        <button type="button" className="ghost-btn" onClick={() => download('csv')}>Export CSV</button>
        <button type="button" className="ghost-btn" onClick={() => download('pdf')}>Export PDF</button>
        <button type="button" className="ghost-btn" onClick={async () => {
          try {
            await apiClient.post('/ledger-accounts/ensure-defaults/')
            setNotice('Default accounts are ready.')
            setReload((value) => value + 1)
          } catch (requestError) {
            const detail = requestError.response?.data?.detail
            setError(typeof detail === 'string' ? detail : 'The chart of accounts could not be loaded.')
          }
        }}>Load default accounts</button>
      </div> : null}
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message" role="status">{notice}</div> : null}
      {loading ? <div className="form-message">Loading financial records...</div> : null}
      {!loading && reportName === 'dashboard' && report ? <Dashboard report={report} /> : null}
      {!loading && reportName === 'profit-loss' && report ? <ProfitAndLoss report={report} /> : null}
      {!loading && reportName === 'balance-sheet' && report ? <BalanceSheet report={report} /> : null}
      {!loading && reportName === 'operations' && report ? <Operations report={report} seasonName={selectedSeason?.name} /> : null}
      {!loading && reportName === 'subscription-report' && report ? <SubscriptionReport report={report} /> : null}
      {!loading && reportName === 'cash-bank' && report ? <CashBank report={report} /> : null}
      {!loading && reportName === 'debtors' ? <Debtors rows={debtors?.results || []} /> : null}
      {!loading && reportName === 'expense-schedule' ? <ExpenseSchedule schedule={schedule} form={expenseForm} setForm={setExpenseForm} onSubmit={saveExpense} /> : null}
    </div>
  )
}

function Dashboard({ report }) {
  const cards = [
    ['Subscription Revenue', report.subscription_revenue ?? report.total_revenue, report.revenue_caption],
    ['Recognized Expenses', report.total_expenses, report.expense_caption],
    ['Net profit', report.net_profit, 'Subscription revenue minus recognized expenses.'],
    ['Total Assets', report.total_assets, 'Opening position at 30 September 2026, calculated from source records. Not a posted journal.'],
    ['Total Liabilities', report.total_liabilities, 'Unverified. The workbook has no payable ledger, so this opening figure stays zero until a liability is confirmed.'],
    ['Total Equity', report.total_equity, 'Includes derived capital, which is not a verified capital balance.'],
    ['Cash on Hand', report.ledger_cash, 'Posted cash for the selected dates. A genuine zero means no cash journals have been posted.'],
    ['Bank Balances', report.bank_balances, 'September closing balance from the reconciled bank book. This is the opening bank figure, not a posted ledger balance.'],
    ['Recognized Receivables', report.ledger_receivable, 'Posted receivables for the selected dates. Opening subscription amounts due are on the balance sheet.'],
    ['Recognized Payables', report.ledger_payable, 'Posted payables for the selected dates. A genuine zero means no payable journals have been posted.'],
  ]
  return (
    <section className="finance-grid">
      {cards.map(([label, value, caption]) => (
        <article className="stat-card" key={label}>
          <span>{label}</span>
          <strong>{money(value)}</strong>
          {caption ? <small>{caption}</small> : null}
        </article>
      ))}
    </section>
  )
}

function ProfitAndLoss({ report }) {
  return (
    <section className="finance-stack">
      <Statement title="Subscription revenue" rows={report.revenue || []} total={report.subscription_revenue || report.total_revenue} />
      {report.other_revenue?.length ? <Statement title="Other posted amounts excluded from income" rows={report.other_revenue} total={report.excluded_revenue} /> : null}
      <Statement title="Recognized expenses" rows={report.expenses || []} total={report.total_expenses} />
      <p className="finance-total">Net profit {money(report.net_profit)}</p>
      {report.basis ? <p className="finance-note">{report.basis}</p> : null}
    </section>
  )
}

function BalanceSheet({ report }) {
  const sheet = report.workbook
  if (!sheet) return <div className="form-message">The workbook balance sheet is not available.</div>
  return (
    <section className="finance-stack">
      <h4>{sheet.title}</h4>
      <p className="finance-note">Reporting date {sheet.as_of}</p>
      <Statement title="Assets" rows={namedRows(sheet.assets)} total={sheet.total_assets} />
      <Statement title="Liabilities" rows={namedRows(sheet.liabilities)} total={sheet.total_liabilities} />
      <Statement title="Equity" rows={namedRows(sheet.equity)} total={sheet.total_equity} />
      <p className={sheet.balanced ? 'finance-total' : 'form-message error'}>
        Assets {money(sheet.total_assets)} · Liabilities {money(sheet.total_liabilities)} · Equity {money(sheet.total_equity)} · Difference {money(sheet.equation_difference)}
      </p>
      {sheet.difference_without_derived_capital ? <p className="finance-note">Without the unverified capital figure, assets exceed liabilities and retained earnings by {money(sheet.difference_without_derived_capital)}.</p> : null}
      {(sheet.notes || []).map((note) => <p className="finance-note" key={note}>{note}</p>)}
    </section>
  )
}

function Operations({ report, seasonName }) {
  const subscriptions = report.subscriptions || {}
  const allocations = report.input_allocations || {}
  const debts = report.input_debts || {}
  const deliveries = report.deliveries || {}
  return (
    <section className="finance-stack">
      <p className="finance-note">Operational figures for {seasonName || 'the selected period'}. They are not accounting balances unless a ledger amount is shown.</p>
      <div className="ops-grid">
        <article className="ops-card">
          <h4>Subscriptions</h4>
          <Metric label="Expected" value={subscriptions.expected} />
          <Metric label="Paid" value={subscriptions.paid} />
          <Metric label="Outstanding" value={subscriptions.outstanding} />
          <Metric label="Posted to the ledger" value={subscriptions.ledger_posted} />
          <Metric label="Collection" value={subscriptions.collection_percent === null || subscriptions.collection_percent === undefined ? 'Not available' : `${money(subscriptions.collection_percent)}%`} plain />
          <p>{subscriptions.note}</p>
        </article>
        <article className="ops-card">
          <h4>Input allocations</h4>
          <Metric label="Allocated cost" value={allocations.total_input_cost} />
          <Metric label="Allocated hectares" value={allocations.hectares} />
          <p>{allocations.note}</p>
          {allocations.programmes?.length ? (
            <div className="table-wrap"><table className="finance-table">
              <thead><tr><th>Programme</th><th className="num">Hectares</th><th className="num">Cost</th></tr></thead>
              <tbody>
                {allocations.programmes.map((row) => (
                  <tr key={row.programme}><td>{row.programme}</td><td className="num">{money(row.hectares)}</td><td className="num">{money(row.cost)}</td></tr>
                ))}
              </tbody>
            </table></div>
          ) : <p>No programme breakdown is available.</p>}
        </article>
        <article className="ops-card">
          <h4>Input debt and recovery</h4>
          <Metric label="Operational debt" value={debts.total_debt} />
          <Metric label="SGR amount" value={debts.sgr_amount} />
          <Metric label="ARDA amount" value={debts.arda_amount} />
          <Metric label="Recovered" value={debts.amount_recovered} />
          <Metric label="Outstanding" value={debts.outstanding} />
          <Metric label="Recognized receivables" value={debts.recognized_receivables} plain />
          <p>{debts.note}</p>
        </article>
        <article className="ops-card">
          <h4>Deliveries</h4>
          <Metric label="Tonnes delivered" value={deliveries.tonnes} />
          <Metric label="Recorded value" value={deliveries.recorded_value} />
          <Metric label="Amount recovered" value={deliveries.amount_recovered} />
          <Metric label="Farmer balance" value={deliveries.farmer_balance} />
          <p>{deliveries.note}</p>
        </article>
      </div>
    </section>
  )
}

function Metric({ label, value, plain = false }) {
  return <p className="metric"><span>{label}</span><strong>{plain ? value ?? 'Not available' : money(value)}</strong></p>
}

function Statement({ title, rows, total }) {
  return (
    <section>
      <h4>{title}</h4>
      {rows.length ? (
        <div className="table-wrap"><table className="finance-table">
          <thead><tr><th>Account</th><th>Name</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.account_id || row.name}>
                <td>{row.code || row.status || ''}</td>
                <td>{row.name}{row.source ? <small className="finance-note">{row.source}</small> : null}</td>
                <td className="num">{money(row.amount)}</td>
              </tr>
            ))}
            <tr><td /><td>Total</td><td className="num">{money(total)}</td></tr>
          </tbody>
        </table></div>
      ) : <div className="form-message">No recognized amounts for this section.</div>}
    </section>
  )
}

function namedRows(rows) {
  return (rows || []).map((row) => ({ ...row, code: row.status === 'derived_unverified' ? 'Unverified' : row.status === 'unverified_zero' ? 'Unverified' : '' }))
}

function SubscriptionReport({ report }) {
  return (
    <section className="finance-grid">
      <article className="stat-card"><span>Obligations due</span><strong>{money(report.obligations_due)}</strong></article>
      <article className="stat-card"><span>Payments received</span><strong>{money(report.payments_received)}</strong></article>
      <article className="stat-card"><span>Outstanding receivables</span><strong>{money(report.outstanding_receivables)}</strong></article>
      <article className="stat-card"><span>Paid / Partial / Unpaid</span><strong>{report.paid} / {report.partial} / {report.unpaid}</strong></article>
      <p className="finance-note">{report.note}</p>
    </section>
  )
}

function CashBank({ report }) {
  const rows = [
    ['Workbook opening bank', report.workbook_opening_bank],
    ['Subscription cash receipts', report.cash_receipts],
    ['Subscription bank receipts', report.bank_receipts],
    ['Other cash receipts', report.other_cash_receipts],
    ['Other bank receipts', report.other_bank_receipts],
    ['Cash expenses', report.cash_expenses],
    ['Bank expenses', report.bank_expenses],
    ['Cash transfers', report.cash_transfers],
    ['Bank transfers', report.bank_transfers],
    ['Cash movement', report.closing_cash_movement],
    ['Bank movement', report.closing_bank_movement],
  ]
  return (
    <section>
      <div className="table-wrap"><table className="finance-table"><tbody>{rows.map(([label, value]) => <tr key={label}><td>{label}</td><td className="num">{money(value)}</td></tr>)}</tbody></table></div>
      <p className="finance-note">{report.note}</p>
    </section>
  )
}

function Debtors({ rows }) {
  if (!rows.length) return <div className="form-message">No recognised outstanding subscription balances for this year.</div>
  return (
    <div className="table-wrap"><table className="finance-table">
      <thead><tr><th>Farmer</th><th>Province</th><th>District</th><th className="num">Due</th><th className="num">Paid</th><th className="num">Subscription outstanding</th><th className="num">Input debt</th><th className="num">Total</th><th>Status</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.farmer}>
            <td>{row.farmer_name}<br /><small>{row.national_id || row.membership_number}</small></td>
            <td>{row.province_name || '—'}</td>
            <td>{row.district_name || '—'}</td>
            <td className="num">{money(row.expected_amount)}</td>
            <td className="num">{money(row.paid_amount)}</td>
            <td className="num">{money(row.outstanding_subscription)}</td>
            <td className="num">{money(row.outstanding_input_debt)}</td>
            <td className="num">{money(row.total_outstanding)}</td>
            <td>{row.payment_status}<br /><a href={`/farmers/${row.farmer}`}>Statement</a></td>
          </tr>
        ))}
      </tbody>
    </table></div>
  )
}

function ExpenseSchedule({ schedule, form, setForm, onSubmit }) {
  const rows = schedule?.results || []
  const categories = schedule?.categories || []
  return (
    <section className="finance-stack">
      <form className="journal-grid" onSubmit={onSubmit}>
        <label>Date <input type="date" required value={form.expense_date} onChange={(event) => setForm({ ...form, expense_date: event.target.value })} /></label>
        <label>Description <input required value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
        <label>Amount <input required inputMode="decimal" value={form.amount} onChange={(event) => setForm({ ...form, amount: event.target.value })} /></label>
        <label>Payment method <select value={form.method} onChange={(event) => setForm({ ...form, method: event.target.value })}><option value="CASH">Cash</option><option value="BANK">Bank</option></select></label>
        <label>Category <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>{categories.map((category) => <option key={category.code} value={category.code}>{category.label}</option>)}{categories.length ? null : <option value="OTHER">Other Expenses</option>}</select></label>
        <label>Reference <input value={form.reference} onChange={(event) => setForm({ ...form, reference: event.target.value })} /></label>
        <label>Paid now <input type="checkbox" checked={form.paid} onChange={(event) => setForm({ ...form, paid: event.target.checked })} /></label>
        <label>Notes <input value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label>
        <button type="submit">Record expense</button>
      </form>
      <p className="finance-total">Total {money(schedule?.total || 0)} · Paid {money(schedule?.paid || 0)} · Outstanding {money(schedule?.outstanding || 0)}</p>
      {rows.length ? (
        <div className="table-wrap"><table className="finance-table">
          <thead><tr><th>Date</th><th>Description</th><th>Category</th><th className="num">Amount</th><th>Method</th><th>Status</th><th>Reference</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id}><td>{row.date}</td><td>{row.description}</td><td>{row.category}</td><td className="num">{money(row.amount)}</td><td>{row.method}</td><td>{row.status}</td><td>{row.reference}</td></tr>)}</tbody>
        </table></div>
      ) : <div className="form-message">No expenses for the selected period.</div>}
    </section>
  )
}

export default FinancePage
