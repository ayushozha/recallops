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
from load_data import lots as source_lots  # noqa: E402

CANDIDATE_MODELS = list(dict.fromkeys([
    "claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-sonnet-5",
    "claude-opus-4-8", "claude-opus-4-7", MODEL, "claude-opus-4-6", "claude-sonnet-4-6",
    "claude-sonnet-4-5", "claude-opus-4-5", "claude-4-sonnet", "claude-haiku-4-5",
    "claude-3-7-sonnet",
]))
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (" - " + str(detail) if detail else ""))
    if not ok:
        raise AssertionError(name)


def as_obj(v):
    return json.loads(v) if isinstance(v, str) else v


def select_fixture(conn, recall_number=None):
    """Pick a recall with pending affected/control orders from the generated fixtures."""
    recalls = query(conn, """SELECT DISTINCT r.* FROM FDA_RECALLS r
        JOIN INVENTORY i ON i.SOURCE_RECALL_NUMBER = r.RECALL_NUMBER
        JOIN ORDERS o ON o.INVENTORY_ID = i.INVENTORY_ID
        WHERE o.STATUS = 'PENDING' AND i.LOT_CODE IS NOT NULL
          AND (%(r)s IS NULL OR r.RECALL_NUMBER = %(r)s)
        ORDER BY r.RECALL_NUMBER""", {"r": recall_number})
    for rec in recalls:
        expected_lots = set(source_lots(rec["CODE_INFO"]))
        if not expected_lots:
            continue
        orders = query(conn, """SELECT o.ORDER_ID, o.STATUS, o.UPDATED_AT, i.UPC, i.LOT_CODE
            FROM ORDERS o JOIN INVENTORY i ON i.INVENTORY_ID = o.INVENTORY_ID
            WHERE i.SOURCE_RECALL_NUMBER = %(r)s AND o.STATUS = 'PENDING'
              AND i.LOT_CODE IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM HOLDS h WHERE h.INVENTORY_ID = i.INVENTORY_ID)
            ORDER BY o.ORDER_ID""", {"r": rec["RECALL_NUMBER"]})
        for affected in orders:
            if affected["LOT_CODE"].upper() not in expected_lots:
                continue
            controls = [o for o in orders if o["UPC"] == affected["UPC"]
                        and o["LOT_CODE"].upper() not in expected_lots]
            if controls:
                return rec, affected, controls[0], expected_lots
    raise RuntimeError("No recall has both an unheld affected and control-lot pending order")


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
    # 2. A real recall with both affected and control orders, based on loader fixture labels.
    rec, affected_order, control_order, expected_lots = select_fixture(conn, a.recall)
    rid = rec["RECALL_NUMBER"]
    print("\nNotice:\n" + notice_from_recall(rec) + "\n")

    t0 = time.time()
    out = interpret(conn, notice_from_recall(rec), model)
    secs = time.time() - t0
    print("Claude scope (%.1fs):" % secs, json.dumps(out, indent=1))
    upcs = sorted({re.sub(r"\D", "", u) for u in out.get("upcs", []) if re.sub(r"\D", "", u)})
    lots = sorted({l.strip().upper() for l in out.get("lot_codes", []) if l.strip()})

    check("Claude returned explicit UPC and lot scope", bool(upcs and lots))
    check("Claude found the recalled UPC", affected_order["UPC"] in upcs, upcs)
    check("Claude includes the affected fixture lot", affected_order["LOT_CODE"].upper() in lots, lots)
    check("Claude excludes the control fixture lot", control_order["LOT_CODE"].upper() not in lots)
    check("Claude lot scope matches the labelled fixture", set(lots) == expected_lots,
          "%s vs %s" % (lots, sorted(expected_lots)))

    # 3. Save case + approve holds via the stored procedure
    case_id = "VERIFY-" + uuid.uuid4().hex[:6].upper()
    scope = {"upcs": upcs, "lot_codes": lots}
    touched_orders = []
    try:
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
        check("No NULL-lot rows silently held", bool(held) and all(h["LOT_CODE"] for h in held))
        controls = query(conn, """SELECT COUNT(*) N FROM INVENTORY i JOIN HOLDS h ON h.INVENTORY_ID = i.INVENTORY_ID
                                  WHERE h.CASE_ID = %(c)s AND i.SOURCE_RECALL_NUMBER = %(r)s
                                  AND NOT ARRAY_CONTAINS(UPPER(i.LOT_CODE)::VARIANT, PARSE_JSON(%(l)s))""",
                           {"c": case_id, "r": rid, "l": json.dumps(lots)})[0]["N"]
        check("Control lots stay unheld", controls == 0, controls)

        # 4. Exercise exactly one affected and one control order, never NULL-lot stock.
        for o, expected in [(affected_order, "BLOCKED"), (control_order, "FULFILLED")]:
            held_count = query(conn, """SELECT COUNT(*) N FROM HOLDS h
                JOIN ORDERS o ON o.INVENTORY_ID = h.INVENTORY_ID
                WHERE h.CASE_ID = %(c)s AND o.ORDER_ID = %(o)s""",
                {"c": case_id, "o": o["ORDER_ID"]})[0]["N"]
            check("Order %s has expected hold" % o["ORDER_ID"],
                  held_count > 0 if expected == "BLOCKED" else held_count == 0, held_count)
            touched_orders.append(o)
            res = as_obj(list(query(conn, "CALL FULFILL_ORDER(%(o)s)", {"o": o["ORDER_ID"]})[0].values())[0])
            check("Order %s %s" % (o["ORDER_ID"], expected), res["result"] == expected, res)
        n = query(conn, "SELECT COUNT(*) N FROM ACTIONS WHERE CASE_ID = %(c)s", {"c": case_id})[0]["N"]
        check("Actions audited", n >= 3, n)
    finally:
        # Release only this verification's holds and restore only orders it attempted.
        try:
            query(conn, "DELETE FROM HOLDS WHERE CASE_ID = %(c)s", {"c": case_id})
        finally:
            try:
                for o in touched_orders:
                    query(conn, "UPDATE ORDERS SET STATUS = %(s)s, UPDATED_AT = %(t)s WHERE ORDER_ID = %(o)s",
                          {"s": o["STATUS"], "t": o["UPDATED_AT"], "o": o["ORDER_ID"]})
            finally:
                conn.close()
    print("\n%d/%d checks passed · case %s · Claude %.1fs · model %s" % (sum(results), len(results), case_id, secs, model))


if __name__ == "__main__":
    main()
