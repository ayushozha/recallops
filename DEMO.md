# One-minute demo script

**Verified:** Opus 5.5 passed **15/15** live verifier checks (12.1-second extraction), the local browser workflow (13.2 seconds) and the hosted browser workflow (11.5 seconds, case `CASE-C2E4E470`). Eleven offline unit checks passed. [Verifier output](docs/verification-opus-5-5.txt), [hosted receipt](docs/hosted-verification.json). **Video URL: pending.**

Record from the [hosted app](https://app.snowflake.com/streamlit/sfsehol/anthropic_snowflake_hackathon_tadcdr/#/apps/RECALLOPS.APP.RECALLOPS_APP) after Snowflake sign-in.

Do not reload the already-prepared account. Open the app and select **H-1339-2026 · Everything Sprouts, LLC**. Its generated fixture contains **125 affected units at 2 stores**, plus **121 units outside this notice's lot scope**. The notice lists lots `222`, `223`, `226`, `230`; the generated control lot is `229`. Approval and both order outcomes passed the live check. The stock figures are demo inputs, not measured business results. This product has no missing-lot row.

**Recording reset confirmed:** H-1339-2026 has **0 holds**, all its cases are `PROPOSED`, and `O-101` / `O-110` are `PENDING`. Cases, audit history and `DEMO_RESET` entries remain; other recalls were untouched. Start a new interpretation and **do not rerun the loader**. The earlier hosted check retried existing order states; the independent verifier proved pending-to-blocked/fulfilled transitions. Disclose any cut over a model wait.

The verified Claude response flagged the notice's UPC check digit and asked about distribution. Keep those warnings visible: this demo matches the identifier printed in the FDA record against generated stock. A retailer must resolve them against its product and supplier records before approving real holds.

Follow tabs **1 The notice → 3 What we found → 4 Lock it down → 5 Audit trail**. Skip the optional map and graph during the one-minute recording. The graph rendered in the hosted app; the map still awaits visual inspection.

| Time | Show | Say |
|---|---|---|
| 0–8s | **1 The notice**, recall H-1339-2026 | "A recall coordinator must find affected stock and stop it moving. This sprouts notice is real FDA data, stored in Snowflake." |
| 8–22s | **Interpret with Claude**, then highlighted evidence and proposed lots | "Claude reads the notice through Snowflake Cortex and proposes product and lot codes with evidence. The coordinator reviews the scope." |
| 22–34s | **3 What we found**: 125 affected units, 2 locations, 121 outside scope | "SQL finds 125 affected units in two stores. Another 121 units have a different lot code and stay outside this notice's scope." |
| 34–51s | **4 Lock it down**: **Approve holds**, then **Try order** on O-101 and O-110 | "Approval saves the holds in Snowflake. The affected seven-unit order is blocked; the 44-unit control order is fulfilled." |
| 51–60s | **5 Audit trail**, showing interpretation, approval and both order decisions | "Snowflake records the model call, approval and order decisions. The FDA notice is real; inventory and orders are generated demo data." |

Repeat approval added zero new holds in the live check. Show it in a longer demo if time allows; concurrent approvals and a production retailer integration have not been tested.
