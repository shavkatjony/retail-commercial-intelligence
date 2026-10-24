# Tableau Build Guide — Retail Commercial Intelligence

A step-by-step spec for assembling the **3-page decision system** in Tableau
Public from the pipeline's extracts. Design split (deliberate):

- **Heavy, opinionated logic** (exception scoring, price-risk, concentration) is
  computed once in `src/metrics.py` — testable, version-controlled, one source of
  truth — and Tableau simply displays those tables.
- **Standard aggregations and interactivity** (SUM, YoY, ASP, drill-down) are done
  live in Tableau with a few LOD / table-calc fields, to keep the model
  responsive and to show the semantic-modeling skill.

Run `make all` first so `dashboard/extracts/` is populated.

---

## 1 · Data sources

| Connect (Text file → CSV) | Grain | Rows at real M5 scale | Feeds |
| --- | --- | ---: | --- |
| `extracts/mart_monthly.csv` | month × store × category | ~2k | Executive trend & KPI cards |
| `extracts/mart_monthly_item.csv` | month × store × item | ~2M | Diagnostics drill-down to item |
| `extracts/mart_daily_segment.csv` | date × store × category | ~58k | Seasonality, events, SNAP |
| `extracts/exceptions_store_category.csv` | store × category | ≤30 | Exec "where to act" + Opportunity/Risk |
| `extracts/contribution_category.csv` | category | 3 | Exec "why" |
| `extracts/item_movers.csv`, `price_risk_items.csv`, `concentration.csv` | decision tables | tiny | Opportunity/Risk |

Why no daily item-level file: at real scale that grain is ~59M rows — far past
Tableau Public's 15M-rows-per-source limit. The item-level drill uses the monthly
item mart; day-level patterns (weekday, events, SNAP) use the daily *segment* mart.
Pick the grain the question needs, not the finest one available.

Keep these as **separate data sources** (they are already at different grains).
Use a dashboard-level **filter action** from the exec page into diagnostics rather
than blending — cleaner and faster than forcing one physical model.

Set data types: `month_start` / `date_key` → Date; all `*_growth`, `*_share`,
`price_change` → Number (%) with 1 decimal.

---

## 2 · Calculated fields (translated from the spec's DAX)

Create on the `mart_monthly` / `mart_monthly_item` / `mart_daily_segment` sources:

```
// Estimated Sales Value  (value-weighted, never call it revenue)
Estimated Sales Value = SUM([Sales Value])

// Units
Units Sold = SUM([Units])

// Average Selling Price — value-weighted, not AVG([Avg Shelf Price])
ASP = SUM([Sales Value]) / SUM([Units])

// Average units per item-day (mart_daily_segment) — the seasonality measure.
// Reproduces AVG(units) over item-days exactly, from pre-aggregated rows.
Units per Item-Day = SUM([Units]) / SUM([Item Days])

// Year-over-year value (LOD, like-for-like) — pair with a relative-date filter
Sales Value LY =
  LOOKUP( SUM([Sales Value]), -12 )        // on a monthly axis; table calc

YoY Growth = ( SUM([Sales Value]) - [Sales Value LY] ) / [Sales Value LY]

// Signal colour (Opportunity/Risk + exec exception strip)
Signal Colour =
  IF   [Signal] = "Strong growth"        THEN "Growth"
  ELSEIF [Signal] = "Demand deterioration" THEN "Decline"
  ELSE "Price risk" END
```

Colour rule everywhere: green = growth, red = decline, amber = price-risk. Money
in `$#,##0`, ASP in `$#,##0.00`, growth in `+0.0%;-0.0%`.

---

## 3 · Page 01 — Executive Control Tower

*Answers: "What requires management attention?"* (mirrors `docs/img/executive_preview.png`)

1. **KPI row** — three big-number cards from `mart_monthly`: `Estimated Sales
   Value`, `Units Sold`, `ASP`, each with `YoY Growth` as a coloured ▲/▼ caption.
2. **Trend** — line of `Estimated Sales Value` by `month_start`; optional prior-year
   line via `Sales Value LY`.
3. **Why?** — horizontal bar of `share_of_change` by `cat_id` from
   `contribution_category` (diverging green/red about zero).
4. **Where?** — top 6 rows of `exceptions_store_category` as a bar of
   `priority_score`, coloured by `Signal Colour`, labelled with `signal` +
   `demand_growth`.

Layout: KPI row on top, Trend below it, Why? and Where? side by side beneath.
Add a `state_id` filter (applies to all).

---

## 4 · Page 02 — Commercial Diagnostics

*Answers: "What is actually driving the movement?"*

Source `mart_monthly_item` — filters (cascading):
`state_id → store_key → cat_id → dept_id → product_key`.
- **Demand trend** — `Units Sold` by `month_start` (line).
- **Price trend** — `ASP` by `month_start` (line, separate sheet — never a dual
  axis); add `AVG([Avg Shelf Price])` beside it to separate promo from list price.
- **Contributor tables** — `Estimated Sales Value` by `product_key` and by
  `store_key`, sorted descending.

Source `mart_daily_segment` — filters `state_id → store_key → cat_id`:
- **Seasonality** — `Units per Item-Day` by `wday` (bar) and by `month` (bar).
- **Event effect** — `Units per Item-Day` split by `event_type` (bar);
  `snap_active` as colour or a small multiple for FOODS.

Assemble as one dashboard with the filter shelf on the left. A filter action from
Page 01's "Where?" bar should land here pre-filtered to the clicked store×category.

---

## 5 · Page 03 — Opportunity & Risk

*Answers: "Where should we act first?"* — the prioritization system.

- **High-growth opportunities** — `item_movers` where `direction = Gainer`
  (bar of `value_delta`, labelled with `demand_growth`).
- **Demand deterioration** — `item_movers` where `direction = Decliner`.
- **Price-risk watch list** — `price_risk_items` as a table: item, `price_change`,
  `demand_growth`, `value_delta` (this is the "raised price, lost volume" list).
- **Concentration** — `concentration`: show `top_k_share` and `HHI` for products
  and stores as two KPI callouts, with a one-line plain-English reading.
- **Exception table** — the full `exceptions_store_category` as a ranked table:
  Priority · Store · Category · Signal · Magnitude · (suggested investigation).

Keep it a **triage list, not a chart gallery** — every element points to an action.

---

## 6 · Publish & capture

1. **File → Save to Tableau Public** (needs a free Tableau Public account — this
   is a manual sign-in step).
2. Copy the published URL into the README's Dashboard section.
3. Capture a PNG of each page into `dashboard/screenshots/`
   (`executive.png`, `diagnostics.png`, `opportunities.png`) — these replace the
   reference render in the README.

> Reminder: on synthetic data the views are for layout/QA only. Rebuild the
> extracts from the real Kaggle M5 (`mode: real` → `make all`) before publishing
> the portfolio version, so the numbers on screen are real.
