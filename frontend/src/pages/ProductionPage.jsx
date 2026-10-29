import { useEffect, useState } from 'react'

import apiClient from '../api/client'
import TabSearch from '../components/TabSearch'

function ProductionPage() {
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const filteredPlans = plans.filter((plan) => `${plan.season} ${plan.crop}`.toLowerCase().includes(search.toLowerCase()))

  useEffect(() => {
    const loadPlans = async () => {
      const token = localStorage.getItem('sgr_access_token')
      if (!token) {
        setLoading(false)
        setError('Please sign in to view production plans.')
        return
      }

      try {
        const response = await apiClient.get('/production-plans/', {
          headers: { Authorization: `Bearer ${token}` },
        })
        setPlans(response.data?.results || response.data || [])
      } catch {
        setError('Unable to load production plans.')
      } finally {
        setLoading(false)
      }
    }

    loadPlans()
  }, [])

  return (
    <div className="page-card">
      <div className="section-head"><h3>Production Plans</h3><TabSearch value={search} onChange={setSearch} placeholder="Filter production..." /></div>
      {error ? <div className="form-message error">{error}</div> : null}
      {loading ? <div className="form-message">Loading production plans...</div> : null}
      {!loading && plans.length === 0 ? <div className="form-message">No production plans found.</div> : null}
      {!loading && filteredPlans.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Season</th><th>Crop</th><th>Target HA</th><th>Actual HA</th><th>Achievement</th></tr></thead>
            <tbody>
              {filteredPlans.map((plan) => (
                <tr key={plan.id}>
                  <td>{plan.season}</td>
                  <td>{plan.crop}</td>
                  <td>{plan.target_hectares}</td>
                  <td>{plan.actual_hectares}</td>
                  <td>{Math.round(Number(plan.achievement || 0) * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

export default ProductionPage
