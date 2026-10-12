"""Render the README hero figure — an 'Executive Control Tower' preview.

Reads the same extracts as Tableau and the HTML dashboard, so the README image
always matches the current data. The caption says "synthetic data" only when
the build ran in sample mode. Output: docs/img/executive_preview.png

Run standalone:  python src/make_figures.py   (also runs at the end of build.py)
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")                     # headless: no display needed
import matplotlib.gridspec as gridspec    # noqa: E402
import matplotlib.pyplot as plt           # noqa: E402
import pandas as pd                       # noqa: E402

from config import path                   # noqa: E402

INK, MUTE, UP, DOWN, RISK = "#1f2a37", "#6b7280", "#0f9d58", "#d1453b", "#b45309"
SIGNAL_COLOUR = {"Strong growth": UP, "Demand deterioration": DOWN, "Price ↑ / demand ↓": RISK}


def _strip_spines(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)


def main() -> None:
    ext = path("dashboard", "extracts")
    img = path("docs", "img")
    img.mkdir(parents=True, exist_ok=True)

    kpi = pd.read_csv(ext / "kpi_summary.csv")
    contrib = pd.read_csv(ext / "contribution_category.csv")
    exc = pd.read_csv(ext / "exceptions_store_category.csv")
    summary = json.loads((ext / "metrics_summary.json").read_text())

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": "#d0d5dd"})
    fig = plt.figure(figsize=(11, 7.2), facecolor="white")
    gs = gridspec.GridSpec(3, 3, height_ratios=[0.9, 1.5, 1.5], hspace=0.55, wspace=0.3,
                           left=0.135, right=0.965, top=0.86, bottom=0.09)

    caption = ("reference render · synthetic data" if summary["mode"] == "sample"
               else "reference render · M5 Walmart data")
    fig.suptitle("Executive Control Tower", x=0.135, y=0.955, ha="left",
                 fontsize=19, fontweight="bold", color=INK)
    fig.text(0.135, 0.905, "Estimated sales value · like-for-like vs same period last year "
             f"({summary['current_window'][0]} → {summary['current_window'][1]})",
             ha="left", fontsize=10, color=MUTE)
    fig.text(0.965, 0.955, caption, ha="right", fontsize=8.5, color=MUTE, style="italic")

    # ── KPI cards ────────────────────────────────────────────────────────────
    cards = [("Estimated Sales Value", kpi.loc[0, "current"], kpi.loc[0, "growth"], "${:,.0f}"),
             ("Units Sold", kpi.loc[1, "current"], kpi.loc[1, "growth"], "{:,.0f}"),
             ("Avg Selling Price", kpi.loc[2, "current"], kpi.loc[2, "growth"], "${:,.2f}")]
    for i, (label, val, g, fmt) in enumerate(cards):
        ax = fig.add_subplot(gs[0, i])
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                                   facecolor="#f9fafb", edgecolor="#e5e7eb", lw=1))
        ax.text(0.5, 0.72, label, ha="center", fontsize=9.5, color=MUTE)
        ax.text(0.5, 0.42, fmt.format(val), ha="center", fontsize=17,
                fontweight="bold", color=INK)
        ax.text(0.5, 0.14, f"{'▲' if g >= 0 else '▼'} {abs(g):.1%} YoY", ha="center",
                fontsize=11, color=UP if g >= 0 else DOWN, fontweight="bold")

    # ── Why? Share of the top-line change, by category ───────────────────────
    axc = fig.add_subplot(gs[1, :])
    contrib = contrib.sort_values("share_of_change")
    axc.barh(contrib.cat_id, contrib.share_of_change, height=0.6,
             color=[UP if x >= 0 else DOWN for x in contrib.share_of_change])
    axc.axvline(0, color=INK, lw=0.8)
    axc.set_title("Why?  Share of total value change, by category", loc="left",
                  fontsize=12, fontweight="bold", color=INK, pad=8)
    axc.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0%}"))
    for y, (v, dg) in enumerate(zip(contrib.share_of_change, contrib.demand_growth)):
        axc.text(v + (0.02 if v >= 0 else -0.02), y, f"{v:+.0%}  (units {dg:+.1%})",
                 va="center", ha="left" if v >= 0 else "right", fontsize=9, color=INK)
    _strip_spines(axc)
    axc.margins(x=0.18)

    # ── Where? Exception segments, ranked by priority ────────────────────────
    axe = fig.add_subplot(gs[2, :])
    e = exc.head(6).iloc[::-1]
    axe.barh(e.store_key + " · " + e.cat_id, e.priority_score, height=0.6,
             color=[SIGNAL_COLOUR.get(s, MUTE) for s in e.signal])
    axe.tick_params(axis="y", labelsize=9)
    axe.set_title("Where?  Exception segments, ranked by priority score", loc="left",
                  fontsize=12, fontweight="bold", color=INK, pad=8)
    for y, (ps, dg, sg) in enumerate(zip(e.priority_score, e.demand_growth, e.signal)):
        axe.text(ps + 0.03, y, f"{sg}  (demand {dg:+.1%})", va="center", fontsize=9, color=INK)
    _strip_spines(axe)
    axe.margins(x=0.32)

    fig.savefig(img / "executive_preview.png", dpi=130, facecolor="white")
    plt.close(fig)
    print("[figure] docs/img/executive_preview.png")


if __name__ == "__main__":
    main()
