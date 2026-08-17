# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A personal fuel-price tracker built from France's official open data feed
(`donnees.roulez-eco.fr`, same source as prix-carburants.gouv.fr). Two
independent tools, both pure-stdlib Python 3 (no dependencies to install, no
`requirements.txt`), each generating a static HTML dashboard that a GitHub
Action commits and publishes via GitHub Pages every 12 hours:

- **Root** — tracks a single station (Esso, Marcq-en-Barœul) in depth:
  `track_price.py` → `historique_prix_essence.csv` → `visualisation.html`.
- **`nord/`** — tracks every station in a department (default: Nord, 59) on
  an interactive map: `nord/build_nord.py` → `nord/stations.csv` +
  `nord/prix.csv` → `nord/build_carte.py` → `nord/carte_nord.html`.
- `index.html` is a static landing page linking to both dashboards.

There is no build system, package manager, linter, or test suite — this is
intentional; treat "no dependencies" as a constraint to preserve, not a gap
to fill.

## Commands

```bash
# Single-station tracker (root)
python3 track_price.py                       # one collection pass; appends to CSV, regenerates visualisation.html
python3 track_price.py --find 59700           # list stations in a postal code, to find/verify a station_id
python3 track_price.py --historique 2026      # backfill a year's full price history (2024 2025 2026 for several)
python3 track_price.py --reparer-prix         # fix old rows stored in pre-2022 "millièmes" price format

# Department-wide map (nord/)
cd nord
python3 build_nord.py                # full pass: instant feed + annual archives configured in config.json
python3 build_nord.py --maj-seulement  # fast pass: instant feed only, no archive re-download
python3 build_carte.py               # regenerate carte_nord.html from stations.csv/prix.csv (run after build_nord.py)
```

No test/lint/build commands exist. Validate changes by running the relevant
script and opening the generated `.html` file in a browser.

## Architecture notes

**Data source contract.** Both scripts hit the same government endpoints:
- instant feed (`/opendata/instantane`): all of France, updated every 10 min.
- annual archive (`/opendata/annee` or `/opendata/annee/{YEAR}`): all of
  France, a zip containing one large XML, available from 2007.
The feed never includes a brand/name (e.g. "Esso") — only address, so
station identity is verified by matching `adresse_attendue` (root) against
the fetched address, printing a warning (not an error) on mismatch.

**Price normalization.** Archives before ~2022 encode price as integer
millièmes with no decimal separator (`"1126"` → 1.126 €); newer feeds use
decimal notation directly (`"1.563"`). `normalize_price()` in both
`track_price.py` and `nord/build_nord.py` detects and converts this — keep
these two copies in sync if the logic changes. `track_price.py
--reparer-prix` re-normalizes an existing CSV that predates this fix.

**Append-only, dedup-on-write CSVs.** Both pipelines only add a CSV row when
a station reports a genuinely new price change, deduplicating on
`(carburant, maj_officielle)` for the root tracker or
`(station_id, carburant, maj_officielle)` for `nord/`. This keeps history
files compact under frequent polling and makes reruns idempotent — never
rewrite these CSVs wholesale except via `stations.csv` (which *is* fully
rewritten each run, since it's small metadata, not a time series).

**`nord/` two-file split.** `stations.csv` (metadata, one row per station,
fully rewritten) is kept separate from `prix.csv` (time series, append-only)
specifically to avoid repeating address text on every price row. Per-station
history is further split into `nord/data/{station_id}.js` chunks — small
JS files that assign into `window.NORD_DATA`, loaded on demand via a
dynamically inserted `<script>` tag when a station is clicked on the map.
This lets `carte_nord.html` work from `file://` with no server and no CORS
issues, at the cost of the map view only ever holding *latest* prices
in-memory (`latest_prices_by_station()` in `build_carte.py`) until a
station's chunk is fetched.

**HTML generation is template substitution, not a template engine.** Both
`generate_html()` (root) and `build_carte.py`'s `main()` embed data as a
`__PLACEHOLDER__`-substituted JSON blob inside an HTML/JS string constant
(`HTML_TEMPLATE`), then write the result. Charts are Plotly.js loaded from a
CDN (`plotly.js-dist-min`) with no bundler; the map layer uses Plotly's
`scattermap` (OSM tiles, no API key). All chart/table logic is inline
`<script>` in the template — edit the Python string constant directly.

**Extending to another department.** Change `cp_prefix` in `nord/config.json`,
clear `stations.csv`, `prix.csv`, and `nord/data/`, then rerun both scripts —
see `nord/README.md` for details.

## CI/CD

`.github/workflows/update.yml` runs both pipelines every 12h (`0 */12 * * *`
UTC) and on manual dispatch (with an optional "full history refresh" input
for the `nord/` pipeline), then commits and pushes any changed CSV/HTML/data
files as `github-actions[bot]`. `concurrency.cancel-in-progress: false`
ensures overlapping runs queue rather than race. GitHub Pages serves the
repo root directly (`index.html`, `visualisation.html`, `nord/carte_nord.html`)
— there is no separate deploy/build step.

See `GITHUB.md` for one-time repo setup (Pages + Actions write permissions)
and `README.md` / `nord/README.md` for detailed usage of each pipeline.
