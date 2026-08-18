# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A fuel-price site built from France's official open data feed
(`donnees.roulez-eco.fr`, same source as prix-carburants.gouv.fr), covering
every station in metropolitan France — 95 départements (Corse is tracked as
a single département "20" since its postal code prefix doesn't distinguish
2A/2B) — with 10 years of price history. There is no map. Three pure-stdlib
Python 3 scripts (no dependencies, no `requirements.txt`) build a static
site that GitHub Actions regenerate and publish via GitHub Pages:

- `collect_prices.py` — fetches/updates `stations.csv` and per-station
  compressed history files (`data/{dept}/{station_id}.json.gz`). Runs every
  12h.
- `fetch_brands.py` — enriches stations with their brand (TotalEnergies,
  Esso, Carrefour, ...) from OpenStreetMap, since the government feed never
  has it. Writes `marques.csv`, independent of `stations.csv`'s lifecycle
  (see below). Runs weekly — brands don't change often.
- `build_site.py` — reads all of the above and (re)generates **two separate
  pages with distinct purposes**, plus the on-demand compressed data chunks
  (`stations/{dept}.json.gz`, `dept_avg/{dept}.json.gz`) they share:
  - `index.html` — postal-code search only. No averages, no comparison —
    that's deliberately not this page's job (see below).
  - `comparaison.html` — current national average (+ its evolution), and
    a département table (sorted by code, sticky header) showing every
    fuel's price with a cheaper/pricier-than-national indicator. Click a
    row for that département's evolution chart.

There is no build system, package manager, linter, or test suite — this is
intentional; treat "no dependencies" as a constraint to preserve, not a gap
to fill (gzip decompression uses the browser's native `DecompressionStream`,
not a library).

**The site must be served over http(s), not opened via `file://`.** `fetch()`
(needed to read the gzip chunks as raw bytes) is blocked on `file://` in
browsers, unlike the `<script src>` tag injection this codebase used before
compression was introduced. Test locally with `python3 -m http.server`.

## Commands

```bash
python3 collect_prices.py                # full pass: instant feed + annual archives configured in config.json
python3 collect_prices.py --maj-seulement # fast pass: instant feed only, no archive re-download
python3 fetch_brands.py                   # refresh marques.csv from OpenStreetMap (independent, run rarely)
python3 build_site.py                     # regenerate index.html + comparaison.html + data chunks (run after the above)
python3 -m http.server                    # serve the site locally (required — see above)
```

No test/lint/build commands exist. Validate changes by running both scripts
in sequence, serving via `http.server`, and opening both
`http://localhost:8000/index.html` (search) and
`http://localhost:8000/comparaison.html` (tables) in a browser.

A full `collect_prices.py` run (no `--maj-seulement`) downloads and merges 10
years of France-wide archives — expect tens of minutes, not seconds. Don't
casually rerun it while iterating; use `--maj-seulement` for quick checks.

## Architecture notes

**Data source contract.** `collect_prices.py` hits two government endpoints:
- instant feed (`/opendata/instantane`): all of France, updated every 10 min.
- annual archive (`/opendata/annee` or `/opendata/annee/{YEAR}`): all of
  France, a zip containing one large XML, available from 2007.
