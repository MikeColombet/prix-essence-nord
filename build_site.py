#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Construit index.html : un site de recherche de stations-service par code
postal (Hauts-de-France, Normandie, Grand Est, Ile-de-France). Tape un code
postal, la liste des stations de son departement s'affiche, clique sur une
station pour voir ses prix actuels et son evolution. La page affiche aussi
la moyenne actuelle de chaque carburant (departement, region, national), et
un bouton "Voir l'evolution" sous chaque niveau ouvre son propre graphique
d'evolution (independant de la station selectionnee, pas superpose dessus).

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


def grouped_latest_averages(latest_by_station, stations_by_id, group_for_cp):
    """Moyenne actuelle de chaque carburant, regroupee par la clef que
    renvoie group_for_cp(cp) (departement, region, ou une constante unique
    pour une moyenne nationale) ; calculee a partir du dernier prix connu de
    chaque station. group_for_cp doit renvoyer None pour exclure une station."""
    sums = {}
    counts = {}
    for sid, prices in latest_by_station.items():
        cp = stations_by_id.get(sid, {}).get("cp", "")
        group = group_for_cp(cp)
        if group is None:
            continue
        for fuel, p in prices.items():
            try:
                val = float(p["prix_eur"])
            except (TypeError, ValueError):
                continue
            sums.setdefault(group, {})
            counts.setdefault(group, {})
            sums[group][fuel] = sums[group].get(fuel, 0.0) + val
            counts[group][fuel] = counts[group].get(fuel, 0) + 1
    result = {}
    for group, fuel_sums in sums.items():
        result[group] = {
            fuel: {"avg": round(fuel_sums[fuel] / counts[group][fuel], 4), "n": counts[group][fuel]}
            for fuel in fuel_sums
        }
    return result


