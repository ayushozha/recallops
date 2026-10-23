# One-minute demo script

**Verified:** the full Claude Opus 5.5 / Snowflake check passed **15/15**, case `VERIFY-873E22`; recall extraction took **12.1 seconds**. [Actual output](docs/verification-opus-5-5.txt). The local browser workflow also passed, case `CASE-DC8432B8`, with a **13.2-second** extraction and the expected holds and order decisions. The hosted app still needs its browser check. **Video URL: pending.**

Do not reload the already-prepared account. Open the app and select **H-1339-2026 · Everything Sprouts, LLC**. Its generated fixture contains **125 affected units at 2 stores**, plus **121 units outside this notice's lot scope**. The notice lists lots `222`, `223`, `226`, `230`; the generated control lot is `229`. Approval and both order outcomes passed the live check. The stock figures are demo inputs, not measured business results. This product has no missing-lot row.

Codex reset only local case `CASE-DC8432B8` to `PROPOSED`, removed that case's holds and restored `O-101` / `O-110` to `PENDING`, retaining a `DEMO_RESET` audit entry. Other cases' holds are preserved. A new interpretation can begin the recording; coordinate further state changes with Codex and do not reload shared tables. If a Claude call takes longer than the recording window, use a clearly disclosed cut over the wait.

The verified Claude response flagged the notice's UPC check digit and asked about distribution. Keep those warnings visible: this demo matches the identifier printed in the FDA record against generated stock. A retailer must resolve them against its product and supplier records before approving real holds.

Follow tabs **1 The notice → 3 What we found → 4 Lock it down → 5 Audit trail**. Skip **2 Where it went** and the optional graph during the one-minute recording. Their rendering is not covered by the earlier core workflow evidence.

| Time | Show | Say |
|---|---|---|
| 0–8s | **1 The notice**, recall H-1339-2026 | "A recall coordinator must find affected stock and stop it moving. This sprouts notice is real FDA data, stored in Snowflake." |
| 8–22s | **Interpret with Claude**, then highlighted evidence and proposed lots | "Claude reads the notice through Snowflake Cortex and proposes product and lot codes with evidence. The coordinator reviews the scope." |
| 22–34s | **3 What we found**: 125 affected units, 2 locations, 121 outside scope | "SQL finds 125 affected units in two stores. Another 121 units have a different lot code and stay outside this notice's scope." |
| 34–51s | **4 Lock it down**: **Approve holds**, then **Try order** on O-101 and O-110 | "Approval saves the holds in Snowflake. The affected seven-unit order is blocked; the 44-unit control order is fulfilled." |
| 51–60s | **5 Audit trail**, showing interpretation, approval and both order decisions | "Snowflake records the model call, approval and order decisions. The FDA notice is real; inventory and orders are generated demo data." |

Repeat approval added zero new holds in the live check. Show it in a longer demo if time allows; concurrent approvals and a production retailer integration have not been tested.
