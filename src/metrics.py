"""Analytical engine — the diagnostic layer.

Turns the star schema into decision-ready tables:

  * Executive KPIs      current period vs the SAME window one year earlier
  * Contribution        who drove the change (by category, by store)
  * Price–demand        association between ASP moves and unit moves (NOT causation)
  * Exception engine    store×category signals ranked by a transparent priority score
  * Item movers         biggest value gainers / losers
  * Price-risk items    price ↑ while demand ↓ (a margin-vs-volume watch list)
  * Concentration       how dependent the business is on a few products / stores

Every threshold comes from config.yaml. Every output CSV lands in
dashboard/extracts/ for Tableau, the notebooks, and the README.

A word on language: we report ASSOCIATION, never proven causation. "Demand fell
alongside a +7% price rise" — not "the price cut demand."
"""
from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd

from config import load_config, path


def _window_agg(con, start, end, by: list[str]) -> pd.DataFrame:
    """Aggregate units and sales_value over [start, end] at the given grain.
    An empty `by` returns the single grand-total row (no GROUP BY)."""
    measures = "SUM(units) AS units, SUM(sales_value) AS value"
    if by:
        cols = ", ".join(by)
        sql = (f"SELECT {cols}, {measures} FROM mart_daily "
               f"WHERE date_key BETWEEN ? AND ? GROUP BY {cols}")
    else:
        sql = f"SELECT {measures} FROM mart_daily WHERE date_key BETWEEN ? AND ?"
    return con.execute(sql, [start, end]).df()


