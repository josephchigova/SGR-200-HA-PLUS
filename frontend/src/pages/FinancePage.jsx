import { useEffect, useRef, useState } from 'react'

import apiClient from '../api/client'

const REPORTS = [
  ['dashboard', 'Dashboard'],
  ['profit-loss', 'Profit & Loss'],
  ['balance-sheet', 'Balance Sheet'],
  ['cash-flow', 'Cash Flow'],
  ['trial-balance', 'Trial Balance'],
  ['journal-register', 'Journals'],
  ['receivables-aging', 'Receivables'],
  ['payables-aging', 'Payables'],
  ['operations', 'Operations'],
  ['asset-register', 'Assets'],
  ['audit', 'Audit'],
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
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [manualRange, setManualRange] = useState(false)
  const [journalError, setJournalError] = useState('')
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
      if (!start || !end) return
      setLoading(true)
      setError('')
      try {
        const params = { start, end, as_of: end }
        if (selectedSeason?.name) params.season_name = selectedSeason.name
        const [reportResponse, accountResponse] = await Promise.all([
          apiClient.get(`/finance-reports/${reportName}/`, { params }),
          apiClient.get('/ledger-accounts/'),
        ])
        if (current !== requestId.current) return
        setReport(reportResponse.data)
        const loadedAccounts = accountResponse.data?.results || accountResponse.data || []
        setAccounts(loadedAccounts)
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

  const postJournal = async (event) => {
    event.preventDefault()
    setJournalError('')
    setNotice('')
    const form = new FormData(event.target)
    const amount = form.get('amount')
    const debit = form.get('debit_account')
    const credit = form.get('credit_account')
    if (!amount || Number(amount) <= 0) {
      setJournalError('Enter an amount greater than zero.')
      return
    }
    if (!debit || !credit) {
      setJournalError('Choose both a debit account and a credit account.')
      return
    }
    if (debit === credit) {
      setJournalError('The debit account and the credit account must be different.')
      return
    }
    try {
      await apiClient.post('/journals/', {
        entry_date: form.get('entry_date'),
        description: form.get('description'),
        post: true,
        lines: [
          { account: Number(debit), debit: amount, credit: '0.00' },
          { account: Number(credit), debit: '0.00', credit: amount },
        ],
      })
      event.target.reset()
      setNotice('The journal was posted.')
      setReportName('journal-register')
      setReload((value) => value + 1)
    } catch (requestError) {
      const detail = requestError.response?.data?.detail
      setJournalError(typeof detail === 'string' ? detail : 'The journal was not posted.')
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
      <div className="finance-filters">
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
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
      {notice ? <div className="form-message" role="status">{notice}</div> : null}
      {loading ? <div className="form-message">Loading financial records...</div> : null}
      {!loading && reportName === 'dashboard' && report ? <Dashboard report={report} /> : null}
      {!loading && reportName === 'profit-loss' && report ? <ProfitAndLoss report={report} /> : null}
      {!loading && reportName === 'balance-sheet' && report ? <BalanceSheet report={report} /> : null}
      {!loading && reportName === 'cash-flow' && report ? <CashFlow report={report} /> : null}
      {!loading && reportName === 'operations' && report ? <Operations report={report} seasonName={selectedSeason?.name} /> : null}
      {!loading && ['trial-balance', 'journal-register', 'receivables-aging', 'payables-aging', 'asset-register', 'audit'].includes(reportName) ? <RecordTable report={report} /> : null}
      <JournalForm accounts={accounts} defaultDate={end} error={journalError} onSubmit={postJournal} />
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

function CashFlow({ report }) {
  const rows = [
    ['Opening cash', report.opening_cash],
    ['Operating', report.operating],
    ['Investing', report.investing],
    ['Financing', report.financing],
    ['Net change', report.net_change],
    ['Closing cash', report.closing_cash],
  ]
  return (
    <section>
      <table className="finance-table">
        <thead><tr><th>Movement</th><th className="num">Amount</th></tr></thead>
        <tbody>
          {rows.map(([label, value]) => <tr key={label}><td>{label}</td><td className="num">{money(value)}</td></tr>)}
        </tbody>
      </table>
      {report.note ? <p className="finance-note">{report.note}</p> : null}
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
            <table className="finance-table">
              <thead><tr><th>Programme</th><th className="num">Hectares</th><th className="num">Cost</th></tr></thead>
              <tbody>
                {allocations.programmes.map((row) => (
                  <tr key={row.programme}><td>{row.programme}</td><td className="num">{money(row.hectares)}</td><td className="num">{money(row.cost)}</td></tr>
                ))}
              </tbody>
            </table>
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
        <table className="finance-table">
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
        </table>
      ) : <div className="form-message">No recognized amounts for this section.</div>}
    </section>
  )
}

function namedRows(rows) {
  return (rows || []).map((row) => ({ ...row, code: row.status === 'derived_unverified' ? 'Unverified' : row.status === 'unverified_zero' ? 'Unverified' : '' }))
}

function RecordTable({ report }) {
  const rows = Array.isArray(report?.rows) ? report.rows : []
  if (!rows.length) return <div className="form-message">No records for the selected period.</div>
  const columns = Object.keys(rows[0]).filter((key) => typeof rows[0][key] !== 'object')
  return (
    <div className="table-scroll">
      <table className="finance-table">
        <thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll('_', ' ')}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || row.reference || row.asset_id || index}>
              {columns.map((column) => <td key={column} className={typeof row[column] === 'string' && /^-?\d+\.\d{2}$/.test(row[column]) ? 'num' : ''}>{String(row[column] ?? '')}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function JournalForm({ accounts, defaultDate, error, onSubmit }) {
  return (
    <form className="journal-form" onSubmit={onSubmit}>
      <h4>Post a balanced journal</h4>
      <p className="finance-note">Debits must equal credits. A posted entry cannot be edited; reverse it if it was wrong.</p>
      <div className="journal-grid">
        <label>Date <input name="entry_date" type="date" required defaultValue={defaultDate} /></label>
        <label>Description <input name="description" required placeholder="What is this entry for?" /></label>
        <label>Amount <input name="amount" inputMode="decimal" required placeholder="0.00" /></label>
        <label>Debit account <AccountSelect accounts={accounts} name="debit_account" /></label>
        <label>Credit account <AccountSelect accounts={accounts} name="credit_account" /></label>
        <button type="submit">Post journal</button>
      </div>
      {error ? <div className="form-message error" role="alert">{error}</div> : null}
    </form>
  )
}

function AccountSelect({ accounts, name }) {
  return (
    <select name={name} required defaultValue="">
      <option value="">Select an account</option>
      {accounts.map((account) => <option key={account.id} value={account.id}>{account.code} {account.name}</option>)}
    </select>
  )
}

export default FinancePage
