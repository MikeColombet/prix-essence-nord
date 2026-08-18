#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recupere et met a jour les prix des carburants de toutes les stations des
departements configures (par defaut : France metropolitaine, 95 departements
— la Corse est suivie comme un seul departement "20" car son code postal ne
distingue pas 2A/2B).

Usage :
    python3 collect_prices.py            -> collecte complete (roster + historique
                                             configure) puis (re)construit le site
    python3 collect_prices.py --maj-seulement
                                          -> ne recupere que les prix actuels (flux
                                             instantane), sans retelecharger les
                                             archives annuelles (rapide)

Sources officielles : voir https://www.prix-carburants.gouv.fr/rubrique/opendata/
Le nom et la marque des stations ne font pas partie des donnees publiques.

Stockage : un fichier compresse par station, data/{dept}/{station_id}.json.gz,
contenant tout son historique (ex: [["Gazole","1.827","2019-03-02T08:00:00"], ...]).
C'est la SEULE copie des prix (pas de CSV plat en parallele) : a l'echelle de
toute la France sur 10 ans, dupliquer les donnees dans deux formats doublerait
inutilement la taille du depot. Le format compact (tableaux, pas d'objets a
cles repetees) + gzip reduit encore la taille sur disque d'un facteur ~5-8
par rapport a du CSV/JSON verbeux non compresse.

Une archive annuelle est traitee en flux (iterparse) : chaque station
rencontree est fusionnee immediatement dans son fichier sur disque, sans
jamais accumuler l'annee entiere (~plusieurs millions de lignes pour la
France) en memoire.

Ce script ne depend d'aucune librairie externe (bibliotheque standard Python 3
uniquement : gzip et json compris).
"""
import csv
import gzip
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
    return _http_get_zip_xml(url, timeout=300)


def _station_meta_from_elem(elem):
    return {
        "adresse": (elem.findtext("adresse") or "").strip(),
        "ville": (elem.findtext("ville") or "").strip(),
        "cp": (elem.get("cp") or "").strip(),
        "latitude": elem.get("latitude") or "",
        "longitude": elem.get("longitude") or "",
    }


def _pdv_department(cp):
    """Departement d'un code postal : 2 premiers chiffres, sauf la Corse
    (20000-20999) regroupee sous le code "20" (le code postal seul ne
    distingue pas 2A/2B)."""
    return cp[:2] if cp else ""


def _extract_pdv(elem, departements):
    """Retourne (station_id, meta, departement, lignes_prix) pour un element
    <pdv> dont le departement fait partie de ceux suivis, sinon None.
    lignes_prix : liste de (carburant, prix_eur, maj_officielle)."""
    cp = (elem.get("cp") or "").strip()
    dept = _pdv_department(cp)
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
        price_rows.append((prix.get("nom"), valeur, maj))
    return sid, meta, dept, price_rows


def merge_meta(target, sid, meta):
    """Fusionne les metadonnees d'une station : on complete les champs vides,
    sans ecraser une valeur deja connue par une chaine vide."""
    if sid not in target:
        target[sid] = dict(meta)
    else:
        for k, v in meta.items():
            if v and not target[sid].get(k):
                target[sid][k] = v


def history_path(data_dir, dept, sid):
    return os.path.join(data_dir, dept, f"{sid}.json.gz")


def read_station_history(path):
    """Lit l'historique compresse d'une station : liste de
    [carburant, prix_eur, maj_officielle], triee chronologiquement.
    Liste vide si le fichier n'existe pas encore."""
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_station_history(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(entries, f, separators=(",", ":"), ensure_ascii=False)


def merge_station_history(path, new_rows):
    """Fusionne new_rows (carburant, prix_eur, maj_officielle) dans
    l'historique existant d'une station (dedoublonnage sur
    carburant+maj_officielle), reecrit le fichier trie chronologiquement.
    Ne touche pas au disque si aucune ligne n'est reellement nouvelle.
    Retourne le nombre de lignes ajoutees."""
    existing = read_station_history(path)
    existing_keys = {(e[0], e[2]) for e in existing}
    to_add = []
    seen = set()
    for carburant, prix_eur, maj in new_rows:
        key = (carburant, maj)
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        to_add.append([carburant, prix_eur, maj])

    if not to_add:
        return 0

    merged = existing + to_add
    merged.sort(key=lambda e: e[2])
    write_station_history(path, merged)
    return len(to_add)


def ingest_pdv_stream(root_iter, departements, data_dir, meta_all):
    """Parcourt un flux d'elements <pdv> (root.findall ou iterparse) et
    fusionne immediatement chaque station rencontree dans son fichier
    data/{dept}/{id}.json.gz — jamais d'accumulation de l'ensemble des
    lignes en memoire, meme pour une grosse archive annuelle. Retourne le
    nombre de stations vues et le nombre de lignes de prix ajoutees."""
    n_stations = 0
    n_rows_added = 0
    for elem in root_iter:
        result = _extract_pdv(elem, departements)
        if result is not None:
            sid, meta, dept, rows = result
            merge_meta(meta_all, sid, meta)
            n_stations += 1
            if rows:
                path = history_path(data_dir, dept, sid)
                n_rows_added += merge_station_history(path, rows)
        elem.clear()
    return n_stations, n_rows_added


def discover_current(departements, data_dir, meta_all):
    """Flux instantane (toute la France, ~1 Mo compresse)."""
    xml_bytes = download_flux()
    root = ET.fromstring(xml_bytes)
    return ingest_pdv_stream(root.findall("pdv"), departements, data_dir, meta_all)


def ingest_year_archive(xml_bytes, departements, data_dir, meta_all):
    """Grosse archive annuelle (toute la France), traitee en flux
    (iterparse) : chaque station est fusionnee sur disque au fil du
    parcours, sans jamais retenir l'annee entiere en memoire."""

    def _pdv_iter():
        for event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
            if elem.tag == "pdv":
                yield elem

    return ingest_pdv_stream(_pdv_iter(), departements, data_dir, meta_all)


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


def main():
    config = load_config()
    departements = set(config["departements"].keys())
    stations_path = os.path.join(BASE_DIR, config["stations_filename"])
    data_dir = os.path.join(BASE_DIR, config["data_dir"])

    maj_seulement = len(sys.argv) > 1 and sys.argv[1] == "--maj-seulement"

    meta_all = {}
    total_stations_seen = 0
    total_rows_added = 0

    print(f"Telechargement du flux instantane (toute la France, {len(departements)} departement(s) suivis)...")
    n_stations, n_rows = discover_current(departements, data_dir, meta_all)
    total_stations_seen += n_stations
    total_rows_added += n_rows
    print(f"  {n_stations} station(s) vue(s), {n_rows} nouvelle(s) ligne(s) de prix.")

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
            print("  Extraction et fusion des stations des departements suivis...")
            n_stations, n_rows = ingest_year_archive(xml_bytes, departements, data_dir, meta_all)
            total_stations_seen += n_stations
            total_rows_added += n_rows
            print(f"  {n_stations} station(s) vue(s), {n_rows} nouvelle(s) ligne(s) de prix pour {label}.")

    write_stations_csv(stations_path, meta_all)

    print(f"\n{len(meta_all)} station(s) dans stations.csv.")
    print(f"{total_rows_added} nouvelle(s) ligne(s) de prix ajoutee(s) au total dans {config['data_dir']}/.")
    print("\nPense a lancer 'python3 build_site.py' pour regenerer le site si ce n'est pas deja fait.")


if __name__ == "__main__":
    main()
