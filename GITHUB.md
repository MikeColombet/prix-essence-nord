# Mise en ligne sur GitHub (Actions + Pages)

Tout le code est prêt (workflow, page d'accueil). Il reste des étapes à faire
**depuis ton Mac** (pas depuis Claude) car elles nécessitent ton compte
GitHub : créer le dépôt, le pousser, et activer deux réglages.

> Note technique : j'ai tenté d'initialiser git directement depuis mon
> environnement, mais l'accès à ton dossier `DataCarb` passe par un pont
> réseau qui ne supporte pas les opérations internes de git (renommage/
> suppression de fichiers temporaires). Un dossier `.git` partiel a pu rester
> dans `DataCarb` — supprime-le avant de commencer (étape 1 ci-dessous).

## 1. Nettoyer et initialiser git (Terminal, sur ton Mac)

```bash
cd ~/DataCarb
rm -rf .git          # supprime le dossier .git partiel laissé par ma tentative
git init -b main
git add -A
git commit -m "Premier import : suivi station Esso + carte du Nord"
```

## 2. Créer le dépôt sur GitHub

Sur https://github.com/new :
- Nom : par exemple `prix-essence-nord`
- Visibilité : **Public** (nécessaire pour GitHub Pages gratuit)
- Ne coche ni "Add a README", ni ".gitignore", ni "license" (le dépôt local en a déjà)
- Clique "Create repository"

GitHub affiche alors une URL du type `https://github.com/<ton-identifiant>/prix-essence-nord.git`.

## 3. Pousser le code

```bash
git remote add origin https://github.com/<ton-identifiant>/prix-essence-nord.git
git push -u origin main
```

(Si Git demande une authentification, utilise un token d'accès personnel
GitHub comme mot de passe — pas ton mot de passe de compte. À créer sur
https://github.com/settings/tokens si tu n'en as pas déjà un.)

## 4. Autoriser la GitHub Action à écrire dans le dépôt

Le workflow doit pouvoir committer les mises à jour de prix. Sur GitHub :
- Va dans **Settings > Actions > General**
- Descends jusqu'à "Workflow permissions"
- Sélectionne **"Read and write permissions"**
- Clique "Save"

Sans ça, la Action tournera mais échouera au moment de `git push`.

## 5. Activer GitHub Pages

- Va dans **Settings > Pages**
- Source : **"Deploy from a branch"**
- Branch : **main**, dossier **/ (root)**
- Clique "Save"

GitHub indique l'URL du site (mise à jour après 1-2 minutes), du type :
`https://<ton-identifiant>.github.io/prix-essence-nord/`

## 6. Tester la mise à jour automatique

- Va dans l'onglet **Actions** du dépôt
- Clique sur le workflow "Mise a jour des prix des carburants"
- Clique "Run workflow" (bouton en haut à droite) pour la lancer une première
  fois manuellement, sans attendre le prochain créneau de 12h
- Vérifie que le job se termine en vert, puis que le site s'est mis à jour

Ensuite, la Action se relance automatiquement toutes les 12 heures
(00:00 et 12:00 UTC) sans rien faire de plus. Pour forcer un rafraîchissement
complet de l'historique des stations suivies (au lieu des prix actuels
seulement), relance-la manuellement avec la case "historique_complet"
cochée.
