-- ============================================================================
-- 03 — FACT: DAILY SALES
-- GRAIN: exactly one row per  item × store × date.
--
-- Estimated Sales Value = units × sell_price. It is NOT accounting revenue —
-- there are no refunds, tax, COGS or markdown adjustments in M5 — so it is named
-- "sales_value" throughout and reported as an estimate. (See docs.)
--
-- sell_price is the WEEKLY price joined on (store, item, fiscal week). When a
-- price is missing (in real M5 that means the item was not on sale that week),
-- sell_price and sales_value are NULL by design.
--
-- snap_active is the SNAP flag for THIS row's state (SNAP is issued per state),
-- resolved from the three calendar snap columns.
-- ============================================================================
CREATE OR REPLACE TABLE fact_daily_sales AS
SELECT
    s.date        AS date_key,      -- FK -> dim_date.date_key
    s.item_id     AS product_key,   -- FK -> dim_product.product_key
    s.store_id    AS store_key,     -- FK -> dim_store.store_key
    s.units,
    p.sell_price,
    s.units * p.sell_price          AS sales_value,
    CASE s.state_id
        WHEN 'CA' THEN c.snap_CA
        WHEN 'TX' THEN c.snap_TX
        WHEN 'WI' THEN c.snap_WI
    END                             AS snap_active
FROM stg_sales s
LEFT JOIN stg_prices p
    ON  s.store_id = p.store_id
    AND s.item_id  = p.item_id
    AND s.wm_yr_wk = p.wm_yr_wk
LEFT JOIN stg_calendar c
    ON  s.date = c.date;
