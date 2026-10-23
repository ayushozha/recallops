"""End-to-end check against live Snowflake: real FDA notice -> Claude scope -> holds -> order enforcement.

Usage: .venv/bin/python scripts/verify.py [--model claude-...] [--recall H-1397-2026]
"""
import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from db import MODEL, connect, query  # noqa: E402
from recall import interpret, notice_from_recall  # noqa: E402

CANDIDATE_MODELS = [MODEL, "claude-opus-4-6", "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-opus-4-5",
                    "claude-4-sonnet", "claude-haiku-4-5", "claude-3-7-sonnet"]
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (" - " + str(detail) if detail else ""))


def as_obj(v):
    return json.loads(v) if isinstance(v, str) else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--recall")
    a = ap.parse_args()
    conn = connect()
    who = query(conn, "SELECT CURRENT_USER() U, CURRENT_ROLE() R, CURRENT_REGION() G")[0]
    print("Connected:", who)

    # 1. Which Claude model answers in this account?
    model = a.model
    for m in ([model] if model else CANDIDATE_MODELS):
        try:
            query(conn, "SELECT AI_COMPLETE(%(m)s, 'Reply with OK') AS R", {"m": m})
            model = m
            break
        except Exception as e:  # model not available in region / not enabled
            print("  model", m, "unavailable:", str(e).splitlines()[0][:120])
            model = None
    check("Claude reachable via AI_COMPLETE", model is not None, model)
    if not model:
        return

    # 2. A real recall that hits inventory
    rid = a.recall or query(conn, """SELECT SOURCE_RECALL_NUMBER R FROM INVENTORY WHERE LOT_CODE IS NOT NULL
                                     GROUP BY 1 ORDER BY COUNT(*) DESC, 1 LIMIT 1""")[0]["R"]
    rec = query(conn, "SELECT * FROM FDA_RECALLS WHERE RECALL_NUMBER = %(r)s", {"r": rid})[0]
    print("\nNotice:\n" + notice_from_recall(rec) + "\n")

    t0 = time.time()
    out = interpret(conn, notice_from_recall(rec), model)
    secs = time.time() - t0
    print("Claude scope (%.1fs):" % secs, json.dumps(out, indent=1))
    upcs = sorted({re.sub(r"\D", "", u) for u in out.get("upcs", []) if re.sub(r"\D", "", u)})
    lots = sorted({l.strip().upper() for l in out.get("lot_codes", []) if l.strip()})

    truth = query(conn, "SELECT DISTINCT UPC, UPPER(LOT_CODE) L FROM INVENTORY WHERE SOURCE_RECALL_NUMBER = %(r)s",
                  {"r": rid})
    true_upc = {t["UPC"] for t in truth}
    check("Claude found the recalled UPC", bool(true_upc & set(upcs)), "%s vs %s" % (upcs, sorted(true_upc)))

    # 3. Save case + approve holds via the stored procedure
    case_id = "VERIFY-" + uuid.uuid4().hex[:6].upper()
    scope = {"upcs": upcs, "lot_codes": lots}
    query(conn, """INSERT INTO RECALL_CASES (CASE_ID, RECALL_NUMBER, NOTICE_TEXT, MODEL, MODEL_OUTPUT, REVIEWED_SCOPE, STATUS)
                   SELECT %(c)s, %(r)s, %(n)s, %(m)s, PARSE_JSON(%(o)s), PARSE_JSON(%(s)s), 'PROPOSED'""",
          {"c": case_id, "r": rid, "n": notice_from_recall(rec), "m": model, "o": json.dumps(out),
           "s": json.dumps(scope)})
    r1 = as_obj(list(query(conn, "CALL APPROVE_HOLDS(%(c)s)", {"c": case_id})[0].values())[0])
    check("APPROVE_HOLDS placed holds", r1["new_holds"] > 0, r1)
    r2 = as_obj(list(query(conn, "CALL APPROVE_HOLDS(%(c)s)", {"c": case_id})[0].values())[0])
    check("Re-approval is idempotent", r2["new_holds"] == 0 and r2["total_holds"] == r1["total_holds"], r2)

    held = query(conn, """SELECT i.UPC, i.LOT_CODE FROM HOLDS h JOIN INVENTORY i ON i.INVENTORY_ID = h.INVENTORY_ID
                          WHERE h.CASE_ID = %(c)s""", {"c": case_id})
    check("No NULL-lot rows silently held", all(h["LOT_CODE"] for h in held) or not lots)
    controls = query(conn, """SELECT COUNT(*) N FROM INVENTORY i JOIN HOLDS h ON h.INVENTORY_ID = i.INVENTORY_ID
                              WHERE h.CASE_ID = %(c)s AND i.SOURCE_RECALL_NUMBER = %(r)s
                              AND NOT ARRAY_CONTAINS(UPPER(i.LOT_CODE)::VARIANT, PARSE_JSON(%(l)s))""",
                       {"c": case_id, "r": rid, "l": json.dumps(lots)})[0]["N"]
    check("Control lots stay unheld", controls == 0 or not lots, controls)

    # 4. Order enforcement on held vs unheld stock of the same product
    orders = query(conn, """SELECT o.ORDER_ID, IFF(h.INVENTORY_ID IS NULL, 0, 1) HELD FROM ORDERS o
                            LEFT JOIN (SELECT DISTINCT INVENTORY_ID FROM HOLDS WHERE CASE_ID = %(c)s) h
                              ON h.INVENTORY_ID = o.INVENTORY_ID ORDER BY HELD DESC""", {"c": case_id})
    for o in orders:
        res = as_obj(list(query(conn, "CALL FULFILL_ORDER(%(o)s)", {"o": o["ORDER_ID"]})[0].values())[0])
        if o["HELD"]:
            check("Held order %s blocked" % o["ORDER_ID"], res["result"] == "BLOCKED", res)
    n = query(conn, "SELECT COUNT(*) N FROM ACTIONS WHERE CASE_ID = %(c)s", {"c": case_id})[0]["N"]
    check("Actions audited", n >= 2, n)

    # release the test holds and reset orders so the live demo starts clean (cases + actions stay as audit)
    query(conn, "DELETE FROM HOLDS WHERE CASE_ID = %(c)s", {"c": case_id})
    query(conn, "UPDATE ORDERS SET STATUS = 'PENDING', UPDATED_AT = NULL")
    print("\n%d/%d checks passed · case %s · Claude %.1fs · model %s" % (sum(results), len(results), case_id, secs, model))


if __name__ == "__main__":
    main()
