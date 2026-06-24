# Dresma Recommendation System — Phase 2 Channel Performance

> **Audience:** BI Engineers building the Phase 2 channel-attribution dashboard in Looker or Looker Studio.  
> **Phase:** 2 (Multi-Channel Retrieval + Signals) — RFC Section 5.3, 15.2, 18.  
> **Purpose:** Measure how each retrieval channel (C1–C5) contributes to impressions and selections so product and ML can tune channel sizes, diagnose weak channels, and validate the heuristic ranker against the Phase 1 cosine baseline.

---

## 1. Overview

Phase 2 fans out retrieval across **five parallel channels** (RFC Section 5.3). After merge and dedupe, each served candidate carries a `source_channels` array listing every channel that retrieved it. A single reference image can appear in multiple channels — for example, both **foreground** (C1) and **trending** (C3). That overlap is intentional: multi-channel retrieval is evidence of quality (RFC Section 5.3).

This dashboard attributes **impressions** and **selections** back to those channels. Because attribution is **multi-label** (one event can credit more than one channel), channel-level impression counts **will not sum** to the total number of `IMPRESSION` rows in `user_actions`. That is expected, not a data bug.

**Channel code map (service → dashboard label):**

| Code | `source_channels` value in telemetry | Retrieval channel |
|---|---|---|
| **C1** | `foreground` | Foreground embedding similarity |
| **C2** | `full_image` | Full-image embedding similarity |
| **C3** | `trending` | Cluster-scoped trending |
| **C4** | `popular` | Cluster-scoped high engagement |
| **C5** | `freshness` | Cluster-scoped freshness |

These string values are emitted by the recommendation service (`src/dresma_rec/retrieval/channels/*.py`) and returned on each item in `POST /v1/recommendations` as `results[].source_channels`. Interaction events should copy that array into `metadata.source_channels` when the client or backend fires `IMPRESSION` / `SELECTION` (see Section 2).

**Definitions:**

| Metric | Definition |
|---|---|
| **Overall Selection Rate** | Session-level: distinct `job_id` with at least one `SELECTION` ÷ distinct `job_id` with at least one `IMPRESSION` in the date range. Same definition as the Phase 1 baseline dashboard — not inflated by multi-channel attribution. |
| **Channel Impression** | One `IMPRESSION` event attributed to a channel after unnesting `metadata.source_channels`. An event with `["foreground","trending"]` counts once toward C1 and once toward C3. |
| **Channel Selection** | One `SELECTION` event attributed to a channel using the same unnest logic. |
| **Channel Selection Rate** | `channel_selections` ÷ `channel_impressions` for a given channel (and date, when sliced daily). |
| **Top Performing Channel** | The channel with the highest **Channel Selection Rate** in the filtered period, requiring a minimum impression volume (recommended: ≥ 100 channel impressions) to avoid noisy leaders on tiny samples. |

---

## 2. Data Source

| Field | Value |
|---|---|
| **Primary table** | `` `PROJECT_ID.dresma.user_actions` `` |
| **Replace** | `PROJECT_ID` with the production GCP project (e.g. `dresma-prod`). |
| **Required columns** | `event_id`, `job_id`, `image_id`, `event_type`, `position`, `event_time`, `metadata` |
| **Event types used** | `IMPRESSION`, `SELECTION` |

### 2.1 `metadata.source_channels` shape

The `metadata` column is BigQuery `JSON`. For channel attribution, each `IMPRESSION` and `SELECTION` row must include a JSON array of channel keys:

```json
{
  "source_channels": ["foreground", "trending", "freshness"],
  "model_version": "none",
  "assigned_cluster_id": 412
}
```

- **Primary JSON path:** `$.source_channels` — copy directly from `results[].source_channels` in the recommendation API response when logging interactions.
- **Fallback JSON path:** `$.feature_snapshot.source_channels` — use only if your ingestion pipeline nests provenance under `feature_snapshot` (matches the Spanner `recommendation_events.feature_snapshot` shape). The live FastAPI interaction handler enriches `model_version` and `assigned_cluster_id` from the session but does **not** currently auto-attach `source_channels`; the client/backend must supply it until a future enrichment task wires a `recommendation_events` lookup.

