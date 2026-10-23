"""RecallOps: a real FDA recall notice -> Claude scope -> reviewed holds in Snowflake -> enforced orders."""
import html
import json
import re
import time
import uuid
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

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


def knowledge_graph(rec, scope, hits, orders, stage=6, flash=None):
    """Notice -> scope -> product -> lots -> stock -> orders. `stage` limits depth for the grow animation;
    `flash` rings the order node that just changed."""
    q = lambda s: '"' + str(s).replace('"', "'").replace(chr(10), "\\n") + '"'
    g = []
    add = lambda lvl, line: g.append(line) if lvl <= stage else None
    add(1, f'notice [label={q("FDA notice" + chr(10) + rec["RECALL_NUMBER"])} fillcolor="#14213D" fontcolor="#FAF8F4"];')
    add(2, f'claude [label={q("Reviewed scope" + chr(10) + str(len(scope["upcs"])) + " UPC · " + str(len(scope["lot_codes"])) + " lots")} fillcolor="#D97757" fontcolor="#14213D"];')
    add(2, 'notice -> claude;')
    for u in scope["upcs"]:
        add(3, f'u{u} [label={q("UPC " + u)} fillcolor="#FBEDE6" fontcolor="#14213D"];')
        add(3, f'claude -> u{u};')
    lots_done = set()
    for r in hits:
        inv, lot = r["INVENTORY_ID"], r["LOT"]
        held, dec = r["HOLD"] == "HELD", r["DECISION"]
        fill, font, tag = (("#9B2C22", "#FFFFFF", "HELD") if held else
                           ("#D97757", "#14213D", "affected") if dec == "Affected" else
                           ("#F5C66B", "#14213D", "needs review") if dec.startswith("Needs") else
                           ("#E3F4FB", "#0C5A7D", "outside scope"))
        add(5, f'{q(inv)} [label={q(r["LOCATION"] + chr(10) + str(r["UNITS"]) + " units · " + tag)} fillcolor="{fill}" fontcolor="{font}"];')
        if lot:
            lid = "lot_" + (str(r["UPC"]) + "\0" + str(lot)).encode("utf-8").hex()
            if lid not in lots_done:
                lots_done.add(lid)
                in_scope = dec != "Not affected: lot outside scope"
                add(4, f'{lid} [label={q("Lot " + lot)} shape=ellipse fillcolor="{"#F7D3C4" if in_scope else "#E3F4FB"}" fontcolor="#14213D"];')
                add(4, f'u{r["UPC"]} -> {lid};')
            add(5, f'{lid} -> {q(inv)};')
        else:
            add(5, f'u{r["UPC"]} -> {q(inv)} [style=dashed label="no lot" fontsize=10 fontcolor="#7A5300"];')
    hit_ids = {r["INVENTORY_ID"] for r in hits}
    for o in orders:
        if o["INVENTORY_ID"] in hit_ids:
            fill, font = {"BLOCKED": ("#9B2C22", "#FFFFFF"), "FULFILLED": ("#1E6A36", "#FFFFFF")}.get(
                o["STATUS"], ("#ECEEF2", "#3D4552"))
            ring = ' penwidth=5 color="#F5C66B"' if o["ORDER_ID"] == flash else ""
            label = o["ORDER_ID"] + chr(10) + {"BLOCKED": "BLOCKED", "FULFILLED": "FULFILLED"}.get(o["STATUS"], "pending") + " → " + o["DESTINATION"]
            add(6, f'{q(o["ORDER_ID"])} [label={q(label)} shape=note fillcolor="{fill}" fontcolor="{font}"{ring}];')
            add(6, f'{q(o["INVENTORY_ID"])} -> {q(o["ORDER_ID"])};')
    head = ['digraph G { rankdir=LR; bgcolor="transparent"; nodesep=0.25; ranksep=0.6;',
            'node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=12 penwidth=0 margin="0.18,0.1"];',
            'edge [color="#9AA5B5" arrowsize=0.7];']
    return "\n".join(head + g + ["}"])


