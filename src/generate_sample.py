"""Generate a realistic, M5-shaped SYNTHETIC dataset.

WHY THIS EXISTS
---------------
The real M5 data lives behind Kaggle's competition rules and is ~450 MB, so it
cannot be committed or auto-downloaded. This script fabricates data with the
*exact same schema and filenames* as real M5 so the whole pipeline runs today.

    >>>  It is a DEVELOPMENT SCAFFOLD, not a source of business findings.  <<<

The synthetic process deliberately bakes in the structure a commercial analyst
must be able to detect: intermittent demand (lots of zeros), day-of-week and
yearly seasonality, holiday/event spikes, SNAP effects on FOODS, price changes
with genuine price elasticity, and a planted minority of strongly growing /
declining series so the exception engine has something true to surface.

To use the REAL data instead: download the three M5 CSVs into data/raw/, set
`data_source.mode: real` in config.yaml, and do NOT run this script — nothing
else changes.

Output (into data/raw/, matching real M5 column-for-column):
    calendar.csv              date, wm_yr_wk, weekday, wday, month, year, d,
                              event_name_1, event_type_1, event_name_2,
                              event_type_2, snap_CA, snap_TX, snap_WI
    sell_prices.csv           store_id, item_id, wm_yr_wk, sell_price
    sales_train_evaluation.csv  id, item_id, dept_id, cat_id, store_id,
                              state_id, d_1 .. d_N
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from config import load_config, raw_dir

# ── Event effects ────────────────────────────────────────────────────────────
# Per-event, per-category demand multiplier. Missing category -> 1.0 (no effect).
# Christmas is special: US stores are closed, so units are forced to 0 that day
# (a well-known feature of the real M5 series).
EVENT_EFFECTS = {
    "NewYear":         ("National",  {"FOODS": 1.25, "HOBBIES": 1.10}),
    "ValentinesDay":   ("Cultural",  {"FOODS": 1.20, "HOBBIES": 1.25}),
    "SuperBowl":       ("Sporting",  {"FOODS": 1.45, "HOUSEHOLD": 1.10}),
    "Easter":          ("Religious", {"FOODS": 1.30, "HOBBIES": 1.15}),
    "MothersDay":      ("Cultural",  {"FOODS": 1.15, "HOBBIES": 1.25}),
    "IndependenceDay": ("National",  {"FOODS": 1.35}),
    "LaborDay":        ("National",  {"FOODS": 1.20}),
    "Halloween":       ("Cultural",  {"HOBBIES": 1.55, "FOODS": 1.20}),
    "Thanksgiving":    ("National",  {"FOODS": 1.60, "HOUSEHOLD": 1.15, "HOBBIES": 1.20}),
    "Christmas":       ("National",  {}),   # stores closed -> handled as 0 units
    "NewYearEve":      ("Cultural",  {"FOODS": 1.30}),
}

# Day-of-week demand shape, indexed by M5 `wday` (1=Saturday … 7=Friday).
DOW_FACTOR = {1: 1.30, 2: 1.25, 3: 0.90, 4: 0.85, 5: 0.85, 6: 0.95, 7: 1.15}

# Per-department baseline demand level (log-space mean). FOODS moves volume;
# HOBBIES is thin and intermittent — this is what creates realistic zeros.
DEPT_BASE_MU = {
    "FOODS_1": 1.1, "FOODS_2": 1.0, "FOODS_3": 1.3,
    "HOUSEHOLD_1": 0.2, "HOUSEHOLD_2": 0.0,
    "HOBBIES_1": -0.4, "HOBBIES_2": -0.6,
}
# Per-department typical unit price (log-space mean), USD.
DEPT_PRICE_MU = {
    "FOODS_1": 1.1, "FOODS_2": 1.3, "FOODS_3": 0.9,
    "HOUSEHOLD_1": 2.3, "HOUSEHOLD_2": 2.6,
    "HOBBIES_1": 1.9, "HOBBIES_2": 2.1,
}


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th `weekday` (Mon=0..Sun=6) of a given month, e.g. 4th Thursday."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def build_event_calendar(years: list[int]) -> dict[date, str]:
    """Map each holiday date -> event name for the years the data spans."""
    events: dict[date, str] = {}
    for y in years:
        events[date(y, 1, 1)] = "NewYear"
        events[date(y, 2, 14)] = "ValentinesDay"
        events[nth_weekday(y, 2, 6, 1)] = "SuperBowl"          # 1st Sunday of Feb (approx)
        events[nth_weekday(y, 5, 6, 2)] = "MothersDay"         # 2nd Sunday of May
        events[date(y, 7, 4)] = "IndependenceDay"
        events[nth_weekday(y, 9, 0, 1)] = "LaborDay"           # 1st Monday of Sep
        events[date(y, 10, 31)] = "Halloween"
        events[nth_weekday(y, 11, 3, 4)] = "Thanksgiving"      # 4th Thursday of Nov
        events[date(y, 12, 25)] = "Christmas"
        events[date(y, 12, 31)] = "NewYearEve"
    # Easter (Anonymous Gregorian algorithm) — a Religious, moving-date event.
    for y in years:
        a = y % 19
        b, c = divmod(y, 100)
        d_, e = divmod(b, 4)
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d_ - g + 15) % 30
        i, k = divmod(c, 4)
        L = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * L) // 451
        month = (h + L - 7 * m + 114) // 31
        day = ((h + L - 7 * m + 114) % 31) + 1
        events[date(y, month, day)] = "Easter"
    return events


def build_calendar(start: date, n_days: int) -> pd.DataFrame:
    """Construct the M5 `calendar.csv` table."""
    dates = [start + timedelta(days=i) for i in range(n_days)]
    events = build_event_calendar(sorted({d.year for d in dates}))

    # M5 weeks start on Saturday; wm_yr_wk is a running fiscal week key.
    anchor = start - timedelta(days=(start.weekday() + 2) % 7)   # Saturday on/before start
    rows = []
    for i, d in enumerate(dates):
        wk = (d - anchor).days // 7
        wm_yr_wk = (start.year % 100 + wk // 52) * 100 + (wk % 52 + 1)
        wday = ((d.weekday() + 2) % 7) + 1                       # Sat=1 … Fri=7
        ev = events.get(d)
        rows.append({
            "date": d.isoformat(),
            "wm_yr_wk": wm_yr_wk,
            "weekday": d.strftime("%A"),
            "wday": wday,
            "month": d.month,
            "year": d.year,
            "d": f"d_{i + 1}",
            "event_name_1": ev if ev else "",
            "event_type_1": EVENT_EFFECTS[ev][0] if ev else "",
            "event_name_2": "",
            "event_type_2": "",
            # SNAP: benefits are issued early in the month; states stagger slightly.
            "snap_CA": int(1 <= d.day <= 10),
            "snap_TX": int(1 <= d.day <= 3 or 11 <= d.day <= 13 or 15 <= d.day <= 17),
            "snap_WI": int(2 <= d.day <= 12),
        })
    return pd.DataFrame(rows)


def main() -> None:
    cfg = load_config()
    s = cfg["sample"]
    rng = np.random.default_rng(s["seed"])
    out = raw_dir(cfg)

    start = date.fromisoformat(s["start_date"])
    n_days = int(s["n_days"])
    calendar = build_calendar(start, n_days)
    n = len(calendar)

    # ── Per-day vectors shared by every series (season, dow, snap, events) ────
    t = np.arange(n)
    doy = np.array([(start + timedelta(days=int(i))).timetuple().tm_yday for i in t])
    # Yearly seasonality: a gentle sine plus a Nov–Dec holiday ramp.
    season = 1.0 + 0.12 * np.sin(2 * np.pi * (doy - 80) / 365.25)
    month = calendar["month"].to_numpy()
    season = season * np.where(month == 11, 1.15, 1.0) * np.where(month == 12, 1.30, 1.0)
    dow = calendar["wday"].map(DOW_FACTOR).to_numpy()
    week_of_day = ((pd.to_datetime(calendar["date"]) -
                    pd.Timestamp(start - timedelta(days=(start.weekday() + 2) % 7)))
                   .dt.days // 7).to_numpy()
    n_weeks = int(week_of_day.max()) + 1
    snap = {st: calendar[f"snap_{st}"].to_numpy() for st in ("CA", "TX", "WI")}
    christmas = (calendar["event_name_1"] == "Christmas").to_numpy()

    # Per-category event multiplier vectors (built once, reused across series).
    cats = ("FOODS", "HOUSEHOLD", "HOBBIES")
    event_mult = {c: np.ones(n) for c in cats}
    for j, name in enumerate(calendar["event_name_1"]):
        if name and name in EVENT_EFFECTS:
            for c, mult in EVENT_EFFECTS[name][1].items():
                event_mult[c][j] = mult

    # ── Build the item catalog and store list ────────────────────────────────
    stores = [(st, store) for st, lst in s["stores"].items() for store in lst]
    store_factor = {store: rng.uniform(0.6, 1.4) for _, store in stores}
    store_price_adj = {store: rng.uniform(0.95, 1.05) for _, store in stores}

    # Store × category systematic trend — the EXECUTIVE-level signal. A store's
    # food business can be growing while its hobbies business shrinks; a minority
    # move hard. This is what the exception engine is meant to surface, so it must
    # exist in the data (item-level trends alone average out at this grain).
    def _draw_growth() -> float:
        r = rng.random()
        if r < 0.12:
            return rng.uniform(-0.30, -0.18)     # strong segment decline
        if r < 0.24:
            return rng.uniform(0.18, 0.35)       # strong segment growth
        return rng.normal(0.0, 0.05)
    store_cat_growth = {(store, cat): _draw_growth()
                        for _, store in stores for cat in s["departments"]}

    items = []   # (item_id, dept_id, cat_id, base_mu, elasticity, base_price, growth)
    for cat, depts in s["departments"].items():
        for dept in depts:
            for k in range(int(s["items_per_department"])):
                item_id = f"{dept}_{k + 1:03d}"
                base_mu = DEPT_BASE_MU[dept] + rng.normal(0, 0.4)
                elasticity = rng.uniform(-1.8, -0.2)          # always negative (a demand curve)
                base_price = float(np.exp(DEPT_PRICE_MU[dept] + rng.normal(0, 0.25)))
                # Per-item drift adds spread WITHIN a segment (for item movers);
                # the dominant segment signal comes from store_cat_growth above.
                roll = rng.random()
                if roll < 0.05:
                    item_g = rng.uniform(-0.40, -0.25)
                elif roll < 0.10:
                    item_g = rng.uniform(0.25, 0.45)
                else:
                    item_g = rng.normal(0.0, 0.06)
                items.append((item_id, dept, cat, base_mu, elasticity, base_price, item_g))

    # ── Generate sales (wide) and prices (long) ──────────────────────────────
    # Preallocated arrays rather than Python lists, so the generator also scales
    # to full M5 size (~30k series × 1,941 days) for stress-testing the pipeline.
    n_series = len(items) * len(stores)
    units_mat = np.zeros((n_series, n), dtype=np.int32)
    price_mat = np.zeros((n_series, n_weeks), dtype=np.float64)
    week_key = calendar.groupby(week_of_day)["wm_yr_wk"].first().to_numpy()
    meta = []                                              # one id tuple per series
    row = 0

    for item_id, dept, cat, base_mu, elasticity, base_price, item_g in items:
        base_level = np.exp(base_mu)
        for st, store in stores:
            # Effective growth = segment trend + item drift (compounded over time).
            eff_growth = float(np.clip(store_cat_growth[(store, cat)] + item_g, -0.6, 0.8))
            trend = (1.0 + eff_growth) ** (t / 365.25)
            # Weekly price path: store-adjusted base, an occasional permanent
            # step change (creates price↑/price↓ signals), and short promos.
            p_base = base_price * store_price_adj[store]
            weekly = np.full(n_weeks, p_base)
            r = rng.random()
            if r < 0.15:      # permanent increase partway through
                w0 = rng.integers(n_weeks // 4, 3 * n_weeks // 4)
                weekly[w0:] *= 1.0 + rng.uniform(0.06, 0.15)
            elif r < 0.30:    # permanent decrease partway through
                w0 = rng.integers(n_weeks // 4, 3 * n_weeks // 4)
                weekly[w0:] *= 1.0 - rng.uniform(0.06, 0.12)
            promo = rng.random(n_weeks) < 0.03                 # ~3% of weeks on promo
            weekly = np.where(promo, weekly * 0.85, weekly).round(2)

            price_daily = weekly[week_of_day]
            price_effect = (price_daily / p_base) ** elasticity

            snap_mult = 1.0 + 0.20 * snap[st] if cat == "FOODS" else 1.0
            intensity = (base_level * store_factor[store] * dow * season * trend
                         * event_mult[cat] * snap_mult * price_effect)
            units = rng.poisson(np.clip(intensity, 0, None))
            units[christmas] = 0                               # stores closed

            units_mat[row] = units
            price_mat[row] = weekly
            meta.append((f"{item_id}_{store}_evaluation", item_id, dept, cat, store, st))
            row += 1

    day_cols = [f"d_{i + 1}" for i in range(n)]
    ids = pd.DataFrame(meta, columns=["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"])
    sales = pd.concat([ids, pd.DataFrame(units_mat, columns=day_cols)], axis=1)
    prices = pd.DataFrame({
        "store_id": np.repeat(ids["store_id"].to_numpy(), n_weeks),
        "item_id": np.repeat(ids["item_id"].to_numpy(), n_weeks),
        "wm_yr_wk": np.tile(week_key, n_series),
        "sell_price": price_mat.ravel(),
    })

    # ── Write, matching real M5 filenames ────────────────────────────────────
    f = cfg["data_source"]["files"]
    calendar.to_csv(out / f["calendar"], index=False)
    prices.to_csv(out / f["prices"], index=False)
    sales.to_csv(out / f["sales"], index=False)

    total_cells = len(sales) * n
    zero_frac = (units_mat == 0).mean()
    print("Synthetic M5-shaped sample written to", out)
    print(f"  calendar.csv              {len(calendar):>8,} rows  "
          f"({calendar['date'].iloc[0]} → {calendar['date'].iloc[-1]})")
    print(f"  sell_prices.csv           {len(prices):>8,} rows")
    print(f"  sales_train_evaluation.csv{len(sales):>8,} series × {n} days "
          f"= {total_cells:,} cells")
    print(f"  intermittency (zero units): {zero_frac:5.1%}")
    print("  NOTE: synthetic data — a dev scaffold, NOT a source of business findings.")


if __name__ == "__main__":
    main()
