-- ============================================================================
-- 02 — DIMENSIONS
-- Conformed dimensions for the star schema. Keys are the natural M5 identifiers
-- (already unique), kept as-is for traceability rather than surrogate integers.
--
-- MODELING DECISION: "event" is modeled as an ATTRIBUTE of dim_date, not a
-- separate DimEvent. In M5 each date carries at most one primary event, so a
-- standalone event dimension would be a sparse, near-degenerate table that only
-- adds a join. Folding it into dim_date is the correct grain. (Documented in
-- docs/data_dictionary.md.)
-- ============================================================================

-- dim_date — one row per DATE.
CREATE OR REPLACE TABLE dim_date AS
SELECT
    date          AS date_key,
    d,
    wm_yr_wk,
    weekday,
    wday,
    month,
    year,
    quarter,
    is_weekend,
    event_name,
    event_type,
    snap_CA, snap_TX, snap_WI
FROM stg_calendar;

-- dim_product — one row per ITEM (item_id is unique across departments).
CREATE OR REPLACE TABLE dim_product AS
SELECT DISTINCT
    item_id       AS product_key,
    item_id,
    dept_id,
    cat_id
FROM stg_sales;

-- dim_store — one row per STORE.
CREATE OR REPLACE TABLE dim_store AS
SELECT DISTINCT
    store_id      AS store_key,
    store_id,
    state_id
FROM stg_sales;