@st.cache_data(ttl=600)
def weekly_recalls():
    return query(get_conn(), """SELECT DATE_TRUNC('week', REPORT_DATE) WK, CLASSIFICATION K, COUNT(*) N
                               FROM FDA_RECALLS WHERE REPORT_DATE IS NOT NULL GROUP BY 1, 2 ORDER BY 1""")


def trends_chart(rows, marked_date):
    fig = go.Figure()
    for k, color in [("Class I", "#B4532F"), ("Class II", "#D97757"), ("Class III", "#F3C7B4")]:
        pts = [r for r in rows if r["K"] == k]
        fig.add_bar(x=[r["WK"] for r in pts], y=[r["N"] for r in pts], name=k, marker_color=color,
                    hovertemplate="week of %{x|%b %d, %Y}: %{y} " + k + " recalls<extra></extra>")
    if marked_date:
        fig.add_vline(x=marked_date, line_width=2, line_dash="dot", line_color="#14213D")
        fig.add_annotation(x=marked_date, y=1, yref="paper", text="this recall", showarrow=False,
                           yanchor="bottom", font=dict(color="#14213D", size=12))
    fig.update_layout(barmode="stack", height=200, margin=dict(l=0, r=0, t=24, b=0), bargap=0.15,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=1.2, x=0, xanchor="left"),
                      yaxis=dict(title="recalls / week", gridcolor="#ECEAE4"), xaxis=dict(showgrid=False))
    return fig


def findings_lines(rec, out):
    lines = [f"🔎 Reading FDA notice **{rec['RECALL_NUMBER']}** inside Snowflake Cortex…",
             f"🏭 Recalling firm: **{out.get('firm', '?')}**"]
    lines += [f"🏷️ Found UPC **{u}**" for u in out.get("upcs", [])]
    lines += [f"📦 Lot **{l}**: in scope" for l in out.get("lot_codes", [])]
    for a in out.get("ambiguities", [])[:3]:
        first = re.split(r"(?<=[.;])\s", a)[0]
        lines.append(f"⚠️ {first[:140]}")
    lines.append(f"✅ Scope ready for human review: {len(out.get('upcs', []))} UPC, {len(out.get('lot_codes', []))} lots")
    return lines


def typed(lines):
    for line in lines:
        for w in line.split(" "):
            yield w + " "
            time.sleep(0.035)
        yield "  \n"
        time.sleep(0.25)


LABEL_OFFSETS = {  # keep the clustered California labels readable
    "Oakland": ([-14, -12], "end"), "San Jose": ([-14, 12], "end"), "Sacramento": ([14, -16], "start"),
    "Fresno": ([16, 4], "start"), "Los Angeles": ([16, 12], "start"), "Warehouse": ([16, -2], "start"),
}


