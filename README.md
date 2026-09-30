# SpeakDo pour ERPNext / SpeakDo for ERPNext

Compagnon officiel entre **ERPNext** et le service **SpeakDo**.
Official companion app between **ERPNext** and the **SpeakDo** service.

Version : voir [`CHANGELOG.md`](CHANGELOG.md) — la version canonique est `speakdo_erpnext.__version__`.
Version: see [`CHANGELOG.md`](CHANGELOG.md) — the canonical version is `speakdo_erpnext.__version__`.

---

# 🇫🇷 Français

## Présentation

SpeakDo permet d'utiliser certaines fonctions d'un ERP depuis le terrain, **par la voix ou le texte**,
depuis une application web installable (PWA) sur téléphone ou tablette.

SpeakDo ne donne pas un accès libre à l'ERP : il repose sur un **catalogue d'actions contrôlé**, défini
et filtré côté SpeakDo, et chaque action réelle s'exécute avec les droits de l'utilisateur ERPNext.

Cette application Frappe (`speakdo_erpnext`) est le **compagnon** installé dans votre ERPNext. Elle ne
contient ni l'interface SpeakDo (PWA), ni le modèle de langage : elle rattache votre instance au
service SpeakDo et gère, côté ERPNext, les utilisateurs, leurs droits et leurs terminaux.

## Rôle du compagnon

- **Rattachement de l'instance** ERPNext au service SpeakDo, avec preuve de contrôle de l'instance et
  secret technique propre à l'installation.
- **Enrôlement des utilisateurs** : chaque utilisateur génère un **QR code** temporaire à usage unique
  pour associer son téléphone ou sa tablette.
- **Terminaux** : plusieurs terminaux par utilisateur, révocables individuellement.
- **Capabilities** : calculées à partir des **permissions ERPNext réelles** de l'utilisateur.
- **Profils SpeakDo autorisés** : l'administrateur choisit, pour chaque utilisateur, les modes de
  travail SpeakDo autorisés (0 à N), parmi le catalogue publié par SpeakDo.
- **Credential API ERPNext par utilisateur**, créé et géré par SpeakDo, pour que les actions s'exécutent
  au nom de l'utilisateur et avec ses droits.
- **Communication sécurisée** avec le middleware SpeakDo (requêtes signées, anti-rejeu).

Il n'ajoute aucune logique métier dans ERPNext : aucun hook sur vos documents, aucune action métier
exécutée par le compagnon.

## Architecture

```
Utilisateur
   ↓
PWA SpeakDo          (application web installable)
   ↓
Middleware SpeakDo   (catalogue d'actions, modèle de langage, sessions)
   ↓
Compagnon ERPNext    (cette application)
   ↓
ERPNext / Frappe
```

## Permissions

```
permissions ERPNext de l'utilisateur
        → capabilities SpeakDo
```

Les capabilities sont une traduction **déterministe** des permissions ERPNext (rôles, permissions de
DocType), recalculée à chaque vérification. Elles indiquent à SpeakDo quelles actions proposer.

Elles ne remplacent pas le contrôle d'ERPNext : chaque appel réel est fait avec le credential de
l'utilisateur, donc **soumis à ses permissions ERPNext** au moment de l'exécution.

## Profils

```
Utilisateur          → profils SpeakDo autorisés [0..N]
Session SpeakDo      → profil actif
```

Le compagnon gère les **profils autorisés** de chaque utilisateur. Le **profil actif** (le mode de
travail en cours) est choisi dans SpeakDo, par session ; le compagnon ne le stocke pas. Un utilisateur
sans profil autorisé reste sans profil : il n'est pas basculé automatiquement sur un profil par défaut.

Le catalogue des profils appartient au service SpeakDo et est lu par le compagnon ; il n'est jamais
recopié dans le code.

## Credentials

- Un **credential API ERPNext propre à chaque utilisateur**, créé par SpeakDo au premier enrôlement et
  partagé par les terminaux de cet utilisateur.
