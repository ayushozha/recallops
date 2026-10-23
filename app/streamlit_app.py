"""RecallOps: a real FDA recall notice -> Claude scope -> reviewed holds in Snowflake -> enforced orders."""
import json
import re
import time
import uuid

import streamlit as st

from db import MODEL, connect, query
from recall import interpret, notice_from_recall

st.set_page_config(page_title="RecallOps", layout="wide")

@st.cache_resource
def get_conn():
    return connect()


def digits(s):
    return re.sub(r"\D", "", s or "")


conn = get_conn()
who = query(conn, "SELECT CURRENT_USER() U, CURRENT_ROLE() R, CURRENT_ACCOUNT() A")[0]

st.title("RecallOps")
st.caption(
    f"Live Snowflake session: user **{who['U']}**, role **{who['R']}**, account **{who['A']}** · "
    f"Claude via `AI_COMPLETE` (`{MODEL}`) · Recall notices are real openFDA enforcement reports"
)

# ---------- Stage 1: pick a real notice ----------
st.header("1 · Recall notice")
recalls = query(conn, """
    SELECT r.*, COUNT(i.INVENTORY_ID) AS INV_ROWS
    FROM FDA_RECALLS r LEFT JOIN INVENTORY i ON i.SOURCE_RECALL_NUMBER = r.RECALL_NUMBER
    GROUP BY ALL ORDER BY INV_ROWS DESC, REPORT_DATE DESC LIMIT 200""")
labels = {
    f"{r['RECALL_NUMBER']} · {r['RECALLING_FIRM']} · {r['REPORT_DATE']}"
    + (" · ⚠ we stock this firm" if r["INV_ROWS"] else ""): r
    for r in recalls
}
choice = st.selectbox(f"Real FDA enforcement reports in Snowflake ({len(recalls)} shown)", list(labels))
rec = labels[choice]
notice = st.text_area("Notice text (editable, e.g. paste a supplier amendment)", notice_from_recall(rec), height=170)

if st.button("Interpret with Claude", type="primary"):
    t0 = time.time()
    out = interpret(conn, notice)
    case_id = "CASE-" + uuid.uuid4().hex[:8].upper()
    query(conn, """INSERT INTO RECALL_CASES (CASE_ID, RECALL_NUMBER, NOTICE_TEXT, MODEL, MODEL_OUTPUT, STATUS)
                   SELECT %(c)s, %(r)s, %(n)s, %(m)s, PARSE_JSON(%(o)s), 'PROPOSED'""",
          {"c": case_id, "r": rec["RECALL_NUMBER"], "n": notice, "m": MODEL, "o": json.dumps(out)})
    query(conn, "INSERT INTO ACTIONS (CASE_ID, ACTION_TYPE, DETAIL) SELECT %(c)s, 'INTERPRETED', PARSE_JSON(%(d)s)",
          {"c": case_id, "d": json.dumps({"seconds": round(time.time() - t0, 1), "model": MODEL})})
    st.session_state.case = {"id": case_id, "out": out, "secs": time.time() - t0}

case = st.session_state.get("case")
if not case:
    st.stop()

# ---------- Stage 2: review Claude's scope ----------
st.header("2 · Claude's proposed scope — review before anything changes")
out = case["out"]
c1, c2 = st.columns(2)
with c1:
    st.write(f"**Case** `{case['id']}` · Claude answered in {case['secs']:.1f}s · saved to `RECALL_CASES`")
    st.write(f"**Firm:** {out.get('firm')}  \n**Reason:** {out.get('reason')}")
    upcs = st.text_input("UPCs in scope (comma-separated)", ", ".join(out.get("upcs", [])))
    lots = st.text_input("Lot codes in scope (comma-separated; empty = every lot of these UPCs)",
                         ", ".join(out.get("lot_codes", [])))
with c2:
    st.write("**Evidence quoted from the notice**")
    for e in out.get("evidence", []):
        st.markdown(f"> {e}")
    for a in out.get("ambiguities", []):
        st.warning(f"Needs review: {a}")

scope = {
    "upcs": sorted({digits(u) for u in upcs.split(",") if digits(u)}),
    "lot_codes": sorted({l.strip().upper() for l in lots.split(",") if l.strip()}),
}

