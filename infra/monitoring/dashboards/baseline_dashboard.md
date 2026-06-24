# Dresma Recommendation System — Baseline Performance

> **Audience:** BI Engineers building the Phase 1 baseline dashboard in Looker or Looker Studio.  
> **Phase:** 1 (Foundations & Instrumentation) — RFC Section 1.4, 15.2, 18.  
> **Purpose:** Establish the pre-ranking / cosine-only baseline for Selection Rate, Selection@3, and MRR before heuristic or XGBoost layers ship.

---

## 1. Overview

This dashboard tracks **online proxy ranking metrics** derived from interaction events in BigQuery. It mirrors the offline logic in `scripts/measure_baseline.py` and is the canonical view for Phase 1 exit criteria: *baseline metrics visible in Looker*.

**Definitions (session = `job_id`):**

| Metric | Definition |
|---|---|
| **Total Sessions** | Distinct `job_id` values with at least one `IMPRESSION` event in the selected date range. |
| **Selection Rate** | Fraction of total sessions with at least one `SELECTION` event. |
| **Selection@3** | Fraction of total sessions where the best (minimum) `SELECTION` position is ≤ 3. |
| **MRR** | Mean Reciprocal Rank: average of `1.0 / MIN(position)` across sessions that recorded a `SELECTION`. |

---

## 2. Data Source

| Field | Value |
|---|---|
| **Primary table** | `` `PROJECT_ID.dresma.user_actions` `` |
| **Replace** | `PROJECT_ID` with the production GCP project (e.g. `dresma-prod`). |
| **Required columns** | `job_id`, `event_type`, `position`, `event_time` |
| **Event types used** | `IMPRESSION`, `SELECTION` |

Connect Looker / Looker Studio directly to BigQuery. Prefer a **custom SQL** data source or **Looker derived table** backed by the queries below.

---

## 3. Global Filters

| Filter | Type | Default | Notes |
|---|---|---|---|
| **Date Range** | Date (inclusive) on `event_time` | Trailing **7 days** | Map to `@start_date` and `@end_date` query parameters. |

**Implementation guidance:**

- In **Looker Studio**, add a **Date range control** bound to `event_time` and pass `@start_date` / `@end_date` into custom SQL (or filter the underlying view).
- In **Looker**, expose a `event_time` date filter on the Explore; default the dashboard to `7 days ago for 7 days`.
- All tiles on this dashboard must respect the same date filter so scorecards and time series are comparable.

---

## 4. Layout Specification

### Row 1 — Key Scorecards (single period aggregate)

Display four scorecards in one horizontal row. Format percentages to **two decimal places**; format MRR to **four decimal places**.

| Tile | Visualization | Value field | Format |
|---|---|---|---|
| Total Sessions | Scorecard | `total_sessions` | Integer |
| Selection Rate | Scorecard | `selection_rate` | Percent |
| Selection@3 | Scorecard | `selection_at_3` | Percent |
| Mean Reciprocal Rank | Scorecard | `mrr` | Number (4 dp) |

**SQL — Scorecards (aggregate over filtered date range):**

```sql
WITH filtered_events AS (
  SELECT
    job_id,
    event_type,
    position
  FROM `PROJECT_ID.dresma.user_actions`
  WHERE DATE(event_time) BETWEEN @start_date AND @end_date
),

sessions_with_impression AS (
  SELECT DISTINCT job_id
  FROM filtered_events
  WHERE event_type = 'IMPRESSION'
),

sessions_with_selection AS (
  SELECT DISTINCT job_id
  FROM filtered_events
  WHERE event_type = 'SELECTION'
),

session_selection_rank AS (
  SELECT
    job_id,
    MIN(position) AS best_selection_position
  FROM filtered_events
  WHERE event_type = 'SELECTION'
    AND position IS NOT NULL
  GROUP BY job_id
),

aggregates AS (
  SELECT
    (SELECT COUNT(*) FROM sessions_with_impression) AS total_sessions,
    (SELECT COUNT(*) FROM sessions_with_selection) AS sessions_with_selection,
    (
      SELECT COUNT(*)
      FROM session_selection_rank AS sr
      INNER JOIN sessions_with_impression AS si USING (job_id)
      WHERE sr.best_selection_position <= 3
    ) AS sessions_with_selection_at_3,
    (
      SELECT AVG(1.0 / sr.best_selection_position)
      FROM session_selection_rank AS sr
      INNER JOIN sessions_with_selection AS ss USING (job_id)
    ) AS mrr
)

SELECT
  total_sessions,
  sessions_with_selection,
  SAFE_DIVIDE(sessions_with_selection, total_sessions) AS selection_rate,
  SAFE_DIVIDE(sessions_with_selection_at_3, total_sessions) AS selection_at_3,
  mrr
FROM aggregates;
```

