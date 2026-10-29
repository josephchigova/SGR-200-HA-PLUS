# HSE 412 QA Defense

Use the terminal-based test plan and live QA kit in [backend/qa/README.md](qa/README.md). The application no longer has a QA dashboard page or QA summary endpoint; test and scan evidence comes from runnable tools and generated artifacts.

From repository root, run:

```bash
bash backend/qa/run_checks.sh
```

The test plan, ISO/IEC 25010 mapping, test traceability, and defect log are in `backend/qa/`. ZAP and performance checks have separate commands and explicit scope/prerequisites. Do not claim certification or a performance SLA that has not been agreed and measured.
