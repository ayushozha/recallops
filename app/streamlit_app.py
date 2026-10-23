"""RecallOps: a real FDA recall notice -> Claude scope -> reviewed holds in Snowflake -> enforced orders."""
import html
import json
import re
import time
import uuid
from pathlib import Path

import pydeck as pdk
import streamlit as st

from db import MODEL, connect, query
from recall import interpret, notice_from_recall

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}
CODES = set(STATES.values())
NATIONWIDE = re.compile(r"nation\s*wide|all 50|throughout the (US|U\.S|United States)", re.I)


def states_in(distribution):
    """Approximate state mentions, with explicit nationwide exclusions honored."""
    d = distribution or ""
    names = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in sorted(STATES, key=len, reverse=True)) + r")\b", re.I)
    by_name = {name.lower(): code for name, code in STATES.items()}

    def mentioned(text):
        found = {by_name[m.group().lower()] for m in names.finditer(text)}
        remaining = names.sub(" ", text)
        codes = set(re.findall(r"\b([A-Z]{2})\b", remaining)) & CODES
        # IN is also a common preposition. Accept its abbreviation only as a
        # standalone/list item; the full name Indiana is always recognized.
        if not re.search(r"(?:^|[,:;/])\s*IN\s*(?:$|[,;/])", remaining):
            codes.discard("IN")
        return found | codes

    if NATIONWIDE.search(d):
        excluded = re.search(r"\b(?:except|excluding)\b(.*)$", d, re.I | re.S)
        return set(CODES) - (mentioned(excluded.group(1)) if excluded else set())
    return mentioned(d)


GEOJSON = json.loads((Path(__file__).parent / "us_states.geojson").read_text())


def _centroid(geom):
    rings = [geom["coordinates"][0]] if geom["type"] == "Polygon" else [max((poly[0] for poly in geom["coordinates"]), key=len)]
    pts = rings[0]
    return [sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)]


CENTROIDS = {STATES[f["properties"]["name"]]: _centroid(f["geometry"]) for f in GEOJSON["features"]
             if f["properties"]["name"] in STATES}
# Map pins for the demo chain's sites (the chain itself is generated demo data)
SITE_COORDS = {"Oakland": [-122.27, 37.80], "San Jose": [-121.89, 37.34], "Fresno": [-119.79, 36.74],
               "Sacramento": [-121.49, 38.58], "Los Angeles": [-118.24, 34.05], "Warehouse": [-120.99, 37.64]}
FLOW_STYLE = {  # status -> (rgb, label)
    "held": ([214, 40, 40], "HELD: stopped in Snowflake"),
    "affected": ([255, 140, 66], "affected: awaiting approval"),
    "review": ([245, 198, 107], "needs review: no lot on record"),
    "safe": ([41, 181, 232], "safe lot: keeps moving"),
    "pending": ([255, 140, 66], "stocked: awaiting Claude's scope"),
}


def site_coord(name):
    return next((c for k, c in SITE_COORDS.items() if k in name), None)


def recall_flows(conn, rec, case):
    """One flow per site holding this recall's product: supplier state -> site, coloured by Snowflake hold state."""
    raw = rec.get("RAW")
    raw = json.loads(raw) if isinstance(raw, str) else (raw or {})
    origin = CENTROIDS.get(raw.get("state"))
    if not origin:
        return None, []
    scope = (case or {}).get("scope")
    upcs = scope["upcs"] if scope else None
    lots = set(scope["lot_codes"]) if scope else None
    rows = query(conn, """
        SELECT l.LOCATION_NAME, i.LOT_CODE, i.QUANTITY, IFF(h.INVENTORY_ID IS NULL, 0, 1) HELD
        FROM INVENTORY i JOIN LOCATIONS l ON l.LOCATION_ID = i.LOCATION_ID
        LEFT JOIN (SELECT DISTINCT INVENTORY_ID FROM HOLDS) h ON h.INVENTORY_ID = i.INVENTORY_ID
        WHERE """ + ("ARRAY_CONTAINS(i.UPC::VARIANT, PARSE_JSON(%(u)s))" if upcs else "i.SOURCE_RECALL_NUMBER = %(r)s"),
        {"u": json.dumps(upcs or []), "r": rec["RECALL_NUMBER"]})
    flows = []
    for r in rows:
        dest = site_coord(r["LOCATION_NAME"])
        if not dest:
            continue
        lot = (r["LOT_CODE"] or "").upper()
        status = ("held" if r["HELD"] else "review" if not lot else "pending" if lots is None
                  else "affected" if (not lots or lot in lots) else "safe")
        rgb, label = FLOW_STYLE[status]
        flows.append({"from": origin, "to": dest, "site": r["LOCATION_NAME"], "lot": lot or "none",
                      "units": int(r["QUANTITY"]), "status": label, "rgb": rgb, "held": status == "held",
                      "firm": f"{rec['RECALLING_FIRM']} ({raw.get('city', '')}, {raw.get('state', '')})"})
    # held/safe flows drawn last so they sit on top
    flows.sort(key=lambda f: f["held"])
    return origin, flows


