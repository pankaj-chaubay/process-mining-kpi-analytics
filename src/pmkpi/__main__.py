"""python -m pmkpi  ->  data/, powerbi/, reports/results.md"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import eventlog, kpis, mining  # noqa: E402

BLUE, GREY, INK, INK2, SURFACE = "#2a78d6", "#b9b8b2", "#0b0b0b", "#52514e", "#fcfcfb"


def md(df: pd.DataFrame) -> str:
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(map(str, r)) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def vendor_chart(by_vendor: pd.DataFrame, path: Path) -> None:
    d = by_vendor.sort_values("on_time_payment_rate")
    fig, ax = plt.subplots(figsize=(7, 3.0), facecolor=SURFACE)
    colors = [BLUE if v < 0.7 else GREY for v in d["on_time_payment_rate"]]
    ax.barh(d["vendor"], d["on_time_payment_rate"] * 100, color=colors, height=0.6)
    for y, v in enumerate(d["on_time_payment_rate"]):
        ax.text(v * 100 + 1, y, f"{v:.0%}", va="center", fontsize=9, color=INK)
    ax.set_xlim(0, 105)
    ax.set_xlabel("Invoices paid by the due date (%)", color=INK2, fontsize=9)
    ax.set_title("On-time payment by vendor", loc="left", fontsize=11, color=INK)
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=INK2, labelsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="pmkpi")
    p.add_argument("--data", default="data")
    p.add_argument("--out", default="reports")
    p.add_argument("--powerbi", default="powerbi")
    a = p.parse_args(argv)
    dd, out, pbi = Path(a.data), Path(a.out), Path(a.powerbi)
    for d in (dd, out / "figures", pbi):
        d.mkdir(parents=True, exist_ok=True)

    log, cases = eventlog.generate()
    log.to_csv(dd / "p2p_event_log.csv", index=False)
    cases.to_csv(dd / "p2p_cases.csv", index=False)

    var = mining.variants(log)
    dfg = mining.directly_follows(log)
    conf = mining.conformance(log, cases)
    conf_sum = mining.conformance_summary(conf)
    bott = mining.bottlenecks(dfg)
    k = kpis.run(log, cases)
    cm = k["case_metrics"].merge(conf, on="case_id")

    drivers = []
    for col, label in [("price_difference_rework", "Price difference at matching"), ("po_after_invoice", "Order after the invoice"), ("po_changed_after_sending", "Order changed after sending")]:
        g = cm.groupby(col)["paid_on_time"].mean()
        drivers.append({"case attribute": label, "on time with it": round(float(g.get(True, 0)), 3), "on time without it": round(float(g.get(False, 0)), 3), "cases": int(cm[col].sum())})
    drivers = pd.DataFrame(drivers)

    # Power BI / star schema export
    k["case_metrics"].to_csv(pbi / "fact_case.csv", index=False)
    log.assign(event_id=range(1, len(log) + 1)).to_csv(pbi / "fact_event.csv", index=False)
    pd.DataFrame({"activity": mining.HAPPY_PATH + ["Approve purchase requisition", "Change purchase order", "Resolve price difference"],
                  "happy_path_order": list(range(1, 8)) + [None] * 3,
                  "is_rework": [False] * 8 + [True, True]}).to_csv(pbi / "dim_activity.csv", index=False)
    conf.to_csv(pbi / "fact_conformance.csv", index=False)

    vendor_chart(k["kpi_by_vendor"], out / "figures" / "on_time_by_vendor.png")
    (out / "dfg.mmd").write_text(mining.mermaid_dfg(dfg), encoding="utf-8")
    overview = k["kpi_overview"].iloc[0].to_dict()
    (out / "summary.json").write_text(json.dumps({k2: (float(v) if not isinstance(v, int) else v) for k2, v in overview.items()}, indent=2), encoding="utf-8")

    rep = [
        "# Process mining results: purchase to pay",
        "",
        f"{len(cases):,} cases, {len(log):,} events, generated data for 2025. Produced by `python -m pmkpi`.",
        "",
        "## KPI overview (SQL)",
        "",
        md(k["kpi_overview"].T.reset_index().rename(columns={"index": "kpi", 0: "value"})),
        "",
        "## Variants",
        "",
        f"{len(var)} variants. The top 5 cover {var['cumulative_share'].iloc[4]:.0%} of cases.",
        "",
        md(var.head(10)[["cases", "share", "cumulative_share", "steps", "variant"]]),
        "",
        "## Directly-follows graph (transitions with at least 50 cases)",
        "",
        "```mermaid",
        mining.mermaid_dfg(dfg),
        "```",
        "",
        "## Conformance",
        "",
        md(conf_sum),
        "",
        f"Cases that follow the designed path exactly (approval aside): {conf['follows_happy_path'].mean():.0%}.",
        "",
        "## Where the time goes",
        "",
        md(bott),
        "",
        "## By vendor (SQL)",
        "",
        md(k["kpi_by_vendor"]),
        "",
        "![on-time payment by vendor](figures/on_time_by_vendor.png)",
        "",
        "## What goes with late payment",
        "",
        md(drivers),
        "",
        md(k["late_payment_drivers"]),
        "",
    ]
    (out / "results.md").write_text("\n".join(rep), encoding="utf-8")
    print(k["kpi_overview"].T.to_string())
    print(drivers.to_string(index=False))


if __name__ == "__main__":
    main()
