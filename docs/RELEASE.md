# Versions et publication — SpeakDo pour ERPNext

## Source unique de version

```
VERSION_SOURCE = speakdo_erpnext/__init__.py :: __version__
```

- `pyproject.toml` déclare `dynamic = ["version"]` : flit lit la version dans ce module.
- Tout le reste en dérive : `constants.COMPANION_VERSION`, l'en-tête `User-Agent`, les preuves envoyées
  au middleware (`companion_version`), le champ `SpeakDo Settings.companion_version` (réécrit à chaque
  `migrate`), la page d'administration et `get_status`.
- Aucun autre fichier ne déclare de version (pas de `setup.py`, `package.json` ni version dans
  `hooks.py`). Le test `tests/test_version.py` le vérifie.

## Règle de versionnement

`MAJEUR.MINEUR.CORRECTIF` (SemVer).

Pour la branche `1.0.x` (convention de lancement) :

- toute correction validée → incrément du **correctif** ;
- toute évolution fonctionnelle compatible → incrément **au minimum du correctif** tant que la
  convention de lancement s'applique ;
- toute **rupture de contrat** (surface compagnon ↔ middleware, modèle de données, comportement
  utilisateur incompatible) exige une **décision explicite** de version mineure ou majeure.

Aucun chantier fonctionnel ou correctif n'est terminé tant que le numéro de version n'a pas été
examiné.

## Règle obligatoire pour les agents et contributeurs

Toute livraison fonctionnelle ou corrective doit :

1. déterminer si la version doit changer ;
2. mettre à jour la version canonique (`speakdo_erpnext/__init__.py`) ;
3. mettre à jour `CHANGELOG.md` ;
4. vérifier `README.md` si le comportement utilisateur ou l'installation change ;
5. mentionner explicitement la version produite dans le compte rendu final.

Un compte rendu ne se limite pas à « tests verts » : il indique

```
Version produite : X.Y.Z
```

ou explique pourquoi aucun changement de version n'est justifié.

Toute modification du script d'une page (`speakdo/page/*/*.js`) doit aussi faire évoluer la date
`modified` du JSON de la page, sinon les navigateurs gardent l'ancien script en cache.

## Workflow de livraison

```
développement
→ tests
→ décision de version
→ mise à jour de la version canonique
→ CHANGELOG.md
→ README.md si nécessaire
→ tests complets + lint
→ commit
→ tag vX.Y.Z
→ GitHub Release
```

Tests et lint (site de test dédié, jamais un site de production) :

```bash
bench --site <site-de-test> set-config allow_tests true
bench --site <site-de-test> run-tests --app speakdo_erpnext
ruff check speakdo_erpnext
```

## Convention GitHub

- Dépôt recommandé : **`speakdo_erpnext`** (même nom que l'application Frappe et le package Python ;
  `bench get-app` déduit le nom de l'application du dépôt cloné, un nom identique évite toute
  divergence).
- Tag : `vX.Y.Z` (ex. `v1.0.0`).
- Release : `SpeakDo ERPNext X.Y.Z`, avec les notes de la section correspondante de `CHANGELOG.md`.

Une GitHub Release n'est créée que lorsque :

- la version canonique est mise à jour ;
- `CHANGELOG.md` est mis à jour ;
- les tests sont verts ;
- le commit est publié ;
- l'état fonctionnel est explicitement validé.

## Première publication (à exécuter manuellement)

```bash
cd speakdo_erpnext
git init -b main
git add .
git status            # vérifier : aucun secret, aucun artefact local
git commit -m "SpeakDo ERPNext 1.0.0"
git remote add origin git@github.com:<organisation>/speakdo_erpnext.git
git push -u origin main
git tag -a v1.0.0 -m "SpeakDo ERPNext 1.0.0"
git push origin v1.0.0
gh release create v1.0.0 --title "SpeakDo ERPNext 1.0.0" --notes-file <notes extraites du CHANGELOG>
```
