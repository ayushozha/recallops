# RecallOps

RecallOps helps a grocery recall coordinator review an FDA notice, identify affected inventory, approve holds and test order enforcement. Claude interprets the notice through Snowflake Cortex `AI_COMPLETE`; SQL matches records and stored procedures save decisions.

## Current status

- The loader fetched 2,000 real openFDA notices. One lacked a recall identifier and was skipped. Verified live counts are **1,999 unique FDA reports, 6 locations, 49 inventory rows and 10 orders**.
- The live event Snowflake connection is verified with role `ATTENDEE_ROLE` and warehouse `DEFAULT_WH` in AWS US West (Oregon). Setup SQL successfully created the database, tables and procedures.
- A live probe, `SELECT AI_COMPLETE('claude-opus-5-5', 'Reply with OK')`, returned `OK` in 2.4 seconds. Opus 5.5's native schema call returned SQL `NULL`; a validated JSON text-output fallback is being implemented. The full Opus 5.5 workflow remains pending.
- **Verified baseline:** `scripts/verify.py --model claude-opus-5 --recall H-1339-2026` passed **15/15 live checks**, case `VERIFY-E09BE1`. Recall extraction took 9.0 seconds. Approval created 2 holds totaling 125 units; repeating approval added 0 holds. No missing-lot row or control lot was held. `O-101` was blocked and `O-110` fulfilled, with 3 case-linked action-history entries. The verifier removed its test holds and restored order states; its case and action history remain.
- The missing-identifier loader issue is fixed and the live data counts are checked. A concurrent load initially duplicated fixtures; those duplicates have been removed. Do not run the loader again during the demo or while another agent is using these tables.
- The local `.env` selects the verified `claude-opus-5-5`, listed in [Snowflake's regional availability documentation](https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql-regional-availability) as a public preview model. Keep this latest requested model unless a specific failure requires a reported fallback.

## Run from the repository root

Credentials belong only in the ignored local `.env`. Use the verified event role `ATTENDEE_ROLE` and warehouse `DEFAULT_WH`. Never print, commit, copy into documentation or paste credentials into a browser recording. Keep the file private (`chmod 600 .env`).

**Current coordination:** Codex owns live verification and demo setup. Opus 5 passed the baseline; the full Opus 5.5 verification for `H-1339-2026` will run after its JSON fallback is ready. Other agents must not start loaders, reset data or run overlapping workflow checks. For the already-loaded account, skip the loader command below.

```bash
.venv/bin/python scripts/load_data.py
.venv/bin/python scripts/verify.py --recall H-1339-2026
.venv/bin/streamlit run app/streamlit_app.py --server.headless true --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

The loader creates `RECALLOPS.APP` and replaces demo table contents, including case history and holds by default. Do not rerun it after recording a case unless a reset is intended. `--dry-run` fetches and generates data without Snowflake writes. The verifier restores its tested orders and removes its own test holds.

## Demo and evidence

- Open `http://127.0.0.1:8501` and select recall `H-1339-2026` (Everything Sprouts).
- Generated fixture: 125 affected units at 2 stores; 121 units outside this notice's scope. The live Opus 5 baseline verified `O-101` blocked after approval and `O-110` fulfilled. Opus 5.5 must pass the same check before claiming that model completed the workflow.
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
