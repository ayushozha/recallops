# RecallOps

RecallOps helps a grocery recall coordinator review an FDA notice, identify affected inventory, approve holds and test order enforcement. Claude interprets the notice through Snowflake Cortex `AI_COMPLETE`; SQL matches records and stored procedures save decisions.

## Current status

- The loader fetched 2,000 real openFDA notices. One lacked a recall identifier and was skipped. Verified live counts are **1,999 unique FDA reports, 6 locations, 49 inventory rows and 10 orders**.
- The live event Snowflake connection is verified with role `ATTENDEE_ROLE` and warehouse `DEFAULT_WH` in AWS US West (Oregon). Setup SQL successfully created the database, tables and procedures.
- **Latest model verified:** `scripts/verify.py --model claude-opus-5-5 --recall H-1339-2026` passed **15/15 live checks**, case `VERIFY-873E22`. Extraction took 12.1 seconds. Approval created 2 holds totaling 125 units; repeating approval added 0 holds. No missing-lot row or control lot was held. `O-101` was blocked and `O-110` fulfilled, with 3 case-linked action-history entries. The verifier removed its test holds and restored orders; its case and action history remain. Full output: `docs/verification-opus-5-5.txt`.
- Opus 5.5's native `response_format` call returned SQL `NULL`. The implemented fallback requests JSON text and validates required fields and types; that path passed the latest-model workflow. Do not claim native structured output worked.
- The local browser workflow passed as case `CASE-DC8432B8`: Opus 5.5 extraction in 13.2 seconds, 125 affected units at 2 stores, 121 outside scope, 2 approved holds and the expected blocked/fulfilled orders. Screenshots: `docs/assets/live-opus55-{notice,stock,orders}.png`. Codex then removed only that case's holds, restored `O-101` / `O-110` to `PENDING` and set the case to `PROPOSED`, retaining a `DEMO_RESET` audit entry. Other cases' holds remain preserved; do not clear them or assume all stock is unheld.
- The hosted Streamlit app `RECALLOPS.APP.RECALLOPS_APP` was successfully republished with explicit `RUNTIME_NAME = 'SYSTEM$WAREHOUSE_RUNTIME'`. The browser is loading; hosted GUI verification remains pending. See [Snowflake's documented runtime default change](https://docs.snowflake.com/en/release-notes/bcr-bundles/2026_06/bcr-2342).
- The missing-identifier loader issue is fixed and the live data counts are checked. A concurrent load initially duplicated fixtures; those duplicates have been removed. Do not run the loader again during the demo or while another agent is using these tables.
- The local `.env` selects the verified `claude-opus-5-5`, listed in [Snowflake's regional availability documentation](https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql-regional-availability) as a public preview model. Keep this latest requested model unless a specific failure requires a reported fallback.

## Run from the repository root

Credentials belong only in the ignored local `.env`. Use the verified event role `ATTENDEE_ROLE` and warehouse `DEFAULT_WH`. Never print, commit, copy into documentation or paste credentials into a browser recording. Keep the file private (`chmod 600 .env`).

**Current coordination:** Codex owns demo setup and hosted browser verification. The full Opus 5.5 workflow has passed. Other agents must not start loaders, reset data or run overlapping workflow checks. For the already-loaded account, skip the loader command below.

```bash
.venv/bin/python scripts/load_data.py
.venv/bin/python scripts/verify.py --model claude-opus-5-5 --recall H-1339-2026
.venv/bin/streamlit run app/streamlit_app.py --server.headless true --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

The loader creates `RECALLOPS.APP` and replaces demo table contents, including case history and holds by default. Do not rerun it after recording a case unless a reset is intended. `--dry-run` fetches and generates data without Snowflake writes. The verifier restores its tested orders and removes its own test holds.

## Demo and evidence

- Open `http://127.0.0.1:8501` and select recall `H-1339-2026` (Everything Sprouts).
- Generated fixture: 125 affected units at 2 stores; 121 units outside this notice's scope. The live Opus 5.5 check verified `O-101` blocked after approval and `O-110` fulfilled.
- FDA notices and recalled product identifiers are real. Stock quantities, locations, orders and control lot strings are generated. Outside-scope control strings are not proof that a real lot is safe.
- Preserve the coordinator's review before approval. Do not describe demo ordering as a production retailer integration or claim measured savings.
- Use `DEMO.md` for the one-minute recording and update `README.md` / `SUBMISSION.md` to match actual verification evidence.

## Main files

- `app/recall.py`: Claude call and extraction schema.
- `app/db.py`: local connection or hosted Snowflake session.
- `app/streamlit_app.py`: coordinator workflow.
- `sql/01_setup.sql`: tables and approval / order procedures.
- `scripts/bootstrap_demo.sql`: optional browser bootstrap with 12 selected FDA notices; do not report 2,000 loaded when using only this path.

Before pushing, review the diff, run `git diff --check`, and report live checks as passed, failed or not run. Preserve other agents' work.
