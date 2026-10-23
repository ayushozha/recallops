# One-minute demo script

Do this before recording: run `scripts/load_data.py`, then `scripts/verify.py` (all checks must pass), then start the app.

| Time | Show | Say |
|---|---|---|
| 0–10s | Step 1, a recall marked "we stock this firm" | "When the FDA posts a recall, a grocery chain has to find the stock, stop it moving, and prove it did. This is a real FDA enforcement report, stored in Snowflake." |
| 10–25s | Click **Interpret with Claude** | "Claude runs inside Snowflake through AI_COMPLETE. It pulls out the UPCs and lot codes, quotes the notice as evidence, and lists anything ambiguous. Maya reviews it and can edit it." |
| 25–40s | Step 3: units, locations, Needs review, a control lot marked NOT AFFECTED | "Snowflake matches the scope against lot-level inventory. Other lots of the same product stay sellable. Rows with no lot on record get flagged for review instead of being treated as safe." |
| 40–52s | **Approve holds**, then **Fulfil** on a held order (BLOCKED) and on a control-lot order (FULFILLED) | "Approving calls a stored procedure that writes the holds; running it twice adds nothing. Orders on held stock are now refused, and other lots still ship." |
| 52–60s | Expand the Audit trail | "Every interpretation, approval and blocked order is recorded in Snowflake. The notices are real FDA data; the store stock levels are generated." |
