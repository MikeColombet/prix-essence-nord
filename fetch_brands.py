#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recupere la marque (enseigne : TotalEnergies, Esso, Carrefour, ...) de
chaque station suivie, a partir d'OpenStreetMap (API Overpass). Le flux
officiel du gouvernement ne contient jamais la marque (voir docstring de
collect_prices.py) ; OpenStreetMap la connait pour une bonne partie des
stations, et beaucoup d'entre elles portent en plus un tag
"ref:FR:prix-carburants" — le meme identifiant de station que celui utilise
par le flux officiel (heritage d'un import initial en 2020 depuis un jeu de
donnees du Ministere, maintenu depuis par la communaute OSM). Ça permet une
jointure exacte par identifiant pour l'essentiel des stations ; pour les
autres, on rattache la station OSM la plus proche (100 m max) portant une
marque.

Sur un test complet (France entiere, aout 2026) : ~64% de correspondance
exacte par identifiant, ~79% en ajoutant le rattachement par proximite.
Les stations restantes n'ont simplement pas de marque connue.

Usage :
    python3 fetch_brands.py

Ecrit marques.csv (station_id, marque), separement de stations.csv : ce
dernier est entierement reecrit par collect_prices.py a chaque collecte
(toutes les 12h), donc y stocker la marque la ferait perdre a la collecte
suivante. build_site.py relit les deux fichiers et les fusionne au moment
de generer le site. Pas besoin de relancer ce script a chaque collecte de
prix : une marque change rarement, un rafraichissement mensuel/occasionnel
suffit (voir .github/workflows/update-brands.yml).

