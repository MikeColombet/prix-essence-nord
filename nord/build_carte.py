#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Construit carte_nord.html : une carte interactive (Plotly, fond OpenStreetMap
gratuit, sans cle API) avec une station par marqueur. Cliquer sur une station
charge son historique (fichier nord/data/{id}.js, genere par build_nord.py)
et affiche les prix actuels + un graphique d'evolution.

Usage : python3 build_carte.py
(a relancer apres chaque python3 build_nord.py pour refleter les nouvelles
donnees)

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


HTML_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Carte des prix des carburants - Département du Nord (59)</title>
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
  .controls {
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    background: #fff; border-radius: 10px; padding: 12px 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px;
  }
  .controls label { font-size: 0.85rem; color: #444; }
  .controls select { font-size: 0.9rem; padding: 4px 6px; border-radius: 6px; border: 1px solid #d8d8dc; }
  .highlight-info { font-size: 0.85rem; display: flex; gap: 18px; flex-wrap: wrap; }
  .highlight-info .cheap { color: #1e8e3e; font-weight: 600; }
  .highlight-info .expensive { color: #c0392b; font-weight: 600; }
  .layout { display: flex; gap: 20px; align-items: flex-start; flex-wrap: wrap; }
  .map-wrap {
    background: #fff; border-radius: 10px; padding: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); flex: 1 1 560px; min-width: 320px;
  }
  #map { width: 100%; height: 620px; }
  .details {
    background: #fff; border-radius: 10px; padding: 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); flex: 1 1 420px; min-width: 320px;
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
  #chart { min-height: 320px; }
</style>
</head>
<body>
  <h1>Carte des prix des carburants - Département du Nord (59)</h1>
  <p class="description">Cette carte situe les stations-service du département du Nord et leurs prix de
  carburant actuels. La couleur de chaque point reflète son niveau de prix pour le carburant sélectionné
  ci-dessous (vert = moins cher, rouge = plus cher). Clique sur une station pour afficher ses prix détaillés
  et l'évolution de ses tarifs dans le temps. La station la moins chère et la plus chère mises en avant ne
  prennent en compte que les prix mis à jour au cours des 72 dernières heures.</p>
  <div class="meta">__NB_STATIONS__ station(s) avec prix connu &middot; page generee le __GENERATED__ &middot; source : flux officiel donnees.roulez-eco.fr</div>

  <div class="controls">
    <label for="fuelSelect">Carburant a comparer :</label>
    <select id="fuelSelect"></select>
    <div class="highlight-info" id="highlightInfo"></div>
  </div>

  <div class="layout">
    <div class="map-wrap">
      <div id="map"></div>
    </div>
    <div class="details" id="details">
      <p class="empty">Clique sur une station sur la carte pour voir ses prix actuels et son historique.</p>
    </div>
  </div>

<script>
const stations = __STATIONS__;

const FUEL_ORDER = ['Gazole', 'SP95', 'SP98', 'E10', 'E85', 'GPLc'];
const fuelsAvailable = Array.from(new Set(stations.flatMap(s => Object.keys(s.prices))))
  .sort((a, b) => {
    const ia = FUEL_ORDER.indexOf(a), ib = FUEL_ORDER.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });

const fuelSelect = document.getElementById('fuelSelect');
fuelsAvailable.forEach(f => {
  const opt = document.createElement('option');
  opt.value = f; opt.textContent = f;
  fuelSelect.appendChild(opt);
});

function hoverFor(s) {
  const fuels = Object.keys(s.prices).sort();
  const priceLines = fuels.map(f => `${f}: ${parseFloat(s.prices[f].prix_eur).toFixed(3)} €`).join('<br>');
  return `<b>${s.adresse}</b><br>${s.ville}<br>${priceLines}`;
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

function buildMapTrace(fuel) {
  const withFuel = stations.filter(s => s.prices[fuel]);
  return {
    type: 'scattermap',
    mode: 'markers',
    lat: withFuel.map(s => s.latitude),
    lon: withFuel.map(s => s.longitude),
    text: withFuel.map(hoverFor),
    customdata: withFuel.map(s => s.id),
    hoverinfo: 'text',
    marker: {
      size: 10,
      color: withFuel.map(s => refPriceFor(s, fuel)),
      colorscale: 'RdYlGn',
      reversescale: true,
      cmin: Math.min(...withFuel.map(s => refPriceFor(s, fuel))),
      cmax: Math.max(...withFuel.map(s => refPriceFor(s, fuel))),
      opacity: 0.9,
      line: { width: 1, color: '#ffffff' },
      colorbar: { title: fuel + ' (€)', thickness: 14, len: 0.6 },
    },
  };
}

function buildHighlightTrace(fuel) {
  const withFuel = stations.filter(s => isFresh(s, fuel));
  if (withFuel.length === 0) {
    document.getElementById('highlightInfo').innerHTML =
      `<span class="empty">Aucun prix ${fuel} mis a jour dans les dernieres ${FRESHNESS_HOURS}h.</span>`;
    return { type: 'scattermap', mode: 'markers', lat: [], lon: [], marker: {} };
  }
  let cheapest = withFuel[0], priciest = withFuel[0];
  withFuel.forEach(s => {
    if (refPriceFor(s, fuel) < refPriceFor(cheapest, fuel)) cheapest = s;
    if (refPriceFor(s, fuel) > refPriceFor(priciest, fuel)) priciest = s;
  });
  updateHighlightInfo(fuel, cheapest, priciest);
  return {
    type: 'scattermap',
    mode: 'markers',
    lat: [cheapest.latitude, priciest.latitude],
    lon: [cheapest.longitude, priciest.longitude],
    text: [
      `<b>Moins chere (${fuel})</b><br>${cheapest.adresse}<br>${cheapest.ville}<br>${refPriceFor(cheapest, fuel).toFixed(3)} €`,
      `<b>Plus chere (${fuel})</b><br>${priciest.adresse}<br>${priciest.ville}<br>${refPriceFor(priciest, fuel).toFixed(3)} €`,
    ],
    customdata: [cheapest.id, priciest.id],
    hoverinfo: 'text',
    marker: { size: 20, color: ['#1e8e3e', '#c0392b'], symbol: 'circle', opacity: 0.95, line: { width: 2, color: '#ffffff' } },
  };
}

function updateHighlightInfo(fuel, cheapest, priciest) {
  document.getElementById('highlightInfo').innerHTML =
    `<span class="cheap">Moins chere : ${cheapest.adresse}, ${cheapest.ville} - ${refPriceFor(cheapest, fuel).toFixed(3)} €</span>` +
    `<span class="expensive">Plus chere : ${priciest.adresse}, ${priciest.ville} - ${refPriceFor(priciest, fuel).toFixed(3)} €</span>`;
}

const initialFuel = fuelsAvailable[0] || null;
const allLats = stations.map(s => s.latitude);
const allLons = stations.map(s => s.longitude);

if (initialFuel) {
  Plotly.newPlot('map', [buildMapTrace(initialFuel), buildHighlightTrace(initialFuel)], {
    map: {
      style: 'open-street-map',
      center: { lat: allLats.reduce((a,b)=>a+b,0)/allLats.length, lon: allLons.reduce((a,b)=>a+b,0)/allLons.length },
      zoom: 8.5,
    },
    margin: { t: 0, r: 0, l: 0, b: 0 },
  }, { responsive: true, displaylogo: false });

  fuelSelect.value = initialFuel;
  fuelSelect.addEventListener('change', () => {
    const fuel = fuelSelect.value;
    Plotly.react('map', [buildMapTrace(fuel), buildHighlightTrace(fuel)], document.getElementById('map').layout);
  });

  document.getElementById('map').on('plotly_click', function(data) {
    if (data.points && data.points.length > 0) {
      const sid = data.points[0].customdata;
      const station = stations.find(s => s.id === sid);
      if (station) selectStationById(station);
    }
  });
} else {
  document.getElementById('map').outerHTML = '<p class="empty">Aucun prix connu pour construire la carte.</p>';
}

const loadedChunks = new Set();
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

function renderStation(station) {
  const detailsEl = document.getElementById('details');
  detailsEl.innerHTML = `
    <div class="station-title">${station.adresse}</div>
    <div class="station-sub">${station.ville} &middot; id ${station.id}</div>
    <div class="cards" id="cards"></div>
    <h2 class="section-title">Évolution (données disponibles)</h2>
    <div id="chart"></div>
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

  const history = (window.NORD_DATA && window.NORD_DATA[station.id]) || [];
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

function selectStationById(station) {
  const sid = station.id;
  if (loadedChunks.has(sid)) {
    renderStation(station);
    return;
  }
  const script = document.createElement('script');
  script.src = 'data/' + sid + '.js';
  script.onload = () => { loadedChunks.add(sid); renderStation(station); };
  script.onerror = () => {
    document.getElementById('details').innerHTML = '<p class="empty">Impossible de charger l\\'historique de cette station (fichier data/' + sid + '.js introuvable).</p>';
  };
  document.head.appendChild(script);
}
</script>
</body>
</html>
"""


def main():
    config = load_config()
    stations_path = os.path.join(BASE_DIR, config["stations_filename"])
    prix_path = os.path.join(BASE_DIR, config["prix_filename"])
    carte_path = os.path.join(BASE_DIR, config["carte_filename"])

    stations_rows = read_csv_rows(stations_path)
    prix_rows = read_csv_rows(prix_path)
    latest = latest_prices_by_station(prix_rows)

    stations_payload = []
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
        stations_payload.append(
            {
                "id": sid,
                "adresse": r["adresse"],
                "ville": r["ville"],
                "latitude": lat,
                "longitude": lon,
                "prices": prices,
            }
        )

    if not stations_payload:
        print("Aucune station avec prix connu et coordonnees valides : lance d'abord build_nord.py.")
        return

    html = HTML_TEMPLATE.replace("__STATIONS__", json.dumps(stations_payload, ensure_ascii=False))
    html = html.replace("__NB_STATIONS__", str(len(stations_payload)))
    html = html.replace("__GENERATED__", datetime.now().strftime("%d/%m/%Y %H:%M"))

    with open(carte_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(
        f"Carte generee : {config['carte_filename']} ({len(stations_payload)} station(s) affichee(s), "
        f"{skipped_no_price} ignoree(s) sans prix connu, {skipped_no_coords} ignoree(s) sans coordonnees)."
    )


if __name__ == "__main__":
    main()