- **Jamais de credential pour le compte `Administrator`** : son enrôlement est refusé.
- Si l'utilisateur possède déjà une clé API **qui n'a pas été créée par SpeakDo**, l'enrôlement est
  refusé : SpeakDo ne réutilise, ne remplace ni ne régénère jamais une clé dont il ne possède pas le
  cycle de vie.
- À la **révocation du dernier terminal** de l'utilisateur, le credential SpeakDo est révoqué.
- Aucune clé ni aucun secret n'est affiché dans l'interface.

## Terminaux

- Plusieurs terminaux par utilisateur.
- Révocation individuelle (par l'utilisateur pour ses propres terminaux, ou par un administrateur).
- Isolation complète entre utilisateurs : un utilisateur ne voit ni ne révoque les terminaux d'un autre.

## Interfaces dans ERPNext

- **Administration SpeakDo** (`/app/speakdo-admin`, rôle *System Manager*) : rattachement de
  l'instance, configuration, diagnostics, et vue par utilisateur (profils autorisés, capabilities,
  état du credential, terminaux).
- **Mon SpeakDo** (`/app/speakdo-me`, tout utilisateur du bureau ERPNext) : ses profils, ses
  capabilities, l'état de son credential, ses terminaux et la génération de son QR code.

## Prérequis

- Frappe Framework et ERPNext **v15** (voir *Compatibilité*).
- Une URL de l'instance ERPNext **joignable depuis Internet** par le service SpeakDo (racine du site,
  sans chemin), idéalement en HTTPS.
- Un abonnement / accès au service SpeakDo.

## Installation

Procédure Frappe standard pour une application publiée sur GitHub (dépôt à créer, voir *Liens*) :

```bash
bench get-app <url-du-depot-github>
bench --site <votre-site> install-app speakdo_erpnext
bench --site <votre-site> migrate
```

Installation réellement utilisée et testée (déploiement Docker `frappe_docker`, application montée
dans `apps/speakdo_erpnext`) :

```bash
./env/bin/pip install -e apps/speakdo_erpnext
grep -qx speakdo_erpnext sites/apps.txt || echo speakdo_erpnext >> sites/apps.txt
bench --site <votre-site> install-app speakdo_erpnext
bench build --app speakdo_erpnext
bench --site <votre-site> migrate
```

puis redémarrer les services Frappe (backend, workers, scheduler).

Après toute mise à jour : `bench --site <votre-site> migrate`.

## Configuration

Dans **Administration SpeakDo** :

| Paramètre | Rôle | Valeur par défaut |
|---|---|---|
| Middleware SpeakDo | service SpeakDo auquel l'instance se rattache | `https://api.speakdo.fr` |
| Application SpeakDo | base des QR codes d'enrôlement | `https://app.speakdo.fr` |
| URL de cette instance ERPNext | racine publique de votre ERPNext | URL du site |

Puis : **Enrôler cette instance**. Chaque utilisateur génère ensuite son QR code depuis
**Mon SpeakDo**. L'administrateur affecte les profils SpeakDo autorisés depuis la vue *Utilisateurs
SpeakDo*.

Aucun secret n'est à saisir : le secret technique de l'instance est obtenu lors du rattachement et
stocké chiffré.

## Compatibilité

Testé avec :

- Frappe **15.121.1**
- ERPNext **15.121.5**
- Python 3.11 (image `frappe_docker`)

Aucune autre version n'a été testée à ce jour.

## Sécurité

- **Isolation par utilisateur** : profils, capabilities, credential et terminaux sont propres à chaque
  utilisateur ; contrôles effectués côté serveur.
- **Permissions ERPNext** : restent l'autorité à l'exécution.
- **Credentials protégés** : stockés chiffrés par Frappe, jamais affichés ni journalisés.
- **QR d'enrôlement** : temporaire, à usage unique, lié à l'utilisateur qui l'a généré.
- **Révocation** des terminaux et du credential.
- **Aucun secret dans les journaux** : seuls des champs techniques non sensibles sont journalisés.
- **Requêtes signées** entre SpeakDo et le compagnon, avec protection contre le rejeu.
- **Catalogue d'actions fermé** côté SpeakDo.

## État du support ERPNext

