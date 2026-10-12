# HTML Dashboard — how to view, edit, and extend

`dashboard/index.html` is a **self-contained** decision system: one file, no
build step, no external requests (system fonts, inline SVG charts, and the data
embedded right in the page). Open it and it works — offline, emailed, or hosted.

It is the **companion** to the Tableau build; the numbers in both come from the
same pipeline, so they always agree.

---

## 1 · View it

| Want | Do |
| --- | --- |
| Just look | Double-click `dashboard/index.html` (opens in your browser) |
| A local server | `cd dashboard && python -m http.server 8000` → open `http://localhost:8000` |
| A **public live link** | Push the repo to GitHub, enable **Settings → Pages**, and share `…/dashboard/index.html` |

Light/dark follows your OS; the ◑ button in the top-right toggles and remembers.

---

## 2 · The one rule: numbers vs. look

The file has two kinds of content, and you edit them differently:

```
┌─ dashboard/index.html ─────────────────────────────────────────┐
│  <script id="rci-data"> … 117 KB of JSON … </script>   ← NUMBERS │  auto-generated
│  <script> CONFIG + CHART TOOLKIT + RENDER + SHELL </script> ← LOOK │  edit by hand
└────────────────────────────────────────────────────────────────┘
```

- **Refresh the numbers** → never hand-edit the JSON. Run `make html` (or
  `python src/build_html.py`, or a full `make all`). It rewrites **only** the
  `<script id="rci-data">` block from `dashboard/extracts/`, leaving your styling
  untouched. On real M5 data (`mode: real`), the whole dashboard updates for free.
- **Change the look** → edit the file directly (next sections). Your edits survive
  every `make html`.

---

## 3 · Quick recipes (edit `index.html`)

Everything editable lives in clearly-banner-commented zones inside the two
`<script>`/`<style>` blocks.

### Rename things / reorder pages — the `CONFIG` object
```js
const CONFIG = {
  title: "Retail Commercial Intelligence",   // top bar + browser tab
  subtitle: "Commercial decision system · M5 retail",
  currency: "$",
  pages: [                                   // reorder or rename tabs here
    { id:"exec", label:"Executive Control Tower" },
    { id:"diag", label:"Commercial Diagnostics" },
    { id:"risk", label:"Opportunity & Risk" },
  ],
  categoryColors: { FOODS:"var(--cat-1)", HOUSEHOLD:"var(--cat-2)", HOBBIES:"var(--cat-3)" },
  signal: { "Strong growth": { color:"var(--growth)", icon:"▲" }, /* … */ },
};
```

### Recolor the theme — the CSS tokens (`:root` blocks in `<style>`)
Change a colour in **one** place and it updates everywhere, in both themes. Edit
the light values under bare `:root`, and the dark values under **both**
`@media (prefers-color-scheme: dark)` and `:root[data-theme="dark"]` (keep the two
dark blocks in sync).
```css
:root{ --accent:#2a78d6; --cat-2:#eb6834; --growth:#0ca30c; /* … */ }
```

### Change a threshold (e.g. what counts as "deterioration")
That is analysis, not display — edit `config.yaml` (`analysis.thresholds`) and
run `make all`. The dashboard re-reads the new results automatically.

### Add a KPI card
1. Add it to the data in `src/build_html.py` → the `kpis` list.
2. Nothing else needed — `kpiCards()` renders whatever is in `DATA.kpis`.

### Add a whole new card or chart
Each card is one small function in the **RENDER** zone (`kpiCards`, `trendCard`,
`contributionCard`, `exceptionsCard`, …). Copy the closest one, point it at your
data, and append it inside the page function (`execPage` / `diagPage` / `riskPage`):
```js
function myCard(){ return card("My title","","one-line lede", vBars(rows,"var(--accent)",fmt.int)); }
// then, inside execPage():  p.append(kpiCards(), trendCard(), myCard());
```
Charts available in the **CHART TOOLKIT** zone: `lineChart`, `divergingBars`,
`vBars`, `scatter` — all single-axis with hover tooltips built in.

### Add a new page/tab
1. Add `{ id:"myid", label:"My Page" }` to `CONFIG.pages`.
2. Write `function myPage(){ … }` returning a grid of cards.
3. Register it: `const RENDER = { exec:execPage, diag:diagPage, risk:riskPage, myid:myPage };`

---

## 4 · The data contract (for adding data)

`src/build_html.py → collect_data()` assembles the JSON the page reads as `DATA`.
Top-level keys the render code expects:

| Key | Shape | Used by |
| --- | --- | --- |
| `meta` | mode, windows, basis, generated | top bar, notice, footer |
| `kpis` | `[{label, value, unit, growth}]` | KPI cards |
| `trend`, `trend_by_cat` | months + value/units arrays | Performance trend |
| `contribution_category` / `_store` | rows w/ `share_of_change` | Why? / diagnostics |
| `exceptions` | ranked segment rows | Where? / risk |
| `movers`, `price_risk`, `concentration`, `price_demand` | decision tables | Opportunity & Risk |
| `diag.segments_monthly` | per state×store×category monthly | Diagnostics filters |
| `diag.dow` / `event_lift` / `snap_foods` | seasonality context | Diagnostics |

To surface a new table: add it to `collect_data()` (read a CSV with `_csv("…")`
or query DuckDB), run `make html`, then render `DATA.yourKey` in a card.

---

## 5 · Keep it self-contained

Do **not** add `<script src="…">`, `<link href="http…">`, or remote images. The
value of this file is that it is one portable artifact — it must keep working
offline and inside a locked-down viewer. Inline anything you add.