def _compare(cur: pd.DataFrame, prior: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Join current vs prior windows and derive growth / ASP / price-change."""
    m = cur.merge(prior, on=keys, how="outer", suffixes=("_cur", "_prior")).fillna(0.0)
    m["demand_growth"] = np.where(m["units_prior"] > 0, m["units_cur"] / m["units_prior"] - 1, np.nan)
    m["value_growth"] = np.where(m["value_prior"] > 0, m["value_cur"] / m["value_prior"] - 1, np.nan)
    m["asp_cur"] = np.where(m["units_cur"] > 0, m["value_cur"] / m["units_cur"], np.nan)
    m["asp_prior"] = np.where(m["units_prior"] > 0, m["value_prior"] / m["units_prior"], np.nan)
    m["price_change"] = np.where(m["asp_prior"] > 0, m["asp_cur"] / m["asp_prior"] - 1, np.nan)
    m["value_delta"] = m["value_cur"] - m["value_prior"]
    return m


def build_metrics(con, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    a = cfg["analysis"]
    th = a["thresholds"]
    ext = path("dashboard", "extracts")
    ext.mkdir(parents=True, exist_ok=True)

    # ── Define the comparison windows ────────────────────────────────────────
    dmin, dmax = con.execute("SELECT MIN(date_key), MAX(date_key) FROM mart_daily").fetchone()
    pdays = int(a["period_days"])
    cur_start, cur_end = dmax - timedelta(days=pdays - 1), dmax
    ly_start, ly_end = cur_start - timedelta(days=365), cur_end - timedelta(days=365)
    if ly_start >= dmin:
        comparable, basis = True, "same window one year earlier (like-for-like)"
        prior_start, prior_end = ly_start, ly_end
    else:                       # not enough history -> immediately preceding window
        comparable, basis = False, "immediately preceding window (no prior year available)"
        prior_end = cur_start - timedelta(days=1)
        prior_start = prior_end - timedelta(days=pdays - 1)

    def agg(win, by):
        s, e = win
        return _window_agg(con, s, e, by)

    cur_win, prior_win = (cur_start, cur_end), (prior_start, prior_end)

    # ── Executive KPIs ───────────────────────────────────────────────────────
    tot_c = agg(cur_win, []).iloc[0]
    tot_p = agg(prior_win, []).iloc[0]
    total_cur_value = float(tot_c["value"])

    def growth(c, p):
        return (c / p - 1) if p else np.nan

    asp_c = tot_c["value"] / tot_c["units"] if tot_c["units"] else np.nan
    asp_p = tot_p["value"] / tot_p["units"] if tot_p["units"] else np.nan

    # ── Store × category exception engine ────────────────────────────────────
    seg = _compare(agg(cur_win, ["store_key", "state_id", "cat_id"]),
                   agg(prior_win, ["store_key", "state_id", "cat_id"]),
                   ["store_key", "state_id", "cat_id"])
    seg["contribution_share"] = seg["value_cur"] / total_cur_value

    # Priority score = Impact × Magnitude × Confidence (all in [0,1] before scaling)
    #   Impact      = share of current sales value the segment represents
    #   Magnitude   = size of the unit-demand move
    #   Confidence  = volume-based reliability (thin history is noisier -> discounted)
    conf_floor = seg["units_prior"].median()
    seg["confidence"] = np.clip(seg["units_prior"] / conf_floor, 0, 1) if conf_floor else 1.0
    seg["priority_score"] = (100 * seg["contribution_share"].clip(lower=0)
                             * seg["demand_growth"].abs() * seg["confidence"]).round(1)

    def classify(r):
        big = r["contribution_share"] >= th["min_contribution_share"]
        if r["price_change"] >= th["price_increase"] and r["demand_growth"] <= th["demand_decline"]:
            return "Price ↑ / demand ↓"
        if big and r["demand_growth"] <= th["demand_decline"]:
            return "Demand deterioration"
        if big and r["demand_growth"] >= th["demand_growth_high"]:
            return "Strong growth"
        return None

    seg["signal"] = seg.apply(classify, axis=1)
    exc = seg[seg["signal"].notna()].copy().sort_values("priority_score", ascending=False)
    exc["priority"] = "Low"                       # ensure the column exists even if empty
    # Relative banding: top / middle / bottom third of what was flagged.
    if len(exc):
        q1, q2 = exc["priority_score"].quantile([1 / 3, 2 / 3])
        exc["priority"] = np.where(exc["priority_score"] >= q2, "High",
                          np.where(exc["priority_score"] >= q1, "Medium", "Low"))
    exc_out = exc[["priority", "store_key", "state_id", "cat_id", "signal",
                   "demand_growth", "price_change", "contribution_share",
                   "value_delta", "priority_score"]].round(4)
    exc_out.to_csv(ext / "exceptions_store_category.csv", index=False)

    at_risk_value = float(seg.loc[seg["signal"] == "Demand deterioration", "value_cur"].sum())

    # ── Contribution (category, store) ───────────────────────────────────────
    for grain, name in [(["cat_id"], "category"), (["store_key", "state_id"], "store")]:
        c = _compare(agg(cur_win, grain), agg(prior_win, grain), grain)
        total_delta = c["value_delta"].sum()
        c["contribution_share"] = c["value_cur"] / total_cur_value
        c["share_of_change"] = c["value_delta"] / total_delta if total_delta else np.nan
        c.sort_values("value_delta", ascending=False).round(4).to_csv(
            ext / f"contribution_{name}.csv", index=False)

    # ── Price–demand association (store × category) ──────────────────────────
    pdrel = seg[["store_key", "state_id", "cat_id", "demand_growth", "price_change",
                 "value_cur"]].copy()
    pdrel["note"] = pdrel.apply(
        lambda r: f"units {r['demand_growth']:+.1%} alongside ASP {r['price_change']:+.1%}"
        if pd.notna(r["demand_growth"]) and pd.notna(r["price_change"]) else "", axis=1)
    pdrel.round(4).to_csv(ext / "price_demand.csv", index=False)

    # ── Item movers (biggest value gainers / losers) ─────────────────────────
    it = _compare(agg(cur_win, ["product_key", "dept_id", "cat_id"]),
                  agg(prior_win, ["product_key", "dept_id", "cat_id"]),
                  ["product_key", "dept_id", "cat_id"])
    it["contribution_share"] = it["value_cur"] / total_cur_value
    # Ranking by absolute $ change is already noise-resistant (a tiny item cannot
    # swing thousands of dollars), so a volume floor is enough — unlike a share
    # floor, it stays meaningful whether there are 210 items or 3,049.
    it_big = it[it["units_prior"] >= th["min_prior_units"]]
    movers = pd.concat([
        it_big.nlargest(10, "value_delta").assign(direction="Gainer"),
        it_big.nsmallest(10, "value_delta").assign(direction="Decliner"),
    ])[["direction", "product_key", "dept_id", "cat_id", "demand_growth",
        "price_change", "value_delta", "contribution_share"]].round(4)
    movers.to_csv(ext / "item_movers.csv", index=False)

    # ── Price-risk items (price ↑ while demand ↓) at STORE × ITEM grain ──────
    # Price changes live per store-item, so this is where the signal is cleanest.
    # A volume floor on prior-period units keeps intermittent noise out.
    si = _compare(agg(cur_win, ["store_key", "product_key", "dept_id", "cat_id"]),
                  agg(prior_win, ["store_key", "product_key", "dept_id", "cat_id"]),
                  ["store_key", "product_key", "dept_id", "cat_id"])
    risk = si[(si["price_change"] >= th["price_increase"]) &
              (si["demand_growth"] <= th["demand_decline"]) &
              (si["units_prior"] >= th["min_prior_units"])].copy()
    risk = risk.sort_values("value_delta").head(15)[
        ["store_key", "product_key", "dept_id", "cat_id", "price_change",
         "demand_growth", "value_delta", "units_prior"]].round(4)
    risk.to_csv(ext / "price_risk_items.csv", index=False)

    # ── Concentration risk (scale-free: adaptive top-k share + HHI) ──────────
    def _concentration(df, label):
        shares = np.sort(df["value"].to_numpy())[::-1] / df["value"].sum()
        n = len(shares)
        k = min(int(th["concentration_top_n"]), max(1, round(n * 0.3)))
        return {"dimension": label, "universe": n, "top_k": k,
                "top_k_share": float(shares[:k].sum()),
                "hhi": float((shares ** 2).sum())}   # Herfindahl index, 1/n … 1
    conc = pd.DataFrame([
        _concentration(agg(cur_win, ["product_key"]), "products"),
        _concentration(agg(cur_win, ["store_key"]), "stores"),
    ]).round(4)
    conc.to_csv(ext / "concentration.csv", index=False)

    # ── Headline KPI table (tidy) + summary json ─────────────────────────────
    kpis = pd.DataFrame([
        {"metric": "Estimated Sales Value", "current": round(float(tot_c["value"]), 2),
         "prior": round(float(tot_p["value"]), 2), "growth": round(growth(tot_c["value"], tot_p["value"]), 4)},
        {"metric": "Units Sold", "current": int(tot_c["units"]), "prior": int(tot_p["units"]),
         "growth": round(growth(tot_c["units"], tot_p["units"]), 4)},
        {"metric": "Avg Selling Price", "current": round(float(asp_c), 4),
         "prior": round(float(asp_p), 4), "growth": round(growth(asp_c, asp_p), 4)},
        {"metric": "At-Risk Value (deteriorating segments)", "current": round(at_risk_value, 2),
         "prior": np.nan, "growth": np.nan},
    ])
    kpis.to_csv(ext / "kpi_summary.csv", index=False)

    summary = {
        "mode": cfg["data_source"]["mode"],
        "period_days": pdays,
        "current_window": [str(cur_start), str(cur_end)],
        "prior_window": [str(prior_start), str(prior_end)],
        "comparison_basis": basis,
        "like_for_like": comparable,
        "sales_value_growth": round(growth(tot_c["value"], tot_p["value"]), 4),
        "units_growth": round(growth(tot_c["units"], tot_p["units"]), 4),
        "asp_growth": round(growth(asp_c, asp_p), 4),
        "at_risk_value": round(at_risk_value, 2),
        "exceptions_flagged": int(len(exc)),
        "top_concentration_share_products": float(conc.loc[conc.dimension == "products", "top_k_share"].iloc[0]),
    }
    (ext / "metrics_summary.json").write_text(json.dumps(summary, indent=2))

    print(f"[metrics] window {cur_start}→{cur_end} vs {prior_start}→{prior_end} ({basis})")
    print(f"[metrics] sales value {summary['sales_value_growth']:+.1%}, "
          f"units {summary['units_growth']:+.1%}, ASP {summary['asp_growth']:+.1%}, "
          f"{len(exc)} exceptions flagged")
    print(f"[metrics] {8} analytical tables → dashboard/extracts/")
    return summary


if __name__ == "__main__":
    import duckdb

    cfg = load_config()
    con = duckdb.connect(str(path(cfg["data_source"]["processed_dir"], "rci.duckdb")))
    build_metrics(con, cfg)
