"""Data-quality validation layer.

Runs production-style checks against the built star schema and writes
docs/data_quality_report.md. Hard checks (duplicate grain, broken referential
integrity, impossible values, null date keys) FAIL the build; coverage/continuity
issues WARN. The point is to present as someone who ships trustworthy pipelines,
not just charts.
"""
from __future__ import annotations

from datetime import datetime

from config import load_config, path

OK, WARN, FAIL = "PASS", "WARN", "FAIL"
_ICON = {OK: "✅", WARN: "⚠️", FAIL: "❌"}


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def validate(con, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    checks: list[tuple[str, str, str]] = []   # (name, status, detail)

    # ── Shape / row counts ───────────────────────────────────────────────────
    n_fact = _scalar(con, "SELECT COUNT(*) FROM fact_daily_sales")
    n_series = _scalar(con, "SELECT COUNT(*) FROM (SELECT DISTINCT product_key, store_key FROM fact_daily_sales)")
    # Sales days, not calendar days: the real M5 calendar runs 28 days past the
    # last sales day, so dim_date would give the wrong denominator.
    n_days = _scalar(con, "SELECT COUNT(DISTINCT date_key) FROM fact_daily_sales")
    complete = n_fact == n_series * n_days
    checks.append(("Complete panel (rows = series × sales days)", OK if complete else FAIL,
                   f"{n_fact:,} {'=' if complete else '≠'} {n_series:,} series × {n_days:,} days"))

    # ── Duplicate grain (the single most important structural check) ─────────
    dup = _scalar(con, """
        SELECT COUNT(*) FROM (
            SELECT date_key, product_key, store_key
            FROM fact_daily_sales
            GROUP BY 1, 2, 3 HAVING COUNT(*) > 1)""")
    checks.append(("Unique grain (date × product × store)", OK if dup == 0 else FAIL,
                   f"{dup:,} duplicated grain keys"))

    # ── Null keys ────────────────────────────────────────────────────────────
    nd = _scalar(con, "SELECT COUNT(*) FROM fact_daily_sales WHERE date_key IS NULL")
    checks.append(("No null date keys", OK if nd == 0 else FAIL, f"{nd:,} null date keys"))

    # ── Impossible values ────────────────────────────────────────────────────
    neg_u = _scalar(con, "SELECT COUNT(*) FROM fact_daily_sales WHERE units < 0")
    checks.append(("No negative units", OK if neg_u == 0 else FAIL, f"{neg_u:,} rows units < 0"))
    neg_p = _scalar(con, "SELECT COUNT(*) FROM fact_daily_sales WHERE sell_price < 0")
    checks.append(("No negative prices", OK if neg_p == 0 else FAIL, f"{neg_p:,} rows price < 0"))

    # ── Referential integrity (fact → each dimension) ────────────────────────
    orphan_p = _scalar(con, "SELECT COUNT(*) FROM fact_daily_sales f LEFT JOIN dim_product d ON f.product_key=d.product_key WHERE d.product_key IS NULL")
    orphan_s = _scalar(con, "SELECT COUNT(*) FROM fact_daily_sales f LEFT JOIN dim_store d ON f.store_key=d.store_key WHERE d.store_key IS NULL")
    orphan_d = _scalar(con, "SELECT COUNT(*) FROM fact_daily_sales f LEFT JOIN dim_date d ON f.date_key=d.date_key WHERE d.date_key IS NULL")
    orph = orphan_p + orphan_s + orphan_d
    checks.append(("Referential integrity (fact → dims)", OK if orph == 0 else FAIL,
                   f"{orphan_p:,} product / {orphan_s:,} store / {orphan_d:,} date orphans"))

    # ── Date continuity (no missing days) ────────────────────────────────────
    gaps = _scalar(con, """
        WITH dd AS (SELECT date_key, LAG(date_key) OVER (ORDER BY date_key) AS prev FROM dim_date)
        SELECT COUNT(*) FROM dd WHERE prev IS NOT NULL AND (date_key - prev) <> 1""")
    checks.append(("Daily calendar continuity", OK if gaps == 0 else WARN,
                   f"{gaps:,} gaps in the daily calendar"))

    # ── Price coverage (WARN, not FAIL — missing price is meaningful in M5) ───
    cov = _scalar(con, "SELECT 100.0*AVG(CASE WHEN sell_price IS NOT NULL THEN 1 ELSE 0 END) FROM fact_daily_sales")
    checks.append(("Price coverage", OK if cov > 99.9 else WARN,
                   f"{cov:.2f}% of sales rows carry a price"))

    # ── Summarize + write the report ─────────────────────────────────────────
    hard = sum(1 for _, s, _ in checks if s == FAIL)
    warn = sum(1 for _, s, _ in checks if s == WARN)
    _write_report(cfg, checks, hard, warn, n_fact, n_series, n_days)

    status = "FAILED" if hard else ("passed with warnings" if warn else "passed clean")
    print(f"[validate] {len(checks)} checks — {status} "
          f"({hard} fail, {warn} warn) → docs/data_quality_report.md")
    return {"checks": checks, "hard_failures": hard, "warnings": warn}


def _write_report(cfg, checks, hard, warn, n_fact, n_series, n_days) -> None:
    mode = cfg["data_source"]["mode"]
    lines = [
        "# Data Quality Report",
        "",
        f"- **Generated:** {datetime.now():%Y-%m-%d %H:%M}",
        f"- **Data source:** `{mode}`"
        + ("  *(synthetic scaffold — not a source of findings)*" if mode == "sample" else ""),
        f"- **Fact table:** `fact_daily_sales` — {n_fact:,} rows "
        f"({n_series:,} series × {n_days:,} days)",
        f"- **Result:** {'❌ FAILED' if hard else ('⚠️ passed with warnings' if warn else '✅ passed clean')} "
        f"— {hard} fail / {warn} warn / {len(checks)} checks",
        "",
        "| Check | Status | Detail |",
        "| --- | :---: | --- |",
    ]
    for name, status, detail in checks:
        lines.append(f"| {name} | {_ICON[status]} {status} | {detail} |")
    lines += [
        "",
        "> Hard checks (unique grain, referential integrity, impossible values, "
        "null keys) block the build. Coverage and continuity checks warn only — a "
        "missing weekly price in M5 legitimately means the item was not on sale.",
        "",
    ]
    (path("docs") / "data_quality_report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    import duckdb

    cfg = load_config()
    con = duckdb.connect(str(path(cfg["data_source"]["processed_dir"], "rci.duckdb")))
    validate(con, cfg)
