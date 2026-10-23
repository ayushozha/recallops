# RecallOps

**Turn a real FDA recall notice into reviewed, enforced inventory holds, using Claude to read the notice and Snowflake to record the holds.**

Built during the Snowflake × Anthropic *Intelligence at Work* hackathon on October 23, 2026, under the Internal theme. Maya, a recall coordinator at a grocery chain, works through five steps:

1. **Notice:** pick one of about 2,000 **real openFDA food enforcement reports** stored in Snowflake, or paste a supplier amendment.
2. **Claude interprets it:** `AI_COMPLETE` with a Claude model and a JSON schema returns the UPCs and in-scope lot codes, quotes from the notice as evidence, and anything ambiguous. The output is saved to `RECALL_CASES`.
3. **Human review and matching in Snowflake:** Maya can edit the scope. SQL then matches it against lot-level inventory and shows affected units per location. Rows with no lot on record are flagged **Needs review**; they are never silently treated as safe.
4. **Governed write-back:** the `APPROVE_HOLDS` stored procedure places holds through a MERGE, so approving twice adds nothing. Every action is logged to `ACTIONS`.
5. **Enforcement:** `FULFILL_ORDER` checks for holds before fulfilling an order. Orders on held stock are **BLOCKED**, and orders on other lots go through.

## What is real and what is generated
- **Real:** the FDA recall notices (openFDA `food/enforcement`), firms, UPCs and lot codes, the Snowflake tables, procedures and writes, and the Claude calls made through Snowflake Cortex.
- **Generated:** the grocery chain's stock levels, its locations and its pending orders, because no public dataset has them. Each inventory product is a real recalled product with its real UPC and lot. Every product also gets non-recalled "control" lots and a few rows with no lot, so the matching is actually tested. A company would swap in its own inventory tables.

## Run
```bash
python3 -m venv .venv && .venv/bin/pip install snowflake-connector-python streamlit requests python-dotenv
cp .env.example .env   # account, user, programmatic access token, warehouse, Claude model
.venv/bin/python scripts/load_data.py      # creates RECALLOPS.APP objects and loads the data
.venv/bin/streamlit run app/streamlit_app.py
```

## Files
- `sql/01_setup.sql`: tables, `APPROVE_HOLDS` and `FULFILL_ORDER`
- `scripts/load_data.py`: openFDA → Snowflake, plus the inventory and orders built from recalled products
- `app/streamlit_app.py`: the workflow UI
- `RecallOps-Hackathon-Brief.md`: the planning brief
