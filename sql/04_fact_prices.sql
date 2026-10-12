-- ============================================================================
-- 04 — FACT: WEEKLY PRICE
-- GRAIN: exactly one row per  item × store × fiscal week (wm_yr_wk).
-- Kept as its own fact because price lives at a WEEKLY grain while sales are
-- DAILY — mixing the two grains in one table would double-count price rows.
-- Used for price-trend analysis and the price-change diagnostics.
-- ============================================================================
CREATE OR REPLACE TABLE fact_weekly_price AS
SELECT
    p.store_id    AS store_key,     -- FK -> dim_store.store_key
    p.item_id     AS product_key,   -- FK -> dim_product.product_key
    p.wm_yr_wk,                      -- FK -> dim_date.wm_yr_wk (week grain)
    p.sell_price
FROM stg_prices p;