Events with a missing or empty `source_channels` array are **excluded from channel breakdown tiles** but still count toward **Overall Selection Rate**.

### 2.2 Why we `UNNEST()` the JSON array

Each row in `user_actions` describes **one user action on one image** (`job_id` + `image_id` + `event_type`). The retrieval system may have found that image through **multiple channels** before ranking. Storing channels as a JSON array preserves that fact in a single event row.

If we counted the whole event toward only the first channel (or picked one channel at random), we would under-credit channels that frequently co-occur with others — for example, C3 **trending** when paired with C1 **foreground**. **`UNNEST()` expands one event into one row per channel** so each contributing channel receives a fair share of credit. Analysts should read channel totals as *attributed exposures*, not as mutually exclusive buckets.

---

## 3. Global Filters

| Filter | Type | Default | Notes |
|---|---|---|---|
| **Date Range** | Date (inclusive) on `event_time` | Trailing **7 days** | Map to `@start_date` and `@end_date` query parameters. |

**Implementation guidance:**

- In **Looker Studio**, add a **Date range control** bound to `event_time` and pass `@start_date` / `@end_date` into custom SQL (or filter the underlying view).
- In **Looker**, expose an `event_time` date filter on the Explore; default the dashboard to `7 days ago for 7 days`.
- All tiles must share the same date filter so scorecards, the bar chart, and the time series are comparable.

**Optional filters (recommended for Phase 2 tuning, not required for v1):**

| Filter | Column / path | Notes |
|---|---|---|
| Cluster | `metadata.assigned_cluster_id` | Slice channel performance within a product cluster. |
| Ranking mode | `metadata.ranking_mode` | Compare heuristic vs baseline once both modes are in production. |

---

## 4. Layout Specification

### Row 1 — Key Scorecards

Two scorecards in one horizontal row.

| Tile | Visualization | Value field | Format |
|---|---|---|---|
| Overall Selection Rate | Scorecard | `overall_selection_rate` | Percent (2 dp) |
| Top Performing Channel | Scorecard | `top_channel_label` + `top_channel_selection_rate` | Text + percent subtitle |

Display the top channel as **`C3 Trending (12.4%)`** style: channel code + friendly name + selection rate.

**SQL — Scorecards:**

```sql
WITH filtered_events AS (
  SELECT
    job_id,
    event_type,
    metadata
  FROM `PROJECT_ID.dresma.user_actions`
  WHERE DATE(event_time) BETWEEN @start_date AND @end_date
    AND event_type IN ('IMPRESSION', 'SELECTION')
),

-- Session-level overall selection rate (not channel-attributed).
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

overall AS (
  SELECT
    (SELECT COUNT(*) FROM sessions_with_impression) AS total_sessions,
    (SELECT COUNT(*) FROM sessions_with_selection) AS sessions_with_selection
),

-- Expand JSON array → one row per (event, channel).
events_with_channels AS (
  SELECT
    fe.event_type,
    JSON_VALUE(channel_json, '$') AS channel
  FROM filtered_events AS fe,
  UNNEST(
    COALESCE(
      JSON_EXTRACT_ARRAY(fe.metadata, '$.source_channels'),
      JSON_EXTRACT_ARRAY(fe.metadata, '$.feature_snapshot.source_channels')
    )
  ) AS channel_json
  WHERE JSON_VALUE(channel_json, '$') IS NOT NULL
),

channel_impressions AS (
  SELECT
    channel,
    COUNT(*) AS impressions
  FROM events_with_channels
  WHERE event_type = 'IMPRESSION'
  GROUP BY channel
),

channel_selections AS (
  SELECT
    channel,
    COUNT(*) AS selections
  FROM events_with_channels
  WHERE event_type = 'SELECTION'
  GROUP BY channel
),

channel_selection_rate AS (
  SELECT
    COALESCE(ci.channel, cs.channel) AS channel,
    COALESCE(ci.impressions, 0) AS impressions,
    COALESCE(cs.selections, 0) AS selections,
    SAFE_DIVIDE(cs.selections, ci.impressions) AS selection_rate
  FROM channel_impressions AS ci
  FULL OUTER JOIN channel_selections AS cs USING (channel)
),

channel_labels AS (
  SELECT * FROM UNNEST([
    STRUCT('foreground' AS channel, 'C1 Foreground' AS channel_label),
    STRUCT('full_image', 'C2 Full Image'),
    STRUCT('trending', 'C3 Trending'),
    STRUCT('popular', 'C4 Popular'),
    STRUCT('freshness', 'C5 Freshness')
  ])
),

ranked_channels AS (
  SELECT
    cl.channel_label,
    csr.selection_rate
  FROM channel_selection_rate AS csr
  INNER JOIN channel_labels AS cl USING (channel)
  WHERE csr.impressions >= 100  -- minimum volume; tune in Looker if needed
  ORDER BY csr.selection_rate DESC
  LIMIT 1
)

SELECT
  SAFE_DIVIDE(o.sessions_with_selection, o.total_sessions) AS overall_selection_rate,
  o.total_sessions,
  o.sessions_with_selection,
  rc.channel_label AS top_channel_label,
  rc.selection_rate AS top_channel_selection_rate
FROM overall AS o
LEFT JOIN ranked_channels AS rc ON TRUE;
```

