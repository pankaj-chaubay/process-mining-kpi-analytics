"""Process discovery and conformance on an event log (case, activity, timestamp, resource).

Written with pandas only, so every step is visible. The same results can be
reproduced in a process mining tool; the definitions are in docs/kpi-definitions.md.
"""

from __future__ import annotations

import pandas as pd

from .eventlog import APPROVAL_LIMIT

HAPPY_PATH = [
    "Create purchase requisition",
    "Create purchase order",
    "Send purchase order",
    "Record goods receipt",
    "Receive invoice",
    "Match invoice",
    "Pay invoice",
]
# goods receipt may also be booked after the invoice is matched, as long as it is before payment
ALLOWED_PATHS = {
    tuple(HAPPY_PATH),
    tuple(HAPPY_PATH[:3] + HAPPY_PATH[4:6] + [HAPPY_PATH[3], HAPPY_PATH[6]]),
}


def variants(log: pd.DataFrame) -> pd.DataFrame:
    v = log.groupby("case_id")["activity"].agg(" > ".join).value_counts().rename_axis("variant").reset_index(name="cases")
    v["share"] = (v["cases"] / v["cases"].sum()).round(3)
    v["cumulative_share"] = v["share"].cumsum().round(3)
    v["steps"] = v["variant"].str.count(">") + 1
    return v


def directly_follows(log: pd.DataFrame) -> pd.DataFrame:
    d = log.sort_values(["case_id", "timestamp"], kind="stable").copy()
    d["next_activity"] = d.groupby("case_id")["activity"].shift(-1)
    d["next_time"] = d.groupby("case_id")["timestamp"].shift(-1)
    d = d.dropna(subset=["next_activity"])
    d["hours"] = (d["next_time"] - d["timestamp"]).dt.total_seconds() / 3600
    g = d.groupby(["activity", "next_activity"]).agg(count=("case_id", "size"), median_hours=("hours", "median"), p90_hours=("hours", lambda s: s.quantile(0.9))).reset_index()
    g[["median_hours", "p90_hours"]] = g[["median_hours", "p90_hours"]].round(1)
    return g.sort_values("count", ascending=False).reset_index(drop=True)


def mermaid_dfg(dfg: pd.DataFrame, min_count: int = 50) -> str:
    """Directly-follows graph as Mermaid, edges labelled with case count and median days."""
    acts = sorted(set(dfg["activity"]) | set(dfg["next_activity"]))
    ids = {a: f"A{i}" for i, a in enumerate(acts)}
    lines = ["flowchart LR"]
    lines += [f'    {ids[a]}["{a}"]' for a in acts]
    for r in dfg[dfg["count"] >= min_count].itertuples(index=False):
        lines.append(f'    {ids[r.activity]} -->|"{r.count} cases, {r.median_hours / 24:.1f} d"| {ids[r.next_activity]}')
    return "\n".join(lines)


def conformance(log: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    """Rule checks per case. Each rule is a control the process owner cares about."""
    first = log.groupby(["case_id", "activity"])["timestamp"].min().unstack()
    out = pd.DataFrame(index=cases["case_id"])
    amt = cases.set_index("case_id")["amount_eur"]
    has = lambda a: first[a].notna() if a in first else pd.Series(False, index=first.index)  # noqa: E731

    out["approval_missing"] = (amt > APPROVAL_LIMIT) & ~has("Approve purchase requisition").reindex(out.index, fill_value=False)
    out["po_after_invoice"] = (first["Create purchase order"] > first["Receive invoice"]).reindex(out.index, fill_value=False)
    pay, gr = first["Pay invoice"], first["Record goods receipt"]
    out["paid_before_goods_receipt"] = (gr.isna() | (pay < gr)).reindex(out.index, fill_value=False)
    out["price_difference_rework"] = has("Resolve price difference").reindex(out.index, fill_value=False)
    out["po_changed_after_sending"] = has("Change purchase order").reindex(out.index, fill_value=False)
    seq = log.groupby("case_id")["activity"].agg(list)
    # approval is checked by its own rule, so it is left out of the path comparison
    out["follows_happy_path"] = seq.map(lambda s: tuple(a for a in s if a != "Approve purchase requisition") in ALLOWED_PATHS).reindex(out.index)
    return out.reset_index().rename(columns={"index": "case_id"})


def conformance_summary(conf: pd.DataFrame) -> pd.DataFrame:
    rows = []
    labels = {
        "approval_missing": ("Compliance", "Requisition above the approval limit without approval"),
        "po_after_invoice": ("Compliance", "Purchase order created after the invoice (order after the fact)"),
        "paid_before_goods_receipt": ("Compliance", "Invoice paid before goods receipt"),
        "price_difference_rework": ("Rework", "Price difference resolved at invoice matching"),
        "po_changed_after_sending": ("Rework", "Purchase order changed after sending"),
    }
    for col, (kind, text) in labels.items():
        rows.append({"type": kind, "check": text, "cases": int(conf[col].sum()), "share": round(float(conf[col].mean()), 3)})
    clean = ~conf[list(labels)].any(axis=1)
    rows.append({"type": "Overall", "check": "Cases with none of the above", "cases": int(clean.sum()), "share": round(float(clean.mean()), 3)})
    return pd.DataFrame(rows)


def bottlenecks(dfg: pd.DataFrame, top: int = 8) -> pd.DataFrame:
    """Transitions that hold the most total waiting time (count x median)."""
    d = dfg.copy()
    d["total_days"] = (d["count"] * d["median_hours"] / 24).round(0).astype(int)
    d = d.sort_values("total_days", ascending=False).head(top)
    d["median_days"] = (d["median_hours"] / 24).round(1)
    return d[["activity", "next_activity", "count", "median_days", "total_days"]].reset_index(drop=True)
