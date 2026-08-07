#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recupere et met a jour les prix des carburants de toutes les stations d'un
departement (par defaut : Nord, 59) et construit une carte interactive.

Usage :
    python3 build_nord.py            -> collecte complete (roster + historique
                                         configure) puis (re)construit la carte
    python3 build_nord.py --maj-seulement
                                      -> ne recupere que les prix actuels (flux
                                         instantane), sans retelecharger les
                                         archives annuelles (rapide)

Sources officielles : voir https://www.prix-carburants.gouv.fr/rubrique/opendata/
Le nom et la marque des stations ne font pas partie des donnees publiques.

Ce script ne depend d'aucune librairie externe (bibliotheque standard Python 3
uniquement).
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

STATIONS_FIELDS = ["station_id", "adresse", "ville", "cp", "latitude", "longitude"]
PRIX_FIELDS = ["station_id", "carburant", "prix_eur", "maj_officielle"]


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def normalize_price(valeur):
    """Uniformise le format des prix : les archives anciennes (avant ~2022)
    expriment le prix en millièmes d'euro sans separateur decimal (ex: '1126'
    pour 1.126 €) ; les flux recents utilisent directement la notation
    decimale (ex: '1.563')."""
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


def _http_get_zip_xml(url, timeout):
    req = urllib.request.Request(
        url, headers={"User-Agent": "suivi-prix-essence-personnel/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml_name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
        return z.read(xml_name)


def download_flux():
    """Flux instantane (toute la France), mis a jour toutes les 10 min."""
    return _http_get_zip_xml(FLUX_URL, timeout=60)


def download_year(year=None):
    """Archive annuelle (toute la France) : stock de l'annee en cours si
    year=None, sinon archive complete de l'annee demandee (depuis 2007)."""
    url = ANNEE_URL if year is None else f"{ANNEE_URL}/{year}"
    return _http_get_zip_xml(url, timeout=180)


def _station_meta_from_elem(elem):
    return {
        "adresse": (elem.findtext("adresse") or "").strip(),
        "ville": (elem.findtext("ville") or "").strip(),
        "cp": (elem.get("cp") or "").strip(),
        "latitude": elem.get("latitude") or "",
        "longitude": elem.get("longitude") or "",
    }


def discover_current(cp_prefix):
    """Parcourt le flux instantane (toute la France, ~1 Mo compresse) et
    conserve les stations dont le code postal commence par cp_prefix.
    Retourne (meta_par_id, lignes_prix)."""
    xml_bytes = download_flux()
    root = ET.fromstring(xml_bytes)
    meta = {}
    price_rows = []
    for pdv in root.findall("pdv"):
        cp = (pdv.get("cp") or "").strip()
        if not cp.startswith(cp_prefix):
            continue
        sid = pdv.get("id")
        meta[sid] = _station_meta_from_elem(pdv)
        for prix in pdv.findall("prix"):
            valeur = normalize_price(prix.get("valeur"))
            maj = prix.get("maj")
            if not valeur or not maj:
                continue
            price_rows.append(
                {
                    "station_id": sid,
                    "carburant": prix.get("nom"),
                    "prix_eur": valeur,
                    "maj_officielle": maj,
                }
            )
    return meta, price_rows


def extract_year_filtered(xml_bytes, cp_prefix):
    """Parcourt une grosse archive annuelle (toute la France) sans tout
    charger en memoire (iterparse) et ne conserve que les stations dont le
    code postal commence par cp_prefix. Retourne (meta_par_id, lignes_prix)."""
    meta = {}
    price_rows = []
    for event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if elem.tag == "pdv":
            cp = (elem.get("cp") or "").strip()
            if cp.startswith(cp_prefix):
                sid = elem.get("id")
                meta[sid] = _station_meta_from_elem(elem)
                for prix in elem.findall("prix"):
                    valeur = normalize_price(prix.get("valeur"))
                    maj = prix.get("maj")
                    if not valeur or not maj:
                        continue
                    price_rows.append(
                        {
                            "station_id": sid,
                            "carburant": prix.get("nom"),
                            "prix_eur": valeur,
                            "maj_officielle": maj,
                        }
                    )
            elem.clear()
    return meta, price_rows


def write_stations_csv(path, stations_meta):
    """Reecrit entierement stations.csv (petit fichier, une ligne par
    station) a partir du dict {id: meta} fusionne."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STATIONS_FIELDS)
        writer.writeheader()
        for sid in sorted(stations_meta.keys()):
            m = stations_meta[sid]
            writer.writerow(
                {
                    "station_id": sid,
                    "adresse": m.get("adresse", ""),
                    "ville": m.get("ville", ""),
                    "cp": m.get("cp", ""),
                    "latitude": m.get("latitude", ""),
                    "longitude": m.get("longitude", ""),
                }
            )


def append_prix_csv(path, new_rows):
    """Ajoute a prix.csv les entrees absentes (dedoublonnage sur
    station_id + carburant + maj_officielle). Retourne le nb de lignes ajoutees."""
    file_exists = os.path.exists(path)
    existing_keys = set()
    if file_exists:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_keys.add(
                    (row["station_id"], row["carburant"], row["maj_officielle"])
                )

    to_write = []
    seen_in_batch = set()
    for r in new_rows:
        key = (r["station_id"], r["carburant"], r["maj_officielle"])
        if key in existing_keys or key in seen_in_batch:
            continue
        seen_in_batch.add(key)
        to_write.append(r)

    if to_write:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=PRIX_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerows(to_write)

    return len(to_write)


def merge_meta(target, source):
    """Fusionne les metadonnees d'une station : on complete les champs vides,
    sans ecraser une adresse deja connue par une chaine vide."""
    for sid, m in source.items():
        if sid not in target:
            target[sid] = dict(m)
        else:
            for k, v in m.items():
                if v and not target[sid].get(k):
                    target[sid][k] = v


def read_csv_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_data_chunks(prix_csv_path, data_dir):
    """Regroupe prix.csv par station et ecrit un petit fichier JS par
    station (chargement a la demande depuis la carte, sans serveur ni
    probleme de CORS en file://)."""
    os.makedirs(data_dir, exist_ok=True)
    rows = read_csv_rows(prix_csv_path)
    by_station = {}
    for r in rows:
        by_station.setdefault(r["station_id"], []).append(
            {
                "carburant": r["carburant"],
                "prix_eur": r["prix_eur"],
                "maj_officielle": r["maj_officielle"],
            }
        )
    for sid, prices in by_station.items():
        chunk_path = os.path.join(data_dir, f"{sid}.js")
        payload = json.dumps(prices, ensure_ascii=False)
        with open(chunk_path, "w", encoding="utf-8") as f:
            f.write("window.NORD_DATA = window.NORD_DATA || {};\n")
            f.write(f'window.NORD_DATA["{sid}"] = {payload};\n')
    return len(by_station)


def main():
    config = load_config()
    cp_prefix = config["cp_prefix"]
    stations_path = os.path.join(BASE_DIR, config["stations_filename"])
    prix_path = os.path.join(BASE_DIR, config["prix_filename"])
    data_dir = os.path.join(BASE_DIR, config["data_dir"])

    maj_seulement = len(sys.argv) > 1 and sys.argv[1] == "--maj-seulement"

    print(f"Telechargement du flux instantane (toute la France, filtre cp={cp_prefix}*)...")
    meta_all = {}
    all_new_rows = []
    current_meta, current_rows = discover_current(cp_prefix)
    merge_meta(meta_all, current_meta)
    all_new_rows.extend(current_rows)
    print(f"  {len(current_meta)} station(s) trouvee(s) dans le departement.")

    if not maj_seulement:
        current_year = datetime.now().year
        years_to_fetch = list(config.get("annees_passees", []))
        if config.get("inclure_annee_courante", True):
            years_to_fetch.append(current_year)

        for y in years_to_fetch:
            is_current = y == current_year
            label = f"{y} (stock en cours)" if is_current else str(y)
            print(f"Telechargement de l'archive {label} (toute la France, 10-35 Mo)...")
            try:
                xml_bytes = download_year(None if is_current else y)
            except Exception as e:
                print(f"  Echec du telechargement pour {label} : {e}")
                continue
            print("  Extraction des stations du departement...")
            year_meta, year_rows = extract_year_filtered(xml_bytes, cp_prefix)
            merge_meta(meta_all, year_meta)
            all_new_rows.extend(year_rows)
            print(f"  {len(year_rows)} entree(s) de prix extraite(s) pour {label}.")

    write_stations_csv(stations_path, meta_all)
    added = append_prix_csv(prix_path, all_new_rows)
    n_chunks = build_data_chunks(prix_path, data_dir)

    print(f"\n{len(meta_all)} station(s) dans stations.csv.")
    print(f"{added} nouvelle(s) ligne(s) de prix ajoutee(s) dans prix.csv.")
    print(f"{n_chunks} fichier(s) de donnees par station regenere(s) dans {config['data_dir']}/.")
    print("\nPense a lancer 'python3 build_carte.py' pour regenerer la carte si ce n'est pas deja fait.")


if __name__ == "__main__":
    main()
