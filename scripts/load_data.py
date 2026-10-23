"""Load real openFDA food recalls + build demo inventory/orders for RecallOps.

Usage: .venv/bin/python scripts/load_data.py [--dry-run] [--skip-setup] [--keep-cases]
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

FDA_URL = ("https://api.fda.gov/food/enforcement.json?search=report_date:[20250101+TO+20261231]"
           "&sort=report_date:desc&limit={limit}&skip={skip}")
FIELDS = ["recall_number", "event_id", "recalling_firm", "product_description", "code_info",
          "reason_for_recall", "classification", "distribution_pattern", "status", "report_date"]
UPC_RE = re.compile(r"UPC[^0-9A-Za-z]{0,6}((?:\d[\s\-]?){10,14}\d)", re.I)
LOT_RE = re.compile(r"\blot(?:\s*(?:code|number|no\.?|#|codes|numbers|s))*\s*[:#.]?", re.I)
END_RE = re.compile(r"(?i)\b(?:exp|best|use|sell|upc|with|packed|date|mfg|manuf|produc|sold|on|in)\w*|[;()]|\.\s|\n|\s{3,}")
TOKEN_RE = re.compile(r"[A-Z0-9][A-Z0-9\-]{2,15}")
STOP = {"CODE", "CODES", "NUMBER", "NUMBERS", "AND", "EXP", "EXPIRATION", "BEST", "DATE", "USE",
        "BY", "SELL", "UPC", "ALL", "THE", "WITH", "FOR", "NO", "LOT", "LOTS", "PACK", "SIZE"}
STORES = ["Oakland", "San Jose", "Fresno", "Sacramento", "Los Angeles"]


def fetch(total=2000):
    out = []
    for skip in range(0, total, 1000):
        r = requests.get(FDA_URL.format(limit=1000, skip=skip), timeout=60)
        r.raise_for_status()
        res = r.json().get("results", [])
        out.extend(res)
        if len(res) < 1000:
            break
    return out


def upcs(desc):
    found = []
    for m in UPC_RE.finditer(desc or ""):
        d = re.sub(r"[\s\-]", "", m.group(1))
        if 11 <= len(d) <= 14 and d not in found:
            found.append(d)
    return found


def lots(code_info):
    found = []
    text = code_info or ""
    for m in LOT_RE.finditer(text):
        seg = text[m.end():m.end() + 120]
        e = END_RE.search(seg)
        for t in TOKEN_RE.findall((seg[:e.start()] if e else seg).upper()):
            t = t.strip("-")
            if t in STOP or len(t) < 3 or not re.search(r"\d", t) or re.fullmatch(r"\d{11,14}|(?:19|20)\d\d", t):
                continue
            if t not in found:
                found.append(t)
    return found


def short_name(desc):
    return re.split(r"\.\s|[,;]", desc.strip(), 1)[0][:60].strip()


def mutate(lot, recalled):
    for ch in "9876543210XYZ":
        cand = lot[:-1] + ch
        if cand != lot and cand not in recalled:
            return cand
    return lot + "X"


def build(records):
    rng = random.Random(42)
    locs = [("WH-1", "Central Warehouse", "WAREHOUSE", "CA")] + \
           [("ST-%d" % (i + 1), "Store %d - %s" % (i + 1, c), "STORE", "CA") for i, c in enumerate(STORES)]
    loc_ids = [l[0] for l in locs]
    chosen, firms = [], set()
    for r in records:  # already sorted by report_date desc
        u, l = upcs(r.get("product_description")), lots(r.get("code_info"))
        firm = r.get("recalling_firm", "")
        if u and l and firm not in firms:
            chosen.append((r, u[0], l))
            firms.add(firm)
        if len(chosen) >= 12:
            break
    inv, n = [], 0

    def add(loc, rec, upc, lot, qty):
        nonlocal n
        n += 1
        inv.append(("INV-%04d" % n, loc, upc, short_name(rec["product_description"]),
                    rec.get("recalling_firm"), lot, qty, rec["recall_number"]))
        return inv[-1]

    recalled_rows, control_rows = [], []
    for i, (rec, upc, lotl) in enumerate(chosen):
        for loc in rng.sample(loc_ids, rng.randint(2, 3)):
            recalled_rows.append(add(loc, rec, upc, rng.choice(lotl[:3]), rng.randint(6, 120)))
        for _ in range(rng.randint(1, 2)):
            ctrl = mutate(rng.choice(lotl[:3]), set(lotl))
            assert ctrl not in lotl
            control_rows.append(add(rng.choice(loc_ids), rec, upc, ctrl, rng.randint(6, 120)))
        if i < 3:
            add(rng.choice(loc_ids), rec, upc, None, rng.randint(6, 120))
    orders = []
    picks = rng.sample(recalled_rows, 6) + rng.sample(control_rows, 4)
    rng.shuffle(picks)
    dests = ["Store %d - %s" % (i + 1, c) for i, c in enumerate(STORES)] + ["Customer pickup"]
    for k, row in enumerate(picks):
        orders.append(("O-%d" % (101 + k), row[0], rng.randint(1, row[6]), rng.choice(dests), "PENDING"))
    return chosen, locs, inv, orders


def insert(cur, table, cols, rows, select=None, batch=200):
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        ph = ",".join(["(" + ",".join(["%s"] * len(cols)) + ")"] * len(chunk))
        sel = select or ", ".join("column%d" % (j + 1) for j in range(len(cols)))
        cur.execute("INSERT INTO %s (%s) SELECT %s FROM VALUES %s" % (table, ", ".join(cols), sel, ph),
                    [v for row in chunk for v in row])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-setup", action="store_true")
    ap.add_argument("--keep-cases", action="store_true")
    a = ap.parse_args()
    records = fetch()
    fda_rows = [tuple((r.get(f) or None) for f in FIELDS) + (json.dumps(r),) for r in records]
    chosen, locs, inv, orders = build(records)
    counts = {"FDA_RECALLS": len(fda_rows), "LOCATIONS": len(locs), "INVENTORY": len(inv), "ORDERS": len(orders)}
    if a.dry_run:
        print("DRY RUN - nothing written. Sample FDA row:", fda_rows[0][:3] if fda_rows else None)
        for row in inv:
            print("  INV", row)
        for o in orders:
            print("  ORD", o)
    else:
        from db import connect
        conn = connect()
        if not a.skip_setup:
            conn.execute_string((ROOT / "sql" / "01_setup.sql").read_text())
        cur = conn.cursor()
        cur.execute("USE SCHEMA RECALLOPS.APP")
        tables = ["FDA_RECALLS", "LOCATIONS", "INVENTORY", "ORDERS"]
        if not a.keep_cases:
            tables += ["HOLDS", "RECALL_CASES", "ACTIONS"]
        for t in tables:
            cur.execute("TRUNCATE TABLE IF EXISTS " + t)
        fda_sel = ", ".join("column%d" % i for i in range(1, 10)) + \
            ", TO_DATE(column10, 'YYYYMMDD'), PARSE_JSON(column11)"
        insert(cur, "FDA_RECALLS", [f.upper() for f in FIELDS] + ["RAW"], fda_rows, fda_sel)
        insert(cur, "LOCATIONS", ["LOCATION_ID", "LOCATION_NAME", "LOCATION_TYPE", "STATE"], locs)
        insert(cur, "INVENTORY", ["INVENTORY_ID", "LOCATION_ID", "UPC", "PRODUCT_NAME", "FIRM", "LOT_CODE",
                                  "QUANTITY", "SOURCE_RECALL_NUMBER"], inv,
               "column1, column2, column3, column4, column5, column6::STRING, column7::NUMBER, column8")
        insert(cur, "ORDERS", ["ORDER_ID", "INVENTORY_ID", "QUANTITY", "DESTINATION", "STATUS"], orders)
        for t in tables:
            counts[t] = cur.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
        conn.close()
    print("\nRow counts:", counts)
    print("\nRecalls that hit our inventory (%d):" % len(chosen))
    for rec, upc, lotl in chosen:
        print("  %s  %s  UPC %s  lots %s  | %s" % (rec["recall_number"], rec.get("report_date"), upc,
                                                   ",".join(lotl), short_name(rec["product_description"])[:45]))


if __name__ == "__main__":
    main()
