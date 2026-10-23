"""RecallOps: a real FDA recall notice -> Claude scope -> reviewed holds in Snowflake -> enforced orders."""
import html
import json
import re
import time
import uuid

import streamlit as st

from db import MODEL, connect, query
from recall import interpret, notice_from_recall

st.set_page_config(page_title="RecallOps", page_icon="🛑", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.5rem; max-width: 1200px;}
.ro-top {display:flex; justify-content:space-between; align-items:center; padding:4px 0 14px;
         border-bottom:1px solid #e3e6eb; margin-bottom:18px;}
.ro-logo {display:flex; align-items:center; gap:10px; font-size:22px; font-weight:600; color:#1b2a41;}
.ro-logo span {background:#1d3a6e; color:#fff; border-radius:7px; width:32px; height:32px;
               display:inline-flex; align-items:center; justify-content:center; font-size:18px;}
.ro-who {color:#5b6472; font-size:13px; text-align:right;}
.ro-eyebrow {color:#5b6472; font-size:12px; letter-spacing:.06em; text-transform:uppercase; margin-bottom:2px;}
.ro-title {font-size:26px; font-weight:600; color:#1b2a41; margin:0 0 4px;}
.ro-sub {color:#5b6472; font-size:13px; margin-bottom:6px;}
.ro-pill {display:inline-block; padding:3px 10px; border-radius:6px; font-size:12px; font-weight:500; margin:2px 4px 2px 0;}
.ro-amber {background:#fdf1d3; color:#7a5300;} .ro-green {background:#dff1e4; color:#1e6a36;}
.ro-red {background:#fbe3e1; color:#9b2c22;} .ro-grey {background:#eceef2; color:#3d4552;}
.ro-notice {font-size:15px; line-height:1.7; color:#1b2a41; white-space:pre-wrap;}
.ro-notice mark {background:#fdeec4; color:#6b4a00; padding:1px 3px; border-radius:3px;}
.ro-kv {display:grid; grid-template-columns:130px 1fr; gap:10px 14px; font-size:14px;}
.ro-kv div:nth-child(odd) {color:#5b6472;} .ro-kv div:nth-child(even) {color:#1b2a41; font-weight:500;}
.ro-big {font-size:34px; font-weight:500; color:#1b2a41; line-height:1;} .ro-biglbl {color:#5b6472; font-size:13px;}
.ro-order {font-weight:600; color:#1b2a41;} .ro-ordersub {color:#5b6472; font-size:13px;}
.ro-foot {border-top:1px solid #e3e6eb; margin-top:26px; padding-top:12px; font-size:13px; color:#5b6472;}
.ro-foot b {color:#1b2a41;}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def get_conn():
    return connect()


def digits(s):
    return re.sub(r"\D", "", s or "")


def pill(text, tone="grey"):
    return f'<span class="ro-pill ro-{tone}">{html.escape(str(text))}</span>'


def highlight(text, quotes):
    out = html.escape(text)
    for q in sorted({q.strip() for q in quotes if q and len(q.strip()) > 3}, key=len, reverse=True):
        eq = html.escape(q)
        if eq in out:
            out = out.replace(eq, f"<mark>{eq}</mark>")
    return out


def call(sql, params):
    v = list(query(conn, sql, params)[0].values())[0]
    return json.loads(v) if isinstance(v, str) else v


conn = get_conn()
who = query(conn, "SELECT CURRENT_USER() U, CURRENT_ROLE() R, CURRENT_ACCOUNT() A")[0]

st.markdown(f"""
<div class="ro-top">
  <div class="ro-logo"><span>R</span>RecallOps</div>
  <div class="ro-who">Live Snowflake · {html.escape(who['A'])} · {html.escape(who['U'])} ({html.escape(who['R'])})<br>
  Claude via Cortex <code>AI_COMPLETE</code> · <code>{html.escape(MODEL)}</code></div>
</div>""", unsafe_allow_html=True)

# ---------- pick a real notice ----------
recalls = query(conn, """
    SELECT r.*, COUNT(i.INVENTORY_ID) AS INV_ROWS
    FROM FDA_RECALLS r LEFT JOIN INVENTORY i ON i.SOURCE_RECALL_NUMBER = r.RECALL_NUMBER
    GROUP BY ALL ORDER BY INV_ROWS DESC, REPORT_DATE DESC LIMIT 200""")
labels = {
    f"{'⚠ ' if r['INV_ROWS'] else ''}{r['RECALL_NUMBER']} · {r['RECALLING_FIRM']} · {r['REPORT_DATE']}": r
    for r in recalls
}
n_total = query(conn, "SELECT COUNT(*) N FROM FDA_RECALLS")[0]["N"]
choice = st.selectbox(f"Real openFDA food enforcement reports in Snowflake ({n_total:,}) · ⚠ = products we stock",
                      list(labels))
rec = labels[choice]
if st.session_state.get("recall") != rec["RECALL_NUMBER"]:
    st.session_state.recall = rec["RECALL_NUMBER"]
    st.session_state.pop("case", None)
    st.session_state.pop("approve_result", None)
case = st.session_state.get("case")
status = query(conn, "SELECT STATUS FROM RECALL_CASES WHERE CASE_ID = %(c)s", {"c": case["id"]})[0]["STATUS"] \
    if case else None

h1, h2 = st.columns([4, 1])
h1.markdown(f"""<div class="ro-eyebrow">Recall {html.escape(rec['RECALL_NUMBER'])} · {html.escape(rec['RECALLING_FIRM'])}
 · {html.escape(rec['CLASSIFICATION'] or '')}</div>
<div class="ro-title">{html.escape((rec['REASON_FOR_RECALL'] or '')[:90])}</div>
<div class="ro-sub">Reported {rec['REPORT_DATE']} · Distribution: {html.escape((rec['DISTRIBUTION_PATTERN'] or '')[:120])}</div>""",
             unsafe_allow_html=True)
h2.markdown("<div style='text-align:right;padding-top:8px'>" + (
    pill("Holds approved", "green") if status == "APPROVED" else
    pill("Scope awaiting review", "amber") if case else pill("Not yet interpreted")) + "</div>",
    unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["1 Notice", "2 Review stock", "3 Approve holds", "4 Audit trail"])

# ---------- 1: notice + Claude scope ----------
with tab1:
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("**Recall notice** " + pill("openFDA · real"), unsafe_allow_html=True)
        notice = notice_from_recall(rec)
        if st.toggle("Edit / paste a supplier amendment"):
            notice = st.text_area("Notice text", notice, height=220, label_visibility="collapsed")
        st.markdown(f'<div class="ro-notice">{highlight(notice, case["out"].get("evidence", []) if case else [])}</div>',
                    unsafe_allow_html=True)
    with right, st.container(border=True):
        st.markdown("**Proposed scope** " + pill("Claude · proposed"), unsafe_allow_html=True)
        if st.button("Interpret with Claude", type="primary", use_container_width=True):
            with st.spinner("Claude is reading the notice inside Snowflake…"):
                t0 = time.time()
                out = interpret(conn, notice)
                secs = time.time() - t0
            case_id = "CASE-" + uuid.uuid4().hex[:8].upper()
            query(conn, """INSERT INTO RECALL_CASES (CASE_ID, RECALL_NUMBER, NOTICE_TEXT, MODEL, MODEL_OUTPUT, STATUS)
                           SELECT %(c)s, %(r)s, %(n)s, %(m)s, PARSE_JSON(%(o)s), 'PROPOSED'""",
                  {"c": case_id, "r": rec["RECALL_NUMBER"], "n": notice, "m": MODEL, "o": json.dumps(out)})
            query(conn, "INSERT INTO ACTIONS (CASE_ID, ACTION_TYPE, DETAIL) SELECT %(c)s, 'INTERPRETED', PARSE_JSON(%(d)s)",
                  {"c": case_id, "d": json.dumps({"seconds": round(secs, 1), "model": MODEL})})
            st.session_state.case = {"id": case_id, "out": out, "secs": secs}
            st.session_state.pop("approve_result", None)
            st.rerun()
        if case:
            out = case["out"]
            st.markdown(f"""<div class="ro-kv">
<div>Firm</div><div>{html.escape(out.get('firm', ''))}</div>
<div>Products</div><div>{'<br>'.join(html.escape(p) for p in out.get('product_names', []))}</div>
<div>UPCs</div><div>{', '.join(html.escape(u) for u in out.get('upcs', [])) or '—'}</div>
<div>Lots in scope</div><div>{', '.join(html.escape(l) for l in out.get('lot_codes', [])) or 'none stated'}</div>
<div>Best-by</div><div>{', '.join(html.escape(d) for d in out.get('best_by_dates', []) or []) or '—'}</div>
<div>Reason</div><div>{html.escape(out.get('reason', ''))}</div></div>""", unsafe_allow_html=True)
            for a in out.get("ambiguities", []):
                st.warning(f"Needs review: {a}")
            st.caption(f"Case `{case['id']}` · Claude answered in {case['secs']:.1f}s · saved to RECALL_CASES. "
                       "Highlighted text in the notice is Claude's quoted evidence.")
        else:
            st.caption("Claude proposes; nothing is held until a coordinator reviews and approves.")

if not case:
    for t in (tab2, tab3, tab4):
        with t:
            st.info("Interpret the notice first.")
    st.stop()

# ---------- 2: review + match ----------
with tab2:
    out = case["out"]
    c1, c2 = st.columns(2)
    upcs = c1.text_input("UPCs in scope (edit if needed)", ", ".join(out.get("upcs", [])))
    lots = c2.text_input("Lot codes in scope (empty = every lot of these UPCs)", ", ".join(out.get("lot_codes", [])))
    scope = {
        "upcs": sorted({digits(u) for u in upcs.split(",") if digits(u)}),
        "lot_codes": sorted({l.strip().upper() for l in lots.split(",") if l.strip()}),
    }
    inv = query(conn, """
        SELECT i.INVENTORY_ID, l.LOCATION_NAME AS LOCATION, i.PRODUCT_NAME AS PRODUCT, i.UPC, i.LOT_CODE AS LOT,
          i.QUANTITY AS UNITS,
          CASE WHEN NOT ARRAY_CONTAINS(i.UPC::VARIANT, PARSE_JSON(%(u)s)) THEN NULL
               WHEN i.LOT_CODE IS NULL THEN 'Needs review: no lot on record'
               WHEN ARRAY_SIZE(PARSE_JSON(%(l)s)) = 0
                 OR ARRAY_CONTAINS(UPPER(i.LOT_CODE)::VARIANT, PARSE_JSON(%(l)s)) THEN 'Affected'
               ELSE 'Not affected: lot outside scope' END AS DECISION,
          IFF(h.INVENTORY_ID IS NULL, '', 'HELD') AS HOLD
        FROM INVENTORY i JOIN LOCATIONS l ON l.LOCATION_ID = i.LOCATION_ID
        LEFT JOIN (SELECT DISTINCT INVENTORY_ID FROM HOLDS) h ON h.INVENTORY_ID = i.INVENTORY_ID
        ORDER BY DECISION, LOCATION""",
        {"u": json.dumps(scope["upcs"]), "l": json.dumps(scope["lot_codes"])})
    hits = [r for r in inv if r["DECISION"]]
    affected = [r for r in hits if r["DECISION"] == "Affected"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Affected units", sum(r["UNITS"] for r in affected))
    m2.metric("Locations", len({r["LOCATION"] for r in affected}))
    m3.metric("Outside scope (stay sellable)", sum(r["UNITS"] for r in hits if r["DECISION"].startswith("Not")))
    m4.metric("Needs review", sum(r["DECISION"].startswith("Needs") for r in hits))
    if hits:
        st.dataframe(hits, use_container_width=True, hide_index=True)
    else:
        st.info("No inventory matches these UPCs. That does not prove the stock is safe — check product aliases.")
    st.caption("Matching runs as SQL in Snowflake against lot-level INVENTORY; Claude never writes SQL.")

# ---------- 3: approve + orders ----------
with tab3:
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("**Holds** " + (pill("Approved", "green") if status == "APPROVED" else pill("Pending approval", "amber")),
                    unsafe_allow_html=True)
        by_loc = {}
        for r in affected:
            by_loc[r["LOCATION"]] = by_loc.get(r["LOCATION"], 0) + r["UNITS"]
        st.markdown(f"""<div style="display:flex;gap:48px;margin:8px 0 14px">
<div><div class="ro-big">{sum(by_loc.values())}</div><div class="ro-biglbl">units to hold</div></div>
<div><div class="ro-big">{len(by_loc)}</div><div class="ro-biglbl">location tasks</div></div></div>""",
                    unsafe_allow_html=True)
        st.dataframe([{"Location": k, "Units": v,
                       "Action": "Hold + segregation task" if "Warehouse" in k else "Hold + removal task"}
                      for k, v in by_loc.items()], use_container_width=True, hide_index=True)
        if st.button(f"Approve holds on {len(affected)} records", type="primary", disabled=not affected,
                     use_container_width=True):
            query(conn, "UPDATE RECALL_CASES SET REVIEWED_SCOPE = PARSE_JSON(%(s)s) WHERE CASE_ID = %(c)s",
                  {"s": json.dumps(scope), "c": case["id"]})
            st.session_state.approve_result = call("CALL APPROVE_HOLDS(%(c)s)", {"c": case["id"]})
            st.rerun()
        if st.session_state.get("approve_result"):
            r = st.session_state.approve_result
            st.markdown(pill(f"APPROVE_HOLDS: {r['new_holds']} new · {r['total_holds']} total · {r['units_held']} units",
                             "green") + pill(f"by {who['U']}", "green"), unsafe_allow_html=True)

    with right, st.container(border=True):
        st.markdown("**Order check** — every fulfilment calls `FULFILL_ORDER`, which refuses held stock")
        upc_set = set(scope["upcs"])
        orders = query(conn, """
            SELECT o.ORDER_ID, i.UPC, i.PRODUCT_NAME, i.LOT_CODE, o.QUANTITY, o.DESTINATION, o.STATUS,
                   l.LOCATION_NAME
            FROM ORDERS o JOIN INVENTORY i ON i.INVENTORY_ID = o.INVENTORY_ID
            JOIN LOCATIONS l ON l.LOCATION_ID = i.LOCATION_ID ORDER BY o.ORDER_ID""")
        orders.sort(key=lambda o: o["UPC"] not in upc_set)  # this recall's product first
        for o in orders:
            a, b = st.columns([4, 1])
            tone = {"BLOCKED": "red", "FULFILLED": "green"}.get(o["STATUS"], "grey")
            label = {"BLOCKED": "Blocked — recall hold", "FULFILLED": "Fulfilled"}.get(o["STATUS"], "Pending")
            a.markdown(f"""<div class="ro-order">{o['ORDER_ID']} · lot {html.escape(str(o['LOT_CODE']))} · {o['QUANTITY']} units</div>
<div class="ro-ordersub">{html.escape(o['PRODUCT_NAME'][:50])} · {html.escape(o['LOCATION_NAME'])} → {html.escape(o['DESTINATION'])}</div>
{pill(label, tone)}""", unsafe_allow_html=True)
            if b.button("Try order", key=o["ORDER_ID"]):
                call("CALL FULFILL_ORDER(%(o)s)", {"o": o["ORDER_ID"]})
                st.rerun()

# ---------- 4: audit ----------
with tab4:
    st.dataframe(query(conn, """SELECT ACTED_AT, ACTION_TYPE, CASE_ID, ACTOR, DETAIL FROM ACTIONS
                                ORDER BY ACTED_AT DESC LIMIT 100"""), use_container_width=True, hide_index=True)
    st.caption("Every interpretation, approval and order decision is written to RECALLOPS.APP.ACTIONS.")

st.markdown("""<div class="ro-foot"><b>Claude</b> · interpret notice &nbsp;→&nbsp; <b>Snowflake</b> · match records and
store actions &nbsp;→&nbsp; <b>Coordinator</b> · review and approve · Recall notices are real openFDA data; store stock
levels and orders are generated around real recalled UPCs and lots.</div>""", unsafe_allow_html=True)
