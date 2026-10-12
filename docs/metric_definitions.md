# Metric Definitions

Exactly how every number is computed. All parameters come from
[`config.yaml`](../config.yaml); no threshold is hard-coded in analysis code.

---

## Comparison windows

All growth is **like-for-like** against the same calendar window one year
earlier — this controls for seasonality (a Q4 vs Q3 comparison would be
meaningless in retail).

```
current window  = the most recent `period_days` (default 90) of data
prior window    = the same `period_days`, shifted back 365 days
```

If fewer than two years of history exist, the engine falls back to the
immediately preceding window and records `like_for_like = false` in
`metrics_summary.json`, so the basis is never silently ambiguous.

---

## Core KPIs

| KPI | Formula |
| --- | --- |
| **Estimated Sales Value** | `Σ (units × sell_price)` — gross sales estimate, **not** accounting revenue |
| **Units Sold** | `Σ units` |
| **Average Selling Price (ASP)** | `Estimated Sales Value ÷ Units Sold` (value-weighted, not a mean of list prices) |
| **Growth** (any metric) | `current ÷ prior − 1` |
| **At-Risk Value** | `Σ current-window sales_value` of every store×category flagged **Demand deterioration** |

ASP is deliberately value-weighted so mix shifts (selling more cheap items) show
up honestly, rather than being hidden by an unweighted average of price tags.

---

## Diagnostic metrics

| Metric | Definition |
| --- | --- |
| **Demand Growth** | `units_current ÷ units_prior − 1` |
| **Price Change** | `ASP_current ÷ ASP_prior − 1` (segment-level ASP) |
| **Value Δ (contribution)** | `value_current − value_prior` |
| **Share of change** | segment `Value Δ ÷ total Value Δ` — who moved the top line |
| **Contribution share** | segment `value_current ÷ total value_current` — how big the segment is |

### Price–demand association
Reported as **association, never causation.** The output pairs each segment's
`Demand Growth` with its `Price Change` and phrases it as, e.g., *"units −12.4%
alongside ASP +7.8%."* We do not claim the price *caused* the demand move —
promotions, stock-outs, events, and competitor moves are all uncontrolled.

---

## Exception engine

The engine scans every **store × category** segment and assigns at most one
signal, in priority order:

| Signal | Condition |
| --- | --- |
| **Price ↑ / demand ↓** | `Price Change ≥ +5%` **and** `Demand Growth ≤ −10%` |
| **Demand deterioration** | `Demand Growth ≤ −10%` and segment ≥ 0.5% of sales value |
| **Strong growth** | `Demand Growth ≥ +15%` and segment ≥ 0.5% of sales value |

Thresholds (`demand_decline`, `demand_growth_high`, `price_increase`,
`min_contribution_share`, `min_prior_units`) are all in `config.yaml`.

### Priority score
A transparent, defensible ranking — **not** a black box:

```
priority_score = 100 × Impact × Magnitude × Confidence

  Impact      = contribution_share        (share of the business at stake)
  Magnitude   = |demand_growth|           (size of the move)
  Confidence  = min(1, prior_units / median_prior_units)
                (thin-history segments are noisier, so they are discounted)
```

Recency is *built in* — every input is the most-recent period versus the same
period last year, so a high score already reflects a recent move. Segments are
then banded **High / Medium / Low** by the top / middle / bottom third of scores
among those flagged (relative banding, so the list is always triaged).

---

## Item-level lists

| List | Grain | Rule |
| --- | --- | --- |
| **Item movers** | item (all stores) | top 10 / bottom 10 by `Value Δ`, among items with `units_prior ≥ min_prior_units` |
| **Price-risk watch list** | store × item | `Price Change ≥ +5%` **and** `Demand Growth ≤ −10%` **and** `units_prior ≥ min_prior_units`, worst 15 by `Value Δ` |

Why a **volume** floor (`min_prior_units`, default 50) rather than a share floor:
ranking by absolute dollar change is already noise-resistant — a near-zero item
cannot swing thousands of dollars — so the floor only needs to stop intermittent
series from producing meaningless ±100% growth rates. A share floor would not
scale: 0.5% of value is a big item among 210 but almost nothing qualifies among
3,049. Price risk sits at store × item because that is where price is set.

---

## Concentration risk

Two scale-free measures, so the reading is honest whether the universe is 10
stores or 3000 items:

| Measure | Definition |
| --- | --- |
| **Top-k share** | share of sales value held by the top `k` entities, `k = min(10, max(1, round(0.3 × universe)))` |
| **HHI** | Herfindahl–Hirschman Index `Σ shareᵢ²`, ranging `1/n` (perfectly even) → `1` (one entity) |

A single top-N cutoff was rejected because "top 10 of 10 stores = 100%" is
meaningless; HHI and an adaptive `k` stay interpretable at any scale.

---

## A note on honesty

On `sample` data these metrics are **mechanically correct but not real
findings** — the data is synthetic. Business conclusions in the README and
notebooks are to be regenerated on the real Kaggle M5 data (`mode: real`), at
which point every formula above applies unchanged.