def animated_map_html(highlight, counts, origin, flows):
    """deck.gl page: states lit by recall count, shipments animating from supplier to stores, held ones red and still."""
    top = max(counts.values() or [1])
    states = {"type": "FeatureCollection", "features": [
        {**f, "properties": {
            "name": f["properties"]["name"], "count": counts.get(STATES.get(f["properties"]["name"]), 0),
            "hit": STATES.get(f["properties"]["name"]) in highlight,
            "elev": 6000 + 70000 * counts.get(STATES.get(f["properties"]["name"]), 0) / top,
            "fill": ([226, 120, 86, 235] if STATES.get(f["properties"]["name"]) in highlight else
                     [46, 120, 190, int(70 + 150 * counts.get(STATES.get(f["properties"]["name"]), 0) / top)])}}
        for f in GEOJSON["features"]]}
    sites, labels = {}, []
    for f in flows:
        s = sites.setdefault(f["site"], {"pos": f["to"], "units": 0, "held": 0, "lots": [], "rgb": f["rgb"]})
        s["units"] += f["units"]
        s["held"] += f["units"] if f["held"] else 0
        s["lots"].append(f"lot {f['lot']}: {f['status']}")
        if f["held"]:
            s["rgb"] = f["rgb"]
    for name, s in sites.items():
        short = name.split(" - ")[-1]
        off, anchor = next((v for k, v in LABEL_OFFSETS.items() if k in name), ([14, 0], "start"))
        text = f"{short} · {s['held']} held" if s["held"] else f"{short} · {s['units']} units"
        labels.append({"pos": s["pos"], "text": text, "off": off, "anchor": anchor, "held": bool(s["held"])})
        s["tip"] = name + "\n" + "\n".join(s["lots"])
    if origin and flows:
        labels.append({"pos": origin, "text": flows[0]["firm"].split(" (")[0], "off": [0, -22], "anchor": "middle",
                       "held": False, "origin": True})
    data = {"states": states, "origin": origin, "sites": list(sites.values()), "labels": labels,
            "flows": [{"to": f["to"], "rgb": f["rgb"], "held": f["held"]} for f in flows]}
    return """<!doctype html><html><head><meta charset="utf-8">
<script src="https://unpkg.com/deck.gl@8.9.36/dist.min.js"></script>
<style>html,body{margin:0;height:100%;background:#0B1424;font-family:Helvetica,Arial,sans-serif;overflow:hidden}
#map{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 20%,#1D3157 0%,#0B1424 70%);border-radius:14px}
.legend{position:absolute;left:16px;bottom:14px;background:rgba(11,20,36,.82);color:#E8EDF5;border:1px solid #2A3F63;
border-radius:10px;padding:10px 14px;font-size:12px;line-height:1.9}
.legend i{display:inline-block;width:22px;height:4px;border-radius:2px;margin-right:8px;vertical-align:middle}
.title{position:absolute;left:16px;top:12px;color:#C3CCD8;font-size:12px;letter-spacing:2px;text-transform:uppercase}</style>
</head><body><div id="map"></div>
<div class="title">Live supply map · RecallOps</div>
<div class="legend"><div><i style="background:#FF8C42"></i>shipment in motion (awaiting approval)</div>
<div><i style="background:#29B5E8"></i>safe lot, keeps moving</div><div><i style="background:#D62828"></i>held in Snowflake, stopped</div>
<div><i style="background:#E27856"></i>states this recall reached</div></div>
<script>
const D = """ + json.dumps(data) + """;
const vp = new deck.WebMercatorViewport({width: innerWidth, height: innerHeight})
  .fitBounds([[-128.5, 23.5], [-66.0, 50.0]], {padding: 48});
const view = {longitude: vp.longitude - 1.5, latitude: vp.latitude - 2.5, zoom: vp.zoom - 0.1, pitch: 40, bearing: -3};
function arc(a, b) {
  const pts = [], ts = [], n = 60, H = Math.hypot(a[0] - b[0], a[1] - b[1]) * 26000;
  for (let i = 0; i <= n; i++) { const f = i / n;
    pts.push([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, 8000 + Math.sin(Math.PI * f) * H]); ts.push(f * 100); }
  return {pts, ts};
}
const flows = D.origin ? D.flows.map((f, i) => Object.assign({}, f, arc(D.origin, f.to), {phase: i * 23})) : [];
const LOOP = 150;
const dg = new deck.DeckGL({container: 'map', initialViewState: view, controller: true,
  getTooltip: ({object}) => object && (object.tip || (object.properties && (object.properties.name + '\\n' +
    object.properties.count + ' FDA recalls named this state' + (object.properties.hit ? '\\nthis recall shipped here' : '')))),
  layers: []});
function layers(t) {
  const pulse = 1 + 0.45 * Math.sin(t / 220);
  return [
    new deck.GeoJsonLayer({id: 'states', data: D.states, extruded: true, getElevation: f => f.properties.elev,
      getFillColor: f => f.properties.fill, getLineColor: [150, 190, 235, 110], lineWidthMinPixels: 0.7, stroked: true,
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 60], material: {ambient: 0.65, diffuse: 0.45}}),
    new deck.PathLayer({id: 'routes', data: flows, getPath: d => d.pts, widthUnits: 'pixels',
      getColor: d => d.held ? [214, 40, 40, 235] : d.rgb.concat([60]), getWidth: d => d.held ? 4 : 2}),
    new deck.TripsLayer({id: 'trips', data: flows.filter(d => !d.held), getPath: d => d.pts, getTimestamps: d => d.ts,
      getColor: d => d.rgb, widthMinPixels: 6, trailLength: 38, fadeTrail: true, capRounded: true, jointRounded: true,
      currentTime: (t / 14) % LOOP, updateTriggers: {currentTime: t}}),
    new deck.ScatterplotLayer({id: 'halo', data: D.sites.filter(s => s.held), getPosition: d => d.pos,
      getRadius: 30000 * pulse, radiusMinPixels: 12 * pulse, getFillColor: [214, 40, 40, 70], updateTriggers: {getRadius: t}}),
    new deck.ScatterplotLayer({id: 'sites', data: D.sites, getPosition: d => d.pos, getRadius: 14000, radiusMinPixels: 6,
      getFillColor: d => d.held ? [214, 40, 40, 255] : [245, 248, 252, 255], stroked: true, getLineColor: d => d.rgb,
      lineWidthMinPixels: 2.5, pickable: true}),
    new deck.ScatterplotLayer({id: 'origin', data: D.origin ? [{pos: D.origin, tip: 'Supplier'}] : [],
      getPosition: d => d.pos, getRadius: 26000 * pulse, radiusMinPixels: 8, getFillColor: [245, 198, 107, 255],
      stroked: true, getLineColor: [255, 255, 255], lineWidthMinPixels: 2, updateTriggers: {getRadius: t}}),
    new deck.TextLayer({id: 'labels', data: D.labels, getPosition: d => d.pos, getText: d => d.text, getSize: 13,
      getColor: d => d.held ? [255, 205, 205] : (d.origin ? [245, 198, 107] : [232, 238, 246]),
      getPixelOffset: d => d.off, getTextAnchor: d => d.anchor, getAlignmentBaseline: 'center', background: true,
      getBackgroundColor: [11, 20, 36, 215], backgroundPadding: [6, 3], fontWeight: 700}),
  ];
}
function frame(now) { dg.setProps({layers: layers(now)}); requestAnimationFrame(frame); }
requestAnimationFrame(frame);
</script></body></html>"""


