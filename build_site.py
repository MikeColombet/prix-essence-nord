#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Construit deux pages statiques a partir des donnees collectees par
collect_prices.py, couvrant la France metropolitaine (95 departements, la
Corse suivie comme un seul departement "20") :

- index.html — uniquement la recherche par code postal. Tape un code
  postal, la liste des stations de son departement s'affiche, clique sur
  une station pour voir ses prix actuels et son evolution. Aucune moyenne
  departement/national ici : voir comparaison.html.
- comparaison.html — moyenne nationale actuelle (+ son evolution), et un
  tableau des departements (tries par numero) avec le prix de chaque
  carburant et un indicateur moins cher/plus cher que la moyenne nationale.
  Clique une ligne pour afficher son evolution. L'en-tete du tableau reste
  visible pendant le defilement (colonne collante).

Aucune des deux pages n'embarque les donnees de station : elles sont
chargees a la demande, par departement (stations/{dept}.json.gz,
dept_avg/{dept}.json.gz) ou par station (data/{dept}/{id}.json.gz). A
l'echelle de la France entiere sur 10 ans, tout charger d'un coup rendrait
ces pages enormes ; le chargement a la demande les garde legeres quel que
soit le nombre total de stations suivies. Chaque fichier est gzippe (le
navigateur le decompresse via DecompressionStream, une API native, pas de
dependance) : ca reduit encore la taille transferee/stockee d'un facteur
~5-8 sur ce genre de donnees tres repetitives. Consequence : le site doit
etre servi en http(s) (GitHub Pages, ou `python3 -m http.server` en local)
— fetch() ne peut pas lire de fichiers locaux via file://.

Usage : python3 build_site.py
(a relancer apres chaque python3 collect_prices.py pour refleter les
nouvelles donnees)

