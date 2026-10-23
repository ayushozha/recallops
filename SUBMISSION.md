# Submission text (Cerebral Valley form)

**Team / project name:** RecallOps

**Team members:** Ayush Ojha; agod

**Public GitHub repository:** https://github.com/ayushozha/recallops

**1-minute demo video:** Pending

**Hosted app:** [Open in Snowflake](https://app.snowflake.com/streamlit/sfsehol/anthropic_snowflake_hackathon_tadcdr/#/apps/RECALLOPS.APP.RECALLOPS_APP) (sign-in required)

**Project description**

RecallOps helps a grocery chain's recall coordinator turn a food recall notice into reviewed inventory holds and blocked orders. Claude Opus 5.5 extracts product and lot codes with supporting quotes; a person reviews the scope; Snowflake matches stock and records approval and order decisions.

The problem is documented: in December 2025, FDA reported finding recalled infant formula on shelves at more than 175 locations across 36 states. [FDA findings](https://www.fda.gov/news-events/press-announcements/fda-takes-action-improve-recall-effectiveness-following-infant-botulism-outbreak-investigation).

**The Value Case**

The buyer would be a grocery chain's food-safety or operations team. We would measure notice-to-approved-hold time, affected units identified, unnecessary holds and location confirmations against the same coordinator's manual spreadsheet process. That baseline and financial value have not yet been measured.

Our live demo check passed 15/15 checks: 125 generated units were held, repeat approval added zero duplicate holds, control lots remained unheld, the affected order was blocked and the control order fulfilled. Another 121 generated units lie outside this notice's lot scope. These are workflow results on demo stock, not proven business savings or prevented harm.

**Architecture Summary**

Snowflake stores 1,999 unique real FDA reports, plus 49 generated inventory rows across 6 locations and 10 orders. One of 2,000 fetched FDA records lacked a recall number and was skipped.

The Streamlit workflow calls Claude Opus 5.5 through Cortex `AI_COMPLETE`. The app validates the resulting JSON, then the coordinator reviews product and lot codes before SQL matching. `APPROVE_HOLDS` saves approved holds; `FULFILL_ORDER` blocks held stock and records order decisions. Native Opus 5.5 `response_format` returned SQL `NULL` in our account, so the working path uses a JSON-only prompt with field/type validation.

The latest-model verifier passed 15/15 checks; extraction took 12.1 seconds. Local browser extraction took 13.2 seconds; the hosted workflow passed with an 11.5-second extraction and 2 holds totaling 125 units. Hosted order-button retries produced fresh blocked/fulfilled action entries; fresh transitions from pending orders were proved separately by the verifier. Eleven offline unit checks also passed. [Verifier output](docs/verification-opus-5-5.txt), [hosted SQL receipt](docs/hosted-verification.json).

**Snowflake account identifier**

`SFSEHOL-ANTHROPIC_SNOWFLAKE_HACKATHON_TADCDR`

**A Short Build Story**

We used Codex and Claude-assisted agents to challenge the problem, build the loader, SQL procedures and Streamlit workflow, and review the verifier. We replaced an initially weak cloud-credit idea with recall coordination. Live testing exposed a missing FDA identifier, duplicated fixtures from overlapping loaders and Opus 5.5's null structured response. We filtered the invalid record, restored unique fixtures, assigned one agent to live testing and added a validated JSON fallback before rerunning all 15 checks successfully.

**Viability**

A retailer's recall coordinator would own the workflow, with its IT team maintaining inventory and ordering connections. The next step is a pilot on approved historical notices and real inventory, compared with the retailer's manual process. Production work includes a separate approver role, verified person-level identity, store confirmations and actual ordering connections. In the hosted session, `CURRENT_USER()` returned `NULL`: action, time and outcome logging work, but attribution to the approving person is not yet proven. Current order enforcement is a demo procedure.

**Which partner tools did you use?**

Snowflake SQL, tables, stored procedures, Cortex `AI_COMPLETE`, Streamlit in Snowflake, and Claude Opus 5.5. Codex and Claude-assisted agents supported development and review; openFDA supplied public recall records.

**Feedback on Anthropic and Snowflake products**

Cortex let us invoke the latest Claude model from SQL using the event account's existing role; the complete workflow passed 15 live checks. The main issue was Opus 5.5 returning SQL `NULL` with `response_format` while a plain model call succeeded. A clear unsupported-format error, a model-by-format compatibility table and a validated JSON fallback example would have saved debugging time.

Initial trial/card verification blocked setup; the event-provided account unblocked it. Put that event-account path prominently in the starter guide. A starter that creates one table, runs one model call and publishes a Streamlit app with the correct role and warehouse would make the first successful run faster.

Hosted startup also stalled after the default selected container runtime. Snowflake's 2026_06 change makes that the default when runtime is omitted; explicitly choosing `SYSTEM$WAREHOUSE_RUNTIME` and pinning Streamlit 1.50 led to a working hosted app. Show the runtime and compute requirements before creation, and keep starter SQL explicit. [Documented runtime change](https://docs.snowflake.com/en/release-notes/bcr-bundles/2026_06/bcr-2342).

**Data disclosure:** FDA notices and selected recalled product identifiers are real. Stock quantities, locations, orders and control lot strings are generated. An outside-scope control string is not independent proof that a real lot is safe. No financial savings or customer adoption are claimed.
