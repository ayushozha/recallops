<p align="center">
  <img src="docs/assets/banner.svg" alt="RecallOps — Recall notice in. Stock locked down." width="100%">
</p>

<p align="center">
  <img alt="Snowflake" src="https://img.shields.io/badge/Snowflake-Cortex-29B5E8?logo=snowflake&logoColor=white">
  <img alt="Claude" src="https://img.shields.io/badge/Claude-Opus%205.5-D97757?logo=anthropic&logoColor=white">
  <img alt="Streamlit" src="https://img.shields.io/badge/Streamlit-app-FF4B4B?logo=streamlit&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white">
  <img alt="Data" src="https://img.shields.io/badge/data-openFDA-14213D">
  <img alt="Hackathon" src="https://img.shields.io/badge/Intelligence%20at%20Work-Oct%2023%2C%202026-F0A58A">
</p>

<h3 align="center">Turn a real FDA recall notice into reviewed, enforced inventory holds.<br>Claude reads the notice. Snowflake finds the stock. A person approves. Orders stop.</h3>

---

## The problem

When a supplier or the FDA recalls a food product, a grocery chain has to find every affected lot across its warehouse and stores, stop that stock from moving, and prove that it did. Notices are free text — UPCs, lot ranges, packaging variants, exceptions — and matching them to inventory is still done with spreadsheets, emails and phone calls to stores.

