#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suivi du prix des carburants d'une station donnee.

Source : flux instantane officiel du gouvernement (donnees.roulez-eco.fr),
le meme flux qui alimente https://www.prix-carburants.gouv.fr/ et le jeu de
donnees data.economie.gouv.fr. Mis a jour cote gouvernement toutes les 10 min.

Usage :
    python3 track_price.py                    -> une collecte, ajoute au CSV, regenere le HTML
    python3 track_price.py --find 59700        -> liste les stations d'un code postal (pour retrouver un id)
    python3 track_price.py --historique 2026   -> importe l'historique de l'annee indiquee (une ou plusieurs,
                                                   ex: --historique 2024 2025 2026)
    python3 track_price.py --reparer-prix      -> corrige dans le CSV existant les prix des annees ou le
                                                   format etait "millièmes sans virgule" (ex: 1126 -> 1.126)

Ce script ne depend d'aucune librairie externe (uniquement la bibliotheque
standard Python 3).

Sources officielles (voir https://www.prix-carburants.gouv.fr/rubrique/opendata/) :
  - flux instantane (mis a jour toutes les 10 min)      : /opendata/instantane
  - stock de l'annee en cours (mis a jour chaque jour)   : /opendata/annee
  - archives des annees completes depuis 2007            : /opendata/annee/{AAAA}
Le nom et la marque des stations (ex: Esso) ne font pas partie des donnees
publiques : seule l'adresse permet d'identifier une station.
"""
import csv
import io
import json
import os
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
FLUX_URL = "https://donnees.roulez-eco.fr/opendata/instantane"
ANNEE_URL = "https://donnees.roulez-eco.fr/opendata/annee"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def normalize_price(valeur):
    """Uniformise le format des prix.

    Les archives anciennes (grosso modo avant 2022) expriment le prix en
    millièmes d'euro sans séparateur décimal, ex: valeur="1126" pour 1.126 €.
    Les flux plus récents utilisent directement la notation décimale, ex:
    valeur="1.563". On détecte l'absence de séparateur et on convertit."""
    if valeur is None:
        return valeur
    v = valeur.strip()
    if not v:
        return v
    if "." in v or "," in v:
        return v.replace(",", ".")
    try:
        return f"{int(v) / 1000:.3f}"
    except ValueError:
        return v


def download_flux():
    """Telecharge et decompresse le flux instantane (zip contenant un XML)."""
    req = urllib.request.Request(
        FLUX_URL, headers={"User-Agent": "suivi-prix-essence-personnel/1.0"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml_name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
        return z.read(xml_name)


def parse_stations(xml_bytes):
    """Retourne un dict {id_station: infos} a partir du XML du flux."""
    root = ET.fromstring(xml_bytes)
    stations = {}
    for pdv in root.findall("pdv"):
        sid = pdv.get("id")
        adresse = (pdv.findtext("adresse") or "").strip()
        ville = (pdv.findtext("ville") or "").strip()
        cp = (pdv.get("cp") or "").strip()
        prices = []
        for prix in pdv.findall("prix"):
            prices.append(
                {
                    "nom": prix.get("nom"),
                    "valeur": normalize_price(prix.get("valeur")),
                    "maj": prix.get("maj"),
                }
            )
        stations[sid] = {
            "id": sid,
            "adresse": adresse,
            "ville": ville,
            "cp": cp,
            "latitude": pdv.get("latitude"),
            "longitude": pdv.get("longitude"),
            "prices": prices,
        }
    return stations


def download_year(year=None):
    """Telecharge l'archive annuelle (stock de l'annee en cours si year=None,
    sinon archive complete de l'annee demandee, disponible depuis 2007)."""
    url = ANNEE_URL if year is None else f"{ANNEE_URL}/{year}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "suivi-prix-essence-personnel/1.0"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml_name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
        return z.read(xml_name)


def extract_station_history(xml_bytes, target_id):
    """Parcourt un gros fichier annuel sans tout charger en memoire (iterparse)
    et ne conserve que les entrees de la station visee."""
    station = None
    prices = []
    for event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if elem.tag == "pdv":
            if elem.get("id") == target_id:
                adresse = (elem.findtext("adresse") or "").strip()
                ville = (elem.findtext("ville") or "").strip()
                cp = (elem.get("cp") or "").strip()
                for prix in elem.findall("prix"):
                    if prix.get("valeur") and prix.get("maj"):
                        prices.append(
                            {
                                "nom": prix.get("nom"),
                                "valeur": normalize_price(prix.get("valeur")),
                                "maj": prix.get("maj"),
                            }
                        )
                station = {"id": target_id, "adresse": adresse, "ville": ville, "cp": cp}
            elem.clear()
    if station is not None:
        station["prices"] = prices
    return station


def cmd_historique(years):
    config = load_config()
    sid = config["station_id"]
    csv_path = os.path.join(BASE_DIR, config["csv_filename"])
    current_year = datetime.now().year
    total_new = 0

    for y in years:
        y = int(y)
        is_current = y == current_year
        label = f"{y} (stock en cours)" if is_current else str(y)
        print(f"Telechargement de l'archive {label} (peut prendre 1-2 minutes, 10-35 Mo)...")
        try:
            xml_bytes = download_year(None if is_current else y)
        except Exception as e:
            print(f"  Echec du telechargement pour {label} : {e}")
            continue

        print("  Extraction de la station dans le fichier annuel...")
        station = extract_station_history(xml_bytes, sid)
        if station is None:
            print(f"  Station id={sid} absente de l'archive {label}.")
            continue

        new_rows = append_csv(csv_path, station, f"import-historique-{y}")
        print(f"  {len(new_rows)} entree(s) ajoutee(s) pour {label}.")
        total_new += len(new_rows)

    rows = read_csv_rows(csv_path)
    if rows:
        last = rows[-1]
        station_label = f"{last['adresse']}, {last['ville']}"
    else:
        station_label = config.get("adresse_attendue", "station")
    html_path = os.path.join(BASE_DIR, config["html_filename"])
    generate_html(csv_path, html_path, station_label)

    print(f"\nTotal : {total_new} nouvelle(s) entree(s) historique(s) ajoutee(s). Visualisation mise a jour.")


def cmd_find(cp_filter):
    print("Telechargement du flux officiel en cours...")
    stations = parse_stations(download_flux())
    cp_filter = cp_filter.strip()
    matches = [
        s
        for s in stations.values()
        if s["cp"] == cp_filter or cp_filter.lower() in s["ville"].lower()
    ]
    if not matches:
        print(f"Aucune station trouvee pour '{cp_filter}'.")
        return
    print(f"\n{len(matches)} station(s) trouvee(s) pour '{cp_filter}' :\n")
    for s in sorted(matches, key=lambda x: x["adresse"]):
        print(f"  id={s['id']:<10} {s['adresse']}, {s['cp']} {s['ville']}")
    print(
        "\nRepere l'adresse de ta station Esso dans la liste ci-dessus, puis "
        "copie son id dans config.json (champ \"station_id\")."
    )


CSV_FIELDS = [
    "collecte_le",
    "carburant",
    "prix_eur",
    "maj_officielle",
    "station_id",
    "adresse",
    "ville",
]


def append_csv(csv_path, station, fetched_at):
    """Ajoute au CSV les prix qui n'y figurent pas deja (dedoublonnage sur
    carburant + date de mise a jour officielle), pour ne conserver que les
    changements de prix reels au fil du temps."""
    file_exists = os.path.exists(csv_path)
    existing_keys = set()
    if file_exists:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_keys.add((row["carburant"], row["maj_officielle"]))

    new_rows = []
    for p in station["prices"]:
        if not p["valeur"] or not p["maj"]:
            continue
        key = (p["nom"], p["maj"])
        if key in existing_keys:
            continue
        new_rows.append(
            {
                "collecte_le": fetched_at,
                "carburant": p["nom"],
                "prix_eur": p["valeur"],
                "maj_officielle": p["maj"],
                "station_id": station["id"],
                "adresse": station["adresse"],
                "ville": station["ville"],
            }
        )

    if new_rows:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerows(new_rows)

    return new_rows


def read_csv_rows(csv_path):
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cmd_reparer_prix():
    """Corrige dans le CSV existant les prix importes avant la prise en
    compte du format 'millièmes sans virgule' des anciennes archives
    (ex: 1126 -> 1.126)."""
    config = load_config()
    csv_path = os.path.join(BASE_DIR, config["csv_filename"])
    rows = read_csv_rows(csv_path)
    if not rows:
        print("Aucun CSV a corriger.")
        return

    fixed = 0
    for row in rows:
        normalized = normalize_price(row["prix_eur"])
        if normalized != row["prix_eur"]:
            row["prix_eur"] = normalized
            fixed += 1

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    html_path = os.path.join(BASE_DIR, config["html_filename"])
    last = rows[-1]
    generate_html(csv_path, html_path, f"{last['adresse']}, {last['ville']}")

    print(f"{fixed} prix corrige(s) sur {len(rows)} ligne(s). Visualisation mise a jour.")


HTML_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Suivi prix essence - __STATION__</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2/plotly.min.js"></script>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 24px; background: #f5f6f8; color: #1c1c1e;
  }
  h1 { font-size: 1.3rem; margin: 0 0 4px 0; }
  .meta { color: #6b6b70; font-size: 0.85rem; margin-bottom: 24px; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 28px; }
  .card {
    background: #fff; border-radius: 10px; padding: 14px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); min-width: 120px;
  }
  .card .fuel { font-size: 0.75rem; text-transform: uppercase; color: #6b6b70; letter-spacing: .04em; }
  .card .price { font-size: 1.5rem; font-weight: 600; margin-top: 4px; }
  .card .date { font-size: 0.7rem; color: #9a9a9e; margin-top: 2px; }
  .chart-wrap {
    background: #fff; border-radius: 10px; padding: 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); max-width: 1000px; margin-bottom: 28px;
  }
  .section-title { font-size: 1rem; margin: 0 0 12px 0; }
  .empty { color: #6b6b70; }
  table { border-collapse: collapse; margin-top: 28px; font-size: 0.85rem; }
  th, td { padding: 6px 12px; text-align: left; border-bottom: 1px solid #e5e5ea; }
  th { color: #6b6b70; font-weight: 600; }
</style>
</head>
<body>
  <h1>__STATION__</h1>
  <div class="meta">Page generee le __GENERATED__ &middot; source : flux officiel donnees.roulez-eco.fr</div>

  <div class="cards" id="cards"></div>

  <div class="chart-wrap">
    <h2 class="section-title">Évolution sur les 12 derniers mois</h2>
    <div id="chart12"></div>
  </div>

  <div class="chart-wrap">
    <h2 class="section-title">Historique complet</h2>
    <div id="chartAll"></div>
  </div>

  <div id="tableWrap"></div>

<script>
const rows = __DATA__;

if (rows.length === 0) {
  document.getElementById('cards').innerHTML = '<p class="empty">Aucune donnee collectee pour le moment. Lance track_price.py pour commencer a enregistrer des prix.</p>';
} else {
  const parseDate = s => new Date(s.includes('T') ? s : s.replace(' ', 'T'));
  const byFuel = {};
  rows.forEach(r => {
    if (!byFuel[r.carburant]) byFuel[r.carburant] = [];
    byFuel[r.carburant].push({ x: parseDate(r.maj_officielle), y: parseFloat(r.prix_eur) });
  });
  Object.values(byFuel).forEach(arr => arr.sort((a, b) => a.x - b.x));

  const now = new Date();
  const cutoff12 = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
  const byFuel12 = {};
  Object.keys(byFuel).forEach(fuel => {
    const recent = byFuel[fuel].filter(p => p.x >= cutoff12);
    if (recent.length > 0) byFuel12[fuel] = recent;
  });

  const colors = {
    Gazole: '#e74c3c', SP95: '#2980b9', SP98: '#8e44ad',
    E10: '#27ae60', E85: '#16a085', GPLc: '#f39c12'
  };
  const fallbackColors = ['#e74c3c','#2980b9','#8e44ad','#27ae60','#16a085','#f39c12','#7f8c8d'];
  let colorIdx = 0;
  const colorFor = name => colors[name] || fallbackColors[(colorIdx++) % fallbackColors.length];

  // Cartes avec le dernier prix connu par carburant
  const cardsEl = document.getElementById('cards');
  Object.keys(byFuel).sort().forEach(fuel => {
    const series = byFuel[fuel];
    const last = series[series.length - 1];
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `<div class="fuel">${fuel}</div>
      <div class="price">${last.y.toFixed(3)} €</div>
      <div class="date">maj ${last.x.toLocaleString('fr-FR')}</div>`;
    cardsEl.appendChild(div);
  });

  function makeTraces(data) {
    return Object.keys(data).sort().map(fuel => ({
      x: data[fuel].map(p => p.x),
      y: data[fuel].map(p => p.y),
      name: fuel,
      mode: 'lines',
      line: { color: colorFor(fuel), shape: 'hv', width: 2 },
      hovertemplate: '%{y:.3f} €<br>%{x|%d/%m/%Y %H:%M}<extra>' + fuel + '</extra>',
    }));
  }

  function makePlot(divId, traces, withRangeSlider) {
    if (typeof Plotly === 'undefined') {
      throw new Error("La librairie Plotly ne s'est pas chargee (probleme reseau ou CDN). Verifie ta connexion internet et recharge la page.");
    }
    const layout = {
      margin: { t: 10, r: 20, l: 55, b: withRangeSlider ? 70 : 40 },
      hovermode: 'x unified',
      legend: { orientation: 'h', y: -0.15 },
      xaxis: { type: 'date' },
      yaxis: { title: 'Prix (EUR / litre)' },
    };
    if (withRangeSlider) {
      layout.xaxis.rangeslider = { visible: true };
      layout.xaxis.rangeselector = {
        buttons: [
          { count: 1, label: '1m', step: 'month', stepmode: 'backward' },
          { count: 6, label: '6m', step: 'month', stepmode: 'backward' },
          { count: 1, label: '1a', step: 'year', stepmode: 'backward' },
          { step: 'all', label: 'Tout' },
        ]
      };
    }
    Plotly.newPlot(divId, traces, layout, { responsive: true, displaylogo: false });
  }

  try {
    if (Object.keys(byFuel12).length > 0) {
      makePlot('chart12', makeTraces(byFuel12), false);
    } else {
      document.getElementById('chart12').outerHTML = '<p class="empty">Pas encore de donnees sur les 12 derniers mois.</p>';
    }

    colorIdx = 0; // memes couleurs par carburant sur les deux graphiques
    makePlot('chartAll', makeTraces(byFuel), true);
  } catch (e) {
    document.querySelectorAll('.chart-wrap').forEach(el => {
      el.innerHTML += `<p class="empty">Graphique indisponible : ${e.message}</p>`;
    });
    console.error(e);
  }

  // Tableau (20 dernieres releves)
  const sorted = [...rows].sort((a, b) => parseDate(b.maj_officielle) - parseDate(a.maj_officielle)).slice(0, 20);
  let html = '<h2 style="font-size:1rem;">Dernieres mises a jour</h2><table><tr><th>Carburant</th><th>Prix</th><th>Mise a jour officielle</th><th>Collecte le</th></tr>';
  sorted.forEach(r => {
    html += `<tr><td>${r.carburant}</td><td>${parseFloat(r.prix_eur).toFixed(3)} €</td><td>${r.maj_officielle}</td><td>${r.collecte_le}</td></tr>`;
  });
  html += '</table>';
  document.getElementById('tableWrap').innerHTML = html;
}
</script>
</body>
</html>
"""


def generate_html(csv_path, html_path, station_label):
    rows = read_csv_rows(csv_path)
    data_json = json.dumps(rows, ensure_ascii=False)
    html = HTML_TEMPLATE.replace("__DATA__", data_json)
    html = html.replace("__STATION__", station_label)
    html = html.replace("__GENERATED__", datetime.now().strftime("%d/%m/%Y %H:%M"))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    config = load_config()

    if len(sys.argv) > 1 and sys.argv[1] == "--find":
        cp = sys.argv[2] if len(sys.argv) > 2 else config.get("cp_recherche", "")
        cmd_find(cp)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--historique":
        years = sys.argv[2:] if len(sys.argv) > 2 else [str(datetime.now().year)]
        cmd_historique(years)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--reparer-prix":
        cmd_reparer_prix()
        return

    print("Telechargement du flux officiel en cours...")
    stations = parse_stations(download_flux())
    sid = config["station_id"]
    station = stations.get(sid)

    if station is None:
        print(
            f"Station id={sid} introuvable dans le flux actuel. "
            f"Verifie config.json, ou relance avec --find {config.get('cp_recherche', '<code postal>')}."
        )
        sys.exit(1)

    hint = config.get("adresse_attendue", "").lower()
    if hint and hint not in station["adresse"].lower():
        print(
            f"ATTENTION : l'adresse de la station id={sid} est "
            f"'{station['adresse']}, {station['cp']} {station['ville']}', "
            f"ce qui ne contient pas '{hint}'. Verifie que c'est la bonne station "
            f"(relance avec --find {station['cp']} pour comparer)."
        )

    fetched_at = datetime.now().isoformat(timespec="seconds")
    csv_path = os.path.join(BASE_DIR, config["csv_filename"])
    new_rows = append_csv(csv_path, station, fetched_at)

    html_path = os.path.join(BASE_DIR, config["html_filename"])
    station_label = f"{station['adresse']}, {station['cp']} {station['ville']}"
    generate_html(csv_path, html_path, station_label)

    if new_rows:
        print(f"{len(new_rows)} nouveau(x) prix enregistre(s) a {fetched_at} :")
        for r in new_rows:
            print(f"  {r['carburant']}: {r['prix_eur']} EUR (maj {r['maj_officielle']})")
    else:
        print(f"Aucun changement de prix depuis la derniere collecte ({fetched_at}).")


if __name__ == "__main__":
    main()
