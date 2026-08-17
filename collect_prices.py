#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recupere et met a jour les prix des carburants de toutes les stations des
departements configures (par defaut : Hauts-de-France, Normandie, Grand Est,
Ile-de-France, soit 28 departements).

Usage :
    python3 collect_prices.py            -> collecte complete (roster + historique
                                             configure) puis (re)construit le site
    python3 collect_prices.py --maj-seulement
                                          -> ne recupere que les prix actuels (flux
                                             instantane), sans retelecharger les
                                             archives annuelles (rapide)

Sources officielles : voir https://www.prix-carburants.gouv.fr/rubrique/opendata/
Le nom et la marque des stations ne font pas partie des donnees publiques.

Les prix sont stockes dans un fichier CSV par departement (prix/{dept}.csv)
plutot qu'un seul fichier global : avec ~28 departements et plusieurs annees
d'historique, un fichier unique grossirait au point de risquer de depasser la
limite de taille de fichier de GitHub. Un fichier par departement reste petit
indefiniment (croissance proportionnelle au nombre de stations de CE
departement, pas de l'ensemble des regions suivies).

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


def _extract_pdv(elem, departements):
    """Retourne (station_id, meta, prix_rows) pour un element <pdv> dont le
    departement (2 premiers chiffres du cp) fait partie de ceux suivis,
    sinon None. Chaque ligne de prix porte un champ transitoire
    "departement" utilise pour repartir les lignes dans le bon fichier
    prix/{dept}.csv (jamais ecrit tel quel dans le CSV final)."""
    cp = (elem.get("cp") or "").strip()
    dept = cp[:2]
    if dept not in departements:
        return None
    sid = elem.get("id")
    meta = _station_meta_from_elem(elem)
    price_rows = []
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
                "departement": dept,
            }
        )
    return sid, meta, price_rows


def discover_current(departements):
    """Parcourt le flux instantane (toute la France, ~1 Mo compresse) et
    conserve les stations des departements suivis. Retourne (meta_par_id,
    lignes_prix)."""
    xml_bytes = download_flux()
    root = ET.fromstring(xml_bytes)
    meta = {}
    price_rows = []
    for pdv in root.findall("pdv"):
        result = _extract_pdv(pdv, departements)
        if result is None:
            continue
        sid, m, rows = result
        meta[sid] = m
        price_rows.extend(rows)
    return meta, price_rows


def extract_year_filtered(xml_bytes, departements):
    """Parcourt une grosse archive annuelle (toute la France) sans tout
    charger en memoire (iterparse) et ne conserve que les stations des
    departements suivis. Retourne (meta_par_id, lignes_prix)."""
    meta = {}
    price_rows = []
    for event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if elem.tag == "pdv":
            result = _extract_pdv(elem, departements)
            if result is not None:
                sid, m, rows = result
                meta[sid] = m
                price_rows.extend(rows)
            elem.clear()
    return meta, price_rows


def write_stations_csv(path, stations_meta):
    """Reecrit entierement stations.csv (petit fichier, une ligne par
    station toutes regions confondues) a partir du dict {id: meta} fusionne."""
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


def append_prix_rows(prix_dir, new_rows):
    """Reparti les lignes de prix par departement et les ajoute a
    prix/{dept}.csv (dedoublonnage sur station_id + carburant +
    maj_officielle, comme avant, mais un fichier par departement). Retourne
    le nombre total de lignes ajoutees."""
    os.makedirs(prix_dir, exist_ok=True)
    by_dept = {}
    for r in new_rows:
        by_dept.setdefault(r["departement"], []).append(r)

    total_added = 0
    for dept, dept_rows in by_dept.items():
        path = os.path.join(prix_dir, f"{dept}.csv")
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
        for r in dept_rows:
            key = (r["station_id"], r["carburant"], r["maj_officielle"])
            if key in existing_keys or key in seen_in_batch:
                continue
            seen_in_batch.add(key)
            to_write.append({k: r[k] for k in PRIX_FIELDS})

        if to_write:
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=PRIX_FIELDS)
                if not file_exists:
                    writer.writeheader()
                writer.writerows(to_write)

        total_added += len(to_write)

    return total_added


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


def build_data_chunks(prix_dir, data_dir):
    """Regroupe l'ensemble des fichiers prix/{dept}.csv par station et ecrit
    un petit fichier JS par station (chargement a la demande depuis le site,
    sans serveur ni probleme de CORS en file://)."""
    os.makedirs(data_dir, exist_ok=True)
    by_station = {}
    if os.path.isdir(prix_dir):
        for fname in sorted(os.listdir(prix_dir)):
            if not fname.endswith(".csv"):
                continue
            for r in read_csv_rows(os.path.join(prix_dir, fname)):
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
            f.write("window.STATION_HISTORY_DATA = window.STATION_HISTORY_DATA || {};\n")
            f.write(f'window.STATION_HISTORY_DATA["{sid}"] = {payload};\n')
    return len(by_station)


def main():
    config = load_config()
    departements = set(config["departements"].keys())
    stations_path = os.path.join(BASE_DIR, config["stations_filename"])
    prix_dir = os.path.join(BASE_DIR, config["prix_dir"])
    data_dir = os.path.join(BASE_DIR, config["data_dir"])

    maj_seulement = len(sys.argv) > 1 and sys.argv[1] == "--maj-seulement"

    print(f"Telechargement du flux instantane (toute la France, {len(departements)} departement(s) suivis)...")
    meta_all = {}
    all_new_rows = []
    current_meta, current_rows = discover_current(departements)
    merge_meta(meta_all, current_meta)
    all_new_rows.extend(current_rows)
    print(f"  {len(current_meta)} station(s) trouvee(s).")

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
            print("  Extraction des stations des departements suivis...")
            year_meta, year_rows = extract_year_filtered(xml_bytes, departements)
            merge_meta(meta_all, year_meta)
            all_new_rows.extend(year_rows)
            print(f"  {len(year_rows)} entree(s) de prix extraite(s) pour {label}.")

    write_stations_csv(stations_path, meta_all)
    added = append_prix_rows(prix_dir, all_new_rows)
    n_chunks = build_data_chunks(prix_dir, data_dir)

    print(f"\n{len(meta_all)} station(s) dans stations.csv.")
    print(f"{added} nouvelle(s) ligne(s) de prix ajoutee(s) dans {config['prix_dir']}/.")
    print(f"{n_chunks} fichier(s) de donnees par station regenere(s) dans {config['data_dir']}/.")
    print("\nPense a lancer 'python3 build_site.py' pour regenerer le site si ce n'est pas deja fait.")


if __name__ == "__main__":
    main()
