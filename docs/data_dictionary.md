# Data Dictionary

Every table in the pipeline, its **grain** (what one row means), and its keys.
Grain is stated first for each table because a model you cannot describe at the
row level is a model you do not control.

---

## Source (raw M5)

The three files are read as-is. In `sample` mode they are generated with an
identical schema; in `real` mode they are the Kaggle M5 downloads.

### `calendar.csv` — grain: one row per **date**
| Column | Type | Notes |
| --- | --- | --- |
| `date` | date | Calendar date |
| `wm_yr_wk` | int | Walmart fiscal week key (joins to `sell_prices`) |
| `weekday`, `wday` | str/int | `wday` 1 = Saturday … 7 = Friday |
| `month`, `year` | int | |
| `d` | str | Day index `d_1 … d_N` (joins to the wide sales table) |
| `event_name_1`, `event_type_1` | str | Primary event; type ∈ {National, Religious, Cultural, Sporting} |
| `event_name_2`, `event_type_2` | str | Secondary event (rare) |
| `snap_CA`, `snap_TX`, `snap_WI` | 0/1 | SNAP benefit day flag, per state |

### `sell_prices.csv` — grain: one row per **store × item × week**
| Column | Type | Notes |
| --- | --- | --- |
| `store_id`, `item_id` | str | |
| `wm_yr_wk` | int | Fiscal week |
| `sell_price` | float | Weekly selling price |

### `sales_train_evaluation.csv` — grain: one row per **item × store** (wide)
Identity columns `id, item_id, dept_id, cat_id, store_id, state_id` plus one
column **per day** `d_1 … d_N` holding units sold. `ingestion.py` reshapes this
wide block into the long table below.

---

## Staging (`sql/01_staging.sql`)

Typed, lightly-derived copies. `stg_calendar` adds `is_weekend` and `quarter`
and nulls empty event strings; `stg_sales` (a view) is the **long** reshaped
sales (one row per item-store-day) with the real `date` attached. The reshape is
streamed one store at a time with dictionary-encoded text columns — see
[architecture.md § Scale](architecture.md#scale--measured-at-real-m5-size).

---

## Star schema (`sql/02`–`04`)

```
                 dim_date
                    |
 dim_product --- fact_daily_sales --- dim_store
                    |
             fact_weekly_price
```

### `dim_date` — grain: one row per **date**
`date_key` (PK), `wm_yr_wk`, `weekday`, `wday`, `month`, `year`, `quarter`,
`is_weekend`, `event_name`, `event_type`, `snap_CA/TX/WI`.

> **Modeling decision — event lives here, not in a separate `DimEvent`.** In M5
> each date carries at most one primary event, so a standalone event dimension
> would be sparse and near-degenerate — it would only add a join. Event is a
> property *of the date*, so it belongs on `dim_date`.

### `dim_product` — grain: one row per **item**
`product_key` (PK = `item_id`), `dept_id`, `cat_id`. Natural keys are kept
(no surrogate integers) for traceability back to source.

### `dim_store` — grain: one row per **store**
`store_key` (PK = `store_id`), `state_id`.

### `fact_daily_sales` — grain: one row per **item × store × date**
| Column | Notes |
| --- | --- |
| `date_key`, `product_key`, `store_key` | Foreign keys to the three dimensions |
| `units` | Units sold |
| `sell_price` | Weekly price joined on (store, item, `wm_yr_wk`); NULL ⇒ item not on sale that week |
| `sales_value` | `units × sell_price` — **Estimated** Sales Value (see below) |
| `snap_active` | SNAP flag for **this row's state** (resolved from the three snap columns) |

> **Naming decision — `sales_value`, never `revenue`.** M5 exposes units and
> selling price but no refunds, tax, COGS, or markdown accounting. `units ×
> price` is therefore an **estimate of gross sales value**, not accounting
> revenue, and is named and captioned as such everywhere.

### `fact_weekly_price` — grain: one row per **item × store × week**
`store_key`, `product_key`, `wm_yr_wk`, `sell_price`. Kept separate because
price is **weekly** while sales are **daily** — combining the two grains in one
table would double-count price rows.

---

## Analytical marts (`sql/05_kpi_queries.sql`)

| Object | Grain | Rows (real M5) | Purpose |
| --- | --- | ---: | --- |
| `mart_daily` *(view)* | item × store × date (star fully joined) | ~59M | Diagnostic backbone for notebooks & metrics — **never exported** |
| `mart_monthly` | month × store × category | ~2k | Executive trend & contribution |
| `mart_monthly_item` | month × store × item | ~2M | Item-level drill-down (Tableau Page 02) |
| `mart_daily_segment` | date × store × category | ~58k | Weekday, event & SNAP patterns; carries `item_days` so `SUM(units)/SUM(item_days)` = average units per item-day |

> **Sizing decision — export the grain the question needs.** The daily item grain
> stays inside DuckDB as a *view* (no second stored copy of 59M rows) and is never
> exported: it would be ~5 GB of CSV and over Tableau Public's 15M-row limit. Each
> exported mart is aggregated to exactly what one dashboard page asks.
>
> `stg_sales` is likewise a view over the staging Parquet — only
> `fact_daily_sales` holds the 59M rows physically.

Derived decision tables (growth, contribution, exceptions, concentration, …) are
produced by `src/metrics.py` into `dashboard/extracts/` — see
[metric_definitions.md](metric_definitions.md).
