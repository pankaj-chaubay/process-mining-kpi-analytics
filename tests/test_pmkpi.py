import pandas as pd
import pytest

from pmkpi import eventlog, kpis, mining
from pmkpi.__main__ import main


@pytest.fixture(scope="module")
def data():
    return eventlog.generate(n_cases=600, seed=9)


def test_log_is_ordered_and_complete(data):
    log, cases = data
    assert log["case_id"].nunique() == len(cases)
    assert (log.groupby("case_id")["timestamp"].apply(lambda s: s.is_monotonic_increasing)).all()
    assert (log.groupby("case_id")["activity"].apply(lambda s: "Pay invoice" in set(s))).all()


def test_variants_cover_all_cases(data):
    log, _ = data
    v = mining.variants(log)
    assert v["cases"].sum() == log["case_id"].nunique()
    assert v["cumulative_share"].iloc[-1] == pytest.approx(1.0, abs=0.01)


def test_dfg_counts_match_log(data):
    log, _ = data
    d = mining.directly_follows(log)
    assert d["count"].sum() == len(log) - log["case_id"].nunique()


def test_conformance_on_handmade_cases():
    t = pd.Timestamp("2025-03-01")
    rows = []
    def case(cid, acts):
        for i, a in enumerate(acts):
            rows.append((cid, a, t + pd.Timedelta(days=i), "x"))
    hp = mining.HAPPY_PATH
    case("ok", hp)
    case("late_po", ["Receive invoice", "Create purchase requisition", "Create purchase order", "Record goods receipt", "Match invoice", "Pay invoice"])
    case("no_gr", ["Create purchase requisition", "Create purchase order", "Send purchase order", "Receive invoice", "Match invoice", "Pay invoice"])
    case("big", hp)
    log = pd.DataFrame(rows, columns=["case_id", "activity", "timestamp", "resource"])
    cases = pd.DataFrame({"case_id": ["ok", "late_po", "no_gr", "big"], "amount_eur": [100, 100, 100, 9000]})
    c = mining.conformance(log, cases).set_index("case_id")
    assert c.loc["ok"].drop("follows_happy_path").sum() == 0 and c.loc["ok", "follows_happy_path"]
    assert c.loc["late_po", "po_after_invoice"]
    assert c.loc["no_gr", "paid_before_goods_receipt"]
    assert c.loc["big", "approval_missing"]


def test_planted_rates_are_recovered(data):
    log, cases = data
    s = mining.conformance_summary(mining.conformance(log, cases)).set_index("check")["share"]
    assert s["Price difference resolved at invoice matching"] == pytest.approx(eventlog.RATES["price_diff"], abs=0.04)
    assert s["Purchase order created after the invoice (order after the fact)"] == pytest.approx(eventlog.RATES["po_after_invoice"], abs=0.03)


def test_sql_matches_pandas(data):
    log, cases = data
    k = kpis.run(log, cases)
    cm = k["case_metrics"]
    span = log.groupby("case_id")["timestamp"].agg(lambda s: (s.max() - s.min()).total_seconds() / 86400)
    merged = cm.set_index("case_id")["throughput_days"]
    assert (merged - span.reindex(merged.index)).abs().max() < 1 / 24 + 1e-9  # SQL counts whole hours
    pay = log[log.activity == "Pay invoice"].groupby("case_id")["timestamp"].min()
    on_time = (pay <= cases.set_index("case_id")["due_date"]).mean()
    assert k["kpi_overview"].loc[0, "on_time_payment_rate"] == pytest.approx(on_time, abs=0.001)


def test_sql_blocks_are_named():
    names = kpis.blocks(kpis.SQL_FILE.read_text())
    assert {"case_metrics", "kpi_overview", "kpi_by_vendor"} <= names.keys()


def test_mermaid_output(data):
    log, _ = data
    m = mining.mermaid_dfg(mining.directly_follows(log), min_count=10)
    assert m.startswith("flowchart LR") and "-->" in m


def test_cli(tmp_path):
    main(["--data", str(tmp_path / "d"), "--out", str(tmp_path / "r"), "--powerbi", str(tmp_path / "p")])
    assert (tmp_path / "p" / "fact_case.csv").exists()
    assert "Conformance" in (tmp_path / "r" / "results.md").read_text()
