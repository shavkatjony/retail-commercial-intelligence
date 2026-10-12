-- ============================================================================
-- 01 — STAGING
-- Light typing and a few derived calendar attributes. No business logic yet.
-- Inputs are the parquet-backed views raw_calendar / raw_prices / raw_sales_long
-- (created by build.py). Outputs feed the dimensions and facts.
-- ============================================================================

-- Calendar: one row per DATE. Adds is_weekend / quarter and nulls the empty
-- event strings so joins and filters behave.
CREATE OR REPLACE TABLE stg_calendar AS
SELECT
    CAST(date AS DATE)                         AS date,
    d,
    wm_yr_wk,
    weekday,
    wday,
    month,
    year,
    (wday IN (1, 2))                           AS is_weekend,   -- M5 wday 1=Sat, 2=Sun
    CAST((month - 1) / 3 + 1 AS INTEGER)       AS quarter,
    NULLIF(event_name_1, '')                   AS event_name,
    NULLIF(event_type_1, '')                   AS event_type,
    snap_CA, snap_TX, snap_WI
FROM raw_calendar;

-- Weekly selling prices: one row per store × item × fiscal week.
CREATE OR REPLACE TABLE stg_prices AS
SELECT
    store_id,
    item_id,
    wm_yr_wk,
    CAST(sell_price AS DOUBLE)                 AS sell_price
FROM raw_prices;

-- Sales (already reshaped to long by ingestion.py): one row per item-store-day.
-- A VIEW, not a table: it is a pass-through cast over the Parquet file, read only
-- while building the dimensions and the fact — materializing it would store a
-- second copy of the ~59M-row real dataset for no benefit.
CREATE OR REPLACE VIEW stg_sales AS
SELECT
    id,
    item_id, dept_id, cat_id,
    store_id, state_id,
    d,
    CAST(date AS DATE)                         AS date,
    wm_yr_wk,
    CAST(units AS INTEGER)                     AS units
FROM raw_sales_long;