Version `1.0.0` : le compagnon (rattachement, enrôlement, profils autorisés, capabilities,
credentials, terminaux) est opérationnel. La **frontière multi-ERP de SpeakDo est encore en cours de
validation réelle** : l'exécution de bout en bout des actions métier sur ERPNext n'est pas encore
annoncée comme disponible. Le support ERPNext ne doit donc pas être considéré comme complet.

## Liens officiels

- Site : https://speakdo.fr
- Application : https://app.speakdo.fr
- Documentation : https://docs.speakdo.fr
- Module Dolibarr : https://github.com/Margepro/speakdo
- Dépôt ERPNext : à créer (voir [`docs/RELEASE.md`](docs/RELEASE.md))

Documentation technique : [`docs/`](docs) — modèle utilisateur, routes, compatibilité, règles de
version et de publication.

## Licence

Le compagnon SpeakDo pour ERPNext est distribué sous licence
**GNU General Public License v3.0 ou ultérieure — GPL-3.0-or-later**, comme le module SpeakDo pour
Dolibarr. Texte complet : [`LICENSE`](LICENSE).

La licence du compagnon ne constitue pas un droit d'accès au service SpeakDo, qui fait l'objet de ses
propres conditions.

---

# 🇬🇧 English

## Overview

SpeakDo lets field users run selected ERP functions **by voice or text**, from an installable web app
(PWA) on a phone or tablet.

SpeakDo does not give free access to the ERP: it relies on a **controlled action catalogue**, defined
and filtered by SpeakDo, and every real action runs with the ERPNext user's own permissions.

This Frappe app (`speakdo_erpnext`) is the **companion** installed in your ERPNext. It contains neither
the SpeakDo interface (PWA) nor the language model: it attaches your instance to the SpeakDo service
and manages, on the ERPNext side, users, their rights and their devices.

## What the companion does

- **Attaches the ERPNext instance** to the SpeakDo service, with a proof of control of the instance and
  a technical secret specific to the installation.
- **User enrolment**: each user generates a temporary, single-use **QR code** to pair a phone or
  tablet.
- **Terminals**: several terminals per user, individually revocable.
- **Capabilities**: computed from the user's **actual ERPNext permissions**.
- **Allowed SpeakDo profiles**: for each user, the administrator selects the allowed SpeakDo working
  modes (0 to N) from the catalogue published by SpeakDo.
- **Per-user ERPNext API credential**, created and managed by SpeakDo, so that actions run on behalf
  of the user and with the user's permissions.
- **Secure communication** with the SpeakDo middleware (signed requests, replay protection).

It adds no business logic to ERPNext: no hooks on your documents, no business action executed by the
companion.

## Architecture

```
User
   ↓
SpeakDo PWA          (installable web app)
   ↓
SpeakDo middleware   (action catalogue, language model, sessions)
   ↓
ERPNext companion    (this app)
   ↓
ERPNext / Frappe
```

## Permissions

```
user's ERPNext permissions
        → SpeakDo capabilities
```

Capabilities are a **deterministic** translation of ERPNext permissions (roles, DocType permissions),
recomputed at every check. They tell SpeakDo which actions to offer.

They do not replace ERPNext's own checks: every real call is made with the user's credential, and is
therefore **subject to the user's ERPNext permissions** at execution time.

## Profiles

```
User                 → allowed SpeakDo profiles [0..N]
SpeakDo session      → active profile
```

The companion manages each user's **allowed profiles**. The **active profile** (the current working
mode) is selected in SpeakDo, per session; the companion does not store it. A user with no allowed
profile stays without a profile: they are not silently switched to a default profile.

The profile catalogue belongs to the SpeakDo service and is read by the companion; it is never copied
into the code.

## Credentials

- A **per-user ERPNext API credential**, created by SpeakDo at the first enrolment and shared by that
  user's terminals.
- **Never a credential for the `Administrator` account**: its enrolment is refused.
- If the user already has an API key **that SpeakDo did not create**, enrolment is refused: SpeakDo
  never reuses, replaces or regenerates a key whose lifecycle it does not own.
