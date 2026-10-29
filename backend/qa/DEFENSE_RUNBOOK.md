# HSE 412 Live Defense Runbook

Use this as a spoken-and-terminal sequence. Target duration: 12-15 minutes. The goal is to demonstrate the process and explain evidence, not just show the application.

## Before the defense

1. Confirm the code is the version you intend to present and run all checks:

   ```bash
   cd "/home/joseph/Desktop/SGR 200HA+ FARMER & INPUT MANAGEMENT SYSTEM"
   bash backend/qa/run_checks.sh
   ```

2. Confirm the demo data and operator account exist. Run from `backend/`:

   ```bash
   .venv/bin/python manage.py seed_golden_path
   .venv/bin/python manage.py load_zimbabwe_geography
   .venv/bin/python manage.py load_cluster_catalogue
   .venv/bin/python manage.py createsuperuser
   ```

   Only create the superuser once. `createsuperuser` prompts securely. Do not write its password into the project or command history.

3. Start the backend and frontend in separate terminals. Confirm login and verify the operator has a role appropriate for the actions to be shown.
4. Confirm the ZAP runner path:

   ```bash
   find "$HOME/Downloads" -maxdepth 5 -type f \( -name zap-baseline.py -o -name zap-baseline.sh \) -print
   ```

   If found, set `ZAP_HOME` or `ZAP_BASELINE` for the ZAP command. The current environment did not expose ZAP on `PATH`; if still unavailable, disclose that and show the prepared command, but do not claim a scan was run.
5. Prepare synthetic farmer data only. Ensure the operator can create a farmer, verify, make subscription payments, work the ARDA and allocation flow, record production/delivery, and view the dashboard.
6. Keep terminal font readable and place these windows in reach: browser, regression terminal, ZAP terminal, performance terminal, coverage/defect documents.

## Live sequence

### 00:00-00:45 | Problem and test objectives

Say: “This system tracks farmer eligibility and agricultural support from registration through input allocation, production, grain delivery and recovery. I will demonstrate its main use case and show how I test both expected and invalid behavior.”

Identify the system boundary: React UI, Django REST API, domain/service rules, and SQLite local test/demo database. Clarify that demo data is synthetic.

### 00:45-01:20 | Test plan and standard

Open `backend/qa/TEST_PLAN.md` and `backend/qa/ISO_25010.md` briefly. Explain that test cases are traceable to requirements in `TRACEABILITY.csv` and that ISO/IEC 25010 is used as a product-quality evaluation framework, not a certification claim.

### 01:20-06:20 | Acceptance/system demonstration

In the browser:

1. Log in.
2. Search a farmer and open their details; point out identity, location, cluster, verification status and farm hectares.
3. Open farmer registration. Attempt a duplicate National ID and show the API-backed error; register a valid synthetic farmer.
4. Verify the submitted farmer and point out verifier/date audit fields.
5. Create/show a subscription unpaid, then update it partial and paid. Explain expected, paid, outstanding and status.
6. Show the 2026/27 season and `SGR 200HA+ 2026/27`, ARDA, 20,000 ha capacity.
7. Create an ARDA batch, try an ineligible farmer and show rejection, then add/approve an eligible farmer.
8. Allocate inputs within approved hectares. Explain that over-allocation is rejected server-side.
9. Record production with planted area no greater than approved/farm hectares.
10. Create recovery debt, record GMB delivery and recovery tonnes, then show debt recalculation.
11. Open the management dashboard and identify values as aggregates from API/database records.

The linked API system scenario can be rerun separately in the terminal and has assertions for each of these results.

### 06:20-08:30 | Test design and automation

Run the whole repeatable suite:

```bash
bash backend/qa/run_checks.sh
```

For a faster targeted demonstration, from `backend/` run:

