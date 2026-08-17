#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Construit index.html : un site de recherche de stations-service par code
postal (Hauts-de-France, Normandie, Grand Est, Ile-de-France). Tape un code
postal, la liste des stations de son departement s'affiche, clique sur une
station pour voir ses prix actuels et son evolution. La page affiche aussi
la moyenne actuelle de chaque carburant pour le departement recherche, et la
superpose (en pointilles) sur le graphique d'evolution de la station
selectionnee.

La page principale ne contient aucune donnee de station ou de prix : elles
sont chargees a la demande, par departement, depuis stations/{dept}.js,
dept_avg/{dept}.js et data/{id}.js (generes par ce script et par
collect_prices.py). Avec ~28 departements suivis, tout charger d'un coup
rendrait la page d'accueil trop lourde ; le chargement par departement la
garde legere quel que soit le nombre total de stations suivies.

Usage : python3 build_site.py
(a relancer apres chaque python3 collect_prices.py pour refleter les
nouvelles donnees)

Ne depend d'aucune librairie externe.
"""
import csv
import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def read_csv_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_prix_dir(prix_dir):
    """Retourne {departement: [lignes de prix]} a partir des fichiers
    prix/{dept}.csv (un fichier par departement, voir collect_prices.py)."""
    by_dept = {}
    if os.path.isdir(prix_dir):
        for fname in sorted(os.listdir(prix_dir)):
            if fname.endswith(".csv"):
                by_dept[fname[:-4]] = read_csv_rows(os.path.join(prix_dir, fname))
    return by_dept


def latest_prices_by_station(prix_rows):
    """Pour chaque (station, carburant), ne garde que l'entree la plus
    recente (comparaison textuelle des dates ISO/"AAAA-MM-JJ ..." qui trient
    correctement dans l'ordre chronologique)."""
    latest = {}
    for r in prix_rows:
        key = (r["station_id"], r["carburant"])
        cur = latest.get(key)
        if cur is None or r["maj_officielle"] > cur["maj_officielle"]:
            latest[key] = r
    by_station = {}
    for (sid, carburant), r in latest.items():
        by_station.setdefault(sid, {})[carburant] = {
            "prix_eur": r["prix_eur"],
            "maj_officielle": r["maj_officielle"],
        }
    return by_station


def department_latest_averages(latest_by_station, stations_by_id):
    """Moyenne actuelle de chaque carburant, par departement (calculee a
    partir du dernier prix connu de chaque station de ce departement)."""
    sums = {}
    counts = {}
    for sid, prices in latest_by_station.items():
        cp = stations_by_id.get(sid, {}).get("cp", "")
        dept = cp[:2]
        if not dept:
            continue
        for fuel, p in prices.items():
            try:
                val = float(p["prix_eur"])
            except (TypeError, ValueError):
                continue
            sums.setdefault(dept, {})
            counts.setdefault(dept, {})
            sums[dept][fuel] = sums[dept].get(fuel, 0.0) + val
            counts[dept][fuel] = counts[dept].get(fuel, 0) + 1
    result = {}
    for dept, fuel_sums in sums.items():
        result[dept] = {
            fuel: {"avg": round(fuel_sums[fuel] / counts[dept][fuel], 4), "n": counts[dept][fuel]}
            for fuel in fuel_sums
        }
    return result


def average_series_for_department(prix_rows):
    """Serie temporelle de la moyenne d'un departement pour chaque carburant :
    pour chaque jour ou au moins un prix a change dans le departement, la
    moyenne du dernier prix connu de chaque station a cette date (report du
    dernier prix connu entre deux changements, comme un graphique en
    escalier). Sert a superposer la tendance du departement au graphique
    d'evolution d'une station."""
    by_fuel = {}
    for r in prix_rows:
        try:
            price = float(r["prix_eur"])
        except (TypeError, ValueError):
            continue
        by_fuel.setdefault(r["carburant"], []).append(
            (r["maj_officielle"], r["station_id"], price)
        )

    series = {}
    for fuel, events in by_fuel.items():
        events.sort(key=lambda e: e[0])
        day_events = {}
        for maj, sid, price in events:
            day_events.setdefault(maj[:10], []).append((sid, price))

        current = {}
        points = []
        for day in sorted(day_events.keys()):
            for sid, price in day_events[day]:
                current[sid] = price
            if current:
                points.append(
                    {
                        "date": day,
                        "avg": round(sum(current.values()) / len(current), 4),
                        "n": len(current),
                    }
                )
        series[fuel] = points
    return series


def write_station_chunks(stations_dir, stations_rows, latest):
    """Ecrit un fichier stations/{dept}.js par departement (chargement a la
    demande cote client, en fonction du code postal recherche)."""
    os.makedirs(stations_dir, exist_ok=True)
    by_dept = {}
    skipped_no_coords = 0
    skipped_no_price = 0
    for r in stations_rows:
        sid = r["station_id"]
        prices = latest.get(sid, {})
        if not prices:
            skipped_no_price += 1
            continue
        try:
            lat = float(r["latitude"]) / 100000
            lon = float(r["longitude"]) / 100000
        except (ValueError, TypeError):
            skipped_no_coords += 1
            continue
        dept = r["cp"][:2]
        by_dept.setdefault(dept, []).append(
            {
                "id": sid,
                "adresse": r["adresse"],
                "ville": r["ville"],
                "cp": r["cp"],
                "latitude": lat,
                "longitude": lon,
                "prices": prices,
            }
        )

    for dept, payload in by_dept.items():
        path = os.path.join(stations_dir, f"{dept}.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write("window.STATIONS_DATA = window.STATIONS_DATA || {};\n")
            f.write(f'window.STATIONS_DATA["{dept}"] = {json.dumps(payload, ensure_ascii=False)};\n')

    return by_dept, skipped_no_coords, skipped_no_price


def write_dept_avg_chunks(dept_avg_dir, dept_series_by_dept):
    """Ecrit un fichier dept_avg/{dept}.js par departement (chargement a la
    demande, superpose au graphique d'evolution d'une station)."""
    os.makedirs(dept_avg_dir, exist_ok=True)
    for dept, series in dept_series_by_dept.items():
        path = os.path.join(dept_avg_dir, f"{dept}.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write("window.DEPT_AVG_DATA = window.DEPT_AVG_DATA || {};\n")
            f.write(f'window.DEPT_AVG_DATA["{dept}"] = {json.dumps(series, ensure_ascii=False)};\n')


HTML_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recherche des prix des carburants - Nord, Normandie, Grand Est, Ile-de-France</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2/plotly.min.js"></script>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 24px; background: #f5f6f8; color: #1c1c1e;
  }
  h1 { font-size: 1.3rem; margin: 0 0 6px 0; }
  h2.section-title { font-size: 1rem; margin: 0 0 12px 0; }
  .description { color: #444; font-size: 0.9rem; max-width: 760px; margin: 0 0 10px 0; line-height: 1.4; }
  .meta { color: #6b6b70; font-size: 0.85rem; margin-bottom: 16px; }
  .search-wrap {
    background: #fff; border-radius: 10px; padding: 14px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px;
  }
  .search-wrap label { font-size: 0.85rem; color: #444; display: block; margin-bottom: 6px; }
  .search-wrap input {
    font-size: 1.1rem; padding: 8px 10px; border-radius: 6px; border: 1px solid #d8d8dc;
    width: 200px; max-width: 100%;
  }
  .search-hint { font-size: 0.8rem; color: #6b6b70; margin-top: 6px; }
  .results-controls {
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    background: #fff; border-radius: 10px; padding: 12px 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px;
  }
  .results-controls label { font-size: 0.85rem; color: #444; }
  .results-controls select { font-size: 0.9rem; padding: 4px 6px; border-radius: 6px; border: 1px solid #d8d8dc; }
  .highlight-info { font-size: 0.85rem; display: flex; gap: 18px; flex-wrap: wrap; }
  .highlight-info .cheap { color: #1e8e3e; font-weight: 600; }
  .highlight-info .expensive { color: #c0392b; font-weight: 600; }
  .layout { display: flex; gap: 20px; align-items: flex-start; flex-wrap: wrap; }
  .results-wrap {
    background: #fff; border-radius: 10px; padding: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); flex: 1 1 320px; min-width: 280px;
    max-height: 640px; overflow-y: auto;
  }
  .results-count { font-size: 0.8rem; color: #6b6b70; padding: 4px 8px 10px; }
  .result-row {
    display: block; width: 100%; text-align: left; background: none; border: none;
    border-bottom: 1px solid #eee; padding: 10px 8px; cursor: pointer; font: inherit; color: inherit;
    border-radius: 6px;
  }
  .result-row:hover { background: #f5f6f8; }
  .result-row.selected { background: #eaf2ff; }
  .result-title { font-weight: 600; font-size: 0.9rem; }
  .result-sub { color: #6b6b70; font-size: 0.8rem; margin-top: 2px; }
  .details {
    background: #fff; border-radius: 10px; padding: 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); flex: 2 1 560px; min-width: 320px;
  }
  .empty { color: #6b6b70; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
  .card {
    background: #f5f6f8; border-radius: 10px; padding: 12px 16px; min-width: 100px;
  }
  .card .fuel { font-size: 0.7rem; text-transform: uppercase; color: #6b6b70; letter-spacing: .04em; }
  .card .price { font-size: 1.3rem; font-weight: 600; margin-top: 4px; }
  .card .date { font-size: 0.65rem; color: #9a9a9e; margin-top: 2px; }
  .dept-avg-wrap {
    background: #fff; border-radius: 10px; padding: 14px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px;
  }
  .station-title { font-weight: 600; margin-bottom: 2px; }
  .station-sub { color: #6b6b70; font-size: 0.85rem; margin-bottom: 16px; }
  #chart { min-height: 560px; }
</style>
</head>
<body>
  <h1>Recherche des prix des carburants - Nord, Normandie, Grand Est, Ile-de-France</h1>
  <p class="description">Cherche un code postal pour voir les stations-service de son departement, leurs prix
  actuels et l'evolution de leurs tarifs dans le temps. Couvre les 28 departements des regions Hauts-de-France,
  Normandie, Grand Est et Ile-de-France.</p>
  <div class="meta">__NB_STATIONS__ station(s) suivies sur __NB_DEPARTEMENTS__ departement(s) &middot; page generee le __GENERATED__ &middot; source : flux officiel donnees.roulez-eco.fr</div>

  <div class="search-wrap">
    <label for="cpInput">Code postal :</label>
    <input id="cpInput" type="text" inputmode="numeric" autocomplete="off" placeholder="ex : 59700" maxlength="5">
    <div class="search-hint" id="searchHint">Tape au moins les 2 premiers chiffres d'un code postal pour voir les stations du departement.</div>
  </div>

  <div class="dept-avg-wrap" id="deptAvgWrap" style="display:none">
    <h2 class="section-title">Moyenne actuelle du departement <span id="deptAvgLabel"></span></h2>
    <div class="cards" id="deptAvgCards"></div>
  </div>

  <div class="results-controls" id="resultsControls" style="display:none">
    <label for="fuelSelect">Comparer par carburant :</label>
    <select id="fuelSelect"></select>
    <div class="highlight-info" id="highlightInfo"></div>
  </div>

  <div class="layout">
    <div class="results-wrap" id="resultsWrap">
      <p class="empty">Cherche un code postal pour afficher les stations.</p>
    </div>
    <div class="details" id="details">
      <p class="empty">Selectionne une station dans la liste pour voir ses prix et son evolution.</p>
    </div>
  </div>

<script>
const NOMS_DEPARTEMENTS = __NOMS_DEPARTEMENTS__;
const deptLatest = __DEPT_LATEST__;

const FUEL_ORDER = ['Gazole', 'SP95', 'SP98', 'E10', 'E85', 'GPLc'];
function sortFuels(fuels) {
  return fuels.slice().sort((a, b) => {
    const ia = FUEL_ORDER.indexOf(a), ib = FUEL_ORDER.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
}

function parseDate(s) {
  return new Date(s.includes('T') ? s : s.replace(' ', 'T'));
}

function refPriceFor(s, fuel) {
  if (s.prices[fuel]) return parseFloat(s.prices[fuel].prix_eur);
  return null;
}

const FRESHNESS_HOURS = 72;
function isFresh(s, fuel) {
  if (!s.prices[fuel]) return false;
  const ageMs = Date.now() - parseDate(s.prices[fuel].maj_officielle).getTime();
  return ageMs <= FRESHNESS_HOURS * 60 * 60 * 1000;
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error("impossible de charger " + src));
    document.head.appendChild(s);
  });
}

const loadedStationChunks = new Set();
const loadedAvgChunks = new Set();
const loadedHistoryChunks = new Set();

const cpInput = document.getElementById('cpInput');
const deptAvgWrap = document.getElementById('deptAvgWrap');
const deptAvgLabel = document.getElementById('deptAvgLabel');
const deptAvgCards = document.getElementById('deptAvgCards');
const resultsControls = document.getElementById('resultsControls');
const resultsWrap = document.getElementById('resultsWrap');
const detailsEl = document.getElementById('details');
const fuelSelect = document.getElementById('fuelSelect');

cpInput.addEventListener('input', () => {
  const digits = cpInput.value.replace(/\\D/g, '').slice(0, 5);
  if (cpInput.value !== digits) cpInput.value = digits;
  onSearch(digits);
});

function resetResults(message) {
  deptAvgWrap.style.display = 'none';
  resultsControls.style.display = 'none';
  resultsWrap.innerHTML = `<p class="empty">${message}</p>`;
}

function showDeptAvg(dept) {
  deptAvgLabel.textContent = NOMS_DEPARTEMENTS[dept] ? `(${dept} - ${NOMS_DEPARTEMENTS[dept]})` : `(${dept})`;
  const avgs = deptLatest[dept];
  deptAvgWrap.style.display = 'block';
  if (!avgs) {
    deptAvgCards.innerHTML = '<p class="empty">Pas encore de prix connus pour ce departement.</p>';
    return;
  }
  deptAvgCards.innerHTML = '';
  sortFuels(Object.keys(avgs)).forEach(fuel => {
    const d = avgs[fuel];
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `<div class="fuel">${fuel}</div>
      <div class="price">${d.avg.toFixed(3)} €</div>
      <div class="date">moyenne sur ${d.n} station(s)</div>`;
    deptAvgCards.appendChild(div);
  });
}

async function onSearch(cp) {
  if (cp.length < 2) {
    resetResults("Tape au moins les 2 premiers chiffres d'un code postal.");
    return;
  }
  const dept = cp.slice(0, 2);
  if (!NOMS_DEPARTEMENTS[dept]) {
    resetResults(`Departement ${dept} non couvert (Hauts-de-France, Normandie, Grand Est, Ile-de-France uniquement).`);
    return;
  }

  showDeptAvg(dept);

  if (!loadedStationChunks.has(dept)) {
    resultsWrap.innerHTML = '<p class="empty">Chargement des stations...</p>';
    try {
      await loadScript('stations/' + dept + '.js');
      loadedStationChunks.add(dept);
    } catch (e) {
      resultsWrap.innerHTML = `<p class="empty">${e.message}</p>`;
      return;
    }
  }

  renderResults(dept, cp);
}

const RESULTS_LIMIT = 150;

function renderResults(dept, cp) {
  const all = (window.STATIONS_DATA && window.STATIONS_DATA[dept]) || [];
  const matches = all.filter(s => s.cp.startsWith(cp)).sort((a, b) => a.adresse.localeCompare(b.adresse));

  if (matches.length === 0) {
    resultsControls.style.display = 'none';
    resultsWrap.innerHTML = '<p class="empty">Aucune station trouvee pour ce code postal.</p>';
    return;
  }

  const fuelsHere = sortFuels(Array.from(new Set(matches.flatMap(s => Object.keys(s.prices)))));
  fuelSelect.innerHTML = '';
  fuelsHere.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f; opt.textContent = f;
    fuelSelect.appendChild(opt);
  });
  resultsControls.style.display = fuelsHere.length ? 'flex' : 'none';

  const shown = matches.slice(0, RESULTS_LIMIT);
  let html = `<div class="results-count">${matches.length} station(s) trouvee(s)` +
    (matches.length > RESULTS_LIMIT ? ` (${RESULTS_LIMIT} premieres affichees, precise le code postal pour affiner)` : '') +
    `</div>`;
  html += shown.map(s => `
    <button type="button" class="result-row" data-id="${s.id}">
      <div class="result-title">${s.adresse}</div>
      <div class="result-sub">${s.cp} ${s.ville}</div>
    </button>
  `).join('');
  resultsWrap.innerHTML = html;
  resultsWrap.querySelectorAll('.result-row').forEach(btn => {
    btn.addEventListener('click', () => {
      resultsWrap.querySelectorAll('.result-row').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      const station = matches.find(s => s.id === btn.dataset.id);
      if (station) selectStation(station);
    });
  });

  if (fuelsHere.length) {
    updateHighlight(fuelSelect.value, matches);
    fuelSelect.onchange = () => updateHighlight(fuelSelect.value, matches);
  }
}

function updateHighlight(fuel, matches) {
  const info = document.getElementById('highlightInfo');
  const withFuel = matches.filter(s => isFresh(s, fuel));
  if (withFuel.length === 0) {
    info.innerHTML = `<span class="empty">Aucun prix ${fuel} mis a jour dans les dernieres ${FRESHNESS_HOURS}h parmi ces resultats.</span>`;
    return;
  }
  let cheapest = withFuel[0], priciest = withFuel[0];
  withFuel.forEach(s => {
    if (refPriceFor(s, fuel) < refPriceFor(cheapest, fuel)) cheapest = s;
    if (refPriceFor(s, fuel) > refPriceFor(priciest, fuel)) priciest = s;
  });
  info.innerHTML =
    `<span class="cheap">Moins chere : ${cheapest.adresse}, ${cheapest.ville} - ${refPriceFor(cheapest, fuel).toFixed(3)} €</span>` +
    `<span class="expensive">Plus chere : ${priciest.adresse}, ${priciest.ville} - ${refPriceFor(priciest, fuel).toFixed(3)} €</span>`;
}

const colors = {
  Gazole: '#e74c3c', SP95: '#2980b9', SP98: '#8e44ad',
  E10: '#27ae60', E85: '#16a085', GPLc: '#f39c12'
};
const fallbackColors = ['#e74c3c','#2980b9','#8e44ad','#27ae60','#16a085','#f39c12','#7f8c8d'];

function colorFor(name, idxRef) {
  if (colors[name]) return colors[name];
  const c = fallbackColors[idxRef.i % fallbackColors.length];
  idxRef.i++;
  return c;
}

async function selectStation(station) {
  detailsEl.innerHTML = `
    <div class="station-title">${station.adresse}</div>
    <div class="station-sub">${station.cp} ${station.ville} &middot; id ${station.id}</div>
    <div class="cards" id="cards"></div>
    <h2 class="section-title">Évolution (données disponibles)</h2>
    <div id="chart"><p class="empty">Chargement...</p></div>
  `;

  const cardsEl = document.getElementById('cards');
  Object.keys(station.prices).sort().forEach(fuel => {
    const p = station.prices[fuel];
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `<div class="fuel">${fuel}</div>
      <div class="price">${parseFloat(p.prix_eur).toFixed(3)} €</div>
      <div class="date">maj ${parseDate(p.maj_officielle).toLocaleString('fr-FR')}</div>`;
    cardsEl.appendChild(div);
  });

  const dept = station.cp.slice(0, 2);
  try {
    if (!loadedHistoryChunks.has(station.id)) {
      await loadScript('data/' + station.id + '.js');
      loadedHistoryChunks.add(station.id);
    }
    if (!loadedAvgChunks.has(dept)) {
      await loadScript('dept_avg/' + dept + '.js');
      loadedAvgChunks.add(dept);
    }
  } catch (e) {
    document.getElementById('chart').innerHTML = `<p class="empty">${e.message}</p>`;
    return;
  }

  const history = (window.STATION_HISTORY_DATA && window.STATION_HISTORY_DATA[station.id]) || [];
  if (history.length === 0) {
    document.getElementById('chart').outerHTML = '<p class="empty">Pas d\\'historique disponible pour cette station.</p>';
    return;
  }

  const byFuel = {};
  history.forEach(r => {
    if (!byFuel[r.carburant]) byFuel[r.carburant] = [];
    byFuel[r.carburant].push({ x: parseDate(r.maj_officielle), y: parseFloat(r.prix_eur) });
  });
  Object.values(byFuel).forEach(arr => arr.sort((a, b) => a.x - b.x));

  const deptSeries = (window.DEPT_AVG_DATA && window.DEPT_AVG_DATA[dept]) || {};

  const idxRef = { i: 0 };
  const traces = Object.keys(byFuel).sort().map(fuel => ({
    x: byFuel[fuel].map(p => p.x),
    y: byFuel[fuel].map(p => p.y),
    name: fuel,
    mode: 'lines',
    line: { color: colorFor(fuel, idxRef), shape: 'hv', width: 2 },
    hovertemplate: '%{y:.3f} €<br>%{x|%d/%m/%Y %H:%M}<extra>' + fuel + '</extra>',
  }));

  // Moyenne du departement pour le meme carburant, en pointilles, pour comparaison.
  Object.keys(byFuel).sort().forEach(fuel => {
    const avgSeries = deptSeries[fuel];
    if (!avgSeries || avgSeries.length === 0) return;
    traces.push({
      x: avgSeries.map(p => parseDate(p.date)),
      y: avgSeries.map(p => p.avg),
      name: 'Moyenne ' + dept + ' - ' + fuel,
      mode: 'lines',
      line: { color: colorFor(fuel, idxRef), shape: 'hv', width: 1.5, dash: 'dot' },
      opacity: 0.6,
      hovertemplate: 'Moyenne departement : %{y:.3f} €<br>%{x|%d/%m/%Y}<extra>' + fuel + '</extra>',
    });
  });

  try {
    if (typeof Plotly === 'undefined') throw new Error("Plotly ne s'est pas charge.");
    Plotly.newPlot('chart', traces, {
      height: 560,
      margin: { t: 10, r: 20, l: 55, b: 70 },
      hovermode: 'x unified',
      legend: { orientation: 'h', y: -0.2 },
      xaxis: {
        type: 'date',
        rangeslider: { visible: true },
        rangeselector: {
          buttons: [
            { count: 1, label: '1m', step: 'month', stepmode: 'backward' },
            { count: 6, label: '6m', step: 'month', stepmode: 'backward' },
            { step: 'all', label: 'Tout' },
          ]
        }
      },
      yaxis: { title: 'Prix (EUR / litre)' },
    }, { responsive: true, displaylogo: false });
  } catch (e) {
    document.getElementById('chart').innerHTML = `<p class="empty">Graphique indisponible : ${e.message}</p>`;
    console.error(e);
  }
}
</script>
</body>
</html>
"""


def main():
    config = load_config()
    departements = config["departements"]
    stations_path = os.path.join(BASE_DIR, config["stations_filename"])
    prix_dir = os.path.join(BASE_DIR, config["prix_dir"])
    stations_dir = os.path.join(BASE_DIR, config["stations_dir"])
    dept_avg_dir = os.path.join(BASE_DIR, config["dept_avg_dir"])
    site_path = os.path.join(BASE_DIR, config["site_filename"])

    stations_rows = read_csv_rows(stations_path)
    stations_by_id = {r["station_id"]: r for r in stations_rows}
    prix_by_dept = read_prix_dir(prix_dir)
    all_prix_rows = [r for rows in prix_by_dept.values() for r in rows]

    if not stations_rows or not all_prix_rows:
        print("Aucune donnee disponible : lance d'abord collect_prices.py.")
        return

    latest = latest_prices_by_station(all_prix_rows)

    by_dept, skipped_no_coords, skipped_no_price = write_station_chunks(stations_dir, stations_rows, latest)

    dept_series_by_dept = {
        dept: average_series_for_department(rows) for dept, rows in prix_by_dept.items()
    }
    write_dept_avg_chunks(dept_avg_dir, dept_series_by_dept)

    dept_latest = department_latest_averages(latest, stations_by_id)

    nb_stations = sum(len(v) for v in by_dept.values())

    html = HTML_TEMPLATE.replace("__NOMS_DEPARTEMENTS__", json.dumps(departements, ensure_ascii=False))
    html = html.replace("__DEPT_LATEST__", json.dumps(dept_latest, ensure_ascii=False))
    html = html.replace("__NB_STATIONS__", str(nb_stations))
    html = html.replace("__NB_DEPARTEMENTS__", str(len(by_dept)))
    html = html.replace("__GENERATED__", datetime.now().strftime("%d/%m/%Y %H:%M"))

    with open(site_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(
        f"Site genere : {config['site_filename']} ({nb_stations} station(s) sur {len(by_dept)} departement(s), "
        f"{skipped_no_price} ignoree(s) sans prix connu, {skipped_no_coords} ignoree(s) sans coordonnees)."
    )


if __name__ == "__main__":
    main()