> In December 2025 the FDA reported recalled infant formula still available at **more than 175 retail locations across 36 states**, after over 4,000 checks. Its findings included confusion about affected product codes and incomplete removal. — [FDA](https://www.fda.gov/food/recalls-outbreaks-emergencies/fda-calls-food-industry-leaders-strengthen-recall-compliance-and-ensure-recall-effectiveness)

**RecallOps** is built for the person who has to fix that: the **recall coordinator** at a grocery chain or food distributor.

## How it works

| | Step | Who | What happens |
|:-:|---|---|---|
| 1 | **Read the notice** | Claude | `AI_COMPLETE` with a JSON schema extracts UPCs, in-scope lot codes, quoted evidence and ambiguities from a real openFDA notice |
| 2 | **Review the scope** | Coordinator | Evidence is highlighted in the notice; UPCs and lots can be edited before anything changes |
| 3 | **Match every lot** | Snowflake SQL | The reviewed scope is matched against lot-level inventory: **Affected**, **Outside scope** or **Needs review** (no lot on record — never silently treated as safe) |
| 4 | **Approve holds** | `APPROVE_HOLDS` | A stored procedure MERGEs holds (re-approval adds nothing) and writes the audit entry |
| 5 | **Block shipments** | `FULFILL_ORDER` | Every fulfilment checks for holds first — held stock is **BLOCKED**, other lots ship |

Claude proposes, Snowflake decides where, and a person approves. Claude never writes SQL; the notice is treated as data, not instructions.

## Architecture

```mermaid
flowchart LR
    FDA[(openFDA<br/>food enforcement API)] -->|load_data.py| R

    subgraph SF["❄️ Snowflake · RECALLOPS.APP"]
        R[(FDA_RECALLS)]
        I[(INVENTORY · LOCATIONS · ORDERS)]
        C[(RECALL_CASES)]
        H[(HOLDS)]
        A[(ACTIONS · audit)]
        AI["Cortex AI_COMPLETE<br/>Claude + JSON schema"]
        M["SQL lot matching"]
        P1["APPROVE_HOLDS()"]
        P2["FULFILL_ORDER()"]
    end

    U([Recall coordinator]) <--> UI[Streamlit app]
    UI -->|notice| AI --> C
    UI -->|reviewed scope| M --> I
    UI -->|approve| P1 --> H
    P1 --> A
    UI -->|try order| P2
    P2 -.checks.-> H
    P2 --> A
    R --> UI
```

Everything — the notices, the model call, the matching, the writes and the audit trail — runs inside the retailer's own Snowflake account. No data leaves it to reach the model.

## Technology

| Layer | Used for |
|---|---|
| **Claude Opus 5.5** via **Snowflake Cortex `AI_COMPLETE`** | Structured extraction of recall scope with evidence and ambiguities |
| **Snowflake SQL** | Lot-level matching across inventory, locations and orders |
| **Snowflake stored procedures** (SQL Scripting) | Governed write-back: idempotent holds and order enforcement |
| **Snowflake tables + VARIANT** | Notices, cases, model output, reviewed scope, holds, audit log |
| **Streamlit** (local or Streamlit in Snowflake) | The coordinator's workflow UI |
| **openFDA** `food/enforcement` | Real recall notices, firms, UPCs and lot codes |
| **Python** · `snowflake-connector-python` | Loader, verifier and app connection |

### Mapped to the hackathon's five dimensions

| Dimension | RecallOps |
|---|---|
| **Surface** | Streamlit workflow app (local, or hosted in Snowsight) |
| **Context** | Real FDA notices, lot-level inventory, orders, case history in Snowflake |
| **Toolkit** | Structured `AI_COMPLETE` call, SQL matching, constrained procedures |
| **Intelligence** | Claude interprets free-text scope, exceptions and ambiguity |
| **Action** | Approved holds written to Snowflake; held orders refused |
| *Cross-cutting* | Audit trail in `ACTIONS` · end-to-end verifier · human approval before any write |

## Data: what is real and what is generated

- **Real:** FDA recall notices from openFDA (the loader fetches up to 2,000 recent reports), including the firms, product descriptions, UPCs and recalled lot codes used in the demo.
- **Generated:** the chain's stock quantities, six locations, pending orders and control lot strings. Each inventory product is a real recalled product with its real UPC and lot; control rows use lot strings outside that notice's scope, and some rows deliberately have no lot code to exercise **Needs review**. Outside-scope strings are not proof that a real lot is safe. A retailer would connect its own inventory and ordering tables.

## Verification status

| Check | Status |
|---|---|
| Snowflake connection (event account) | ✅ Verified |
| Setup SQL: database, tables, procedures | ✅ Created |
| Claude through `AI_COMPLETE` (`claude-opus-5-5`) | ✅ Probe returned `OK` in 2.4 s |
| openFDA load into Snowflake | ⏳ In progress |
| Structured extraction, approval, order blocking | ⏳ Pending the live `verify.py` run |

No time savings or prevented harm are claimed; those need a measured manual baseline.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install snowflake-connector-python streamlit requests python-dotenv
cp .env.example .env          # account, user, token, role, warehouse, model — never commit it

.venv/bin/python scripts/load_data.py                    # create RECALLOPS.APP and load real FDA data
.venv/bin/python scripts/verify.py --recall H-1339-2026  # live end-to-end check
.venv/bin/streamlit run app/streamlit_app.py             # open http://localhost:8501
```

No local login? Paste `scripts/bootstrap_demo.sql` into a Snowsight worksheet: it creates the same objects with 12 selected real notices.

## Project structure

```
app/
  streamlit_app.py      coordinator workflow: notice → scope → match → approve → orders → audit
  recall.py             Claude prompt, JSON schema and AI_COMPLETE call
  db.py                 local connection or Streamlit-in-Snowflake session
sql/
  01_setup.sql          tables, APPROVE_HOLDS, FULFILL_ORDER
  02_streamlit_in_snowflake.sql   optional hosting in Snowsight
scripts/
  load_data.py          openFDA → Snowflake, plus inventory and orders built from recalled products
  verify.py             live end-to-end checks
  bootstrap_demo.sql    browser-only setup with 12 real notices
docs/assets/            banner and concept images
DEMO.md · SUBMISSION.md
```

## Built at the hackathon

Everything in this repository was built on **October 23, 2026** at the Snowflake × Anthropic *Intelligence at Work* hackathon: the schema and procedures, the openFDA loader, the Claude extraction prompt and schema, the Streamlit app and the verifier.

## Roadmap

- Supplier amendments with a side-by-side diff of notice versions
- Location confirmations ("Store 1 segregated 36 units") tracked against holds
- Ingest notices from email and PDF with `AI_PARSE_DOCUMENT`
- Separate approver role, enforced by Snowflake RBAC rather than the UI
- Pilot with one retailer on historical notices and approved inventory records
