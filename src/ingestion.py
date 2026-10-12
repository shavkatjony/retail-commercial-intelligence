"""Ingestion & reshaping — the Python half of the pipeline.

Reads the three raw M5 CSVs (real or synthetic; identical schema), reshapes the
WIDE sales table (one column per day, d_1 … d_N) into a TIDY LONG table (one row
per item-store-day), attaches the real calendar date, and writes typed staging
files as Parquet for the SQL layer to build on.

Two memory decisions make the real ~59M-row reshape fit on a laptop:
  1. STREAM BY STORE — melt one store (~5.9M rows) at a time and append each
     chunk to a single Parquet file, instead of materializing all 59M rows.
  2. CATEGORICALS — every text column (item, store, day, …) has few distinct
     values, so each row holds a 2-byte code instead of a Python string. Parquet
     stores them dictionary-encoded anyway; DuckDB reads them back as VARCHAR.

Why Parquet as the hand-off: columnar, typed, ~10x smaller than CSV, and DuckDB
reads it directly — the SQL layer starts from clean, typed inputs.
"""
from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import load_config, processed_dir, raw_dir

ID_VARS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]


def _read_raw(cfg: dict):
    r = raw_dir(cfg)
    f = cfg["data_source"]["files"]
    # keep_default_na=False so the empty-string event cells stay "" (not NaN).
    calendar = pd.read_csv(r / f["calendar"], keep_default_na=False)
    prices = pd.read_csv(r / f["prices"],
                         dtype={"store_id": "category", "item_id": "category"})
    header = pd.read_csv(r / f["sales"], nrows=0).columns
    sales = pd.read_csv(r / f["sales"], dtype={
        **{c: "category" for c in ID_VARS},
        **{c: "int32" for c in header if c.startswith("d_")}})
    return calendar, prices, sales


def ingest(cfg: dict | None = None) -> dict:
    """Reshape + type the raw files; write staging Parquet. Returns row counts."""
    cfg = cfg or load_config()
    out = processed_dir(cfg)
    calendar, prices, sales = _read_raw(cfg)

    calendar = calendar.copy()
    calendar["date"] = pd.to_datetime(calendar["date"])

    # Date + fiscal week per day column, aligned to the d_1..d_N order (the real
    # calendar runs past the last sales day, so align by name, not position).
    day_cols = [c for c in sales.columns if c.startswith("d_")]
    by_day = calendar.set_index("d").loc[day_cols]
    dates_by_day = by_day["date"].to_numpy()
    weeks_by_day = by_day["wm_yr_wk"].to_numpy()

    # ── Reshape: wide (d_1..d_N) -> long, streamed one store at a time ───────
    # Categories are global (read once for the whole file), so every chunk has
    # identical dictionaries and therefore an identical Parquet schema.
    rows, writer = 0, None
    for _, chunk in sales.groupby("store_id", sort=True, observed=True):
        long = chunk.melt(id_vars=ID_VARS, value_vars=day_cols,
                          var_name="d", value_name="units")
        long["units"] = long["units"].astype("int32", copy=False)
        long["d"] = pd.Categorical(long["d"], categories=day_cols)
        codes = long["d"].cat.codes.to_numpy()
        long["date"] = dates_by_day[codes]                 # attach the real date
        long["wm_yr_wk"] = weeks_by_day[codes]
        table = pa.Table.from_pandas(long, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(out / "stg_sales_long.parquet", table.schema)
        writer.write_table(table)
        rows += len(long)
    writer.close()

    calendar.to_parquet(out / "stg_calendar.parquet", index=False)
    prices.to_parquet(out / "stg_prices.parquet", index=False)

    counts = {
        "sales_series": len(sales),
        "sales_long_rows": rows,
        "calendar_rows": len(calendar),
        "price_rows": len(prices),
    }
    print(f"[ingest] wide→long: {len(sales):,} series × {len(day_cols)} days "
          f"→ {rows:,} rows (streamed by store)")
    print(f"[ingest] staging written to {out}")
    return counts


if __name__ == "__main__":
    ingest()
