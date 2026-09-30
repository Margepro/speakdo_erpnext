# Changelog

Toutes les modifications notables du compagnon **SpeakDo pour ERPNext** (`speakdo_erpnext`) sont
documentées dans ce fichier.

Le versionnage suit le principe `MAJEUR.MINEUR.CORRECTIF` (SemVer). Règles : voir
[`docs/RELEASE.md`](docs/RELEASE.md). La version canonique est `speakdo_erpnext.__version__`.

---

## [1.0.0] - 2026-09-30

### Version initiale

Première version publiable du compagnon ERPNext. Le compagnon est opérationnel ; l'exécution de bout
en bout des actions métier SpeakDo sur ERPNext est encore en cours de validation côté service SpeakDo
et n'est pas annoncée par cette version.

### Ajouté

* Rattachement d'une instance ERPNext au service SpeakDo (bootstrap avec preuve de contrôle de
  l'instance), réparation du rattachement, identité d'installation stable.
* Surface compagnon appelée par le middleware SpeakDo : preuves de rattachement et de réparation,
  vérification d'enrôlement, statut de terminal, capacités utilisateur.
* Enrôlement des utilisateurs par **QR code** temporaire à usage unique, lié à l'utilisateur qui le
  génère.
* **Terminaux par utilisateur**, plusieurs terminaux possibles, révocation individuelle.
* Page **Administration SpeakDo** (`/app/speakdo-admin`) : rattachement de l'instance,
  configuration, diagnostics et vue par utilisateur.
* Page **Mon SpeakDo** (`/app/speakdo-me`) : état personnel, terminaux et QR code de l'utilisateur
  connecté.
* **Capabilities** calculées depuis les permissions ERPNext réelles de l'utilisateur, selon le
  contrat du middleware : Customer / lecture → `thirdparty.read`, Task / création → `task.create`.
* **Profils SpeakDo multiples autorisés** par utilisateur (0 à N), affectés par l'administrateur.
* Récupération du **catalogue des profils** depuis le middleware SpeakDo (alias résolus, profils
  inconnus refusés).
* Transmission de `allowed_profiles` au middleware (vérification d'enrôlement et capacités).
* `permissions_version` : empreinte des capabilities et des profils autorisés, pour la revalidation
  sans ré-enrôlement.
* **Credential API ERPNext par utilisateur** (`erpnext_api_token`), créé par SpeakDo au premier
  enrôlement.
* Partage du credential entre les terminaux d'un même utilisateur.
* Révocation des terminaux ; **révocation du credential au dernier terminal** révoqué ou supprimé.
* Protection contre une **clé API préexistante étrangère** : l'enrôlement est refusé, la clé n'est
  jamais modifiée.
* Réinitialisation et relocation préparées (activées uniquement si le service SpeakDo les autorise).

### Sécurité

* Refus d'enrôler le compte **Administrator**.
* **Isolation par utilisateur** : profils, capabilities, credential et terminaux.
* **Contrôles côté serveur** pour toutes les surfaces (administration réservée au rôle
  *System Manager*, surface personnelle limitée à l'utilisateur connecté).
* Aucune exposition de `api_secret` ni de `erp_credential` dans l'interface ou les journaux.
* Protection contre la **révocation croisée** de terminaux.
* Credentials gérés uniquement lorsqu'ils ont été créés par SpeakDo (preuve de propriété).
* Requêtes signées HMAC avec horodatage, nonce anti-rejeu et comparaison en temps constant.
* Secret technique de l'instance stocké chiffré ; journaux limités à des champs techniques non
  sensibles.

### Compatibilité

* Testé avec Frappe 15.121.1 et ERPNext 15.121.5.

### Licence

* Distribué sous licence GPL-3.0-or-later (fichier `LICENSE`), comme le module SpeakDo pour Dolibarr.