Ce script ne depend d'aucune librairie externe (bibliotheque standard
Python 3 uniquement).
"""
import csv
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# Rectangle englobant la France metropolitaine (marge incluse). Une requete
# Overpass par rectangle (bbox) est beaucoup moins couteuse pour le serveur
# qu'une requete par polygone administratif ("area") — testee ~3x plus
# rapide/fiable en pratique sur l'infrastructure publique partagee.
FRANCE_BBOX = (41.0, -5.5, 51.5, 9.8)  # (lat_min, lon_min, lat_max, lon_max)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

MAX_FALLBACK_DISTANCE_M = 100
GRID_STEP_DEG = 0.01  # ~1 km, taille des cases de la grille de recherche


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def fetch_osm_fuel_stations():
    """Interroge l'API Overpass pour toutes les stations-service
    (amenity=fuel) dans le rectangle englobant la France, avec repli sur
    plusieurs miroirs publics (l'infrastructure Overpass partagee est
    parfois indisponible/surchargee). Retourne la liste brute des elements
    OSM (dicts avec 'tags' et lat/lon ou 'center')."""
    lat_min, lon_min, lat_max, lon_max = FRANCE_BBOX
    query = (
        f"[out:json][timeout:180][bbox:{lat_min},{lon_min},{lat_max},{lon_max}];"
        '(node["amenity"="fuel"];way["amenity"="fuel"];);'
        "out center tags;"
    )
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")

    last_error = None
    for endpoint in OVERPASS_ENDPOINTS:
        print(f"Interrogation d'Overpass ({endpoint})...")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "User-Agent": "suivi-prix-essence-personnel/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                payload = json.loads(resp.read())
            elements = payload.get("elements", [])
            print(f"  {len(elements)} station(s)-service trouvee(s) sur OpenStreetMap.")
            return elements
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
            print(f"  Echec sur ce miroir : {e}")
            last_error = e
            continue

    raise RuntimeError(f"Tous les miroirs Overpass ont echoue : {last_error}")


def _elem_latlon(elem):
    if "lat" in elem and "lon" in elem:
        return elem["lat"], elem["lon"]
    center = elem.get("center")
    if center:
        return center.get("lat"), center.get("lon")
    return None, None


def index_osm_elements(elements):
    """A partir des elements OSM bruts, construit :
    - brand_by_ref : {ref:FR:prix-carburants -> marque} pour la jointure exacte
    - grid : grille spatiale {(lat_arrondi, lon_arrondi): [(lat, lon, marque), ...]}
      pour le rattachement par proximite des stations sans ref exact."""
    brand_by_ref = {}
    grid = {}
    for elem in elements:
        tags = elem.get("tags", {})
        brand = tags.get("brand") or tags.get("name")
        if not brand:
            continue
        ref = tags.get("ref:FR:prix-carburants")
        if ref:
            brand_by_ref.setdefault(ref, brand)
        lat, lon = _elem_latlon(elem)
        if lat is None or lon is None:
            continue
        key = (round(lat, 2), round(lon, 2))
        grid.setdefault(key, []).append((lat, lon, brand))
    return brand_by_ref, grid


def _nearest_brand(grid, lat, lon, max_m):
    """Marque du point de la grille le plus proche de (lat, lon), a moins
    de max_m mètres, ou None. Cherche dans la case correspondante et ses 8
    voisines (assez pour ne rater aucun point a moins de ~1km, largement
    au-dessus de max_m)."""
    best_brand, best_dist = None, max_m
    base_lat = round(lat / GRID_STEP_DEG) * GRID_STEP_DEG
    base_lon = round(lon / GRID_STEP_DEG) * GRID_STEP_DEG
    for dlat in (-GRID_STEP_DEG, 0, GRID_STEP_DEG):
        for dlon in (-GRID_STEP_DEG, 0, GRID_STEP_DEG):
            key = (round(base_lat + dlat, 2), round(base_lon + dlon, 2))
            for plat, plon, brand in grid.get(key, []):
                dx = (plon - lon) * 111320 * math.cos(math.radians(lat))
                dy = (plat - lat) * 110540
                dist = math.hypot(dx, dy)
                if dist < best_dist:
                    best_dist = dist
                    best_brand = brand
    return best_brand


def read_stations(stations_path):
    if not os.path.exists(stations_path):
        return []
    with open(stations_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def match_brands(stations_rows, brand_by_ref, grid):
    """Retourne {station_id: marque}. Prefere la correspondance exacte par
    identifiant ; a defaut, rattache a la station OSM la plus proche
    (MAX_FALLBACK_DISTANCE_M) portant une marque."""
    result = {}
    n_exact = 0
    n_fallback = 0
    for r in stations_rows:
        sid = r["station_id"]
        brand = brand_by_ref.get(sid)
        if brand:
            result[sid] = brand
            n_exact += 1
            continue
        try:
            lat = float(r["latitude"]) / 100000
            lon = float(r["longitude"]) / 100000
        except (ValueError, TypeError):
            continue
        brand = _nearest_brand(grid, lat, lon, MAX_FALLBACK_DISTANCE_M)
        if brand:
            result[sid] = brand
            n_fallback += 1
    print(
        f"{n_exact} station(s) associee(s) par identifiant exact, "
        f"{n_fallback} de plus par proximite (< {MAX_FALLBACK_DISTANCE_M} m)."
    )
    return result


def write_marques_csv(path, brand_by_station):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["station_id", "marque"])
        for sid in sorted(brand_by_station.keys()):
            writer.writerow([sid, brand_by_station[sid]])


def main():
    config = load_config()
    stations_path = os.path.join(BASE_DIR, config["stations_filename"])
    marques_path = os.path.join(BASE_DIR, config["marques_filename"])

    stations_rows = read_stations(stations_path)
    if not stations_rows:
        print("Aucune station dans stations.csv : lance d'abord collect_prices.py.")
        return

    elements = fetch_osm_fuel_stations()
    brand_by_ref, grid = index_osm_elements(elements)

    brand_by_station = match_brands(stations_rows, brand_by_ref, grid)
    write_marques_csv(marques_path, brand_by_station)

    print(
        f"\n{len(brand_by_station)}/{len(stations_rows)} station(s) avec marque connue "
        f"({100 * len(brand_by_station) / len(stations_rows):.1f}%) ecrite(s) dans "
        f"{config['marques_filename']}."
    )
    print("Pense a lancer 'python3 build_site.py' pour regenerer le site si ce n'est pas deja fait.")


if __name__ == "__main__":
    main()
