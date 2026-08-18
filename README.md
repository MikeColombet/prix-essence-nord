# Recherche des prix essence – France

Deux pages statiques, générées à partir des mêmes données, chacune avec un
objectif unique :
- `index.html` — recherche de stations par code postal : prix actuels et
  évolution sur 10 ans d'une station.
- `comparaison.html` — moyenne nationale actuelle (et son évolution), et un
  tableau des départements (triés par numéro, en-tête figé au défilement)
  avec le prix de chaque carburant et un indicateur moins cher/plus cher
  que la moyenne nationale ; clique une ligne pour voir son évolution.

Couvre la France métropolitaine (95 départements — la Corse est suivie
comme un seul département « 20 », son code postal ne distinguant pas
2A/2B ; voir la liste complète dans `config.json`).

Le site est mis à jour automatiquement toutes les 12h par une GitHub Action
et publié via GitHub Pages — voir `GITHUB.md` pour la mise en ligne.

Source des données : flux officiel `donnees.roulez-eco.fr` (même source que
prix-carburants.gouv.fr), mis à jour côté gouvernement toutes les 10 minutes.

**Important : ce site doit être servi en http(s)**, pas ouvert directement
depuis le disque (double-clic sur `index.html`). Les données étant
compressées (voir plus bas), le navigateur les récupère via `fetch()`, qui ne
peut pas lire de fichier local via `file://`. En local, lance
`python3 -m http.server` puis ouvre `http://localhost:8000/`. En production,
GitHub Pages sert déjà le site en https.

## Fichiers

- `collect_prices.py` — récupère les stations des départements suivis et
  leur historique de prix, écrit `stations.csv` et `data/{dept}/{id}.json.gz`.
- `fetch_brands.py` — récupère la marque des stations (TotalEnergies, Esso,
  Carrefour, ...) depuis OpenStreetMap, écrit `marques.csv`. Indépendant de
  `collect_prices.py` (voir « Marque des stations » plus bas).
- `build_site.py` — génère `index.html` et `comparaison.html`, plus les
  fichiers de données chargés à la demande, à partir de `stations.csv`,
  `marques.csv` et `data/*/*.json.gz`.
- `config.json` — paramètres (départements suivis, regroupement par région,
  années d'historique à récupérer, noms des fichiers/pages générés).
- `stations.csv` — une ligne par station (adresse, ville, code postal, coordonnées).
- `marques.csv` — une ligne par station ayant une marque connue (station_id, marque).
- `data/{dept}/{id}.json.gz` — historique complet des prix d'une station
  (ex: `[["Gazole","1.827","2019-03-02T08:00:00"], ...]`), compressé,
  chargé à la demande quand tu la sélectionnes depuis `index.html`. **Seule
  copie** des prix : il n'y a pas de CSV séparé en plus (voir « Pourquoi
  compresser » plus bas).
- `stations/{dept}.json.gz` — liste des stations d'un département avec leurs
  prix actuels, chargée à la demande quand tu recherches un code postal
  dans `index.html`.
- `dept_avg/{dept}.json.gz` — moyenne historique d'un département par
  carburant, chargée à la demande depuis `comparaison.html` quand tu cliques
  sur une ligne du tableau des départements. La moyenne nationale est assez
  petite (une valeur par jour, pas par station) pour être embarquée
  directement dans `comparaison.html`, non compressée.
- `index.html` — la page de recherche par code postal (page d'accueil du
  dépôt / de GitHub Pages).
- `comparaison.html` — la page de comparaison département / national.

## Pourquoi compresser, et pourquoi une seule copie des prix

À l'échelle d'un seul département sur 2-3 ans, stocker les prix deux fois (un
CSV à plat + un JSON par station) restait gérable. À l'échelle de toute la
France sur 10 ans (~13x plus de volume), dupliquer les données doublerait
inutilement la taille du dépôt. `data/{dept}/{id}.json.gz` est donc la seule
copie : `collect_prices.py` s'en sert à la fois pour dédupliquer les
nouvelles lignes et comme source servie au navigateur, et `build_site.py`
relit ces mêmes fichiers pour calculer les moyennes.

Chaque fichier est en plus :
- **compact** : tableaux (`["Gazole","1.827","2019-03-02T08:00:00"]`) plutôt
  que des objets JSON à clés répétées (`{"carburant":"Gazole",...}`) ;
- **gzippé** : le texte tabulaire très répétitif (identifiants, dates,
  quelques noms de carburant) compresse typiquement 5 à 8x. Décompression
  côté navigateur via `DecompressionStream` (API native, aucune dépendance).

