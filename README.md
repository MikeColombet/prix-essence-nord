# Recherche des prix essence – Hauts-de-France, Normandie, Grand Est, Île-de-France

Site de recherche des stations-service par code postal, avec prix actuels,
moyennes département / région / nationale par carburant (actuelles et leur
évolution) et historique par station. Couvre les 28 départements des régions
Hauts-de-France, Normandie, Grand Est et Île-de-France (voir la liste dans
`config.json`).

Le site est mis à jour automatiquement toutes les 12h par une GitHub Action
et publié via GitHub Pages — voir `GITHUB.md` pour la mise en ligne.

Source des données : flux officiel `donnees.roulez-eco.fr` (même source que
prix-carburants.gouv.fr), mis à jour côté gouvernement toutes les 10 minutes.

## Fichiers

- `collect_prices.py` — récupère les stations des départements suivis et
  leur historique de prix, écrit `stations.csv` et `prix/{dept}.csv`.
- `build_site.py` — génère `index.html` et les fichiers de données chargés à
  la demande, à partir de `stations.csv` et `prix/*.csv`.
- `config.json` — paramètres (départements suivis, regroupement par région,
  années d'historique à récupérer).
- `stations.csv` — une ligne par station (adresse, ville, code postal, coordonnées).
- `prix/{dept}.csv` — une ligne par relevé de prix (station_id, carburant, prix,
  date), un fichier par département.
- `stations/{dept}.js` — liste des stations d'un département avec leurs prix
  actuels, chargée à la demande quand tu recherches un code postal.
- `data/{id}.js` — historique complet des prix d'une station, chargé à la
  demande quand tu la sélectionnes.
- `dept_avg/{dept}.js` — moyenne historique d'un département par carburant,
  chargée à la demande quand tu cliques sur « Voir l'évolution du
  département ». Les moyennes régionale et nationale sont assez petites (une
  valeur par jour, pas par station) pour être embarquées directement dans
  `index.html`.
- `index.html` — la page de recherche (page d'accueil du dépôt / de GitHub Pages).

Toutes ces données sont chargées à la demande, par département ou par
station, plutôt que d'un bloc au chargement de la page : avec ~28
départements suivis, tout embarquer dans `index.html` la rendrait beaucoup
trop lourde. La page principale ne contient que l'interface de recherche.

Le prix est aussi éclaté en un fichier CSV par département (`prix/{dept}.csv`)
plutôt qu'un fichier unique : avec plusieurs années d'historique sur ~28
départements, un fichier unique grossirait au point de risquer de dépasser la
limite de taille de fichier de GitHub (100 Mo). Un fichier par département
reste petit indéfiniment.

## Utilisation

```bash
cd ~/DataCarb
python3 collect_prices.py  # 1er lancement : télécharge le flux instantané +
                            # les archives 2024, 2025 et l'année en cours
                            # (toute la France, filtré ensuite sur les
                            # départements suivis)
python3 build_site.py      # génère/actualise le site
```

Ouvre ensuite `index.html` dans un navigateur, tape un code postal (au moins
les 2 premiers chiffres) pour voir les stations du département, puis clique
sur une station pour voir ses prix actuels et son évolution.

À prévoir au premier lancement : `collect_prices.py` télécharge 3 archives
annuelles complètes de la France (~10-35 Mo chacune, zip) avant de ne garder
que les stations des départements suivis — l'essentiel du temps est le
téléchargement, pas l'extraction. Compte 2 à 5 minutes selon ta connexion.

## Relancer plus tard

- `python3 collect_prices.py --maj-seulement` : ne récupère que les prix
  actuels (flux instantané, rapide), sans retélécharger les archives annuelles.
- `python3 collect_prices.py` (sans option) : retélécharge aussi les archives
  configurées dans `config.json` — utile en début d'année suivante pour
  ajouter une nouvelle année, ou si tu changes `annees_passees`.
- Relance `python3 build_site.py` après chaque mise à jour de `prix/` /
  `stations.csv` pour que le site reflète les nouvelles données.

## Moyennes département / région / nationale

La moyenne nationale actuelle de chaque carburant (sur l'ensemble des
départements suivis) s'affiche en haut de la page, avant même de chercher un
code postal. Dès que tu recherches un code postal ou sélectionnes une
station, ses moyennes département et région s'affichent aussi (calculées à
partir du dernier prix connu de chaque station concernée) ; elles se
recalculent pour refléter le département/la région de la station
effectivement sélectionnée, pas seulement du code postal tapé.

Chaque niveau a son propre bouton « Voir l'évolution » : clique dessus pour
afficher son graphique d'évolution (une courbe par carburant, recalculée jour
par jour à partir de `prix/*.csv`). C'est un graphique indépendant, pas
superposé à celui d'une station.

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
*/30 * * * * /usr/bin/python3 /Users/mikecolombet/DataCarb/collect_prices.py --maj-seulement && /usr/bin/python3 /Users/mikecolombet/DataCarb/build_site.py >> /Users/mikecolombet/DataCarb/log.txt 2>&1
```

Enregistre et quitte (`:wq` si l'éditeur est vim).

Note macOS : la première fois, le Terminal (ou `cron`) peut demander
l'autorisation d'accès au dossier `DataCarb` dans Réglages Système >
Confidentialité et sécurité > Accès complet au disque.

## Ajouter ou retirer un département

Édite l'objet `"departements"` dans `config.json` (clé = code département sur
2 chiffres, valeur = nom affiché). Supprime `stations.csv`, le contenu de
`prix/`, `data/`, `stations/` et `dept_avg/`, puis relance `collect_prices.py`
et `build_site.py`.

## Autres carburants

Le graphique et les résultats de recherche s'adaptent automatiquement aux
carburants disponibles à chaque station (Gazole, SP95, SP98, E10, E85, GPLc) :
rien à configurer.
