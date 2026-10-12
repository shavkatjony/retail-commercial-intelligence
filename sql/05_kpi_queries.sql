-- ============================================================================
-- 05 — ANALYTICAL MARTS
-- Star-joined tables the notebooks, the metrics engine, and Tableau read from.
-- The heavy period-over-period logic (growth, contribution, exceptions) lives in
-- src/metrics.py; here we build the clean aggregate backbones it sits on.
--
-- Sizing rule: anything exported for Tableau must stay well under Tableau
-- Public's 15M-row-per-source limit at REAL M5 scale (~59M item-store-days).
-- So the daily item grain stays inside DuckDB (as a view), and the exports are
-- aggregated to the grain each dashboard page actually needs.
-- ============================================================================

-- mart_daily — the enriched daily grain (star fully joined). Diagnostic backbone.
-- GRAIN: one row per item × store × date. A VIEW: DuckDB joins on the fly, so the
-- 59M-row fact is not stored a second time. Never exported.
CREATE OR REPLACE VIEW mart_daily AS
SELECT
    f.date_key,
    d.year, d.month, d.quarter, d.wday, d.is_weekend,
    d.event_name, d.event_type,
    f.store_key,  st.state_id,
    f.product_key, pr.dept_id, pr.cat_id,
    f.units,
    f.sell_price,
    f.sales_value,
    f.snap_active
FROM fact_daily_sales f
JOIN dim_date    d  ON f.date_key    = d.date_key
JOIN dim_store   st ON f.store_key   = st.store_key
JOIN dim_product pr ON f.product_key = pr.product_key;

-- mart_monthly — executive trend & contribution rollup.
-- GRAIN: one row per month × store × category.        (real M5: ~1.9k rows)
CREATE OR REPLACE TABLE mart_monthly AS
SELECT
    date_trunc('month', date_key)              AS month_start,
    state_id,
    store_key,
    cat_id,
    SUM(units)                                 AS units,
    SUM(sales_value)                           AS sales_value,
    SUM(sales_value) / NULLIF(SUM(units), 0)   AS avg_selling_price
FROM mart_daily
GROUP BY 1, 2, 3, 4;

-- mart_monthly_item — Commercial Diagnostics drill-down to the item.
-- GRAIN: one row per month × store × item.            (real M5: ~2M rows)
-- avg_selling_price is value-weighted (what customers paid); avg_shelf_price is
-- the plain average list price (what the shelf said) — the two diverge on promo.
CREATE OR REPLACE TABLE mart_monthly_item AS
SELECT
    date_trunc('month', date_key)              AS month_start,
    state_id,
    store_key,
    cat_id,
    dept_id,
    product_key,
    SUM(units)                                 AS units,
    SUM(sales_value)                           AS sales_value,
    SUM(sales_value) / NULLIF(SUM(units), 0)   AS avg_selling_price,
    AVG(sell_price)                            AS avg_shelf_price
FROM mart_daily
GROUP BY 1, 2, 3, 4, 5, 6;

-- mart_daily_segment — seasonality, event, and SNAP views.
-- GRAIN: one row per date × store × category.         (real M5: ~58k rows)
-- item_days lets a BI tool reproduce "average units per item-day" exactly:
-- SUM(units) / SUM(item_days).
CREATE OR REPLACE TABLE mart_daily_segment AS
SELECT
    date_key, year, month, wday, is_weekend, event_name, event_type,
    state_id, store_key, cat_id,
    MAX(snap_active)                           AS snap_active,   -- constant per date × state
    SUM(units)                                 AS units,
    SUM(sales_value)                           AS sales_value,
    COUNT(*)                                   AS item_days
FROM mart_daily
GROUP BY date_key, year, month, wday, is_weekend, event_name, event_type,
         state_id, store_key, cat_id;