---

### Row 2 — Bar Chart: Impressions vs. Selections by Channel

| Tile | Visualization | Dimensions | Metrics |
|---|---|---|---|
| Impressions vs. Selections by Channel | Grouped bar chart | `channel_label` (C1–C5) | `impressions`, `selections` |

Sort channels in display order C1 → C5 (not alphabetically by rate).

**SQL — Bar chart:**

```sql
WITH filtered_events AS (
  SELECT
    event_type,
    metadata
  FROM `PROJECT_ID.dresma.user_actions`
  WHERE DATE(event_time) BETWEEN @start_date AND @end_date
    AND event_type IN ('IMPRESSION', 'SELECTION')
),

events_with_channels AS (
  SELECT
    fe.event_type,
    JSON_VALUE(channel_json, '$') AS channel
  FROM filtered_events AS fe,
  UNNEST(
    COALESCE(
      JSON_EXTRACT_ARRAY(fe.metadata, '$.source_channels'),
      JSON_EXTRACT_ARRAY(fe.metadata, '$.feature_snapshot.source_channels')
    )
  ) AS channel_json
  WHERE JSON_VALUE(channel_json, '$') IS NOT NULL
),

channel_impressions AS (
  SELECT
    channel,
    COUNT(*) AS impressions
  FROM events_with_channels
  WHERE event_type = 'IMPRESSION'
  GROUP BY channel
),

channel_selections AS (
  SELECT
    channel,
    COUNT(*) AS selections
  FROM events_with_channels
  WHERE event_type = 'SELECTION'
  GROUP BY channel
),

channel_selection_rate AS (
  SELECT
    COALESCE(ci.channel, cs.channel) AS channel,
    COALESCE(ci.impressions, 0) AS impressions,
    COALESCE(cs.selections, 0) AS selections,
    SAFE_DIVIDE(cs.selections, ci.impressions) AS selection_rate
  FROM channel_impressions AS ci
  FULL OUTER JOIN channel_selections AS cs USING (channel)
),

channel_labels AS (
  SELECT * FROM UNNEST([
    STRUCT('foreground' AS channel, 'C1 Foreground' AS channel_label, 1 AS sort_order),
    STRUCT('full_image', 'C2 Full Image', 2),
    STRUCT('trending', 'C3 Trending', 3),
    STRUCT('popular', 'C4 Popular', 4),
    STRUCT('freshness', 'C5 Freshness', 5)
  ])
)

SELECT
  cl.channel_label,
  cl.sort_order,
  csr.impressions,
  csr.selections,
  csr.selection_rate
FROM channel_labels AS cl
LEFT JOIN channel_selection_rate AS csr USING (channel)
ORDER BY cl.sort_order;
```

