"""Snowflake connection shared by the app and scripts. Reads credentials from .env."""
import os
from pathlib import Path

import snowflake.connector
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # Streamlit in Snowflake has no .env
    pass

MODEL = os.getenv("RECALLOPS_MODEL", "claude-opus-5-5")


def connect(*, select_schema=True):
    if not os.getenv("SNOWFLAKE_ACCOUNT"):
        # The hosted app already has its RECALLOPS.APP context; owner rights forbid USE.
        from snowflake.snowpark.context import get_active_session

        conn = get_active_session().connection
        return conn
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],  # a programmatic access token works here
        role=os.getenv("SNOWFLAKE_ROLE") or None,
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE") or None,
        **({"database": "RECALLOPS", "schema": "APP"} if select_schema else {}),
        session_parameters={"QUERY_TAG": "recallops"},
    )


def query(conn, sql, params=None):
    cur = conn.cursor(snowflake.connector.DictCursor)
    cur.execute(sql, params or {})
    return cur.fetchall()