AUDIT_STYLE = {  # action -> (icon, colour, title)
    "INTERPRETED": ("🧠", "#D97757", "Claude read the notice"),
    "APPROVED": ("✅", "#1E6A36", "Holds approved"),
    "NOTICE_TO_HOLD": ("⏱", "#11729E", "Response time measured"),
    "ORDER_BLOCKED": ("⛔", "#9B2C22", "Order blocked"),
    "ORDER_FULFILLED": ("📦", "#1E6A36", "Order fulfilled"),
}


def audit_sentence(kind, d):
    if kind == "INTERPRETED":
        return f"Claude ({d.get('model', 'model')}) turned the FDA notice into a structured scope in {d.get('seconds', '?')}s."
    if kind == "APPROVED":
        return f"APPROVE_HOLDS placed {d.get('new_holds', 0)} new holds · {d.get('units', d.get('units_held', '?'))} units now frozen."
    if kind == "NOTICE_TO_HOLD":
        return f"From reading the notice to approved holds took {d.get('seconds', '?')}s, protecting {d.get('units', '?')} units."
    if kind == "ORDER_BLOCKED":
        return f"FULFILL_ORDER refused {d.get('order_id', 'an order')}: it carried held, recalled stock."
    if kind == "ORDER_FULFILLED":
        return f"{d.get('order_id', 'An order')} shipped: its lot is outside the recall."
    return ", ".join(f"{k}: {v}" for k, v in d.items()) or kind.replace("_", " ").lower()