Both are downloaded in full (there's no server-side département filter) and
filtered client-side to the départements in `config.json`. The feed never
includes a brand/name — only address — so station identity is address-only.

**Brand enrichment is a separate data lifecycle, deliberately not merged
into `stations.csv`.** `stations.csv` is fully rewritten by
`collect_prices.py` every 12h from scratch (`write_stations_csv()`) — any
brand column added to it would be silently wiped on the next price
collection. `fetch_brands.py` instead writes `marques.csv`
(`station_id,marque`), read independently by `build_site.py`
(`read_marques()`) and merged into each station's payload only at build
time (`write_station_chunks()`'s `marques` param) — a station with no known
brand simply omits the `"marque"` key rather than carrying a null. Matching
against OpenStreetMap: prefer the exact `ref:FR:prix-carburants` tag (same
station ID as the government feed — an inherited artifact of a 2020
government-data import into OSM, since community-maintained); for stations
without that tag, fall back to the nearest OSM fuel node with a brand tag
within `MAX_FALLBACK_DISTANCE_M` (100m), found via a simple lat/lon grid
bucketed at `GRID_STEP_DEG` (~1km) rather than brute-force distance to every
OSM node. Measured coverage (Aug 2026, France-wide): ~64% exact-ID match,
~79% including the proximity fallback.

**Price normalization.** Archives before ~2022 encode price as integer
millièmes with no decimal separator (`"1126"` → 1.126 €); newer feeds use
decimal notation directly (`"1.563"`). `normalize_price()` in
`collect_prices.py` detects and converts this at ingestion time.

**One canonical, compressed, per-station data layer — no duplication.**
Earlier iterations of this project kept two copies of every price (a flat
CSV for dedup/aggregation, a separate JSON chunk for the client) — fine at
one département's scale, but at all-of-France×10-years scale (~13x more
volume than the last checkpoint) duplicating would double an already large
number. `data/{dept}/{station_id}.json.gz` is now the *only* copy: compact
arrays (`["Gazole","1.827","2019-03-02T08:00:00"]`, not keyed objects),
gzip-compressed (`gzip` stdlib module to write, `DecompressionStream` to
read — typically 5-8x smaller for this repetitive tabular data).
`collect_prices.py` reads+merges this same file for dedup; `build_site.py`
reads it again to compute latest prices and averages. Sharding by
département (subdirectory) keeps any single file far below GitHub's 100MB
limit and keeps directory listings manageable (a few hundred files each,
not tens of thousands flat).

**Streaming merge, not batch-accumulate, during a full backfill.**
`ingest_pdv_stream()` merges each `<pdv>` into its station's on-disk file
*immediately* while iterating (`elem.clear()` right after), rather than
collecting a year's rows into memory before writing. At France-wide,
10-year scale, batching a single year in memory (millions of rows) risked
multi-GB peak memory; streaming keeps peak memory bounded to whatever's
being processed at that instant, independent of total corpus size.
`merge_station_history()` does the actual dedup-and-rewrite per station,
keyed on `(carburant, maj_officielle)`.

**`index.html` and `comparaison.html` are two independent HTML string
templates in `build_site.py` (`HTML_TEMPLATE` and `HTML_TEMPLATE_COMPARE`),
each self-contained** — no shared JS module, matching this project's
long-standing "no build step, no bundler" approach. Small helpers
(`fetchGzipJson`, `colorFor`, `renderSeriesChart`, `sortFuels`, `parseDate`)
are duplicated between the two rather than factored out; keep both in sync
if their logic changes.

**`index.html` ships only the search UI plus `NOMS_DEPARTEMENTS`** (for
validating a typed postal code's département). No average data is embedded
or fetched here at all — that's `comparaison.html`'s job entirely. Typing a
postal code prefix fetches+decompresses `stations/{dept}.json.gz` (via
`fetchGzipJson()` → `ensureStationsLoaded()`, cached in `stationsCache`);
selecting a station fetches `data/{dept}/{id}.json.gz`
(`ensureHistoryLoaded()` → `historyCache`) and renders *only that station's*
price lines — no dept/region/national overlay (an earlier version
superimposed those on a station's chart for comparison; removed as unwanted
complexity, then the whole averages concept was later moved off this page
entirely).

**`comparaison.html` embeds `NOMS_DEPARTEMENTS`, the *current* average per
fuel at both levels (`deptLatest`, `nationalLatest`), and the *historical*
`nationalSeries`.** Unlike per-station data, series size is bounded by
*calendar days* not station count (see below) — one national series is
cheap enough to embed directly. `dept_avg/{dept}.json.gz` (a département's
own historical series) stays chunked/lazy (`ensureAvgLoaded()` →
`avgCache`) since there are 95 of them — fetched only when its table row is
clicked.

The département table is built by iterating `Object.keys(NOMS_DEPARTEMENTS)`
client-side (sorted, which is also numeric order since every code is a
2-digit zero-padded string), one `<tr>` per département; each fuel cell
(`fuelCell()`) compares that row's average against `nationalLatest[fuel]`
via `indicatorFor()` (▼ green if cheaper, ▲ red if pricier, nothing if
within 0.0005€). Clicking a row (`.cmp-row`) loads/renders that
département's series into a shared `#evolutionDetail` panel below the
table — not a chart per row. The table sits in a `.table-scroll` container
with `max-height: 75vh; overflow: auto` and `th { position: sticky; top: 0 }`
so the header stays visible while scrolling through all 95 rows — this
requires the scroll context to be that container itself (not the page),
which is why it has a bounded height rather than relying on page-level
scroll (position:sticky relative to an ancestor with default overflow
wouldn't reliably pin to the viewport).

**Average series (`average_series()` in `build_site.py`) is grouping-agnostic
— the same function would compute a region- or arbitrary-group series if
ever needed again** (a region breakdown existed before and was removed as
unwanted UI complexity, but the aggregation code stayed general-purpose
since there was no reason to special-case it back to département-only).
For whatever set of `(station_id, carburant, prix_eur, maj_officielle)`
rows it's given, it computes one point per calendar day where at least one
included station changed price: the average of each station's latest known
price as of that day (forward-filled between changes, i.e. a step
function). Called once per département (that département's own rows from
`process_all_departments()`) for `dept_avg/{dept}.json.gz`; the national
series is then obtained by `merge_series()` — combining the already-computed
small département series (weighted by station count) rather than ever
re-touching raw rows, see that function's docstring. Latest
(non-historical) averages use the analogous `grouped_latest_averages()`,
parameterized by a `group_for_cp(cp) -> key` callback (département code, or
a constant for the national bucket).

**HTML generation is template substitution, not a template engine.** Each
of `HTML_TEMPLATE` / `HTML_TEMPLATE_COMPARE` is a Python string with
`__PLACEHOLDER__` markers substituted via `.replace()` in `main()`, then
written to `index.html` / `comparaison.html` respectively. Charts are
Plotly.js loaded from a CDN (`plotly.js-dist-min`) with no bundler. All
UI/search/chart/table logic is inline `<script>` in the templates — edit
the Python string constants directly.

**Adding/removing a département.** Edit the `departements` object in
`config.json` (2-digit code → display name), clear `stations.csv`, `data/`,
`stations/`, `dept_avg/`, then rerun both scripts.

## CI/CD

Two independent scheduled workflows, matching the two independent data
lifecycles above:

- `.github/workflows/update.yml` — `collect_prices.py` + `build_site.py`
  every 12h (`0 */12 * * *` UTC) and on manual dispatch (with an optional
  "full history refresh" input — this re-downloads all configured years
  across all of France, hence the 3-hour `timeout-minutes`).
- `.github/workflows/update-brands.yml` — `fetch_brands.py` + `build_site.py`
  weekly (Sunday 3am UTC) and on manual dispatch. Kept infrequent
  deliberately, to avoid hammering the shared public Overpass infrastructure
  for data that rarely changes.

Both commit and push any changed data as `github-actions[bot]`, each with
its own `concurrency` group so they queue rather than race each other or
themselves. GitHub Pages serves the repo root directly — there is no
separate deploy/build step.

See `GITHUB.md` for one-time repo setup (Pages + Actions write permissions)
and `README.md` for detailed usage.
