# Defect Log

This is a small project defect register for the practical defense. Statuses below reflect verified repository/local-demo findings; do not add a defect as resolved until its retest is run.

| ID | Summary | Severity | Status | Evidence / reproduction | Correction / retest |
|---|---|---|---|---|---|
| GEO-001 | Manicaland was stored with uppercase name and only an `Unknown` district, so selecting the province did not yield usable districts. | Major | Closed | Before seed: `GET /api/districts/?province=6` returned only `Unknown`. | Case-insensitive idempotent seed; seven Manicaland districts now returned. Covered by `GeographyDropdownTests.test_geography_seed_command_provides_all_manicaland_districts_once`. |
| GEO-002 | Workbook has no district assignments for its Manicaland cluster row, so no Manicaland cluster options can be derived from this source. | Medium | Open: source-data action | `load_cluster_catalogue` skipped unresolved location rows; API returns zero Manicaland clusters. | Request authoritative Manicaland cluster-to-district mapping from the data owner, then rerun importer and selector test. Do not guess assignments. |
| SEC-001 | Local JWT signing key emits a short-HMAC-key warning during auth tests. | Medium | Open: environment action | PyJWT test output warns configured key is 26 bytes, below 32 bytes recommended for SHA-256. Do not display the key value. | Set a strong, randomly generated `SECRET_KEY` in local `backend/.env`, restart Django, rerun auth tests. Never commit the secret. |
| QA-001 | ZAP baseline was not found on the active shell PATH or in searched common install directories at setup time. | Low | Open: operator setup | `command -v zap.sh zap-baseline.py` found no executable; Docker daemon was unavailable. | Locate the downloaded ZAP distribution and set `ZAP_HOME`/`ZAP_BASELINE`; run the baseline script and attach its generated report. |

## Retest record

Add a dated note below when an open entry is resolved:

- Date / tester:
- Defect ID:
- Build or commit identifier:
- Retest command and result:
- Regression command and result:
- Evidence path:
