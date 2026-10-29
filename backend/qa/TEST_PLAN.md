# HSE 412 Test Plan and Live Defense Script

## Scope

System under test: SGR 200HA+ local demonstration deployment (`http://127.0.0.1:5173` frontend, `http://127.0.0.1:8000` API). Use synthetic test data and the local SQLite database. No scan or load test is authorized against production or real farmer data.

## Objectives

- Demonstrate the Golden Path business workflow and its validation rules.
- Show that automated tests fail for invalid/boundary/security cases and pass for valid cases.
- Produce repeatable test, coverage, lint, ZAP, and performance evidence from the terminal.
- Record defects, severity, owner, fix, and retest result.
- Evaluate quality against selected ISO/IEC 25010 characteristics without claiming certification.

## Test levels and current evidence

| Level / type | Live evidence | Scope and limit |
|---|---|---|
| Component/service | `pytest` farmer eligibility, subscription, capacity, and recovery service tests | Django ORM/service tests; not all are isolated pure unit tests. |
| Integration | Django REST API tests in `backend/apps/**/tests.py` | Serializers, permissions, views, and database are exercised together. |
| System | `pytest apps/farmers/test_golden_path.py -q` | One end-to-end API journey crosses the Golden Path. |
| Acceptance | Complete the UI defense flow in order and compare each result to expected outcomes below. | Human-observed acceptance; lecturer signs off verbally or in their rubric. |
| Regression | `bash backend/qa/run_checks.sh` | Backend tests, schema checks, frontend lint and production build. |
| UI | Use browser to register, search, inspect details, change verification, and demonstrate error messages/dropdowns. | Manual UI evidence; no browser automation framework is currently configured. |
| Security | Auth/RBAC tests plus ZAP passive baseline | ZAP is not a replacement for role-specific authorization tests or an authenticated penetration test. |
| Performance | `backend/qa/performance_smoke.py` | Small read-only local API smoke workload; not a formal capacity/load/stress test. |

## Black-box test design evidence

| Technique | Input partition / boundary | Expected result | Automated reference |
|---|---|---|---|
| Equivalence partitioning | Farmer hectares: positive decimal | Accept registration and create farm. | `FarmerVerificationActionTests.test_farmer_registration_creates_submitted_farmer_and_farm` |
| Equivalence partitioning | Farmer hectares: zero, negative, nonnumeric | Reject with validation error. | `test_farmer_registration_hectare_equivalence_partitions` |
| Equivalence partitioning | National ID: new vs duplicate | New ID accepted; duplicate rejected on field. | `test_farmer_registration_rejects_duplicate_national_id` |
| Boundary value analysis | Programme capacity 20,000 ha: 19,999 / 20,000 / 20,001 | First two valid; last invalid. | `ProgrammeAllocationTests.test_programme_capacity_boundary_values` |
| Boundary value analysis | Recovery: zero, full, negative, greater than required | Correct zero/full summary; negative and over-recovery rejected. | `RecoveryRecordTests.test_recovery_calculation_boundaries` |
| Decision table | Farmer verified × subscription paid × farm verified | Eligible only when all three are true. | `FarmerDomainServiceTests.test_farmer_eligibility_decision_table` |
| Use-case based | Registration through dashboard after delivery/recovery | Persisted records and derived aggregate values agree. | `GoldenPathSystemTest.test_golden_path_from_farmer_registration_to_dashboard_recovery` |

## White-box evidence

Run `bash backend/qa/run_checks.sh`; the pytest-cov command enables `--cov-branch`. Explain both numbers:

- Statement coverage: executed source statements / measured statements.
- Branch coverage: executed control-flow branches / measured branches.

Coverage is scoped to `apps`. It is not proof that every requirement or browser interaction passed. Present exact values from `backend/qa-coverage.json`, do not round differently from the artifact without saying so.

## Decision table

| Farmer verified | Subscription paid | Farm verified | Eligible |
|---|---|---|---|
| Yes | Yes | Yes | Yes |
| Yes | No | Yes | No |
| No | Yes | Yes | No |
| Yes | Yes | No | No |

The automated test exercises these four rows. Farmer account active status and presence of a farm are additional eligibility rules and should be mentioned if asked.

## Security test cases

| ID | Action | Expected |
|---|---|---|
| SEC-01 | Request protected API without token | 401 Unauthorized |
| SEC-02 | Login with valid credentials | Access and refresh JWT returned |
| SEC-03 | Login with invalid password | 401; no tokens returned |
| SEC-04 | Use expired JWT | 401 Unauthorized |
| SEC-05 | Viewer attempts restricted programme/subscription/production write | 403 Forbidden |
| SEC-06 | District coordinator requests another district farmer | 404 due to scoped queryset |
| SEC-07 | District coordinator creates farmer outside assigned district | 400 validation denial |
| SEC-08 | ZAP baseline against local app | Review passive alerts in generated HTML/JSON; classify and retest each relevant alert. |

Automated evidence: `apps/accounts/tests.py`, `apps/farmers/tests.py`, `apps/programmes/tests.py`, `apps/subscriptions/tests.py`, and `apps/production/tests.py`. ZAP scan is a separate manual command because ZAP is not currently present on PATH.

## UI acceptance script

1. Sign in with a locally provisioned operator account.
2. Search an existing farmer; open the farmer detail record and show province, district, cluster, verification and hectares.
3. Attempt a duplicate National ID; show the field validation error. Register a synthetic farmer with valid positive hectares and a province/district pair.
4. Verify the submitted farmer; show status, verifier and timestamp. Show the farm verification state.
5. Create subscription as unpaid, update it to partial, then fully paid; show expected, paid, outstanding, and status.
6. Select the 2026/27 season and create/select `SGR 200HA+ 2026/27`, ARDA, 20,000 ha.
7. Create an ARDA batch. Add an eligible farmer. Attempt an unverified/unpaid farmer and show rejection. Approve hectares within capacity; try the 20,001 boundary in automated test output.
8. Allocate input within the approved hectares; demonstrate over-allocation rejection using the test output.
9. Record production within approved hectares; show the invalid-hectare test result.
10. Record a GMB delivery with positive tonnes, depot, date, and ticket. Use recovery tonnes against an existing debt.
11. Show debt before/after delivery: required 5.00, recovered 2.50, outstanding 2.50, recovery 50% (using the system test data).
12. Show the live database-backed dashboard.
13. In terminal, run the test suite, inspect JUnit and coverage, run lint/build, and run ZAP/performance commands if their prerequisites are ready.

## Defect lifecycle

For every observed issue: assign an ID, capture environment and exact reproduction steps, expected/actual result, severity and priority, link the test/requirement, fix, rerun the reproducer, and rerun regression. Current entries are in `DEFECT_LOG.md`.
