# Compatibilité du compagnon ERPNext avec le middleware SpeakDo (LAB multi-ERP)

> Compagnon : `speakdo_erpnext` 0.1.0 (Frappe/ERPNext v15.121).
> Middleware : instance LAB SpeakDo (URL non publiée), généralisé pour `erp_type = erpnext`
> (bootstrap, repair, enrollment, sessions, revalidation, credentials génériques, `user.id` chaîne).
> Routes du compagnon : `docs/ERPNEXT_COMPANION_ROUTES.md`.
> État au 29/09/2026 : **premier enrôlement réel réussi** (bootstrap → preuve → finalize → QR →
> enrollment_verify → session → revalidation terminal_status + user_capabilities).

## 1. Modèle

| Concept interne | Valeur | Sur le fil |
|---|---|---|
| `erp_type` | `erpnext` | `erp_type` (bootstrap/start) |
| `erp_base_url` | racine réelle ERPNext, sans chemin (`SpeakDo Settings.instance_url`) | `dolibarr_base_url` (nom historique conservé par le middleware) |
| `companion_base_url` | `{erp_base_url}/api/method/speakdo_erpnext.api.companion` (dérivée, jamais configurée) | `companion_base_url` |
| `installation_id` | UUID v4 stable | `installation_id` |
| `tenant_uuid` | reçu du middleware | `tenant_id` (bootstrap finalize, QR) / `tenant_uuid` (repair) |
| `hmac_secret` | chiffré (`__Auth`) | `dolibarr_hmac_secret` (lu aussi `erp_hmac_secret` si présent) |
| `erp_user_id` | `User.name` (ex. `jane@example.fr`) | `user.id` |
| `erp_credential` | **aucun émis** (voir §4) | — (jamais de `dolibarr_apikey`) |

Les noms `dolibarr_*` n'existent que dans `adapters/middleware_legacy.py` (test
`test_no_dolibarr_naming_outside_the_adapter`). Aucun préfixe n'est ajouté à `erp_base_url`.

## 2. Analyse par élément

| Élément | Fonctionne tel quel | Adaptation compagnon | Modification middleware nécessaire | Impact | Proposition minimale |
|---|---|---|---|---|---|
| bootstrap/start `{installation_id, erp_type, dolibarr_base_url, companion_base_url}` | **Oui (LAB réel, 201)** | noms historiques confinés à l'adaptateur | Non | — | renommer `dolibarr_base_url` → `erp_base_url` (double lecture) |
| bootstrap_proof (GET, invité) | **Oui (LAB réel)** | méthode whitelistée renvoyant du JSON brut | Non | — | — |
| bootstrap/finalize → `tenant_id` + `dolibarr_hmac_secret` | **Oui (LAB réel, new_installation)** | secret chiffré, jamais renvoyé au navigateur | Non | — | émettre `erp_hmac_secret` / `tenant_uuid` |
| QR + enrollment token | **Oui (LAB réel)** | token local 43 car., SHA-256 seul stocké, TTL 600 s, usage unique | Non | — | — |
| enrollment_verify (POST, HMAC) | **Oui (LAB réel, 201 côté PWA)** | REQUEST_TARGET = chemin + query brute (voir §3) | Non (convention figée) | — | — |
| `user.id` = `User.name` e-mail | **Oui (LAB réel, `User.name` e-mail réel conservé dans enrollment et resume)** | aucun ID numérique | Non | — | — |
| sessions/resume → terminal_status + user_capabilities | **Oui (LAB réel, 201, deux appels HMAC 200)** | — | Non | — | — |
| `display_name` dans la réponse `sessions/resume` | Non (`null` côté middleware alors que le compagnon a renvoyé `"Imhof"` à l'enrôlement) | — | Oui (cosmétique) | nom absent dans la PWA après reprise | conserver `display_name` du terminal/utilisateur |
| repair (start/proof/finalize) | Testé localement (faux middleware conforme) | secret remplacé, ancien refusé | Non (à confirmer en réel) | — | — |
| relocation | Non (refusée par le middleware pour ERPNext) | jamais appelée ; UI « indisponible » ; `relocation_proof` exposée | Oui (futur) | changement d'URL ERP impossible | — |
| reset | Non vérifié (feature gate) | `404 not_found` ⇒ indisponible, rien effacé | — | — | — |
| action | Refusée | endpoint HMAC renvoyant `424 erp_connector_unavailable` | connecteur ERPNext (hors périmètre) | aucune action métier | — |
| credential `erpnext_api_token` | Absence acceptée | aucun credential émis | Oui (décision + nom de champ sur le fil) | connecteur futur sans accès ERP | voir §4 |

## 3. Convention HMAC (figée le 30/09/2026)

Chaîne canonique : `METHOD \n REQUEST_TARGET \n TIMESTAMP \n NONCE \n SHA256_HEX(BODY_RAW)`, où
REQUEST_TARGET = chemin + query brute exactement telle qu'envoyée (ex.
`/api/method/speakdo_erpnext.api.companion.terminal_status?terminal_uuid=abc`). Le middleware LAB
applique cette convention dans les deux sens ; le compagnon n'accepte plus que cette forme (la
tolérance « chemin seul », ajoutée le 29/09 après la divergence constatée, est supprimée).

## 4. Credential ERPNext (`erpnext_api_token`) — décision requise, rien n'est généré

Mécanisme natif Frappe v15 (`frappe.core.doctype.user.user.generate_keys`, `frappe.auth.validate_api_key_secret`) :

- **une seule paire par utilisateur** (`User.api_key` + `User.api_secret`, secret chiffré dans `__Auth`) ;
- `generate_keys` réservé au System Manager ; il conserve `api_key` s'il existe et **régénère
  `api_secret`**, ce qui casse toute autre intégration utilisant déjà la clé de cet utilisateur ;
- le jeton `Authorization: token <api_key>:<api_secret>` porte **tous les droits** de l'utilisateur
  (aucune portée, aucune expiration) ;
- révocation = régénérer le secret ou vider `api_key` (pas de révocation par terminal).

Questions à trancher avant toute génération automatique : un jeton par utilisateur ou un utilisateur
technique dédié ; que faire si l'utilisateur a déjà une clé ; révocation lors de la révocation d'un
terminal ; nom exact du champ credential dans la réponse `enrollment_verify` (non fourni).
`domain/erp_credentials.py` renvoie `None` ; l'adaptateur ne sérialise aucun credential.

## 5. Contraintes d'environnement (LAB)

- `erp_base_url` LAB = `http://<ip-publique-de-l-hote>:8080` (IP publique de l'hôte Docker ; nginx impose le
  site `erpnext.local` quel que soit l'hôte). HTTP en clair : acceptable en LAB seulement.
- `middleware_url` LAB corrigée vers la racine du middleware LAB (la valeur `…/api`
  produisait `/api/api/v1/…` → 404).
- Le token d'enrôlement apparaît dans les journaux d'accès nginx (`docker logs frappe-frontend-1`,
  constaté) et, si `enable_frappe_logger` est actif, dans `frappe.web.log`. Il est à usage unique et
  consommé à ce moment-là.
- Le logger Frappe est à `ERROR` hors serveur de développement : le compagnon force `INFO` sur son
  seul logger `speakdo` (champs techniques whitelistés uniquement).
- `frappe_docker` : le service `configurator` régénère `sites/apps.txt` sans le montage
  `speakdo_erpnext` ; ajouter le bind-mount au `configurator`.