---

### Row 2 — Time Series Charts (daily trend)

Two line charts side by side. **X-axis:** `metric_date` (daily). **Session attribution:** assign each session to the calendar date of its **first `IMPRESSION`** within the filtered window (consistent daily session counts).

| Tile | Visualization | Y-axis | X-axis |
|---|---|---|---|
| Selection@3 over time | Time series (line) | `selection_at_3` (percent) | `metric_date` |
| MRR over time | Time series (line) | `mrr` | `metric_date` |

**SQL — Daily metrics (powers both time series charts):**

```sql
WITH filtered_events AS (
  SELECT
    job_id,
    event_type,
    position,
    DATE(event_time) AS event_date
  FROM `PROJECT_ID.dresma.user_actions`
  WHERE DATE(event_time) BETWEEN @start_date AND @end_date
),

session_impression_date AS (
  SELECT
    job_id,
    MIN(event_date) AS session_date
  FROM filtered_events
  WHERE event_type = 'IMPRESSION'
  GROUP BY job_id
),

session_events AS (
  SELECT
    fe.job_id,
    fe.event_type,
    fe.position,
    sid.session_date
  FROM filtered_events AS fe
  INNER JOIN session_impression_date AS sid USING (job_id)
),

session_selection_rank AS (
  SELECT
    job_id,
    session_date,
    MIN(position) AS best_selection_position
  FROM session_events
  WHERE event_type = 'SELECTION'
    AND position IS NOT NULL
  GROUP BY job_id, session_date
),

daily_impression_sessions AS (
  SELECT
    session_date AS metric_date,
    COUNT(DISTINCT job_id) AS total_sessions
  FROM session_events
  WHERE event_type = 'IMPRESSION'
  GROUP BY session_date
),

daily_selection_sessions AS (
  SELECT
    session_date AS metric_date,
    COUNT(DISTINCT job_id) AS sessions_with_selection
  FROM session_events
  WHERE event_type = 'SELECTION'
  GROUP BY session_date
),

daily_selection_at_3 AS (
  SELECT
    session_date AS metric_date,
    COUNT(*) AS sessions_with_selection_at_3
  FROM session_selection_rank
  WHERE best_selection_position <= 3
  GROUP BY session_date
),

daily_mrr AS (
  SELECT
    session_date AS metric_date,
    AVG(1.0 / best_selection_position) AS mrr
  FROM session_selection_rank
  GROUP BY session_date
)

SELECT
  di.metric_date,
  di.total_sessions,
  COALESCE(ds.sessions_with_selection, 0) AS sessions_with_selection,
  SAFE_DIVIDE(ds.sessions_with_selection, di.total_sessions) AS selection_rate,
  SAFE_DIVIDE(d3.sessions_with_selection_at_3, di.total_sessions) AS selection_at_3,
  dm.mrr
FROM daily_impression_sessions AS di
LEFT JOIN daily_selection_sessions AS ds USING (metric_date)
LEFT JOIN daily_selection_at_3 AS d3 USING (metric_date)
LEFT JOIN daily_mrr AS dm USING (metric_date)
ORDER BY metric_date;
```

---

## 5. Validation Checklist

Before publishing the dashboard, confirm:

1. **Parity with offline script** — Scorecard values for the same 7-day window match `python scripts/measure_baseline.py --project_id PROJECT_ID --days 7` within rounding tolerance.
2. **Empty state** — When no data exists, scorecards show `0` or `n/a` gracefully (not errors).
3. **Date filter** — Changing the global date range updates all tiles consistently.
4. **Permissions** — Looker service account has `bigquery.dataViewer` on `dresma.user_actions`.

---

## 6. Future Extensions (Out of Scope for Phase 1)

Do **not** implement these in the Phase 1 baseline dashboard; track separately in Phase 2+ specs:

- CTR and per-position click curves
- Generation Rate and Download Rate funnels
- Canary vs production model comparison (`model_version` from session metadata)
- Per-cluster breakdowns (`assigned_cluster_id` enrichment)

---

## 7. References

- RFC Section 1.4 — Success metrics and KPIs
- RFC Section 15.2 — Looker dashboards on BigQuery
- `scripts/measure_baseline.py` — Offline baseline measurement (Task 1.22)
- `infra/bigquery/schemas/user_actions.json` — Table schema contract
