# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A fuel-price search site built from France's official open data feed
(`donnees.roulez-eco.fr`, same source as prix-carburants.gouv.fr), covering
every station in metropolitan France — 95 départements (Corse is tracked as
a single département "20" since its postal code prefix doesn't distinguish
2A/2B) — with 10 years of price history. Users search by postal code; there
is no map. Two pure-stdlib Python 3 scripts (no dependencies, no
`requirements.txt`) build a static site that a GitHub Action regenerates and
publishes via GitHub Pages every 12 hours:

- `collect_prices.py` — fetches/updates `stations.csv` and per-station
  compressed history files (`data/{dept}/{station_id}.json.gz`).
- `build_site.py` — reads those files and (re)generates `index.html` plus the
  on-demand compressed data chunks (`stations/{dept}.json.gz`,
  `dept_avg/{dept}.json.gz`).

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
python3 build_site.py                     # regenerate index.html + data chunks (run after collect_prices.py)
python3 -m http.server                    # serve the site locally (required — see above)
```

No test/lint/build commands exist. Validate changes by running both scripts
in sequence, serving via `http.server`, and opening `http://localhost:8000/`
in a browser (type a 2+ digit postal code prefix, e.g. `59`, to trigger the
on-demand chunk loading path).

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

**Station/price data is lazy-loaded by département/station; averages are
three-tier (département/région/national).** `index.html` ships only the
search UI plus small lookups: `NOMS_DEPARTEMENTS`, `DEPT_TO_REGION` (derived
from `config.json`'s `regions` map — 13 official metropolitan régions), and
the *current* average per fuel at each level (`deptLatest`, `regionLatest`,
`nationalLatest`). Typing a postal code prefix fetches+decompresses
`stations/{dept}.json.gz` (via `fetchGzipJson()` → `ensureStationsLoaded()`,
cached in `stationsCache`); selecting a station fetches
`data/{dept}/{id}.json.gz` (`ensureHistoryLoaded()` → `historyCache`).
`dept_avg/{dept}.json.gz` (`ensureAvgLoaded()` → `avgCache`) is fetched
separately, only when the user clicks "Voir l'évolution du département" —
not tied to station selection.

**Régional and national *historical* series (`regionSeries`,
`nationalSeries`) are the one exception to "nothing embedded" in
`index.html`.** Unlike per-station or per-département data, their size is
bounded by *calendar days*, not station count (see below) — at only 13
regions + 1 national series, cheap enough to embed directly rather than
chunk.

**Average series (`average_series()` in `build_site.py`) is grouping-agnostic
— same function computes département, region, and national.** For whatever
set of `(station_id, carburant, prix_eur, maj_officielle)` rows it's given,
it computes one point per calendar day where at least one included station
changed price: the average of each station's latest known price as of that
day (forward-filled between changes, i.e. a step function). Called once per
département (that département's own rows from `load_all_history()`) for
`dept_avg/{dept}.json.gz`, once per region (concatenated rows of member
départements) for the embedded `regionSeries`, once on every row for
`nationalSeries`. Output size depends only on distinct days touched, not on
station count — why region/national series don't need chunking despite
aggregating far more stations than any one département. Latest
(non-historical) averages use the analogous `grouped_latest_averages()`,
parameterized by a `group_for_cp(cp) -> key` callback (département code,
region name via `DEPT_TO_REGION`, or a constant for the national bucket).

**Average evolution graphs are standalone, not overlaid on a station's
chart.** An earlier version superimposed dept/region/national trend lines on
a selected station's own evolution chart for direct comparison; this was
removed as unwanted complexity. Each average level (national, département,
région) instead has its own "Voir l'évolution" toggle button next to its
cards (`nationalEvolutionBtn`/`deptEvolutionBtn`/`regionEvolutionBtn`) that
renders *only that level's* trend into its own chart div
(`renderSeriesChart()`, shared by all three) — a station's evolution chart
(`selectStation()`) shows only that station's own price lines.

**Averages reflect the selected station, not just the search box.**
`selectStation(station)` derives `dept` from `station.cp` itself (not from
outer search state) and calls `showLocalAvg(dept)` again on selection — the
"Moyennes actuelles" cards (and `currentDept`/`currentRegion`, which the
evolution buttons read) are always keyed off the station actually clicked.
`showLocalAvg()` also closes and resets any open département/région
evolution chart from a previous context, so a stale graph is never left
showing after the department/region changes.

**HTML generation is template substitution, not a template engine.**
`build_site.py`'s `HTML_TEMPLATE` is a Python string with
`__PLACEHOLDER__` markers substituted via `.replace()`, then written to
`index.html`. Charts are Plotly.js loaded from a CDN (`plotly.js-dist-min`)
with no bundler. All UI/search/chart logic is inline `<script>` in the
template — edit the Python string constant directly.

**Adding/removing a département.** Edit the `departements` (and `regions`,
if needed) objects in `config.json` (2-digit code → display name), clear
`stations.csv`, `data/`, `stations/`, `dept_avg/`, then rerun both scripts.

## CI/CD

`.github/workflows/update.yml` runs both scripts every 12h (`0 */12 * * *`
UTC) and on manual dispatch (with an optional "full history refresh" input —
this re-downloads all configured years across all of France, hence the
3-hour `timeout-minutes`), then commits and pushes any changed data as
`github-actions[bot]`. `concurrency.cancel-in-progress: false` ensures
overlapping runs queue rather than race. GitHub Pages serves the repo root
directly (`index.html`) — there is no separate deploy/build step.

See `GITHUB.md` for one-time repo setup (Pages + Actions write permissions)
and `README.md` for detailed usage.
