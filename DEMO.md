# One-minute demo script

**Current status:** this is a recording plan; the live integration has not yet been verified. Do not describe the expected outcomes below as observed until the Snowflake test passes.

Before recording, load the data and run `scripts/verify.py --recall H-1339-2026`; all checks must pass. Then open the app and select **H-1339-2026 · Everything Sprouts, LLC**. The generated fixture is expected to contain **125 affected units at 2 stores**, plus **121 units outside this notice's lot scope**. Its affected lots are `222`, `223`, `226`, `230`; its generated control lot is `229`. The stock figures are demo inputs, not measured business results. This particular product has no missing-lot row; demonstrate that state on another product only if time allows.

Start with a clean demo case. The verifier restores the tested orders and removes its own test holds. If a Claude call takes longer than the recording window, use a clearly disclosed cut over the wait; do not replace it with an invented response.

| Time | Show | Say |
|---|---|---|
| 0–8s | **1 Notice**, recall H-1339-2026 | "A recall coordinator must find affected stock and stop it moving. This sprouts notice is real FDA data, stored in Snowflake." |
| 8–22s | **Interpret with Claude**, then highlighted evidence and proposed lots | "Claude reads the notice through Snowflake Cortex and proposes product and lot codes with evidence. The coordinator reviews the scope." |
| 22–34s | **2 Review stock**: 125 affected units, 2 locations, 121 outside scope | "SQL finds 125 affected units in two stores. Another 121 units have a different lot code and stay outside this notice's scope." |
| 34–51s | **3 Approve holds**, then **Try order** on O-101 and O-110 | "Approval saves the holds in Snowflake. The affected seven-unit order is blocked; the 44-unit control order is fulfilled." |
| 51–60s | **4 Audit trail**, showing interpretation, approval and both order decisions | "Snowflake records the model call, approval and order decisions. The FDA notice is real; inventory and orders are generated demo data." |

If showing repeat approval, do it during verification or a longer live demo: approving the same case again should add zero new holds. Do not imply that this proves concurrent approvals or a production retailer integration.