Ne depend d'aucune librairie externe (gzip compris, bibliotheque standard).
"""
import csv
import gzip
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


def read_marques(path):
    """{station_id: marque} depuis marques.csv (voir fetch_brands.py).
    Dict vide si le fichier n'existe pas encore (fetch_brands.py jamais
    lance) : le site fonctionne alors sans marque affichee."""
    return {r["station_id"]: r["marque"] for r in read_csv_rows(path) if r.get("marque")}


def read_gzip_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_gzip_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)


def process_all_departments(data_dir):
    """Parcourt data/{dept}/*.json.gz departement par departement. Pour
    chaque departement, calcule sa propre serie de moyennes (average_series)
    directement a partir de ses lignes, PUIS les libere avant de passer au
    departement suivant.

    C'est deliberement different d'un simple "tout charger puis tout
    calculer" : a l'echelle de la France entiere sur 10 ans (~43 millions de
    lignes), materialiser l'ensemble des lignes dans une seule structure
    Python (avant meme de commencer les calculs) a fait planter une
    premiere version de ce script (tue par manque de memoire). Ici, la
    memoire de pointe ne depend jamais que de la taille d'UN departement
    (au plus quelques centaines de milliers de lignes), jamais de la France
    entiere. La moyenne nationale est ensuite obtenue par fusion des series
    departementales (petites, quelques milliers de points) via
    merge_series() plutot qu'en refusionnant les lignes brutes — voir sa
    docstring.

    Retourne (latest_by_station, dept_series_by_dept) :
    - latest_by_station : {station_id: {carburant: {prix_eur, maj_officielle}}}
      (dernier prix connu de chaque station, toutes annees confondues)
    - dept_series_by_dept : {dept: average_series(...)} pour ce departement."""
    latest_by_station = {}
    dept_series_by_dept = {}
    if not os.path.isdir(data_dir):
        return latest_by_station, dept_series_by_dept

    for dept in sorted(os.listdir(data_dir)):
        dept_path = os.path.join(data_dir, dept)
        if not os.path.isdir(dept_path):
            continue
        dept_rows = []
        for fname in os.listdir(dept_path):
            if not fname.endswith(".json.gz"):
                continue
            sid = fname[: -len(".json.gz")]
            entries = read_gzip_json(os.path.join(dept_path, fname))
            latest = {}
            for carburant, prix_eur, maj in entries:
                cur = latest.get(carburant)
                if cur is None or maj > cur["maj_officielle"]:
                    latest[carburant] = {"prix_eur": prix_eur, "maj_officielle": maj}
                dept_rows.append((sid, carburant, prix_eur, maj))
            if latest:
                latest_by_station[sid] = latest
        dept_series_by_dept[dept] = average_series(dept_rows)
        # dept_rows sort de portee ici et est garbage-collecte avant de
        # passer au departement suivant.

    return latest_by_station, dept_series_by_dept


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


def average_series(rows):
    """rows : iterable de (station_id, carburant, prix_eur, maj_officielle),
    typiquement toutes les lignes d'UN SEUL departement (voir
    process_all_departments — volontairement pas plus, pour rester petit en
    memoire). Serie temporelle de la moyenne de cet ensemble pour chaque
    carburant : pour chaque jour ou au moins un prix a change parmi ces
    lignes, la moyenne du dernier prix connu de chaque station a cette date
    (report du dernier prix connu entre deux changements, comme un
    graphique en escalier). Les moyennes regionale et nationale ne
    rappellent PAS cette fonction sur un ensemble de lignes plus large :
    elles fusionnent les series departementales deja calculees, voir
    merge_series()."""
    by_fuel = {}
    for sid, carburant, prix_eur, maj in rows:
        try:
            price = float(prix_eur)
        except (TypeError, ValueError):
            continue
        by_fuel.setdefault(carburant, []).append((maj, sid, price))

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


def merge_series(series_list):
    """series_list : liste de resultats de average_series() (typiquement,
    un par departement). Fusionne ces series departementales en une seule
    serie ponderee par nombre de stations, par carburant — sans jamais
    retoucher aux lignes de prix brutes. Chaque point d'une serie
    departementale porte deja (avg, n) ; sum = avg*n redonne la somme des
    prix de ce departement a cette date, et une somme/compte regionale ou
    nationale s'obtient en sommant ces sommes/comptes a travers les
    departements (moyenne ponderee, exacte, pas juste une "moyenne de
    moyennes"). Cout : proportionnel au nombre de points des series
    d'entree (quelques milliers par departement) et au nombre de
    departements fusionnes, jamais au nombre de relevés de prix bruts —
    c'est ce qui permet de calculer la moyenne nationale sans jamais
    recharger les dizaines de millions de lignes de tous les departements
    a la fois."""
    fuels = set()
    for s in series_list:
        fuels.update(s.keys())

    result = {}
    for fuel in fuels:
        lists = [s.get(fuel, []) for s in series_list]
        idx = [0] * len(lists)
        current = [None] * len(lists)  # (avg, n) le plus recent connu par departement

        points = []
        while True:
            candidate_days = [lists[i][idx[i]]["date"] for i in range(len(lists)) if idx[i] < len(lists[i])]
            if not candidate_days:
                break
            day = min(candidate_days)
            for i in range(len(lists)):
                while idx[i] < len(lists[i]) and lists[i][idx[i]]["date"] == day:
                    p = lists[i][idx[i]]
                    current[i] = (p["avg"], p["n"])
                    idx[i] += 1
            total_n = sum(c[1] for c in current if c)
            if total_n:
                total_sum = sum(c[0] * c[1] for c in current if c)
                points.append({"date": day, "avg": round(total_sum / total_n, 4), "n": total_n})
        result[fuel] = points

    return result


def write_station_chunks(stations_dir, stations_rows, latest, marques):
    """Ecrit un fichier stations/{dept}.json.gz par departement (chargement
    a la demande cote client, en fonction du code postal recherche). marques
    (station_id -> marque, depuis marques.csv/fetch_brands.py) est une
    donnee independante de stations.csv : voir docstring de fetch_brands.py
    pour pourquoi elle n'est pas fusionnee dans stations.csv lui-meme."""
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
        station = {
            "id": sid,
            "adresse": r["adresse"],
            "ville": r["ville"],
            "cp": r["cp"],
            "latitude": lat,
            "longitude": lon,
            "prices": prices,
        }
        marque = marques.get(sid)
        if marque:
            station["marque"] = marque
        by_dept.setdefault(dept, []).append(station)

    for dept, payload in by_dept.items():
        write_gzip_json(os.path.join(stations_dir, f"{dept}.json.gz"), payload)

    return by_dept, skipped_no_coords, skipped_no_price


def write_dept_avg_chunks(dept_avg_dir, dept_series_by_dept):
    """Ecrit un fichier dept_avg/{dept}.json.gz par departement (charge a la
    demande quand on clique sur "Voir l'evolution du departement")."""
    for dept, series in dept_series_by_dept.items():
        write_gzip_json(os.path.join(dept_avg_dir, f"{dept}.json.gz"), series)


HTML_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recherche des prix des carburants - France</title>
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
  .mode-tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .mode-tab {
    font-size: 0.9rem; padding: 8px 16px; border-radius: 8px; border: 1px solid #d8d8dc;
    background: #fff; color: #444; cursor: pointer;
  }
  .mode-tab:hover { background: #f5f6f8; }
  .mode-tab.active { background: #2980b9; color: #fff; border-color: #2980b9; }
  .map-wrap {
    background: #fff; border-radius: 10px; padding: 12px; max-width: 700px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px;
  }
  #franceMap { width: 100%; height: 420px; }
  @media (max-width: 600px) { #franceMap { height: 360px; } }
  .station-map-wrap { margin-bottom: 16px; }
  #stationMap { width: 100%; height: 220px; border-radius: 8px; overflow: hidden; }
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
  .result-brand { font-weight: 700; font-size: 1.05rem; margin-bottom: 2px; }
  .result-title { font-weight: 500; font-size: 0.85rem; color: #444; }
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
  .station-title { font-weight: 600; margin-bottom: 2px; }
  .station-sub { color: #6b6b70; font-size: 0.85rem; margin-bottom: 16px; }
  .brand-badge {
    display: inline-block; background: #eef2f7; color: #2c3e50; font-weight: 600;
    padding: 1px 9px; border-radius: 999px; font-size: 0.72rem; vertical-align: middle;
  }
  #chart { min-height: 560px; }
  .nav-link { display: inline-block; margin-bottom: 16px; font-size: 0.9rem; color: #2980b9; text-decoration: none; }
  .nav-link:hover { text-decoration: underline; }
</style>
</head>
<body>
  <h1>Recherche des prix des carburants - France</h1>
  <p class="description">Cherche un code postal pour voir les stations-service de son departement, leurs prix
  actuels et l'evolution de leurs tarifs dans le temps. Couvre la France metropolitaine (la Corse est suivie
  comme un seul departement, son code postal ne distinguant pas 2A/2B).</p>
  <div class="meta">__NB_STATIONS__ station(s) suivies sur __NB_DEPARTEMENTS__ departement(s) &middot; page generee le __GENERATED__ &middot; source : flux officiel donnees.roulez-eco.fr</div>

  <a class="nav-link" href="comparaison.html">Comparer les prix par departement / national &rarr;</a>

  <div class="mode-tabs">
    <button type="button" class="mode-tab active" id="modeTabCp">Par code postal</button>
    <button type="button" class="mode-tab" id="modeTabMap">Sur la carte</button>
  </div>

  <div class="search-wrap" id="cpSearchWrap">
    <label for="cpInput">Code postal :</label>
    <input id="cpInput" type="text" inputmode="numeric" autocomplete="off" placeholder="ex : 59700" maxlength="5">
    <div class="search-hint" id="searchHint">Tape au moins les 2 premiers chiffres d'un code postal pour voir les stations du departement.</div>
  </div>

  <div class="map-wrap" id="mapWrap" style="display:none">
    <div id="franceMap"><p class="empty">Chargement des stations...</p></div>
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

// Chaque chunk de donnees est un petit fichier JSON gzippe : fetch() recupere
// les octets bruts, DecompressionStream (API native du navigateur, aucune
// dependance) les decompresse a la volee. Necessite d'etre servi en http(s)
// (GitHub Pages ou `python3 -m http.server` en local) : fetch() ne peut pas
// lire de fichier local via file://.
async function fetchGzipJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error('impossible de charger ' + url + ' (HTTP ' + resp.status + ')');
  if (typeof DecompressionStream === 'undefined') {
    throw new Error("ce navigateur ne supporte pas DecompressionStream (mets-le a jour)");
  }
  const stream = resp.body.pipeThrough(new DecompressionStream('gzip'));
  const text = await new Response(stream).text();
  return JSON.parse(text);
}

const stationsCache = new Map();
const historyCache = new Map();

async function ensureStationsLoaded(dept) {
  if (stationsCache.has(dept)) return stationsCache.get(dept);
  const data = await fetchGzipJson('stations/' + dept + '.json.gz');
  stationsCache.set(dept, data);
  return data;
}

async function ensureHistoryLoaded(sid, dept) {
  if (historyCache.has(sid)) return historyCache.get(sid);
  const data = await fetchGzipJson('data/' + dept + '/' + sid + '.json.gz');
  historyCache.set(sid, data);
  return data;
}

// Pour la carte, on a besoin de TOUTES les stations d'un coup plutot que
// d'un seul departement : on reutilise simplement ensureStationsLoaded()
// sur chaque departement en parallele (memes chunks, meme cache) plutot que
// de generer un fichier France entiere supplementaire qui dupliquerait ces
// memes donnees sur le disque.
let allStationsPromise = null;
function ensureAllStationsLoaded() {
  if (!allStationsPromise) {
    allStationsPromise = Promise.all(
      Object.keys(NOMS_DEPARTEMENTS).map(d => ensureStationsLoaded(d).catch(() => []))
    ).then(lists => lists.flat());
  }
  return allStationsPromise;
}

const cpInput = document.getElementById('cpInput');
const resultsWrap = document.getElementById('resultsWrap');
const detailsEl = document.getElementById('details');
const modeTabCp = document.getElementById('modeTabCp');
const modeTabMap = document.getElementById('modeTabMap');
const cpSearchWrap = document.getElementById('cpSearchWrap');
const mapWrap = document.getElementById('mapWrap');

cpInput.addEventListener('input', () => {
  const digits = cpInput.value.replace(/\\D/g, '').slice(0, 5);
  if (cpInput.value !== digits) cpInput.value = digits;
  onSearch(digits);
});

function resetResults(message) {
  resultsWrap.innerHTML = `<p class="empty">${message}</p>`;
}

let mapRendered = false;

modeTabCp.addEventListener('click', () => {
  modeTabCp.classList.add('active');
  modeTabMap.classList.remove('active');
  cpSearchWrap.style.display = 'block';
  mapWrap.style.display = 'none';
  resetResults("Tape au moins les 2 premiers chiffres d'un code postal.");
});

modeTabMap.addEventListener('click', async () => {
  modeTabMap.classList.add('active');
  modeTabCp.classList.remove('active');
  cpSearchWrap.style.display = 'none';
  mapWrap.style.display = 'block';
  resultsWrap.innerHTML = '<p class="empty">Clique une station sur la carte pour voir ses prix et son evolution.</p>';

  if (mapRendered) return;
  let allStations;
  try {
    allStations = await ensureAllStationsLoaded();
  } catch (e) {
    document.getElementById('franceMap').innerHTML = `<p class="empty">${e.message}</p>`;
    return;
  }
  await renderFranceMap(allStations);
  mapRendered = true;
});

async function renderFranceMap(stations) {
  const el = document.getElementById('franceMap');
  const withCoords = stations.filter(s => s.latitude && s.longitude);
  try {
    if (typeof Plotly === 'undefined') throw new Error("Plotly ne s'est pas charge.");
    // Plotly.newPlot ne vide pas le contenu HTML deja present dans le div
    // cible (ex: le message "Chargement..."), il ajoute juste sa carte a
    // cote : on vide explicitement avant de dessiner.
    el.innerHTML = '';
    // La France est plus large que haute : sur un conteneur etroit/portrait
    // (mobile), un zoom fixe cadre trop serre en largeur et montre surtout
    // les pays voisins en haut/bas. On zoome un peu moins dans ce cas pour
    // que la France entiere reste visible par defaut.
    const rect = el.getBoundingClientRect();
    const zoom = rect.width < rect.height ? 4.0 : 4.6;
    await Plotly.newPlot('franceMap', [{
      type: 'scattermap',
      mode: 'markers',
      lat: withCoords.map(s => s.latitude),
      lon: withCoords.map(s => s.longitude),
      text: withCoords.map(s => `<b>${s.marque || s.adresse}</b><br>${s.adresse}<br>${s.cp} ${s.ville}`),
      customdata: withCoords.map(s => s.id),
      hoverinfo: 'text',
      marker: { size: 6, color: '#2980b9', opacity: 0.7 },
    }], {
      map: {
        style: 'open-street-map',
        center: { lat: 46.6, lon: 2.5 },
        zoom: zoom,
      },
      margin: { t: 0, r: 0, l: 0, b: 0 },
    }, { responsive: true, displaylogo: false });

    el.on('plotly_click', (data) => {
      if (!data.points || !data.points.length) return;
      const sid = data.points[0].customdata;
      const station = withCoords.find(s => s.id === sid);
      if (station) selectStation(station);
    });
  } catch (e) {
    el.innerHTML = `<p class="empty">Carte indisponible : ${e.message}</p>`;
    console.error(e);
  }
}

// Petite carte de localisation d'une seule station (pas d'interaction
// necessaire au-dela du zoom/pan natif de la carte, donc pas de barre
// d'outils Plotly qui n'apporterait rien dans un si petit espace).
function renderStationMap(station) {
  const el = document.getElementById('stationMap');
  if (!el || !station.latitude || !station.longitude) return;
  try {
    if (typeof Plotly === 'undefined') throw new Error("Plotly ne s'est pas charge.");
    Plotly.newPlot('stationMap', [{
      type: 'scattermap',
      mode: 'markers',
      lat: [station.latitude],
      lon: [station.longitude],
      hoverinfo: 'skip',
      marker: { size: 16, color: '#c0392b' },
    }], {
      map: {
        style: 'open-street-map',
        center: { lat: station.latitude, lon: station.longitude },
        zoom: 14,
      },
      margin: { t: 0, r: 0, l: 0, b: 0 },
    }, { responsive: true, displaylogo: false, displayModeBar: false });
  } catch (e) {
    el.innerHTML = `<p class="empty">Carte indisponible : ${e.message}</p>`;
    console.error(e);
  }
}

async function onSearch(cp) {
  if (cp.length < 2) {
    resetResults("Tape au moins les 2 premiers chiffres d'un code postal.");
    return;
  }
  const dept = cp.slice(0, 2);
  if (!NOMS_DEPARTEMENTS[dept]) {
    resetResults(`Departement ${dept} non couvert.`);
    return;
  }

  resultsWrap.innerHTML = '<p class="empty">Chargement des stations...</p>';
  let all;
  try {
    all = await ensureStationsLoaded(dept);
  } catch (e) {
    resultsWrap.innerHTML = `<p class="empty">${e.message}</p>`;
    return;
  }

  renderResults(all, cp);
}

const RESULTS_LIMIT = 150;

function renderResults(all, cp) {
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
      ${s.marque ? `<div class="result-brand">${s.marque}</div>` : ''}
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
  const dept = station.cp.slice(0, 2);

  detailsEl.innerHTML = `
    <div class="station-title">${station.adresse}${station.marque ? ' <span class="brand-badge">' + station.marque + '</span>' : ''}</div>
    <div class="station-sub">${station.cp} ${station.ville} &middot; id ${station.id}</div>
    <div class="station-map-wrap"><div id="stationMap"></div></div>
    <div class="cards" id="cards"></div>
    <h2 class="section-title">Évolution (données disponibles)</h2>
    <div id="chart"><p class="empty">Chargement...</p></div>
  `;

  renderStationMap(station);

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

  let history;
  try {
    history = await ensureHistoryLoaded(station.id, dept);
  } catch (e) {
    document.getElementById('chart').innerHTML = `<p class="empty">${e.message}</p>`;
    return;
  }

  if (!history || history.length === 0) {
    document.getElementById('chart').outerHTML = '<p class="empty">Pas d\\'historique disponible pour cette station.</p>';
    return;
  }

  const byFuel = {};
  history.forEach(([carburant, prix_eur, maj]) => {
    if (!byFuel[carburant]) byFuel[carburant] = [];
    byFuel[carburant].push({ x: parseDate(maj), y: parseFloat(prix_eur) });
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
    // Plotly.newPlot ne vide pas le contenu HTML deja present dans le div
    // cible (ex: le message "Chargement..."), il ajoute juste son propre
    // graphique a cote : on vide explicitement avant de dessiner.
    document.getElementById('chart').innerHTML = '';
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
            { count: 1, label: '1a', step: 'year', stepmode: 'backward' },
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


HTML_TEMPLATE_COMPARE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comparaison des prix des carburants - France</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2/plotly.min.js"></script>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 24px; background: #f5f6f8; color: #1c1c1e;
  }
  h1 { font-size: 1.3rem; margin: 0 0 6px 0; }
  h2.section-title { font-size: 1rem; margin: 0 0 12px 0; }
  .section-title .dim { font-weight: 400; color: #6b6b70; font-size: 0.85rem; }
  .description { color: #444; font-size: 0.9rem; max-width: 760px; margin: 0 0 10px 0; line-height: 1.4; }
  .meta { color: #6b6b70; font-size: 0.85rem; margin-bottom: 16px; }
  .nav-link { display: inline-block; margin-bottom: 16px; font-size: 0.9rem; color: #2980b9; text-decoration: none; }
  .nav-link:hover { text-decoration: underline; }
  .empty { color: #6b6b70; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
  .card {
    background: #f5f6f8; border-radius: 10px; padding: 12px 16px; min-width: 100px;
  }
  .card .fuel { font-size: 0.7rem; text-transform: uppercase; color: #6b6b70; letter-spacing: .04em; }
  .card .price { font-size: 1.3rem; font-weight: 600; margin-top: 4px; }
  .card .date { font-size: 0.65rem; color: #9a9a9e; margin-top: 2px; }
  .panel {
    background: #fff; border-radius: 10px; padding: 14px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 20px;
  }
  .evolution-btn {
    margin-top: 10px; font-size: 0.8rem; padding: 6px 12px; border-radius: 6px;
    border: 1px solid #d8d8dc; background: #fff; color: #2980b9; cursor: pointer;
  }
  .evolution-btn:hover { background: #f5f6f8; }
  .evolution-chart { margin-top: 12px; min-height: 380px; }
  .table-scroll { overflow: auto; max-height: 75vh; }
  table.cmp-table { border-collapse: collapse; width: 100%; font-size: 0.85rem; white-space: nowrap; }
  table.cmp-table th, table.cmp-table td { padding: 7px 10px; text-align: left; border-bottom: 1px solid #eee; }
  table.cmp-table th { color: #6b6b70; font-weight: 600; position: sticky; top: 0; background: #fff; z-index: 1; }
  table.cmp-table tbody tr { cursor: pointer; }
  table.cmp-table tbody tr:hover { background: #f5f6f8; }
  table.cmp-table tbody tr.selected { background: #eaf2ff; }
  td.na { color: #c3c3c8; }
  .ind { font-size: 0.75rem; margin-left: 3px; }
  .ind.cheaper { color: #1e8e3e; }
  .ind.pricier { color: #c0392b; }
  .evolution-detail {
    background: #fff; border-radius: 10px; padding: 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 20px;
  }
  #evolutionDetailChart { min-height: 400px; }
</style>
</head>
<body>
  <h1>Comparaison des prix des carburants - France</h1>
  <p class="description">Moyenne nationale actuelle, et prix moyen par departement, avec un
  indicateur (&#9660; moins cher, &#9650; plus cher) par rapport a la moyenne nationale de chaque carburant.
  Clique une ligne pour voir son evolution dans le temps.</p>
  <div class="meta">page generee le __GENERATED__ &middot; source : flux officiel donnees.roulez-eco.fr</div>

  <a class="nav-link" href="index.html">&larr; Recherche par code postal</a>

  <div class="panel">
    <h2 class="section-title">Moyenne nationale actuelle <span class="dim">(departements suivis)</span></h2>
    <div class="cards" id="nationalAvgCards"></div>
    <button type="button" class="evolution-btn" id="nationalEvolutionBtn">Voir l'evolution nationale</button>
    <div class="evolution-chart" id="nationalChart" style="display:none"></div>
  </div>

  <div class="panel">
    <h2 class="section-title">Par departement</h2>
    <div class="table-scroll">
      <table class="cmp-table" id="deptTable">
        <thead><tr id="deptTableHead"></tr></thead>
        <tbody id="deptTableBody"></tbody>
      </table>
    </div>
  </div>

  <div class="evolution-detail" id="evolutionDetail" style="display:none">
    <h2 class="section-title" id="evolutionDetailTitle"></h2>
    <div id="evolutionDetailChart"></div>
  </div>

<script>
const NOMS_DEPARTEMENTS = __NOMS_DEPARTEMENTS__;
const deptLatest = __DEPT_LATEST__;
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

// Chaque chunk de donnees est un petit fichier JSON gzippe : fetch() recupere
// les octets bruts, DecompressionStream (API native du navigateur, aucune
// dependance) les decompresse a la volee. Necessite d'etre servi en http(s).
async function fetchGzipJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error('impossible de charger ' + url + ' (HTTP ' + resp.status + ')');
  if (typeof DecompressionStream === 'undefined') {
    throw new Error("ce navigateur ne supporte pas DecompressionStream (mets-le a jour)");
  }
  const stream = resp.body.pipeThrough(new DecompressionStream('gzip'));
  const text = await new Response(stream).text();
  return JSON.parse(text);
}

const avgCache = new Map();
async function ensureAvgLoaded(dept) {
  if (avgCache.has(dept)) return avgCache.get(dept);
  const data = await fetchGzipJson('dept_avg/' + dept + '.json.gz');
  avgCache.set(dept, data);
  return data;
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

const fuelsAvailable = sortFuels(Object.keys(nationalLatest));

function renderAvgCards(container, avgs) {
  if (!avgs || Object.keys(avgs).length === 0) {
    container.innerHTML = '<p class="empty">Pas encore de prix connus.</p>';
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

renderAvgCards(document.getElementById('nationalAvgCards'), nationalLatest);

// Graphique d'evolution d'un niveau (departement ou national) : ses
// propres tendances uniquement.
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
    // Plotly.newPlot ne vide pas le contenu HTML deja present dans le div
    // cible (ex: le message "Chargement..." ou un graphique precedent), il
    // ajoute juste son propre graphique a cote : on vide explicitement.
    el.innerHTML = '';
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

const nationalEvolutionBtn = document.getElementById('nationalEvolutionBtn');
const nationalChartEl = document.getElementById('nationalChart');
nationalEvolutionBtn.addEventListener('click', () => {
  const showing = nationalChartEl.style.display !== 'none';
  if (showing) {
    nationalChartEl.style.display = 'none';
    nationalEvolutionBtn.textContent = "Voir l'evolution nationale";
    return;
  }
  nationalChartEl.style.display = 'block';
  nationalEvolutionBtn.textContent = "Masquer l'evolution nationale";
  if (!nationalChartEl.dataset.rendered) {
    renderSeriesChart('nationalChart', nationalSeries);
    nationalChartEl.dataset.rendered = '1';
  }
});

function indicatorFor(avg, nationalAvg) {
  const diff = avg - nationalAvg;
  if (Math.abs(diff) < 0.0005) return '';
  return diff < 0
    ? ' <span class="ind cheaper">&#9660;</span>'
    : ' <span class="ind pricier">&#9650;</span>';
}

function fuelCell(latestForRow, fuel) {
  const d = latestForRow && latestForRow[fuel];
  if (!d) return '<td class="na">—</td>';
  const nat = nationalLatest[fuel];
  return `<td>${d.avg.toFixed(3)} €${nat ? indicatorFor(d.avg, nat.avg) : ''}</td>`;
}

function buildHeadRow(firstLabel) {
  return `<th>${firstLabel}</th>` + fuelsAvailable.map(f => `<th>${f}</th>`).join('');
}

document.getElementById('deptTableHead').innerHTML = '<th>N&deg;</th>' + buildHeadRow('Departement');

const deptTableBody = document.getElementById('deptTableBody');
Object.keys(NOMS_DEPARTEMENTS).sort().forEach(dept => {
  const cells = fuelsAvailable.map(f => fuelCell(deptLatest[dept], f)).join('');
  const tr = document.createElement('tr');
  tr.className = 'cmp-row';
  tr.dataset.dept = dept;
  tr.innerHTML = `<td>${dept}</td><td>${NOMS_DEPARTEMENTS[dept]}</td>${cells}`;
  deptTableBody.appendChild(tr);
});

const evolutionDetail = document.getElementById('evolutionDetail');
const evolutionDetailTitle = document.getElementById('evolutionDetailTitle');
const evolutionDetailChart = document.getElementById('evolutionDetailChart');

document.querySelectorAll('.cmp-row').forEach(row => {
  row.addEventListener('click', async () => {
    document.querySelectorAll('.cmp-row').forEach(r => r.classList.remove('selected'));
    row.classList.add('selected');
    const dept = row.dataset.dept;

    evolutionDetail.style.display = 'block';
    evolutionDetailTitle.textContent = `Evolution - ${dept} ${NOMS_DEPARTEMENTS[dept]}`;
    evolutionDetailChart.innerHTML = '<p class="empty">Chargement...</p>';

    let series;
    try {
      series = await ensureAvgLoaded(dept);
    } catch (e) {
      evolutionDetailChart.innerHTML = `<p class="empty">${e.message}</p>`;
      return;
    }
    renderSeriesChart('evolutionDetailChart', series);
    evolutionDetail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
});
</script>
</body>
</html>
"""


def main():
    config = load_config()
    departements = config["departements"]
    stations_path = os.path.join(BASE_DIR, config["stations_filename"])
    marques_path = os.path.join(BASE_DIR, config["marques_filename"])
    data_dir = os.path.join(BASE_DIR, config["data_dir"])
    stations_dir = os.path.join(BASE_DIR, config["stations_dir"])
    dept_avg_dir = os.path.join(BASE_DIR, config["dept_avg_dir"])
    site_path = os.path.join(BASE_DIR, config["site_filename"])
    comparison_path = os.path.join(BASE_DIR, config["comparison_filename"])

    stations_rows = read_csv_rows(stations_path)
    stations_by_id = {r["station_id"]: r for r in stations_rows}
    marques = read_marques(marques_path)

    latest, dept_series_by_dept = process_all_departments(data_dir)

    if not stations_rows or not latest:
        print("Aucune donnee disponible : lance d'abord collect_prices.py.")
        return

    by_dept, skipped_no_coords, skipped_no_price = write_station_chunks(
        stations_dir, stations_rows, latest, marques
    )

    write_dept_avg_chunks(dept_avg_dir, dept_series_by_dept)

    national_series = merge_series(list(dept_series_by_dept.values()))

    dept_latest = grouped_latest_averages(latest, stations_by_id, lambda cp: cp[:2] or None)
    national_latest_grouped = grouped_latest_averages(
        latest, stations_by_id, lambda cp: "national" if cp[:2] else None
    )
    national_latest = national_latest_grouped.get("national", {})

    nb_stations = sum(len(v) for v in by_dept.values())

    generated = datetime.now().strftime("%d/%m/%Y %H:%M")

    html = HTML_TEMPLATE.replace("__NOMS_DEPARTEMENTS__", json.dumps(departements, ensure_ascii=False))
    html = html.replace("__NB_STATIONS__", str(nb_stations))
    html = html.replace("__NB_DEPARTEMENTS__", str(len(by_dept)))
    html = html.replace("__GENERATED__", generated)

    with open(site_path, "w", encoding="utf-8") as f:
        f.write(html)

    html_compare = HTML_TEMPLATE_COMPARE.replace(
        "__NOMS_DEPARTEMENTS__", json.dumps(departements, ensure_ascii=False)
    )
    html_compare = html_compare.replace("__DEPT_LATEST__", json.dumps(dept_latest, ensure_ascii=False))
    html_compare = html_compare.replace("__NATIONAL_LATEST__", json.dumps(national_latest, ensure_ascii=False))
    html_compare = html_compare.replace("__NATIONAL_SERIES__", json.dumps(national_series, ensure_ascii=False))
    html_compare = html_compare.replace("__GENERATED__", generated)

    with open(comparison_path, "w", encoding="utf-8") as f:
        f.write(html_compare)

    print(
        f"Site genere : {config['site_filename']} + {config['comparison_filename']} "
        f"({nb_stations} station(s) sur {len(by_dept)} departement(s), "
        f"{skipped_no_price} ignoree(s) sans prix connu, {skipped_no_coords} ignoree(s) sans coordonnees, "
        f"{len(marques)} avec marque connue)."
    )


if __name__ == "__main__":
    main()
