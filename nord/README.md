# Carte des prix essence - Département du Nord (59)

## Fichiers

- `build_nord.py` — récupère les stations du département (filtre sur le code
  postal) et leur historique de prix, écrit `stations.csv` et `prix.csv`.
- `build_carte.py` — génère `carte_nord.html` à partir de ces deux CSV.
- `config.json` — paramètres (département, années d'historique à récupérer).
- `stations.csv` — une ligne par station (adresse, ville, coordonnées).
- `prix.csv` — une ligne par relevé de prix (station_id, carburant, prix, date).
- `data/{id}.js` — un petit fichier par station, chargé à la demande par la
  carte quand tu cliques dessus (pas de serveur nécessaire).
- `carte_nord.html` — la carte interactive.

Ce format à deux fichiers (au lieu d'un seul CSV plat) évite de répéter
l'adresse de chaque station à chaque ligne de prix, ce qui réduit sensiblement
la taille sur le disque.

## Utilisation

```bash
cd ~/DataCarb/nord
python3 build_nord.py      # 1er lancement : télécharge le flux instantané +
                            # les archives 2024, 2025 et l'année en cours
                            # (toute la France, filtré ensuite sur le 59)
python3 build_carte.py     # génère/actualise la carte
```

Ouvre ensuite `carte_nord.html` dans un navigateur, clique sur une station :
ses prix actuels et son évolution s'affichent à droite de la carte.

À prévoir au premier lancement : `build_nord.py` télécharge 3 archives
annuelles complètes de la France (~10-35 Mo chacune, zip) avant de ne garder
que les ~250 stations du Nord — l'essentiel du temps est le téléchargement,
pas l'extraction. Compte 2 à 5 minutes selon ta connexion.

## Relancer plus tard

- `python3 build_nord.py --maj-seulement` : ne récupère que les prix actuels
  (flux instantané, rapide), sans retélécharger les archives annuelles.
- `python3 build_nord.py` (sans option) : retélécharge aussi les archives
  configurées dans `config.json` — utile en début d'année suivante pour
  ajouter une nouvelle année, ou si tu changes `annees_passees`.
- Relance `python3 build_carte.py` après chaque mise à jour de `prix.csv` /
  `stations.csv` pour que la carte reflète les nouvelles données.

Ce dossier n'est **pas** ajouté au cron existant (qui suit uniquement ta
station Esso) : c'est un import ponctuel. Si tu veux un suivi continu des
250 stations plus tard, on pourra ajouter une ligne cron dédiée à
`build_nord.py --maj-seulement`.

## Étendre à un autre département

Change `"cp_prefix"` dans `config.json` (ex: `"62"` pour le Pas-de-Calais),
supprime `stations.csv`, `prix.csv` et le contenu de `data/`, puis relance
`build_nord.py` et `build_carte.py`.
