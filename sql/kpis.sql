-- Purchase-to-pay process KPIs on an event log.
-- Tables: events(case_id, activity, ts, resource), cases(case_id, vendor, company_code,
--         amount_eur, invoice_date, due_date, payment_terms_days)
--
-- Written for DuckDB. To run on Snowflake, change the date functions:
--   date_diff('hour', a, b)  ->  DATEDIFF(hour, a, b)
--   date_trunc('month', x)   ->  DATE_TRUNC('month', x)   (same)
-- Everything else is standard SQL with window functions.

-- name: case_metrics
-- One row per case: timestamps of the key steps and derived flags.
CREATE OR REPLACE VIEW case_metrics AS
WITH firsts AS (
    SELECT
        case_id,
        MIN(ts) AS case_start,
        MAX(ts) AS case_end,
        MIN(CASE WHEN activity = 'Create purchase requisition' THEN ts END) AS pr_created,
        MIN(CASE WHEN activity = 'Approve purchase requisition' THEN ts END) AS pr_approved,
        MIN(CASE WHEN activity = 'Create purchase order' THEN ts END) AS po_created,
        MIN(CASE WHEN activity = 'Pay invoice' THEN ts END) AS paid,
        COUNT(*) AS events,
        SUM(CASE WHEN resource = 'system' THEN 1 ELSE 0 END) AS system_events,
        SUM(CASE WHEN activity IN ('Change purchase order', 'Resolve price difference') THEN 1 ELSE 0 END) AS rework_events,
        SUM(CASE WHEN activity = 'Match invoice' THEN 1 ELSE 0 END) AS match_attempts
    FROM events
    GROUP BY case_id
)
SELECT
    f.*,
    c.vendor,
    c.company_code,
    c.amount_eur,
    c.due_date,
    date_diff('hour', f.case_start, f.case_end) / 24.0 AS throughput_days,
    date_diff('hour', f.pr_created, f.pr_approved) / 24.0 AS approval_days,
    CASE WHEN f.paid <= c.due_date THEN 1 ELSE 0 END AS paid_on_time,
    CASE WHEN f.rework_events > 0 THEN 1 ELSE 0 END AS has_rework,
    CASE WHEN f.match_attempts = 1 THEN 1 ELSE 0 END AS first_time_match
FROM firsts f
JOIN cases c USING (case_id);

-- name: kpi_overview
SELECT
    COUNT(*)                                                    AS cases,
    ROUND(MEDIAN(throughput_days), 1)                           AS median_throughput_days,
    ROUND(QUANTILE_CONT(throughput_days, 0.9), 1)               AS p90_throughput_days,
    ROUND(AVG(paid_on_time), 3)                                 AS on_time_payment_rate,
    ROUND(AVG(has_rework), 3)                                   AS rework_rate,
    ROUND(AVG(first_time_match), 3)                             AS first_time_match_rate,
    ROUND(SUM(system_events) * 1.0 / SUM(events), 3)            AS automation_rate,
    ROUND(AVG(CASE WHEN approval_days > 2 THEN 1.0 ELSE 0 END)
          FILTER (WHERE approval_days IS NOT NULL), 3)          AS approval_sla_breach_rate
FROM case_metrics;

-- name: kpi_by_vendor
SELECT
    vendor,
    COUNT(*)                                  AS cases,
    ROUND(MEDIAN(throughput_days), 1)         AS median_throughput_days,
    ROUND(AVG(paid_on_time), 3)               AS on_time_payment_rate,
    ROUND(AVG(has_rework), 3)                 AS rework_rate
FROM case_metrics
GROUP BY vendor
ORDER BY median_throughput_days DESC;

-- name: kpi_by_company_month
SELECT
    company_code,
    date_trunc('month', case_start)           AS month,
    COUNT(*)                                  AS cases,
    ROUND(MEDIAN(throughput_days), 1)         AS median_throughput_days,
    ROUND(AVG(paid_on_time), 3)               AS on_time_payment_rate
FROM case_metrics
GROUP BY company_code, month
ORDER BY company_code, month;

-- name: late_payment_drivers
-- On-time payment rate with and without each rework type.
SELECT
    CASE WHEN rework_events > 0 THEN 'with rework' ELSE 'no rework' END   AS rework,
    company_code,
    COUNT(*)                                                             AS cases,
    ROUND(AVG(paid_on_time), 3)                                          AS on_time_payment_rate,
    ROUND(MEDIAN(throughput_days), 1)                                    AS median_throughput_days
FROM case_metrics
GROUP BY rework, company_code
ORDER BY rework, company_code;