```bash
.venv/bin/pytest apps/farmers/tests.py::FarmerVerificationActionTests::test_farmer_registration_hectare_equivalence_partitions -v
.venv/bin/pytest apps/programmes/tests.py::ProgrammeAllocationTests::test_programme_capacity_boundary_values -v
.venv/bin/pytest apps/farmers/tests.py::FarmerDomainServiceTests::test_farmer_eligibility_decision_table -v
.venv/bin/pytest apps/farmers/test_golden_path.py -v
```

Explain:

- Equivalence partitioning: valid positive hectares vs zero, negative and nonnumeric input.
- Boundary value analysis: 19,999 and 20,000 accepted; 20,001 rejected for a 20,000 ha capacity.
- Decision table: only verified + paid subscription + verified farm is eligible in the four demonstrated combinations.
- Automation: pytest runs the API/service tests repeatedly and JUnit records test outcomes.

### 08:30-09:30 | White-box evidence

Point to the coverage table produced by `run_checks.sh` and `backend/qa-coverage.json`. Explain statement and branch coverage, then state the actual measured values from this run. Mention the denominator/scope: coverage is measured for `apps`, and excluded/unexercised legacy paths reduce the aggregate. Do not present coverage as proof of correctness.

### 09:30-11:00 | Security and ZAP

Run the role/authentication tests:

```bash
cd backend
.venv/bin/pytest apps/accounts/tests.py apps/farmers/tests.py apps/programmes/tests.py apps/subscriptions/tests.py apps/production/tests.py -k 'auth or unauthorized or viewer or district or expired' -v
```

Explain the expected 401 for unauthenticated/expired access, 403 for forbidden roles, and scoped denial for another district. Then run the local passive ZAP baseline if its downloaded runner is located:

```bash
cd ..
ZAP_HOME="/absolute/path/to/ZAP" bash backend/qa/run_zap_baseline.sh
```

Show the generated HTML/JSON report. Explain that baseline checks are passive security signals and that the pytest authorization tests cover application roles; neither alone is a full penetration test. Only scan the local demo target.

### 11:00-12:00 | Performance

Run a low-load, read-only API test:

```bash
backend/.venv/bin/python backend/qa/performance_smoke.py --requests 30 --workers 5
```

Enter an operator account when prompted. State the request count, concurrency, endpoint, observed p95 and throughput. Do not call it a load/stress test or claim an SLA. If comparing a p95 limit, agree that limit first and pass it explicitly with `--max-p95-ms`.

### 12:00-13:00 | Defect management and ISO quality

Open `backend/qa/DEFECT_LOG.md`. Show a closed geography defect with reproducer/fix/retest and open items for the missing authoritative Manicaland cluster mapping and weak local JWT secret. Explain the retest method and do not hide unresolved items.

Close with `backend/qa/ISO_25010.md`: map functional suitability, performance, compatibility, usability, reliability, security, maintainability and portability to the test evidence. Say explicitly that this is an ISO-based quality assessment, not a certificate or compliance audit.

## Questions to be ready for

- Why does Manicaland show no cluster choices? The provided workbook row does not identify a district for its Manicaland cluster; the importer skips unresolved assignments rather than guessing. An authoritative mapping is an open data defect.
- What does ZAP prove? It reports passive web security observations on the scoped local target. It does not replace authenticated role testing or a full security assessment.
- Why is coverage below 100%? Coverage includes legacy app paths outside the Golden Path; statement/branch coverage is a measurement, not a target claimed as achieved.
- Is this ISO certified? No. ISO/IEC 25010 characteristics organize product-quality evaluation; no certification is claimed.
- What is the next quality action? Replace the weak local JWT key, resolve the authoritative cluster mapping, run ZAP and performance checks, then attach their actual reports to the evidence set.

## Evidence checklist

- [ ] `qa-junit.xml` generated from the current run
- [ ] `qa-coverage.json` generated from the current run
- [ ] `frontend/qa-lint.json` generated from the current run
- [ ] ZAP HTML/JSON generated, or its absence explicitly disclosed
- [ ] Performance output recorded, or not-run status disclosed
- [ ] Defect log updated with actual retest results
- [ ] Browser demo uses synthetic records and an authorized operator