Combinés, dédoublonnage + compression permettent de couvrir 13x plus de
départements et 4x plus d'années tout en gardant une taille de dépôt
comparable à l'ancienne version (un seul département, CSV/JSON non compressés).

Les prix sont aussi éclatés par département (`data/{dept}/`, un fichier par
station) plutôt qu'en un ou quelques gros fichiers : ça garde chaque fichier
petit indéfiniment (croissance proportionnelle au nombre de stations de CE
département, pas de la France entière), bien loin de la limite de taille de
fichier de GitHub (100 Mo).

## Utilisation

```bash
cd ~/DataCarb
python3 collect_prices.py  # 1er lancement : telecharge le flux instantane +
                            # 10 ans d'archives annuelles (toute la France),
                            # filtre et fusionne station par station
python3 build_site.py      # genere/actualise le site
python3 -m http.server     # sert le site en local (necessaire, voir plus haut)
```

Ouvre ensuite `http://localhost:8000/`, tape un code postal (au moins les 2
premiers chiffres) pour voir les stations du département, puis clique sur
une station pour voir ses prix actuels et son évolution. Depuis cette page,
un lien mène à `comparaison.html` pour comparer les prix par département
et national.

À prévoir au premier lancement : `collect_prices.py` télécharge 10 archives
annuelles complètes de la France (~10-35 Mo chacune, zip), traitées une par
une en flux (jamais toute une année en mémoire à la fois). Compte plusieurs
dizaines de minutes selon ta connexion et la puissance de la machine — c'est
un import ponctuel, les mises à jour suivantes (`--maj-seulement`) sont rapides.

## Relancer plus tard

- `python3 collect_prices.py --maj-seulement` : ne récupère que les prix
  actuels (flux instantané, rapide), sans retélécharger les archives annuelles.
- `python3 collect_prices.py` (sans option) : retélécharge aussi les archives
  configurées dans `config.json` — utile en début d'année suivante pour
  ajouter une nouvelle année, ou si tu changes `annees_passees`.
- Relance `python3 build_site.py` après chaque mise à jour de `data/` /
  `stations.csv` pour que le site reflète les nouvelles données.

## Comparaison département / nationale (`comparaison.html`)

En haut de la page : la moyenne nationale actuelle de chaque carburant (sur
l'ensemble des départements suivis), avec un bouton « Voir l'évolution »
(graphique indépendant, pas superposé à une station).

En dessous, un tableau des départements (triés par numéro, en-tête de
colonnes figé au défilement pour rester lisible sur les 95 lignes) avec le
prix moyen actuel de chaque carburant et un indicateur (▼ vert = moins cher,
▲ rouge = plus cher) par rapport à la moyenne nationale de ce carburant.
Clique une ligne pour afficher son évolution dans le temps (chargée à la
demande depuis `dept_avg/{dept}.json.gz`).

## Marque des stations

Le flux officiel du gouvernement ne contient jamais la marque/enseigne
d'une station (Esso, TotalEnergies, Carrefour, ...) — seule l'adresse.
`fetch_brands.py` la récupère séparément depuis OpenStreetMap (API
Overpass) : beaucoup de stations OSM portent un tag
`ref:FR:prix-carburants` — le même identifiant que celui du flux officiel —
ce qui permet une jointure exacte. Pour les stations sans ce tag, la
station OSM la plus proche (moins de 100 m) portant une marque est utilisée
à la place. Sur toute la France (août 2026) : ~64% de correspondance exacte
par identifiant, ~79% en ajoutant le rattachement par proximité — les
stations restantes n'ont simplement pas de marque affichée.

```bash
python3 fetch_brands.py    # ecrit marques.csv (quelques minutes, interroge
                            # plusieurs miroirs Overpass avec repli si l'un
                            # est indisponible)
python3 build_site.py      # regenere le site pour inclure les marques
```

Une marque change rarement : pas besoin de relancer `fetch_brands.py` à
chaque collecte de prix. `.github/workflows/update-brands.yml` le fait
automatiquement une fois par semaine (dimanche 3h UTC), ou à la demande
depuis l'onglet Actions de GitHub.

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

Édite l'objet `"departements"` dans `config.json` (clé = code département
sur 2 chiffres, valeur = nom affiché). Supprime `stations.csv`,
`marques.csv` et le contenu de `data/`, `stations/` et `dept_avg/`, puis
relance `collect_prices.py`, `fetch_brands.py` (optionnel) et `build_site.py`.

## Autres carburants

Le graphique et les résultats de recherche s'adaptent automatiquement aux
carburants disponibles à chaque station (Gazole, SP95, SP98, E10, E85, GPLc) :
rien à configurer.