def us_map_3d(highlight, counts, origin=None, flows=()):
    """3D map: states extruded by FDA recall count, this recall's states in coral, glowing supplier -> store arcs."""
    top = max(counts.values() or [1])
    feats = []
    for f in GEOJSON["features"]:
        code = STATES.get(f["properties"]["name"])
        n, hit = counts.get(code, 0), code in highlight
        feats.append({**f, "properties": {
            "name": f["properties"]["name"], "count": n, "elev": 15000 + 170000 * n / top,
            "status": "this recall shipped here" if hit else "not in this recall",
            "fill": [217, 119, 87, 200] if hit else [41, 181, 232, int(40 + 100 * n / top)]}})
    layers = [pdk.Layer(
        "GeoJsonLayer", {"type": "FeatureCollection", "features": feats}, extruded=True, wireframe=True,
        get_elevation="properties.elev", get_fill_color="properties.fill", get_line_color=[255, 255, 255, 160],
        pickable=True, auto_highlight=True, material={"ambient": 0.55, "diffuse": 0.6, "shininess": 40})]
    if flows:
        glow = [{**f, "c": f["rgb"] + [70]} for f in flows]
        core = [{**f, "c": f["rgb"] + [255], "c2": ([255, 220, 220] if f["held"] else [255, 255, 255]) + [255]}
                for f in flows]
        arc = dict(get_source_position="from", get_target_position="to", get_height=0.55, great_circle=False)
        layers += [
            pdk.Layer("ArcLayer", glow, get_source_color="c", get_target_color="c",
                      get_width="4 + units / 6", width_min_pixels=10, **arc),
            pdk.Layer("ArcLayer", core, get_source_color="c", get_target_color="c",
                      get_width=3, width_min_pixels=3, pickable=True, **arc),
            pdk.Layer("ScatterplotLayer", [{"pos": origin, "firm": flows[0]["firm"]}], get_position="pos",
                      get_radius=60000, radius_min_pixels=9, get_fill_color=[20, 33, 61, 255],
                      stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=3),
            pdk.Layer("ScatterplotLayer", core, get_position="to", get_radius=22000, radius_min_pixels=7,
                      get_fill_color="c", stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=2,
                      pickable=True),
        ]
    view = pdk.ViewState(latitude=37.8, longitude=-104.5, zoom=4.55, pitch=52, bearing=-8)
    return pdk.Deck(layers=layers, initial_view_state=view, map_style="light",
                    tooltip={"html": "<b>{name}{site}</b><br/>{count}{units} {status}<br/>{lot}"})


def knowledge_graph(rec, scope, hits, orders):
    """Notice -> Claude scope -> product -> lots -> stock at each location -> orders, coloured by outcome."""
    q = lambda s: '"' + str(s).replace('"', "'").replace(chr(10), "\\n") + '"'
    g = ['digraph G { rankdir=LR; bgcolor="transparent"; nodesep=0.25; ranksep=0.6;',
         'node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=12 penwidth=0 margin="0.18,0.1"];',
         'edge [color="#9AA5B5" arrowsize=0.7];',
         f'notice [label={q("FDA notice" + chr(92) + "n" + rec["RECALL_NUMBER"])} fillcolor="#14213D" fontcolor="#FAF8F4"];',
         f'claude [label={q("Reviewed scope" + chr(92) + "n" + str(len(scope["upcs"])) + " UPC · " + str(len(scope["lot_codes"])) + " lots")} fillcolor="#D97757" fontcolor="#14213D"];',
         'notice -> claude;']
    for u in scope["upcs"]:
        g += [f'u{u} [label={q("UPC " + u)} fillcolor="#FBEDE6" fontcolor="#14213D"];', f'claude -> u{u};']
    lots_done = set()
    for r in hits:
        inv, lot = r["INVENTORY_ID"], r["LOT"]
        held, dec = r["HOLD"] == "HELD", r["DECISION"]
        fill, font, tag = (("#9B2C22", "#FFFFFF", "HELD") if held else
                           ("#D97757", "#14213D", "affected") if dec == "Affected" else
                           ("#F5C66B", "#14213D", "needs review") if dec.startswith("Needs") else
                           ("#E3F4FB", "#0C5A7D", "outside scope"))
        g.append(f'{q(inv)} [label={q(r["LOCATION"] + chr(10) + str(r["UNITS"]) + " units · " + tag)} fillcolor="{fill}" fontcolor="{font}"];')
        if lot:
            lid = "lot_" + (str(r["UPC"]) + "\0" + str(lot)).encode("utf-8").hex()
            if lid not in lots_done:
                lots_done.add(lid)
                in_scope = dec != "Not affected: lot outside scope"
                g.append(f'{lid} [label={q("Lot " + lot)} shape=ellipse fillcolor="{"#F7D3C4" if in_scope else "#E3F4FB"}" fontcolor="#14213D"];')
                g.append(f'u{r["UPC"]} -> {lid};')
            g.append(f'{lid} -> {q(inv)};')
        else:
            g.append(f'u{r["UPC"]} -> {q(inv)} [style=dashed label="no lot" fontsize=10 fontcolor="#7A5300"];')
    hit_ids = {r["INVENTORY_ID"] for r in hits}
    for o in orders:
        if o["INVENTORY_ID"] in hit_ids:
            fill, font = {"BLOCKED": ("#9B2C22", "#FFFFFF"), "FULFILLED": ("#1E6A36", "#FFFFFF")}.get(
                o["STATUS"], ("#ECEEF2", "#3D4552"))
            g.append(f'{q(o["ORDER_ID"])} [label={q(o["ORDER_ID"] + chr(10) + o["STATUS"].lower() + " → " + o["DESTINATION"])} shape=note fillcolor="{fill}" fontcolor="{font}"];')
            g.append(f'{q(o["INVENTORY_ID"])} -> {q(o["ORDER_ID"])};')
    return "\n".join(g + ["}"])

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
session_label = " · ".join(html.escape(str(who[k])) for k in ("A", "U", "R") if who.get(k))

