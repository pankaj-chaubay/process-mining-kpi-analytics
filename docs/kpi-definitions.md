# KPI and check definitions

Every number in the report comes from one of these definitions. The SQL is in [`sql/kpis.sql`](../sql/kpis.sql), the conformance checks in [`src/pmkpi/mining.py`](../src/pmkpi/mining.py).

## Event log

| Column | Meaning |
|---|---|
| case_id | One purchase requisition line, followed from request to payment |
| activity | Step name |
| timestamp | When the step happened |
| resource | Who did it: requester, approver, buyer, or system for automated steps |

Case attributes: vendor, company code, amount, invoice date, due date, payment terms.

## Process KPIs

| KPI | Definition | Why it matters |
|---|---|---|
| Throughput time | First event to last event of the case, in days. Median and 90th percentile | Speed of the whole process, from the requester's point of view |
| On-time payment rate | Share of cases where payment is on or before the due date (invoice date + payment terms) | Late payment costs supplier trust, late fees and lost early-payment discounts |
| Rework rate | Share of cases with at least one rework step (purchase order changed after sending, price difference resolved) | Rework is effort that adds no value |
| First-time match rate | Share of cases where the invoice matched on the first attempt | Each failed match means manual work in accounts payable and procurement |
| Automation rate | Share of events done by the system | Where manual work remains |
| Approval SLA breach rate | Share of approved requisitions where approval took more than 2 days | Slow approval delays the order |

## Conformance checks

| Check | Rule | Type |
|---|---|---|
| Approval missing | Amount above 5,000 EUR and no approval step | Compliance |
| Order after the fact | Purchase order created after the invoice arrived | Compliance |
| Paid before goods receipt | Payment before goods receipt, or no receipt at all | Compliance |
| Price difference | A price difference was resolved at matching | Rework |
| Order changed | Purchase order changed after it was sent | Rework |
| Designed path | Case follows the designed sequence exactly (approval aside); goods receipt may come before or after invoice matching | Overall |

## Bottlenecks

For each directly-follows transition: number of cases × median waiting time = total waiting days. The transitions with the most total waiting are where a change saves the most time.

## Power BI model

`python -m pmkpi` writes a small star schema to `powerbi/`:

| Table | Grain | Key |
|---|---|---|
| fact_event | One event | event_id, case_id |
| fact_case | One case, with all KPI flags from `case_metrics` | case_id |
| fact_conformance | One case, with the result of each check | case_id |
| dim_activity | One activity, with its place in the designed path and a rework flag | activity |

Relationships: fact_event[case_id] → fact_case[case_id], fact_conformance[case_id] → fact_case[case_id] (1:1), fact_event[activity] → dim_activity[activity]. The KPIs above become simple measures, for example `On-time payment rate = AVERAGE(fact_case[paid_on_time])`.
