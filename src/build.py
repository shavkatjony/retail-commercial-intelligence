"""Orchestrator — raw data to decision-ready outputs in one command.

    generate (sample mode)  ->  ingest  ->  SQL star schema  ->  validate
    ->  metrics  ->  export Tableau extracts

The whole project is reproducible from `python src/build.py` (or `make all`).
A hard data-quality failure stops the build with a non-zero exit code, so a
broken pipeline can never silently produce a dashboard.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import duckdb

import build_html
import make_figures
import metrics
import validation
from config import load_config, path, processed_dir, raw_dir

SQL_FILES = [
    "01_staging.sql", "02_dimensions.sql", "03_fact_sales.sql",
    "04_fact_prices.sql", "05_kpi_queries.sql",
]

RAW_VIEWS = [
    ("raw_calendar", "stg_calendar.parquet"),
    ("raw_prices", "stg_prices.parquet"),
    ("raw_sales_long", "stg_sales_long.parquet"),
]


def _ensure_raw(cfg) -> None:
    """In sample mode, generate the synthetic files if missing. In real mode,
    require the user's downloaded M5 files and fail loudly with instructions."""
    mode = cfg["data_source"]["mode"]
    sales = raw_dir(cfg) / cfg["data_source"]["files"]["sales"]
    if mode == "sample":
        if not sales.exists():
            print("[build] sample mode: generating synthetic M5 data …")
            import generate_sample
            generate_sample.main()
        else:
            print("[build] sample mode: using existing synthetic data in data/raw/")
    else:
        missing = [f for f in cfg["data_source"]["files"].values()
                   if not (raw_dir(cfg) / f).exists()]
        if missing:
            sys.exit(f"[build] real mode: missing files in data/raw/: {missing}\n"
                     "        Download the M5 CSVs from Kaggle "
                     "(competition: m5-forecasting-accuracy) and place them there.")


def _ingest_isolated() -> None:
    """Run ingestion in its own process. When it exits, its pandas heap goes
    back to the OS, so the DuckDB stages don't stack on top of it: peak memory
    is the largest single stage, not the sum of all of them."""
    subprocess.run([sys.executable, str(path("src", "ingestion.py"))], check=True)


def _register_raw(con, proc: Path) -> None:
    for name, file in RAW_VIEWS:
        con.execute(f"CREATE OR REPLACE VIEW {name} AS "
                    f"SELECT * FROM read_parquet('{(proc / file).as_posix()}')")


def _run_sql(con) -> None:
    for f in SQL_FILES:
        con.execute(path("sql", f).read_text())
        print(f"[sql] ran {f}")


TABLEAU_MARTS = ["mart_monthly", "mart_monthly_item", "mart_daily_segment"]


def _export_marts(con, ext: Path) -> None:
    # The daily item grain (mart_daily) is never exported — at real M5 scale it is
    # ~59M rows, far past Tableau Public's 15M-row limit. These marts are sized
    # to what each dashboard page needs (see sql/05_kpi_queries.sql).
    sizes = []
    for mart in TABLEAU_MARTS:
        con.execute(f"COPY {mart} TO '{(ext / f'{mart}.csv').as_posix()}' (HEADER)")
        sizes.append(f"{mart} ({con.execute(f'SELECT COUNT(*) FROM {mart}').fetchone()[0]:,})")
    print(f"[export] {', '.join(sizes)} → dashboard/extracts/")


def main() -> None:
    t0 = time.time()
    cfg = load_config()
    proc = processed_dir(cfg)
    ext = path("dashboard", "extracts")
    ext.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Retail Commercial Intelligence — build ({cfg['data_source']['mode']} mode) ===")
    _ensure_raw(cfg)
    _ingest_isolated()

    db = proc / "rci.duckdb"
    if db.exists():
        db.unlink()                       # fresh build every time
    con = duckdb.connect(str(db))
    # Bounded memory: spill to disk past the cap instead of exhausting a laptop;
    # dropping insertion order lets large CREATE TABLE AS statements stream.
    con.execute(f"SET memory_limit = '{cfg['engine']['duckdb_memory_limit']}'")
    con.execute("SET preserve_insertion_order = false")
    _register_raw(con, proc)
    _run_sql(con)

    result = validation.validate(con, cfg)
    if result["hard_failures"]:
        con.close()
        sys.exit(f"[build] ABORTED — {result['hard_failures']} hard data-quality failure(s). "
                 "See docs/data_quality_report.md")

    metrics.build_metrics(con, cfg)
    _export_marts(con, ext)
    con.close()

    build_html.main()     # refresh the self-contained HTML dashboard's data block
    make_figures.main()   # re-render the README hero figure from the same outputs

    print(f"=== build complete in {time.time() - t0:.1f}s → dashboard/extracts/ ===\n")


if __name__ == "__main__":
    main()
