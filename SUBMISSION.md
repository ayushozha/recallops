# Submission text (Cerebral Valley form)

**Project name:** RecallOps

**Tagline:** Turn a real FDA recall notice into reviewed, enforced inventory holds, using Claude to read the notice and Snowflake to act on it.

**Repository:** https://github.com/ayushozha/recallops

**Description:**
When a supplier or the FDA recalls a product, a grocery chain has to find every affected lot across its warehouse and stores, stop that stock from moving, and keep a record of what it did. In December 2025 the FDA reported that recalled infant formula was still on sale at more than 175 retail locations in 36 states. Among the reasons it found were confusion over which product codes were affected and incomplete removal.

RecallOps is built for the chain's recall coordinator:
1. About 2,000 real openFDA food enforcement reports are loaded into Snowflake.
2. Claude, called inside Snowflake through `AI_COMPLETE` with a JSON schema, pulls out the in-scope UPCs and lot codes, quotes the notice as evidence, and flags anything ambiguous.
3. The coordinator reviews and edits that scope. Snowflake SQL then matches it against lot-level inventory. Other lots of the same product stay sellable, and rows with no lot on record are flagged for review instead of being treated as safe.
4. Approving calls a stored procedure, `APPROVE_HOLDS`, which writes the holds. Approving twice adds nothing, and every action is written to an audit table.
5. `FULFILL_ORDER` checks for holds before fulfilling an order, so orders on held stock are blocked.

**Built during the hackathon (all of it):** the Snowflake schema and stored procedures, the openFDA loader, the Claude prompt and schema for extracting recall scope, the Streamlit workflow app, and the end-to-end check script.

**Snowflake + Claude:** Snowflake holds the recall notices, the inventory, the case history and the holds. Claude runs inside Cortex through `AI_COMPLETE` with structured outputs. The writes go through stored procedures, the app is a Streamlit workflow, and every action is logged in Snowflake.

**What's real and what's generated:** the recall notices, firms, UPCs and lot codes are real FDA data. The Snowflake writes and Claude calls are live. The chain's stock levels, locations and orders are generated, because no public dataset has them. Their product identities come from real recalls.