# ---------- Stage 3: match stock in Snowflake ----------
st.header("3 · Matching stock in Snowflake")
inv = query(conn, """
    SELECT i.INVENTORY_ID, l.LOCATION_NAME, i.UPC, i.PRODUCT_NAME, i.LOT_CODE, i.QUANTITY,
      CASE WHEN NOT ARRAY_CONTAINS(i.UPC::VARIANT, PARSE_JSON(%(u)s)) THEN NULL
           WHEN i.LOT_CODE IS NULL THEN 'NEEDS REVIEW: no lot on record'
           WHEN ARRAY_SIZE(PARSE_JSON(%(l)s)) = 0 OR ARRAY_CONTAINS(UPPER(i.LOT_CODE)::VARIANT, PARSE_JSON(%(l)s))
             THEN 'AFFECTED' ELSE 'NOT AFFECTED: lot outside scope' END AS DECISION,
      IFF(h.INVENTORY_ID IS NULL, '', 'HELD') AS HOLD
    FROM INVENTORY i JOIN LOCATIONS l ON l.LOCATION_ID = i.LOCATION_ID
    LEFT JOIN (SELECT DISTINCT INVENTORY_ID FROM HOLDS) h ON h.INVENTORY_ID = i.INVENTORY_ID
    ORDER BY DECISION, LOCATION_NAME""",
    {"u": json.dumps(scope["upcs"]), "l": json.dumps(scope["lot_codes"])})
hits = [r for r in inv if r["DECISION"]]
affected = [r for r in hits if r["DECISION"] == "AFFECTED"]
m1, m2, m3 = st.columns(3)
m1.metric("Affected units", sum(r["QUANTITY"] for r in affected))
m2.metric("Locations", len({r["LOCATION_NAME"] for r in affected}))
m3.metric("Needs review", sum(r["DECISION"].startswith("NEEDS") for r in hits))
if hits:
    st.dataframe(hits, use_container_width=True, hide_index=True)
else:
    st.info("No inventory matches these UPCs. That does not prove the stock is safe — check product aliases.")

# ---------- Stage 4: approve (governed write-back) ----------
st.header("4 · Approve holds")
if st.button(f"Approve holds on {len(affected)} inventory records", disabled=not affected):
    query(conn, "UPDATE RECALL_CASES SET REVIEWED_SCOPE = PARSE_JSON(%(s)s) WHERE CASE_ID = %(c)s",
          {"s": json.dumps(scope), "c": case["id"]})
    res = query(conn, "CALL APPROVE_HOLDS(%(c)s)", {"c": case["id"]})[0]
    st.success(f"APPROVE_HOLDS returned: {list(res.values())[0]}")
    st.rerun()

# ---------- Stage 5: orders are enforced against holds ----------
st.header("5 · Pending orders are checked against holds")
orders = query(conn, """
    SELECT o.ORDER_ID, o.INVENTORY_ID, i.PRODUCT_NAME, i.LOT_CODE, o.QUANTITY, o.DESTINATION, o.STATUS
    FROM ORDERS o JOIN INVENTORY i ON i.INVENTORY_ID = o.INVENTORY_ID ORDER BY o.ORDER_ID""")
for o in orders:
    a, b = st.columns([5, 1])
    a.write(f"`{o['ORDER_ID']}` {o['QUANTITY']} × {o['PRODUCT_NAME']} lot `{o['LOT_CODE']}` → {o['DESTINATION']} · **{o['STATUS']}**")
    if b.button("Fulfil", key=o["ORDER_ID"]):
        r = list(query(conn, "CALL FULFILL_ORDER(%(o)s)", {"o": o["ORDER_ID"]})[0].values())[0]
        r = json.loads(r) if isinstance(r, str) else r
        (st.error if r["result"] == "BLOCKED" else st.success)(f"{o['ORDER_ID']}: {r['result']}")

with st.expander("Audit trail (ACTIONS table)"):
    st.dataframe(query(conn, "SELECT * FROM ACTIONS ORDER BY ACTED_AT DESC LIMIT 50"), use_container_width=True)
