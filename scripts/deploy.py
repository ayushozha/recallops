"""Deploy the four app files to Streamlit in Snowflake using the existing .env.

Usage: .venv/bin/python scripts/deploy.py [--warehouse DEFAULT_WH] [--dry-run]
SQL reference: https://docs.snowflake.com/en/developer-guide/streamlit/app-development/creating-your-app
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
from db import connect, query  # noqa: E402

FILES = ("streamlit_app.py", "db.py", "recall.py", "environment.yml")
STAGE = "@RECALLOPS.APP.APP_STAGE/app"
APP = "RECALLOPS.APP.RECALLOPS_APP"


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", default=os.getenv("SNOWFLAKE_WAREHOUSE") or "DEFAULT_WH")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    warehouse = '"' + args.warehouse.replace('"', '""') + '"'
    paths = [ROOT / "app" / name for name in FILES]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.dry_run:
        print("No connection or writes. App:", APP, "warehouse:", args.warehouse)
        print("Files:", ", ".join(FILES))
        return

    conn = connect()
    try:
        query(conn, "CREATE STAGE IF NOT EXISTS RECALLOPS.APP.APP_STAGE DIRECTORY = (ENABLE = TRUE)")
        for path in paths:
            uri = "file://" + path.as_posix()
            rows = query(conn, f"PUT {literal(uri)} {STAGE} AUTO_COMPRESS = FALSE OVERWRITE = TRUE")
            statuses = [str(row.get("status", row.get("STATUS", ""))).upper() for row in rows]
            if not statuses or any(status not in ("UPLOADED", "SKIPPED") for status in statuses):
                raise RuntimeError("Upload failed for %s: %s" % (path.name, statuses))
            print("Staged", path.name, ", ".join(statuses))
        query(conn, f"""CREATE OR REPLACE STREAMLIT {APP}
            FROM '{STAGE}' MAIN_FILE = 'streamlit_app.py'
            QUERY_WAREHOUSE = {warehouse} TITLE = 'RecallOps'""")
        query(conn, f"ALTER STREAMLIT {APP} ADD LIVE VERSION FROM LAST")
        rows = query(conn, "SHOW STREAMLITS LIKE 'RECALLOPS_APP' IN SCHEMA RECALLOPS.APP")
        app = next(row for row in rows if row.get("name", row.get("NAME")) == "RECALLOPS_APP")
        print("Created and published:", APP)
        print("URL ID:", app.get("url_id", app.get("URL_ID")))
        print("Open Snowsight > Projects > Streamlit > RecallOps.")
        print("Deployment does not confirm that the app runs; open it and verify the workflow.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
