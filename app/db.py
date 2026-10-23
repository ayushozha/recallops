"""Snowflake connection shared by the app and scripts. Reads credentials from .env."""
import os
from pathlib import Path

import snowflake.connector
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = os.getenv("RECALLOPS_MODEL", "claude-sonnet-4-5")


def connect():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],  # a programmatic access token works here
        role=os.getenv("SNOWFLAKE_ROLE") or None,
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE") or None,
        database="RECALLOPS",
        schema="APP",
        session_parameters={"QUERY_TAG": "recallops"},
    )


def query(conn, sql, params=None):
    cur = conn.cursor(snowflake.connector.DictCursor)
    cur.execute(sql, params or {})
    return cur.fetchall()