---

### Row 3 — Time Series: Selection Rate by Channel (Daily)

| Tile | Visualization | X-axis | Series | Y-axis |
|---|---|---|---|---|
| Selection Rate by Channel | Line chart (multi-series) | `metric_date` | `channel_label` | `selection_rate` (percent) |

One line per channel (C1–C5). Use the same `channel_labels` ordering in the legend.

**SQL — Daily selection rate by channel:**

```sql
WITH filtered_events AS (
  SELECT
    event_type,
    metadata,
    DATE(event_time) AS event_date
  FROM `PROJECT_ID.dresma.user_actions`
  WHERE DATE(event_time) BETWEEN @start_date AND @end_date
    AND event_type IN ('IMPRESSION', 'SELECTION')
),

events_with_channels AS (
  SELECT
    fe.event_type,
    fe.event_date,
    JSON_VALUE(channel_json, '$') AS channel
  FROM filtered_events AS fe,
  UNNEST(
    COALESCE(
      JSON_EXTRACT_ARRAY(fe.metadata, '$.source_channels'),
      JSON_EXTRACT_ARRAY(fe.metadata, '$.feature_snapshot.source_channels')
    )
  ) AS channel_json
  WHERE JSON_VALUE(channel_json, '$') IS NOT NULL
),

channel_impressions AS (
  SELECT
    event_date AS metric_date,
    channel,
    COUNT(*) AS impressions
  FROM events_with_channels
  WHERE event_type = 'IMPRESSION'
  GROUP BY metric_date, channel
),

channel_selections AS (
  SELECT
    event_date AS metric_date,
    channel,
    COUNT(*) AS selections
  FROM events_with_channels
  WHERE event_type = 'SELECTION'
  GROUP BY metric_date, channel
),

channel_selection_rate AS (
  SELECT
    COALESCE(ci.metric_date, cs.metric_date) AS metric_date,
    COALESCE(ci.channel, cs.channel) AS channel,
    COALESCE(ci.impressions, 0) AS impressions,
    COALESCE(cs.selections, 0) AS selections,
    SAFE_DIVIDE(cs.selections, ci.impressions) AS selection_rate
  FROM channel_impressions AS ci
  FULL OUTER JOIN channel_selections AS cs
    ON ci.metric_date = cs.metric_date
   AND ci.channel = cs.channel
),

channel_labels AS (
  SELECT * FROM UNNEST([
    STRUCT('foreground' AS channel, 'C1 Foreground' AS channel_label, 1 AS sort_order),
    STRUCT('full_image', 'C2 Full Image', 2),
    STRUCT('trending', 'C3 Trending', 3),
    STRUCT('popular', 'C4 Popular', 4),
    STRUCT('freshness', 'C5 Freshness', 5)
  ])
)

SELECT
  csr.metric_date,
  cl.channel_label,
  cl.sort_order,
  csr.impressions,
  csr.selections,
  csr.selection_rate
FROM channel_selection_rate AS csr
INNER JOIN channel_labels AS cl USING (channel)
ORDER BY csr.metric_date, cl.sort_order;
```

---

## 5. Core CTE Pattern (Reference)

All channel queries above share the same attribution core. BI engineers can materialize this as a **BigQuery view** (e.g. `dresma.v_channel_attributed_events`) or a **Looker derived table**:

