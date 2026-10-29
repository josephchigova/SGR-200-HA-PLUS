# HSE 412 Live QA Defense Kit

This folder contains command-line test runners and evidence planning for the HSE 412 practical. The app's QA screen has been removed from the demo navigation; demonstrate checks from the terminal and show the generated reports directly.

## 1. Start the system

Terminal A, from `backend/`:

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Terminal B, from `frontend/`:

```bash
npm run dev -- --host 127.0.0.1
```

The app's current local environment accepts both `localhost:5173` and `127.0.0.1:5173` origins.

## 2. Prepare an operator and demo catalogue

From `backend/`:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_golden_path
.venv/bin/python manage.py load_zimbabwe_geography
.venv/bin/python manage.py load_cluster_catalogue
.venv/bin/python manage.py createsuperuser
```

`createsuperuser` prompts for the password; do not put it in shell history or project files. `load_cluster_catalogue` reads only cluster name, province, and district columns from `SGR SOURCE DATABASE.xlsx`. It skips unresolved assignments. It will not manufacture Manicaland clusters when that source has no Manicaland district values.

## 3. Run automated checks

From repository root:

```bash
bash backend/qa/run_checks.sh
```

It runs Django checks, migration drift detection, pytest with statement and branch coverage, emits JUnit/coverage reports, runs frontend ESLint JSON evidence, and creates the frontend production build.

Focused Golden Path run:

```bash
cd backend
.venv/bin/pytest apps/farmers/test_golden_path.py -q
```

## 4. Run a read-only performance smoke test

From repository root, after the API is running:

```bash
backend/.venv/bin/python backend/qa/performance_smoke.py --requests 30 --workers 5
```

The script asks for an operator email/password with the password hidden, obtains a JWT, then issues GET requests only. It reports observed latency/throughput; it does not claim an SLA. To evaluate against a threshold agreed with the lecturer:

```bash
backend/.venv/bin/python backend/qa/performance_smoke.py --requests 30 --workers 5 --max-p95-ms 1000
```

The threshold is a demonstration argument, not an ISO requirement. Explain the chosen workload and threshold before interpreting the result.

## 5. Run OWASP ZAP baseline

Start the local backend, then from repository root:

```bash
ZAP_HOME="/absolute/path/to/ZAP" bash backend/qa/run_zap_baseline.sh
```

Or set `ZAP_BASELINE` to the packaged `zap-baseline.py` path. The script is intentionally restricted to localhost by default and runs a passive baseline spider/scan. Reports go to `backend/qa/artifacts/`.

A baseline scan is a useful security smoke test, not proof of authorization or penetration-test coverage. ZAP does not log in as each RBAC role here. Demonstrate the automated role, district-scope, invalid-login, unauthenticated, and expired-token tests as separate evidence. Do not run an active scan against production or real farmer data. If the lecturer requires active scanning, use only the local demo database, confirm a backup, and explicitly authorize that scope.

The ZAP runner was not discoverable on the current shell PATH at setup. Before the defense, confirm the downloaded distribution contains `zap-baseline.py`, or set `ZAP_BASELINE` to its full path.

## Evidence files

- `backend/qa-junit.xml`: actual pytest case totals and pass/failure details.
- `backend/qa-coverage.json`: statement and branch coverage.
- `frontend/qa-lint.json`: ESLint result.
- `backend/qa/artifacts/zap-baseline.html` and `zap-baseline.json`: ZAP output when run.
- `backend/qa/TEST_PLAN.md`: live checklist and testing-technique mapping.
- `backend/qa/ISO_25010.md`: quality-characteristic assessment and limits.
- `backend/qa/DEFECT_LOG.md`: resolved and open issues with retest status.

See `backend/QA_DEFENSE.md` for the compact rubric-to-evidence summary.
