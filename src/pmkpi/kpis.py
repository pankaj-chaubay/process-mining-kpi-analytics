"""Run the SQL in sql/kpis.sql on DuckDB."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

SQL_FILE = Path(__file__).resolve().parents[2] / "sql" / "kpis.sql"


def blocks(sql: str) -> dict[str, str]:
    parts = re.split(r"^-- name: (\w+)\s*$", sql, flags=re.M)
    return {parts[i]: parts[i + 1].strip().rstrip(";") for i in range(1, len(parts), 2)}


def run(log: pd.DataFrame, cases: pd.DataFrame, sql_file: Path = SQL_FILE) -> dict[str, pd.DataFrame]:
    con = duckdb.connect()
    events = log.rename(columns={"timestamp": "ts"})
    con.register("events_df", events)
    con.register("cases_df", cases)
    con.execute("CREATE TABLE events AS SELECT * FROM events_df")
    con.execute("CREATE TABLE cases AS SELECT * FROM cases_df")
    out = {}
    for name, q in blocks(sql_file.read_text(encoding="utf-8")).items():
        if q.upper().startswith("CREATE"):
            con.execute(q)
        else:
            out[name] = con.execute(q).df()
    out["case_metrics"] = con.execute("SELECT * FROM case_metrics ORDER BY case_id").df()
    con.close()
    return out