```sql
-- Shared attribution spine: one row per (event, channel).
WITH filtered_events AS (
  SELECT
    event_id,
    job_id,
    image_id,
    event_type,
    position,
    event_time,
    DATE(event_time) AS event_date,
    metadata
  FROM `PROJECT_ID.dresma.user_actions`
  WHERE DATE(event_time) BETWEEN @start_date AND @end_date
    AND event_type IN ('IMPRESSION', 'SELECTION')
),

events_with_channels AS (
  SELECT
    fe.*,
    JSON_VALUE(channel_json, '$') AS channel
  FROM filtered_events AS fe,
  UNNEST(
    COALESCE(
      JSON_EXTRACT_ARRAY(fe.metadata, '$.source_channels'),
      JSON_EXTRACT_ARRAY(fe.metadata, '$.feature_snapshot.source_channels')
    )
  ) AS channel_json
  WHERE JSON_VALUE(channel_json, '$') IS NOT NULL
),

channel_impressions AS (
  SELECT
    event_date,
    channel,
    COUNT(*) AS impressions
  FROM events_with_channels
  WHERE event_type = 'IMPRESSION'
  GROUP BY event_date, channel
),

channel_selections AS (
  SELECT
    event_date,
    channel,
    COUNT(*) AS selections
  FROM events_with_channels
  WHERE event_type = 'SELECTION'
  GROUP BY event_date, channel
),

channel_selection_rate AS (
  SELECT
    COALESCE(ci.event_date, cs.event_date) AS event_date,
    COALESCE(ci.channel, cs.channel) AS channel,
    COALESCE(ci.impressions, 0) AS impressions,
    COALESCE(cs.selections, 0) AS selections,
    SAFE_DIVIDE(cs.selections, ci.impressions) AS selection_rate
  FROM channel_impressions AS ci
  FULL OUTER JOIN channel_selections AS cs
    ON ci.event_date = cs.event_date
   AND ci.channel = cs.channel
)

SELECT * FROM channel_selection_rate;
```

---

## 6. Validation Checklist

Before publishing the dashboard, confirm:

1. **Metadata coverage** — In the trailing 7-day window, ≥ 95% of `IMPRESSION` rows have a non-empty `metadata.source_channels` array (or `feature_snapshot.source_channels`). If coverage is low, fix client instrumentation before trusting channel tiles.
2. **Multi-channel sanity** — Spot-check a `job_id` known to return multi-channel results from `POST /v1/recommendations`; verify its `IMPRESSION` events unnest to multiple channels in the queries above.
3. **Overall vs channel totals** — Overall Selection Rate matches the Phase 1 baseline dashboard for the same date range. Sum of channel impressions **may exceed** total `IMPRESSION` rows — document this on the dashboard subtitle.
4. **C1-only legacy traffic** — Phase 1 traffic should attribute entirely to `foreground` (C1) when `source_channels` is copied from API responses.
5. **Empty state** — Channels with zero impressions show `0` selections and `NULL` or `0%` selection rate without query errors.
6. **Permissions** — Looker service account has `bigquery.dataViewer` on `dresma.user_actions`.

---

## 7. Interpretation Notes for Analysts

- **Higher channel selection rate** means users select a larger fraction of images that channel retrieved. It does **not** mean the channel alone caused the selection — ranking and position still matter.
- **Low C1 rate with high C3/C4 rates** may indicate engagement/trend signals are surfacing better references than raw cosine similarity — expected Phase 2 win condition.
- **Very high C5 (freshness) impressions with low selections** may mean fresh items are shown often but not chosen; consider shrinking C5 pool size (RFC Section 21.3 per-cluster overrides).
- Compare this dashboard alongside the Phase 1 baseline (`infra/monitoring/dashboards/baseline_dashboard.md`) for Selection@3 and MRR; channel rates explain *which retrieval paths* drive session-level lifts.

---

## 8. References

- RFC Section 5.3 — Multi-channel retrieval and `source_channels` merge semantics
- RFC Section 8 — Interaction event model (`IMPRESSION`, `SELECTION`)
- RFC Section 15.2 — Looker dashboards on BigQuery
- `infra/monitoring/dashboards/baseline_dashboard.md` — Phase 1 session-level metrics (Overall Selection Rate parity)
- `infra/bigquery/schemas/user_actions.json` — BigQuery table contract
- `src/dresma_rec/api/v1/recommendations.py` — Serve-time `source_channels` on each ranked result
- `src/dresma_rec/retrieval/channels/` — Channel key strings (`foreground`, `full_image`, `trending`, `popular`, `freshness`)