def render_audit(case):
    show_all = st.toggle("Show all activity in Snowflake", value=not case)
    if case and not show_all:
        rows = query(conn, """SELECT ACTED_AT, ACTION_TYPE, CASE_ID, ACTOR, DETAIL FROM ACTIONS
            WHERE CASE_ID = %(c)s OR (ACTION_TYPE LIKE 'ORDER_%%'
              AND ACTED_AT >= (SELECT MIN(ACTED_AT) FROM ACTIONS WHERE CASE_ID = %(c)s))
            ORDER BY ACTED_AT""", {"c": case["id"]})
    else:
        rows = list(reversed(query(conn, """SELECT ACTED_AT, ACTION_TYPE, CASE_ID, ACTOR, DETAIL FROM ACTIONS
            ORDER BY ACTED_AT DESC LIMIT 40""")))
    details = [json.loads(r["DETAIL"]) if isinstance(r["DETAIL"], str) else (r["DETAIL"] or {}) for r in rows]
    resp = next((d.get("seconds") for r, d in zip(rows, details) if r["ACTION_TYPE"] == "NOTICE_TO_HOLD"), None)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Recorded events", len(rows))
    k2.metric("Notice → holds", f"{resp:.0f}s" if isinstance(resp, (int, float)) else "—")
    k3.metric("Orders blocked", sum(r["ACTION_TYPE"] == "ORDER_BLOCKED" for r in rows))
    k4.metric("Orders fulfilled", sum(r["ACTION_TYPE"] == "ORDER_FULFILLED" for r in rows))
    if not rows:
        st.info("Nothing recorded yet for this case.")
        return
    t_first = rows[0]["ACTED_AT"]
    items = []
    for r, d in zip(rows, details):
        icon, colour, title = AUDIT_STYLE.get(r["ACTION_TYPE"], ("•", "#6B7280", r["ACTION_TYPE"].replace("_", " ").title()))
        if r["ACTION_TYPE"].startswith("ORDER_") and d.get("order_id"):
            title += f" · {d['order_id']}"
        delta = int((r["ACTED_AT"] - t_first).total_seconds())
        items.append(f"""<div class="tl-item"><div class="tl-dot" style="background:{colour}">{icon}</div>
<div class="tl-card" style="border-left-color:{colour}"><div class="tl-head"><b>{html.escape(title)}</b>
<span>{r['ACTED_AT']:%H:%M:%S} · +{delta}s</span></div><div class="tl-body">{html.escape(audit_sentence(r['ACTION_TYPE'], d))}</div>
<div class="tl-meta">{pill(r['ACTOR'] or 'system')}{pill(r['CASE_ID'] or 'order check')}{pill('ACTIONS table')}</div></div></div>""")
    st.markdown("""<style>.tl{position:relative;margin:10px 0 0 8px;padding-left:26px;border-left:2px solid #E7E2D8}
.tl-item{position:relative;margin:0 0 14px} .tl-dot{position:absolute;left:-46px;top:10px;width:36px;height:36px;border-radius:50%;
display:flex;align-items:center;justify-content:center;font-size:17px;box-shadow:0 0 0 4px #FFFFFF}
.tl-card{background:#FFFEFB;border:1px solid #E7E2D8;border-left:5px solid;border-radius:12px;padding:12px 16px;
box-shadow:0 6px 18px rgba(20,33,61,.06)} .tl-head{display:flex;justify-content:space-between;gap:12px}
.tl-head b{color:#14213D;font-size:16px} .tl-head span{color:#6B7280;font-size:13px;font-variant-numeric:tabular-nums}
.tl-body{color:#3D4552;font-size:14.5px;margin:4px 0 8px}</style><div class="tl">""" + "".join(items) + "</div>",
                unsafe_allow_html=True)
    with st.expander("Raw ACTIONS rows (as stored in Snowflake)"):
        st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("Every interpretation, approval and order decision is written to RECALLOPS.APP.ACTIONS.")


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
    st.session_state.pop("t_hold", None)
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

