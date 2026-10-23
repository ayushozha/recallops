# Submission text (Cerebral Valley form)

**Project name:** RecallOps

**Tagline:** Turn a real FDA recall notice into reviewed, enforced inventory holds, using Claude to read the notice and Snowflake to act on it.

**Repository:** https://github.com/ayushozha/recallops

**Current verification status:** code and the offline FDA-data test are complete. Snowflake loading, a Claude response, approved holds and blocked/fulfilled orders remain pending live verification. No measured operational savings are claimed.

**Description:**
When a supplier or the FDA recalls a product, a grocery chain has to find every affected lot across its warehouse and stores, stop that stock from moving, and keep a record of what it did. In December 2025 the FDA reported finding recalled infant formula on shelves at more than 175 locations across 36 states. Its findings included confusion about affected product codes and incomplete removal. [FDA recall-effectiveness findings, December 15, 2025](https://www.fda.gov/news-events/press-announcements/fda-takes-action-improve-recall-effectiveness-following-infant-botulism-outbreak-investigation).

RecallOps is built for the chain's recall coordinator:

1. The loader fetched 2,000 real openFDA food enforcement reports in an offline test. It can load those reports into Snowflake; an optional browser bootstrap contains 12 selected notices. The app reports the actual loaded count.
2. The implemented Cortex `AI_COMPLETE` call asks Claude for structured UPCs, lot codes, evidence quotes and ambiguities. A successful live response is still pending.
3. The coordinator can review and edit that scope before SQL matches it against lot-level inventory. The app distinguishes affected stock, lot strings outside scope and rows with no lot code that need review.
4. Approval calls the `APPROVE_HOLDS` stored procedure to save holds and an audit entry. Its MERGE is intended to avoid duplicate holds on a repeated approval of the same case; this still needs live verification.
5. The demo `FULFILL_ORDER` procedure checks for holds before deciding whether to block or fulfill an order. This is demo enforcement, not a connection to a retailer's production ordering system.

**Built during the hackathon (all of it):** the Snowflake schema and stored procedures, the openFDA loader, the Claude prompt and schema for extracting recall scope, the Streamlit workflow app, and the end-to-end check script.

**Snowflake + Claude:** the architecture uses Snowflake for notices, lot-level inventory, cases, holds and action history. Claude is called through Cortex `AI_COMPLETE` with structured outputs to interpret the unstructured notice. SQL performs matching; stored procedures perform approval and order checks. The Streamlit interface supports a hosted Snowflake session or a local connection. These integrations remain pending live verification.

**What's real and what's generated:** the notices and the selected recalled product identifiers come from real FDA records. Stock quantities, locations, orders and control lot strings are generated. Control strings are outside the selected notice's extracted scope, not independently established as safe. Snowflake writes and Claude calls have not yet been verified live.