- When the user's **last terminal is revoked**, the SpeakDo credential is revoked.
- No key or secret is ever displayed in the interface.

## Terminals

- Several terminals per user.
- Individual revocation (by the user for their own terminals, or by an administrator).
- Full isolation between users: a user can neither see nor revoke another user's terminals.

## Screens in ERPNext

- **SpeakDo administration** (`/app/speakdo-admin`, *System Manager* role): instance attachment,
  configuration, diagnostics, and a per-user view (allowed profiles, capabilities, credential state,
  terminals).
- **My SpeakDo** (`/app/speakdo-me`, any ERPNext desk user): own profiles, capabilities, credential
  state, terminals and QR code generation.

## Requirements

- Frappe Framework and ERPNext **v15** (see *Compatibility*).
- An ERPNext instance URL **reachable from the Internet** by the SpeakDo service (site root, no path),
  ideally over HTTPS.
- A subscription / access to the SpeakDo service.

## Installation

Standard Frappe procedure for an app published on GitHub (repository to be created, see *Links*):

```bash
bench get-app <github-repository-url>
bench --site <your-site> install-app speakdo_erpnext
bench --site <your-site> migrate
```

Installation actually used and tested (Docker `frappe_docker` deployment, app mounted in
`apps/speakdo_erpnext`):

```bash
./env/bin/pip install -e apps/speakdo_erpnext
grep -qx speakdo_erpnext sites/apps.txt || echo speakdo_erpnext >> sites/apps.txt
bench --site <your-site> install-app speakdo_erpnext
bench build --app speakdo_erpnext
bench --site <your-site> migrate
```

then restart the Frappe services (backend, workers, scheduler).

After any update: `bench --site <your-site> migrate`.

## Configuration

In **SpeakDo administration**:

| Setting | Purpose | Default |
|---|---|---|
| SpeakDo middleware | SpeakDo service the instance attaches to | `https://api.speakdo.fr` |
| SpeakDo application | base of the enrolment QR codes | `https://app.speakdo.fr` |
| This ERPNext instance URL | public root of your ERPNext | site URL |

Then: **Enrol this instance**. Each user then generates their QR code from **My SpeakDo**. The
administrator assigns allowed SpeakDo profiles from the *SpeakDo users* view.

No secret has to be entered: the instance's technical secret is obtained during attachment and stored
encrypted.

## Compatibility

Tested with:

- Frappe **15.121.1**
- ERPNext **15.121.5**
- Python 3.11 (`frappe_docker` image)

No other version has been tested so far.

## Security

- **Per-user isolation**: profiles, capabilities, credential and terminals belong to each user;
  checks are enforced server side.
- **ERPNext permissions** remain the authority at execution time.
- **Protected credentials**: stored encrypted by Frappe, never displayed nor logged.
- **Enrolment QR code**: temporary, single-use, bound to the user who generated it.
- **Revocation** of terminals and credential.
- **No secret in logs**: only non-sensitive technical fields are logged.
- **Signed requests** between SpeakDo and the companion, with replay protection.
- **Closed action catalogue** on the SpeakDo side.

## ERPNext support status

Version `1.0.0`: the companion (attachment, enrolment, allowed profiles, capabilities, credentials,
terminals) is operational. SpeakDo's **multi-ERP boundary is still being validated end to end**:
executing business actions on ERPNext is not yet announced as available. ERPNext support should
therefore not be considered complete.

## Official links

- Website: https://speakdo.fr
- Application: https://app.speakdo.fr
- Documentation: https://docs.speakdo.fr
- Dolibarr module: https://github.com/Margepro/speakdo
- ERPNext repository: to be created (see [`docs/RELEASE.md`](docs/RELEASE.md))

Technical documentation: [`docs/`](docs) — user model, routes, compatibility, versioning and release
rules.

## License

The SpeakDo companion for ERPNext is distributed under the
**GNU General Public License v3.0 or later — GPL-3.0-or-later**, like the SpeakDo module for Dolibarr.
Full text: [`LICENSE`](LICENSE).

The companion's license does not grant any right of access to the SpeakDo service, which is governed
by its own terms.
