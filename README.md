# Suivi prix essence – Esso, 115 Bd Clemenceau, Marcq-en-Barœul

Ce dépôt contient deux outils :
- le suivi détaillé d'une station (ce dossier, racine) ;
- la carte de toutes les stations du département du Nord (dossier `nord/`, voir `nord/README.md`).

Les deux sont mis à jour automatiquement toutes les 12h par une GitHub Action
et publiés via GitHub Pages — voir `GITHUB.md` pour la mise en ligne.

## Fichiers

- `track_price.py` — script de collecte (aucune dépendance à installer, Python 3 standard).
- `config.json` — station suivie et noms de fichiers.
- `historique_prix_essence.csv` — historique des prix (créé/complété à chaque exécution).
- `visualisation.html` — tableau de bord (graphique + dernières valeurs), régénéré à chaque exécution.

Source des données : flux officiel `donnees.roulez-eco.fr` (même source que
prix-carburants.gouv.fr), mis à jour côté gouvernement toutes les 10 minutes.

## 1. Premier lancement — à faire manuellement

```bash
cd ~/DataCarb
python3 track_price.py
```

L'identifiant de station renseigné dans `config.json` (`59700004`) correspond
à l'adresse **115 Boulevard Clemenceau, 59700 Marcq-en-Barœul**, retrouvée via
un comparateur de prix public. Comme le flux officiel ne contient pas
l'enseigne (Esso), le script vérifie l'adresse à chaque exécution et affiche
un avertissement si elle ne correspond plus. Si l'avertissement apparaît,
lance :

```bash
python3 track_price.py --find 59700
```

Cela liste toutes les stations de Marcq-en-Barœul avec leur adresse : repère
la bonne et remplace `station_id` dans `config.json`.

## 2. Ouvrir la visualisation

Double-clique sur `visualisation.html` (ou ouvre-le depuis un navigateur). Il
se met à jour à chaque fois que `track_price.py` tourne — il suffit de
recharger la page.

## 3. Récupérer un historique (avant le lancement du suivi)

Le gouvernement publie aussi des **archives annuelles** avec l'historique
complet des changements de prix de chaque station (source : même flux que
`prix-carburants.gouv.fr`). Le nom des stations n'y figure pas non plus, mais
comme le script identifie déjà la station par son id, ça fonctionne pareil.

```bash
python3 track_price.py --historique 2026          # stock de l'année en cours (2026)
python3 track_price.py --historique 2024 2025 2026 # plusieurs années d'un coup
```

Chaque année téléchargée pèse entre ~10 et ~35 Mo (zip) et peut prendre une à
deux minutes selon la connexion. Les archives complètes existent depuis
**2007** ; l'année en cours (2026) est mise à jour chaque jour côté
gouvernement mais ne contient que les changements survenus depuis le 1er
janvier. Les entrées importées sont fusionnées avec le CSV existant sans
doublon, et `visualisation.html` est régénéré automatiquement à la fin.

Note sur les vieilles données : les archives antérieures à ~2022 expriment le
prix en millièmes d'euro sans virgule (ex: `1126` pour 1,126 €), alors que les
archives récentes utilisent directement la notation décimale (`1.563`). Le
script convertit automatiquement ce format à l'import. Si tu as un CSV créé
avant ce correctif et que tu vois des prix sans virgule, corrige-le avec :

```bash
python3 track_price.py --reparer-prix
```

## 4. Automatiser la collecte (macOS, optionnel)

Si tu utilises la mise à jour automatique via GitHub Actions (voir
`GITHUB.md`), cette section n'est plus nécessaire — passe-la. Elle reste utile
si tu préfères une collecte locale sur ton Mac, indépendante de GitHub.

Pour que la collecte tourne toute seule, ajoute une tâche cron. Dans le
Terminal :

```bash
crontab -e
```

Ajoute cette ligne (collecte toutes les 30 minutes) :

```
*/30 * * * * /usr/bin/python3 /Users/mikecolombet/DataCarb/track_price.py >> /Users/mikecolombet/DataCarb/log.txt 2>&1
```

Enregistre et quitte (`:wq` si l'éditeur est vim). Le prix n'est ajouté au CSV
que lorsqu'il change réellement, donc le fichier reste compact même avec des
collectes fréquentes.

Note macOS : la première fois, le Terminal (ou `cron`) peut demander
l'autorisation d'accès au dossier `DataCarb` dans Réglages Système >
Confidentialité et sécurité > Accès complet au disque.

## 5. Autres carburants

Le graphique et les cartes s'adaptent automatiquement aux carburants
disponibles à la station (Gazole, SP95, SP98, E10, E85, GPLc) : rien à
configurer.
