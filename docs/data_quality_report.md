# Data Quality Report

- **Generated:** 2026-10-12 20:58
- **Data source:** `sample`  *(synthetic scaffold — not a source of findings)*
- **Fact table:** `fact_daily_sales` — 1,533,000 rows (2,100 series × 730 days)
- **Result:** ✅ passed clean — 0 fail / 0 warn / 8 checks

| Check | Status | Detail |
| --- | :---: | --- |
| Complete panel (rows = series × sales days) | ✅ PASS | 1,533,000 = 2,100 series × 730 days |
| Unique grain (date × product × store) | ✅ PASS | 0 duplicated grain keys |
| No null date keys | ✅ PASS | 0 null date keys |
| No negative units | ✅ PASS | 0 rows units < 0 |
| No negative prices | ✅ PASS | 0 rows price < 0 |
| Referential integrity (fact → dims) | ✅ PASS | 0 product / 0 store / 0 date orphans |
| Daily calendar continuity | ✅ PASS | 0 gaps in the daily calendar |
| Price coverage | ✅ PASS | 100.00% of sales rows carry a price |

> Hard checks (unique grain, referential integrity, impossible values, null keys) block the build. Coverage and continuity checks warn only — a missing weekly price in M5 legitimately means the item was not on sale.