def average_series(prix_rows):
    """Serie temporelle de la moyenne d'un ensemble de lignes de prix pour
    chaque carburant : pour chaque jour ou au moins un prix a change parmi
    ces lignes, la moyenne du dernier prix connu de chaque station a cette
    date (report du dernier prix connu entre deux changements, comme un
    graphique en escalier). Utilisee pour les moyennes departementale,
    regionale et nationale : meme calcul, seul l'ensemble de lignes passe en
    entree change (un departement, les departements d'une region, ou tout).
    Sert a superposer ces tendances au graphique d'evolution d'une station."""
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
  .dept-avg-wrap, .national-avg-wrap {
    background: #fff; border-radius: 10px; padding: 14px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px;
  }
  .section-title .dim { font-weight: 400; color: #6b6b70; font-size: 0.85rem; }
  .avg-group-title {
    font-size: 0.7rem; text-transform: uppercase; color: #6b6b70;
    letter-spacing: .04em; margin: 12px 0 6px;
  }
  .avg-group:first-child .avg-group-title { margin-top: 0; }
  .evolution-btn {
    margin-top: 10px; font-size: 0.8rem; padding: 6px 12px; border-radius: 6px;
    border: 1px solid #d8d8dc; background: #fff; color: #2980b9; cursor: pointer;
  }
  .evolution-btn:hover { background: #f5f6f8; }
  .evolution-chart { margin-top: 12px; min-height: 380px; }
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

  <div class="national-avg-wrap">
    <h2 class="section-title">Moyenne nationale actuelle <span class="dim">(departements suivis)</span></h2>
    <div class="cards" id="nationalAvgCards"></div>
    <button type="button" class="evolution-btn" id="nationalEvolutionBtn">Voir l'evolution nationale</button>
    <div class="evolution-chart" id="nationalChart" style="display:none"></div>
  </div>

  <div class="search-wrap">
    <label for="cpInput">Code postal :</label>
    <input id="cpInput" type="text" inputmode="numeric" autocomplete="off" placeholder="ex : 59700" maxlength="5">
    <div class="search-hint" id="searchHint">Tape au moins les 2 premiers chiffres d'un code postal pour voir les stations du departement.</div>
  </div>

  <div class="dept-avg-wrap" id="deptAvgWrap" style="display:none">
    <h2 class="section-title">Moyennes actuelles <span id="deptAvgLabel"></span></h2>
    <div class="avg-group">
      <div class="avg-group-title">Departement</div>
      <div class="cards" id="deptAvgCards"></div>
      <button type="button" class="evolution-btn" id="deptEvolutionBtn">Voir l'evolution du departement</button>
      <div class="evolution-chart" id="deptChart" style="display:none"></div>
    </div>
    <div class="avg-group">
      <div class="avg-group-title">Region</div>
      <div class="cards" id="regionAvgCards"></div>
      <button type="button" class="evolution-btn" id="regionEvolutionBtn">Voir l'evolution de la region</button>
      <div class="evolution-chart" id="regionChart" style="display:none"></div>
    </div>
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
const DEPT_TO_REGION = __DEPT_TO_REGION__;
const deptLatest = __DEPT_LATEST__;
const regionLatest = __REGION_LATEST__;
const regionSeries = __REGION_SERIES__;
const nationalLatest = __NATIONAL_LATEST__;
const nationalSeries = __NATIONAL_SERIES__;

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
const regionAvgCards = document.getElementById('regionAvgCards');
const nationalAvgCards = document.getElementById('nationalAvgCards');
const resultsWrap = document.getElementById('resultsWrap');
const detailsEl = document.getElementById('details');
const nationalEvolutionBtn = document.getElementById('nationalEvolutionBtn');
const nationalChartEl = document.getElementById('nationalChart');
const deptEvolutionBtn = document.getElementById('deptEvolutionBtn');
const deptChartEl = document.getElementById('deptChart');
const regionEvolutionBtn = document.getElementById('regionEvolutionBtn');
const regionChartEl = document.getElementById('regionChart');

cpInput.addEventListener('input', () => {
  const digits = cpInput.value.replace(/\\D/g, '').slice(0, 5);
  if (cpInput.value !== digits) cpInput.value = digits;
  onSearch(digits);
});

function resetResults(message) {
  deptAvgWrap.style.display = 'none';
  resultsWrap.innerHTML = `<p class="empty">${message}</p>`;
}

function renderAvgCards(container, avgs, emptyMessage) {
  if (!avgs || Object.keys(avgs).length === 0) {
    container.innerHTML = `<p class="empty">${emptyMessage}</p>`;
    return;
  }
  container.innerHTML = '';
  sortFuels(Object.keys(avgs)).forEach(fuel => {
    const d = avgs[fuel];
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `<div class="fuel">${fuel}</div>
      <div class="price">${d.avg.toFixed(3)} €</div>
      <div class="date">moyenne sur ${d.n} station(s)</div>`;
    container.appendChild(div);
  });
}

renderAvgCards(nationalAvgCards, nationalLatest, "Pas encore de prix connus.");

// Graphique d'evolution d'un niveau (departement, region ou national) : ses
// propres tendances uniquement, pas de superposition avec une station.
function renderSeriesChart(divId, seriesByFuel) {
  const el = document.getElementById(divId);
  const fuels = sortFuels(Object.keys(seriesByFuel || {}).filter(f => seriesByFuel[f] && seriesByFuel[f].length));
  if (fuels.length === 0) {
    el.innerHTML = '<p class="empty">Pas encore d\\'historique disponible.</p>';
    return;
  }
  const idxRef = { i: 0 };
  const traces = fuels.map(fuel => ({
    x: seriesByFuel[fuel].map(p => parseDate(p.date)),
    y: seriesByFuel[fuel].map(p => p.avg),
    name: fuel,
    mode: 'lines',
    line: { color: colorFor(fuel, idxRef), shape: 'hv', width: 2 },
    hovertemplate: '%{y:.3f} €<br>%{x|%d/%m/%Y}<extra>' + fuel + '</extra>',
  }));
  try {
    if (typeof Plotly === 'undefined') throw new Error("Plotly ne s'est pas charge.");
    Plotly.newPlot(divId, traces, {
      height: 380,
      margin: { t: 10, r: 20, l: 55, b: 60 },
      hovermode: 'x unified',
      legend: { orientation: 'h', y: -0.25 },
      xaxis: { type: 'date', rangeslider: { visible: true } },
      yaxis: { title: 'Prix moyen (EUR / litre)' },
    }, { responsive: true, displaylogo: false });
  } catch (e) {
    el.innerHTML = `<p class="empty">Graphique indisponible : ${e.message}</p>`;
    console.error(e);
  }
}

function toggleEvolution(btn, el, label, renderFn) {
  const showing = el.style.display !== 'none';
  if (showing) {
    el.style.display = 'none';
    btn.textContent = label;
    return;
  }
  el.style.display = 'block';
  btn.textContent = label.replace("Voir", "Masquer");
  renderFn();
}

nationalEvolutionBtn.addEventListener('click', () => {
  toggleEvolution(nationalEvolutionBtn, nationalChartEl, "Voir l'evolution nationale", () => {
    if (!nationalChartEl.dataset.rendered) {
      renderSeriesChart('nationalChart', nationalSeries);
      nationalChartEl.dataset.rendered = '1';
    }
  });
});

let currentDept = null;
let currentRegion = null;

// Moyennes departement + region pour une station donnee (code postal de la
// station selectionnee, ou du departement recherche avant toute selection).
function showLocalAvg(dept) {
  currentDept = dept;
  currentRegion = DEPT_TO_REGION[dept] || null;

  deptAvgLabel.textContent = NOMS_DEPARTEMENTS[dept]
    ? `(${dept} - ${NOMS_DEPARTEMENTS[dept]}${currentRegion ? ' / ' + currentRegion : ''})`
    : `(${dept})`;
  deptAvgWrap.style.display = 'block';
  renderAvgCards(deptAvgCards, deptLatest[dept], "Pas encore de prix connus pour ce departement.");
  renderAvgCards(regionAvgCards, currentRegion ? regionLatest[currentRegion] : null, "Pas encore de prix connus pour cette region.");

  // Le departement/la region ont pu changer : referme les graphiques
  // ouverts pour un contexte precedent plutot que de laisser un graphique
  // perime affiche.
  deptChartEl.style.display = 'none';
  deptChartEl.removeAttribute('data-rendered-for');
  deptEvolutionBtn.textContent = "Voir l'evolution du departement";
  regionChartEl.style.display = 'none';
  regionChartEl.removeAttribute('data-rendered-for');
  regionEvolutionBtn.textContent = "Voir l'evolution de la region";
}

deptEvolutionBtn.addEventListener('click', async () => {
  if (!currentDept) return;
  const showing = deptChartEl.style.display !== 'none';
  if (showing) {
    deptChartEl.style.display = 'none';
    deptEvolutionBtn.textContent = "Voir l'evolution du departement";
    return;
  }
  deptChartEl.style.display = 'block';
  deptEvolutionBtn.textContent = "Masquer l'evolution du departement";
  if (deptChartEl.dataset.renderedFor === currentDept) return;
  deptChartEl.innerHTML = '<p class="empty">Chargement...</p>';
  if (!loadedAvgChunks.has(currentDept)) {
    try {
      await loadScript('dept_avg/' + currentDept + '.js');
      loadedAvgChunks.add(currentDept);
    } catch (e) {
      deptChartEl.innerHTML = `<p class="empty">${e.message}</p>`;
      return;
    }
  }
  const series = (window.DEPT_AVG_DATA && window.DEPT_AVG_DATA[currentDept]) || {};
  renderSeriesChart('deptChart', series);
  deptChartEl.dataset.renderedFor = currentDept;
});

regionEvolutionBtn.addEventListener('click', () => {
  if (!currentRegion) return;
  const showing = regionChartEl.style.display !== 'none';
  if (showing) {
    regionChartEl.style.display = 'none';
    regionEvolutionBtn.textContent = "Voir l'evolution de la region";
    return;
  }
  regionChartEl.style.display = 'block';
  regionEvolutionBtn.textContent = "Masquer l'evolution de la region";
  if (regionChartEl.dataset.renderedFor === currentRegion) return;
  renderSeriesChart('regionChart', regionSeries[currentRegion] || {});
  regionChartEl.dataset.renderedFor = currentRegion;
});

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

  showLocalAvg(dept);

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
    resultsWrap.innerHTML = '<p class="empty">Aucune station trouvee pour ce code postal.</p>';
    return;
  }

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
  // Reflete explicitement le departement/la region de la station selectionnee
  // (et pas seulement du code postal tape dans la recherche).
  const dept = station.cp.slice(0, 2);
  showLocalAvg(dept);

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

  try {
    if (!loadedHistoryChunks.has(station.id)) {
      await loadScript('data/' + station.id + '.js');
      loadedHistoryChunks.add(station.id);
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

  const idxRef = { i: 0 };
  const traces = Object.keys(byFuel).sort().map(fuel => ({
    x: byFuel[fuel].map(p => p.x),
    y: byFuel[fuel].map(p => p.y),
    name: fuel,
    mode: 'lines',
    line: { color: colorFor(fuel, idxRef), shape: 'hv', width: 2 },
    hovertemplate: '%{y:.3f} €<br>%{x|%d/%m/%Y %H:%M}<extra>' + fuel + '</extra>',
  }));

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
    regions = config["regions"]
    dept_to_region = {d: region for region, depts in regions.items() for d in depts}
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

    dept_series_by_dept = {dept: average_series(rows) for dept, rows in prix_by_dept.items()}
    write_dept_avg_chunks(dept_avg_dir, dept_series_by_dept)

    region_series_by_region = {
        region: average_series([r for d in depts for r in prix_by_dept.get(d, [])])
        for region, depts in regions.items()
    }
    national_series = average_series(all_prix_rows)

    dept_latest = grouped_latest_averages(latest, stations_by_id, lambda cp: cp[:2] or None)
    region_latest = grouped_latest_averages(
        latest, stations_by_id, lambda cp: dept_to_region.get(cp[:2])
    )
    national_latest_grouped = grouped_latest_averages(
        latest, stations_by_id, lambda cp: "national" if cp[:2] else None
    )
    national_latest = national_latest_grouped.get("national", {})

    nb_stations = sum(len(v) for v in by_dept.values())

    html = HTML_TEMPLATE.replace("__NOMS_DEPARTEMENTS__", json.dumps(departements, ensure_ascii=False))
    html = html.replace("__DEPT_TO_REGION__", json.dumps(dept_to_region, ensure_ascii=False))
    html = html.replace("__DEPT_LATEST__", json.dumps(dept_latest, ensure_ascii=False))
    html = html.replace("__REGION_LATEST__", json.dumps(region_latest, ensure_ascii=False))
    html = html.replace("__REGION_SERIES__", json.dumps(region_series_by_region, ensure_ascii=False))
    html = html.replace("__NATIONAL_LATEST__", json.dumps(national_latest, ensure_ascii=False))
    html = html.replace("__NATIONAL_SERIES__", json.dumps(national_series, ensure_ascii=False))
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