@st.fragment(run_every="1s")
def response_banner():
    c = st.session_state.get("case")
    if not c or "t0" not in c:
        return
    done = st.session_state.get("t_hold")
    secs = int((done or time.time()) - c["t0"])
    units = (st.session_state.get("approve_result") or {}).get("units_held", 0) if done else 0
    clock = f"{secs // 60:02d}:{secs % 60:02d}"
    state = "holds approved · stock stopped" if done else "awaiting review and approval"
    count = (f'<span class="rb-count" style="--target:{units}"></span>' if units else "0")
    st.markdown(f"""<style>@property --n {{syntax:'<integer>'; initial-value:0; inherits:false}}
.rb {{display:flex; gap:36px; align-items:center; background:linear-gradient(90deg,#14213D,#23365C); color:#FAF8F4;
  border-radius:14px; padding:14px 26px; margin:6px 0 14px;}}
.rb b {{font-size:30px; font-variant-numeric:tabular-nums}} .rb small {{color:#C3CCD8; font-size:13px; letter-spacing:1px; text-transform:uppercase}}
.rb-dot {{width:10px; height:10px; border-radius:50%; background:{"#4ADE80" if done else "#F5C66B"}; display:inline-block; margin-right:8px;
  box-shadow:0 0 12px {"#4ADE80" if done else "#F5C66B"}}}
.rb-count {{animation: rbc 1.8s ease-out forwards; counter-reset: n var(--n)}} .rb-count::after {{content: counter(n)}}
@keyframes rbc {{from {{--n:0}} to {{--n:var(--target)}}}}</style>
<div class="rb"><div><small>Notice → holds</small><br><b>⏱ {clock}</b></div>
<div><small>Units protected</small><br><b style="color:#F0A58A">{count}</b></div>
<div><small>Status</small><br><span class="rb-dot"></span>{state}</div>
<div style="margin-left:auto;text-align:right"><small>Measured live · case</small><br>{html.escape(c["id"])}</div></div>""",
                unsafe_allow_html=True)


response_banner()

STEPS = ["1 · The notice", "2 · Where it went", "3 · What we found", "4 · Lock it down", "5 · Audit trail"]
STEP_HINTS = ["Claude reads the real FDA notice", "Where the recalled product went", "Snowflake traces lots to stock",
              "Approve holds and test orders", "Everything Snowflake recorded"]


@st.cache_data(ttl=600)
def recall_counts_by_state():
    counts = {}
    for r in query(get_conn(), "SELECT DISTRIBUTION_PATTERN D FROM FDA_RECALLS"):
        for c in states_in(r["D"]):
            counts[c] = counts.get(c, 0) + 1
    return counts


def go_step(i):
    st.session_state.step_label = STEPS[i]


def next_step(i, label=None, primary=True):
    if i + 1 < len(STEPS):
        st.button(label or f"Next: {STEPS[i + 1].split(' · ')[1]} →", type="primary" if primary else "secondary",
                  on_click=go_step, args=(i + 1,), key=f"next_{i}", use_container_width=True)


if st.session_state.get("step_label") not in STEPS:
    st.session_state.step_label = STEPS[0]
st.segmented_control("Steps", STEPS, key="step_label", label_visibility="collapsed")
step = STEPS.index(st.session_state.step_label or STEPS[0])
st.caption(f"Step {step + 1} of {len(STEPS)} · {STEP_HINTS[step]}")

