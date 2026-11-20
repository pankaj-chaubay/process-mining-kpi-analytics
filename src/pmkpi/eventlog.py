"""Generated purchase-to-pay event log for a fictional company.

One case = one purchase requisition line. Each event has case, activity,
timestamp and resource ("system" for automated steps). Deviations are planted
at known rates so the mining results can be checked:

* approval skipped although the amount is above the limit
* purchase order created after the invoice arrived (order after the fact)
* invoice paid before goods receipt
* price difference at invoice matching, resolved by procurement (rework)
* purchase order changed after it was sent (rework)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

APPROVAL_LIMIT = 5000
VENDORS = {"V01 Turbine parts": 1.0, "V02 Cables": 1.0, "V03 Office supplies": 0.6, "V04 Engineering services": 1.4, "V05 IT hardware": 0.9}
COMPANIES = {"DE01": 1.0, "ES01": 1.25}
RATES = {"skip_approval": 0.04, "po_after_invoice": 0.05, "pay_before_gr": 0.03, "price_diff": 0.14, "po_change": 0.10}


def _hours(rng, mean_h: float) -> pd.Timedelta:
    return pd.Timedelta(hours=float(rng.gamma(2.0, mean_h / 2.0)))


def generate(n_cases: int = 2500, seed: int = 5, start: str = "2025-01-01") -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    events, cases = [], []
    t0 = pd.Timestamp(start)
    for i in range(n_cases):
        cid = f"PR{i + 1:05d}"
        vendor = rng.choice(list(VENDORS))
        company = rng.choice(list(COMPANIES), p=[0.65, 0.35])
        amount = float(np.round(rng.lognormal(7.8, 1.0), 2))
        slow = VENDORS[vendor] * COMPANIES[company]
        flags = {k: rng.random() < v for k, v in RATES.items()}
        if flags["po_after_invoice"]:
            flags["skip_approval"] = False
        t = t0 + pd.Timedelta(days=float(rng.uniform(0, 330)))
        ev = []

        def add(act, when, res):
            ev.append((cid, act, when, res))

        if flags["po_after_invoice"]:
            # goods ordered informally, paperwork afterwards
            t_inv = t + _hours(rng, 24 * 10 * slow)
            add("Receive invoice", t_inv, "system")
            t = t_inv + _hours(rng, 24 * 2)
            add("Create purchase requisition", t, "requester")
            t += _hours(rng, 24 * 1)
            add("Create purchase order", t, "buyer")
            t += _hours(rng, 24 * 1)
            add("Record goods receipt", t, "requester")
            t += _hours(rng, 24 * 2)
            add("Match invoice", t, "system")
        else:
            add("Create purchase requisition", t, "requester")
            if amount > APPROVAL_LIMIT and not flags["skip_approval"]:
                t += _hours(rng, 24 * 1.5 * slow)
                add("Approve purchase requisition", t, "approver")
            t += _hours(rng, 24 * 1.0)
            add("Create purchase order", t, "buyer")
            t += _hours(rng, 6)
            add("Send purchase order", t, "system")
            if flags["po_change"]:
                t += _hours(rng, 24 * 2)
                add("Change purchase order", t, "buyer")
                t += _hours(rng, 4)
                add("Send purchase order", t, "system")
            t_gr = t + _hours(rng, 24 * 9 * slow)
            t_inv = t + _hours(rng, 24 * 10 * slow)
            if flags["pay_before_gr"]:
                t_gr = t_inv + pd.Timedelta(days=40)  # receipt booked long after payment
            add("Receive invoice", t_inv, "system")
            t = t_inv + _hours(rng, 24 * 1)
            add("Match invoice", t, "system")
            if not flags["pay_before_gr"]:
                add("Record goods receipt", t_gr, "requester")
                t = max(t, t_gr)
        if flags["price_diff"]:
            t += _hours(rng, 24 * 6 * slow)
            add("Resolve price difference", t, "buyer")
            t += _hours(rng, 24 * 1)
            add("Match invoice", t, "system")
        terms = 30
        due = t_inv + pd.Timedelta(days=terms)
        pay = t + _hours(rng, 24 * 16 * slow)  # waits for the payment run
        add("Pay invoice", pay, "system")
        if flags["pay_before_gr"]:
            add("Record goods receipt", t_gr, "requester")
        events += ev
        cases.append({"case_id": cid, "vendor": vendor, "company_code": company, "amount_eur": amount, "invoice_date": t_inv, "due_date": due, "payment_terms_days": terms})
    log = pd.DataFrame(events, columns=["case_id", "activity", "timestamp", "resource"])
    log = log.sort_values(["case_id", "timestamp"], kind="stable").reset_index(drop=True)
    return log, pd.DataFrame(cases)
