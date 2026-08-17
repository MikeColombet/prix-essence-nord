# Carte des prix essence – Département du Nord (59)

Carte interactive des stations-service du département du Nord, avec prix
actuels, comparaison moins chère / plus chère, moyenne départementale par
carburant et historique par station.

La carte est mise à jour automatiquement toutes les 12h par une GitHub
Action et publiée via GitHub Pages — voir `GITHUB.md` pour la mise en ligne.

Source des données : flux officiel `donnees.roulez-eco.fr` (même source que
prix-carburants.gouv.fr), mis à jour côté gouvernement toutes les 10 minutes.

## Fichiers

- `build_nord.py` — récupère les stations du département (filtre sur le code
  postal) et leur historique de prix, écrit `stations.csv` et `prix.csv`.
- `build_carte.py` — génère `index.html` à partir de ces deux CSV.
- `config.json` — paramètres (département, années d'historique à récupérer).
- `stations.csv` — une ligne par station (adresse, ville, coordonnées).
- `prix.csv` — une ligne par relevé de prix (station_id, carburant, prix, date).
- `data/{id}.js` — un petit fichier par station, chargé à la demande par la
  carte quand tu cliques dessus (pas de serveur nécessaire).
- `index.html` — la carte interactive (page d'accueil du dépôt / de GitHub Pages).

Ce format à deux fichiers (au lieu d'un seul CSV plat) évite de répéter
l'adresse de chaque station à chaque ligne de prix, ce qui réduit sensiblement
la taille sur le disque.

## Utilisation

```bash
cd ~/DataCarb
python3 build_nord.py      # 1er lancement : télécharge le flux instantané +
                            # les archives 2024, 2025 et l'année en cours
                            # (toute la France, filtré ensuite sur le 59)
python3 build_carte.py     # génère/actualise la carte
```

Ouvre ensuite `index.html` dans un navigateur, clique sur une station : ses
prix actuels et son évolution s'affichent à droite de la carte, avec en
pointillés la moyenne départementale du même carburant pour comparaison.

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

## Moyenne départementale

La carte affiche, sous les contrôles, la moyenne actuelle de chaque
carburant sur l'ensemble des stations du département (calculée à partir du
dernier prix connu de chaque station). Quand tu sélectionnes une station, le
graphique d'évolution superpose en pointillés la tendance historique de
cette moyenne départementale (recalculée jour par jour à partir de
`prix.csv`), pour comparer la station à la tendance générale.

## Automatiser la collecte (macOS, optionnel)

Si tu utilises la mise à jour automatique via GitHub Actions (voir
`GITHUB.md`), cette section n'est plus nécessaire — passe-la. Elle reste utile
si tu préfères une collecte locale sur ton Mac, indépendante de GitHub.

Pour que la collecte tourne toute seule, ajoute une tâche cron. Dans le
Terminal :

```bash
crontab -e
```

Ajoute cette ligne (mise à jour rapide toutes les 30 minutes) :

```
*/30 * * * * /usr/bin/python3 /Users/mikecolombet/DataCarb/build_nord.py --maj-seulement && /usr/bin/python3 /Users/mikecolombet/DataCarb/build_carte.py >> /Users/mikecolombet/DataCarb/log.txt 2>&1
```

Enregistre et quitte (`:wq` si l'éditeur est vim).

Note macOS : la première fois, le Terminal (ou `cron`) peut demander
l'autorisation d'accès au dossier `DataCarb` dans Réglages Système >
Confidentialité et sécurité > Accès complet au disque.

## Étendre à un autre département

Change `"cp_prefix"` dans `config.json` (ex: `"62"` pour le Pas-de-Calais),
supprime `stations.csv`, `prix.csv` et le contenu de `data/`, puis relance
`build_nord.py` et `build_carte.py`.

## Autres carburants

Le graphique et la carte s'adaptent automatiquement aux carburants
disponibles dans le département (Gazole, SP95, SP98, E10, E85, GPLc) : rien
à configurer.
