"""Refresh the self-contained HTML dashboard's data block.

The dashboard is ONE file — dashboard/index.html — that carries its data inline in
a `<script id="rci-data" type="application/json">` tag. This script reads the
current extracts (+ a few compact aggregates from DuckDB) and rewrites ONLY that
tag, leaving the template, CONFIG, styles, and rendering code untouched.

So the workflow is:
  * edit the LOOK / layout / CONFIG  → hand-edit dashboard/index.html
  * refresh the NUMBERS               → run this (or `make all` / `make html`)

Run standalone:  python src/build_html.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import duckdb
import pandas as pd

from config import load_config, path, processed_dir

EXT = path("dashboard", "extracts")
HTML = path("dashboard", "index.html")


def _csv(name: str) -> list[dict]:
    df = pd.read_csv(EXT / name)
    return json.loads(df.to_json(orient="records"))


def collect_data(cfg: dict) -> dict:
    con = duckdb.connect(str(processed_dir(cfg) / "rci.duckdb"), read_only=True)
    summary = json.loads((EXT / "metrics_summary.json").read_text())

    # ── Company + category monthly trend (single-axis; the UI toggles metric) ─
    mm = pd.read_csv(EXT / "mart_monthly.csv")
    mm["month"] = pd.to_datetime(mm["month_start"]).dt.strftime("%Y-%m")
    comp = mm.groupby("month", as_index=False).agg(sales_value=("sales_value", "sum"),
                                                    units=("units", "sum"))
    by_cat = mm.groupby(["month", "cat_id"], as_index=False)["sales_value"].sum()
    cats = sorted(mm["cat_id"].unique())
    trend_by_cat = {c: [round(float(by_cat[(by_cat.month == m) & (by_cat.cat_id == c)]
                       ["sales_value"].sum()), 2) for m in comp["month"]] for c in cats}

    # ── Diagnostics: per state×store×category monthly (small; drives filters) ─
    seg = mm[["month", "state_id", "store_key", "cat_id", "units", "sales_value",
              "avg_selling_price"]].round(3)

    # ── Global seasonality / event / SNAP context (compact aggregates) ───────
    # Average units per item-day, read from the small segment mart (~58k rows at
    # real scale) instead of the 59M-row daily view. SUM(units)/SUM(item_days)
    # is exactly AVG(units) over item-days.
    dow = con.execute("""
        SELECT wday, SUM(units) / SUM(item_days) u
        FROM mart_daily_segment GROUP BY 1 ORDER BY 1""").df()
    dow_labels = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]
    event = con.execute("""
        SELECT cat_id,
               SUM(units)     FILTER (WHERE event_name IS NOT NULL)
             / SUM(item_days) FILTER (WHERE event_name IS NOT NULL) ev,
               SUM(units)     FILTER (WHERE event_name IS NULL)
             / SUM(item_days) FILTER (WHERE event_name IS NULL)     base
        FROM mart_daily_segment GROUP BY 1 ORDER BY 1""").df()
    event_lift = [{"cat": r.cat_id, "lift_pct": round(100 * (r.ev / r.base - 1), 1)}
                  for r in event.itertuples()]
    snap = con.execute("""
        SELECT snap_active, SUM(units) / SUM(item_days) u FROM mart_daily_segment
        WHERE cat_id = 'FOODS' GROUP BY 1 ORDER BY 1""").df()
    snap_foods = {"non": round(float(snap.u.iloc[0]), 3), "snap": round(float(snap.u.iloc[1]), 3),
                  "lift_pct": round(100 * (snap.u.iloc[1] / snap.u.iloc[0] - 1), 1)}
    con.close()

    kpi = pd.read_csv(EXT / "kpi_summary.csv")
    kpis = [
        {"key": "sales_value", "label": "Estimated Sales Value", "unit": "money",
         "value": float(kpi.loc[0, "current"]), "growth": float(kpi.loc[0, "growth"])},
        {"key": "units", "label": "Units Sold", "unit": "int",
         "value": float(kpi.loc[1, "current"]), "growth": float(kpi.loc[1, "growth"])},
        {"key": "asp", "label": "Avg Selling Price", "unit": "price",
         "value": float(kpi.loc[2, "current"]), "growth": float(kpi.loc[2, "growth"])},
        {"key": "at_risk", "label": "At-Risk Value", "unit": "money",
         "value": float(kpi.loc[3, "current"]), "growth": None},
    ]

    return {
        "meta": {
            "mode": summary["mode"],
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "current_window": summary["current_window"],
            "prior_window": summary["prior_window"],
            "basis": summary["comparison_basis"],
            "like_for_like": summary["like_for_like"],
        },
        "kpis": kpis,
        "trend": {"months": comp["month"].tolist(),
                  "sales_value": [round(v, 2) for v in comp["sales_value"]],
                  "units": [int(v) for v in comp["units"]]},
        "trend_by_cat": {"months": comp["month"].tolist(), "cats": trend_by_cat},
        "contribution_category": _csv("contribution_category.csv"),
        "contribution_store": _csv("contribution_store.csv"),
        "exceptions": _csv("exceptions_store_category.csv"),
        "movers": _csv("item_movers.csv"),
        "price_risk": _csv("price_risk_items.csv"),
        "concentration": _csv("concentration.csv"),
        "price_demand": _csv("price_demand.csv"),
        "diag": {
            "segments_monthly": json.loads(seg.to_json(orient="records")),
            "dow": {"labels": dow_labels, "units": [round(float(x), 2) for x in dow.u]},
            "event_lift": event_lift,
            "snap_foods": snap_foods,
        },
    }


def inject(data: dict) -> None:
    if not HTML.exists():
        raise SystemExit(f"[html] {HTML} not found — the template must exist first.")
    html = HTML.read_text()
    blob = json.dumps(data, separators=(",", ":"))
    pattern = re.compile(
        r'(<script id="rci-data" type="application/json">)(.*?)(</script>)', re.DOTALL)
    if not pattern.search(html):
        raise SystemExit('[html] data script tag not found in index.html.')
    HTML.write_text(pattern.sub(lambda m: m.group(1) + blob + m.group(3), html))
    print(f"[html] injected {len(blob):,} bytes of data → dashboard/index.html "
          f"(mode: {data['meta']['mode']})")


def main() -> None:
    inject(collect_data(load_config()))


if __name__ == "__main__":
    main()