# ---------- shared state: reviewed scope + matched stock (used by steps 2-5) ----------
scope, hits, affected, graph_orders = {"upcs": [], "lot_codes": []}, [], [], []
if case:
    scope = {
        "upcs": sorted({digits(u) for u in st.session_state.get("scope_upcs", "").split(",") if digits(u)}),
        "lot_codes": sorted({l.strip().upper() for l in st.session_state.get("scope_lots", "").split(",") if l.strip()}),
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
    graph_orders = query(conn, "SELECT ORDER_ID, INVENTORY_ID, DESTINATION, STATUS FROM ORDERS ORDER BY ORDER_ID")


def need_case():
    st.info("Start with step 1: let Claude read the notice first.")
    st.button("← Go to step 1", on_click=go_step, args=(0,), type="primary")


# ---------- 1: notice + Claude scope ----------
if step == 0:
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
                st.session_state.pop("t_hold", None)
                out = interpret(conn, notice)
                secs = time.time() - t0
            case_id = "CASE-" + uuid.uuid4().hex[:8].upper()
            query(conn, """INSERT INTO RECALL_CASES (CASE_ID, RECALL_NUMBER, NOTICE_TEXT, MODEL, MODEL_OUTPUT, STATUS)
                           SELECT %(c)s, %(r)s, %(n)s, %(m)s, PARSE_JSON(%(o)s), 'PROPOSED'""",
                  {"c": case_id, "r": rec["RECALL_NUMBER"], "n": notice, "m": MODEL, "o": json.dumps(out)})
            query(conn, "INSERT INTO ACTIONS (CASE_ID, ACTION_TYPE, DETAIL) SELECT %(c)s, 'INTERPRETED', PARSE_JSON(%(d)s)",
                  {"c": case_id, "d": json.dumps({"seconds": round(secs, 1), "model": MODEL})})
            st.session_state.case = {"id": case_id, "out": out, "secs": secs, "t0": t0}
            st.session_state.scope_upcs = ", ".join(out.get("upcs", []))
            st.session_state.scope_lots = ", ".join(out.get("lot_codes", []))
            st.session_state.stream_findings = True
            st.session_state.pop("approve_result", None)
            st.session_state.pop("flash", None)
            st.rerun()
        if case:
            out = case["out"]
            st.markdown("**Claude's findings**")
            if st.session_state.pop("stream_findings", False):
                st.write_stream(typed(findings_lines(rec, out)))
            else:
                st.markdown("  \n".join(findings_lines(rec, out)))
            with st.expander("Full structured scope and review notes"):
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
            next_step(0)
        else:
            st.caption("Claude proposes; nothing is held until a coordinator reviews and approves.")

# ---------- 2: where it went (real FDA distribution data) ----------
elif step == 1:
    shipped = states_in(rec["DISTRIBUTION_PATTERN"])
    counts = recall_counts_by_state()
    n_class1 = query(conn, "SELECT COUNT_IF(CLASSIFICATION = 'Class I') N FROM FDA_RECALLS")[0]["N"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("States this recall reached", len(shipped))
    k2.metric("FDA food recalls in Snowflake", f"{n_total:,}")
    k3.metric("Class I (most dangerous)", f"{n_class1:,}")
    k4.metric("States hit by any recall", len(counts))
    origin, flows = recall_flows(conn, rec, {"scope": scope} if case and scope["upcs"] else None)
    if flows:
        held_u = sum(f["units"] for f in flows if f["held"])
        moving = sum(f["units"] for f in flows if not f["held"])
        st.markdown(pill(f"Supplier: {flows[0]['firm']}", "grey") +
                    pill(f"{len(flows)} shipments into our network", "amber") +
                    (pill(f"{held_u} units stopped", "red") if held_u else "") +
                    pill(f"{moving} units still moving", "green" if held_u else "amber"), unsafe_allow_html=True)
    components.html(animated_map_html(shipped, counts, origin, flows), height=620)
    st.caption(f"Coral states: inferred from the FDA distribution text for {rec['RECALL_NUMBER']}. Height and blue: how "
               f"many of the {n_total:,} FDA recalls named each state. Moving lines: shipments of this product into our "
               "stores; red lines are held in Snowflake. Store stock is generated demo data.")
    st.markdown("**FDA food recalls per week** — it never stops")
    st.plotly_chart(trends_chart(weekly_recalls(), rec["REPORT_DATE"]), use_container_width=True,
                    config={"displayModeBar": False})
    next_step(1)

# ---------- 3: review + match ----------
elif step == 2:
    if not case:
        need_case()
    else:
        c1, c2 = st.columns(2)
        st.session_state.scope_upcs = c1.text_input("UPCs in scope (edit if needed)", st.session_state.get("scope_upcs", ""))
        st.session_state.scope_lots = c2.text_input("Lot codes in scope (empty = every lot of these UPCs)",
                                                    st.session_state.get("scope_lots", ""))
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Affected units", sum(r["UNITS"] for r in affected))
        m2.metric("Locations", len({r["LOCATION"] for r in affected}))
        m3.metric("Outside scope (stay sellable)", sum(r["UNITS"] for r in hits if r["DECISION"].startswith("Not")))
        m4.metric("Needs review", sum(r["DECISION"].startswith("Needs") for r in hits))
        if hits:
            g1, g2 = st.columns([5, 1])
            g1.markdown("**Recall knowledge graph** — notice → reviewed scope → product → lots → stock → orders")
            trace = g2.button("▶ Trace the recall", use_container_width=True)
            graph_slot = st.empty()
            if trace:  # grow the graph one layer at a time
                for stage in range(1, 7):
                    graph_slot.graphviz_chart(knowledge_graph(rec, scope, hits, graph_orders, stage),
                                              use_container_width=True)
                    time.sleep(0.55)
            else:
                graph_slot.graphviz_chart(knowledge_graph(rec, scope, hits, graph_orders,
                                                          flash=st.session_state.get("flash")), use_container_width=True)
            with st.expander("Matched inventory rows"):
                st.dataframe(hits, use_container_width=True, hide_index=True)
        else:
            st.info("No inventory matches these UPCs. That does not prove the stock is safe — check product aliases.")
        st.caption("Matching runs as SQL in Snowflake against lot-level INVENTORY; Claude never writes SQL.")
        next_step(2)

# ---------- 4: approve + orders ----------
elif step == 3:
    if not case:
        need_case()
    else:
        left, right = st.columns(2)
        with left, st.container(border=True):
            st.markdown("**Holds** " + (pill("Approved", "green") if status == "APPROVED" else
                                        pill("Pending approval", "amber")), unsafe_allow_html=True)
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
                if "t0" in case and not st.session_state.get("t_hold"):
                    st.session_state.t_hold = time.time()
                    query(conn, "INSERT INTO ACTIONS (CASE_ID, ACTION_TYPE, DETAIL) SELECT %(c)s, 'NOTICE_TO_HOLD', "
                                "PARSE_JSON(%(d)s)",
                          {"c": case["id"], "d": json.dumps({"seconds": round(st.session_state.t_hold - case["t0"], 1),
                                                              "units": st.session_state.approve_result.get("units_held")})})
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
            orders = [o for o in orders if o["UPC"] in upc_set] or orders  # this recall's orders first
            for o in orders:
                a, b = st.columns([4, 1])
                tone = {"BLOCKED": "red", "FULFILLED": "green"}.get(o["STATUS"], "grey")
                label = {"BLOCKED": "Blocked — recall hold", "FULFILLED": "Fulfilled"}.get(o["STATUS"], "Pending")
                a.markdown(f"""<div class="ro-order">{o['ORDER_ID']} · lot {html.escape(str(o['LOT_CODE']))} · {o['QUANTITY']} units</div>
<div class="ro-ordersub">{html.escape(o['PRODUCT_NAME'][:50])} · {html.escape(o['LOCATION_NAME'])} → {html.escape(o['DESTINATION'])}</div>
{pill(label, tone)}""", unsafe_allow_html=True)
                if b.button("Try order", key=o["ORDER_ID"]):
                    call("CALL FULFILL_ORDER(%(o)s)", {"o": o["ORDER_ID"]})
                    st.session_state.flash = o["ORDER_ID"]
                    st.rerun()

        if hits:
            st.markdown("**Live recall graph** — order nodes flip the moment Snowflake decides")
            st.graphviz_chart(knowledge_graph(rec, scope, hits, graph_orders, flash=st.session_state.get("flash")),
                              use_container_width=True)
        n1, n2 = st.columns(2)
        with n1:
            st.button("See the shipments stop on the map", on_click=go_step, args=(1,), use_container_width=True)
        with n2:
            next_step(3, "Next: Audit trail →")

# ---------- 5: audit ----------
else:
    render_audit(case)

st.markdown("""<div class="ro-foot"><b>Claude</b> · interpret notice &nbsp;→&nbsp; <b>Snowflake</b> · match records and
store actions &nbsp;→&nbsp; <b>Coordinator</b> · review and approve · Recall notices are real openFDA data; store stock
levels and orders are generated around real recalled UPCs and lots.</div>""", unsafe_allow_html=True)