st.markdown(f"""
<div class="ro-top">
  <div class="ro-logo"><span>R</span>RecallOps</div>
  <div class="ro-who">Live Snowflake · {session_label}<br>
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

tab1, tabmap, tab2, tab3, tab4 = st.tabs(
    ["1 The notice", "2 Where it went", "3 What we found", "4 Lock it down", "5 Audit trail"])


@st.cache_data(ttl=600)
def recall_counts_by_state():
    counts = {}
    for r in query(get_conn(), "SELECT DISTRIBUTION_PATTERN D FROM FDA_RECALLS"):
        for c in states_in(r["D"]):
            counts[c] = counts.get(c, 0) + 1
    return counts

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

# ---------- 2: where it went (real FDA distribution data) ----------
with tabmap:
    shipped = states_in(rec["DISTRIBUTION_PATTERN"])
    counts = recall_counts_by_state()
    n_class1 = query(conn, "SELECT COUNT_IF(CLASSIFICATION = 'Class I') N FROM FDA_RECALLS")[0]["N"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("States inferred from FDA distribution text", len(shipped))
    k2.metric("FDA food recalls in Snowflake", f"{n_total:,}")
    k3.metric("Class I (most dangerous)", f"{n_class1:,}")
    k4.metric("States inferred across all notices", len(counts))
    map_scope = None
    if case:
        map_scope = {"upcs": sorted({digits(u) for u in case["out"].get("upcs", []) if digits(u)}),
                     "lot_codes": sorted({l.strip().upper() for l in case["out"].get("lot_codes", []) if l.strip()})}
    origin, flows = recall_flows(conn, rec, {"scope": map_scope} if map_scope and map_scope["upcs"] else None)
    if flows:
        held_u = sum(f["units"] for f in flows if f["held"])
        moving = sum(f["units"] for f in flows if not f["held"])
        st.markdown(pill(f"Supplier: {flows[0]['firm']}", "grey") +
                    pill(f"{len(flows)} shipments into our network", "amber") +
                    (pill(f"{held_u} units stopped", "red") if held_u else "") +
                    pill(f"{moving} units still moving", "green" if held_u else "amber"), unsafe_allow_html=True)
    st.pydeck_chart(us_map_3d(shipped, counts, origin, flows), use_container_width=True, height=600)
    st.caption(f"Coral: states inferred for {rec['RECALL_NUMBER']}. Height and blue shade: counts inferred from "
               f"{n_total:,} FDA distribution patterns. This approximate text parser includes DC and can miss or "
               "misread locations; the map does not verify shipments or store receipt.")
    st.markdown(pill("FDA, Dec 2025: recalled infant formula was still on sale at 175+ stores in 36 states", "red"),
                unsafe_allow_html=True)

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
    graph_orders = query(conn, """SELECT o.ORDER_ID, o.INVENTORY_ID, o.DESTINATION, o.STATUS FROM ORDERS o
                                  ORDER BY o.ORDER_ID""")
    if hits:
        st.markdown("**Recall knowledge graph** — notice → reviewed scope → product → lots → stock → orders")
        st.graphviz_chart(knowledge_graph(rec, scope, hits, graph_orders), use_container_width=True)
        with st.expander("Matched inventory rows"):
            st.dataframe(hits, use_container_width=True, hide_index=True)
    if not hits:
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
                             "green") + (pill(f"by {who['U']}", "green") if who.get("U") else ""),
                        unsafe_allow_html=True)

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
