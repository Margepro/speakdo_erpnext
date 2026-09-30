# Routes réelles du compagnon ERPNext (`speakdo_erpnext`)

Valeurs à reporter dans `resources/erp/companion_routes.v1.json` côté middleware (entrée
`erpnext`). Le schéma de ce fichier n'est pas connu du compagnon : seules les **valeurs**
ci-dessous sont garanties.

Vérifié dans Frappe v15.121 (`frappe/api/v1.py`, `frappe/handler.py`) et par des requêtes HTTP
réelles (`tests/test_http_live.py`, gunicorn + nginx) :

- `/api/method/<chemin.python>` → `handle_rpc_call` → `execute_cmd` ; la fonction doit être
  `@frappe.whitelist` ; `allow_guest=True` pour être appelable sans session ; méthode HTTP
  hors liste ⇒ **403** ;
- une fonction qui renvoie un `werkzeug.Response` est transmise telle quelle : les réponses
  sont du **JSON brut** (pas d'enveloppe Frappe `{"message": …}`), `Cache-Control: no-store` ;
- paramètres lus **uniquement dans la query string** (`request.args`) : Frappe fusionne les clés
  du corps JSON dans `form_dict`, un corps ne peut donc pas écraser un paramètre ;
- `xss_safe=True` : Frappe ne réécrit pas les entrées invité (validées strictement, jamais
  rendues en HTML).

## companion_base_url

```
companion_base_url = {erp_base_url}/api/method/speakdo_erpnext.api.companion
```

- même hôte et même port que `erp_base_url` (dérivé, jamais configuré) ; chemin commençant par
  `/api/method/` ; `erp_base_url` est la racine ERPNext sans chemin.
- URL d'un appel = `{companion_base_url}.{fonction}?{query}`.
- **REQUEST_TARGET signé HMAC** = chemin + query brute, exactement tels qu'envoyés (ordre,
  encodage percent-encoded, paramètres répétés ou vides conservés ; aucune reconstruction) :
  `/api/method/speakdo_erpnext.api.companion.{fonction}?{query}`. C'est la **seule** forme
  acceptée : une signature sur le chemin seul est refusée dès que la requête porte une query.
  Le compagnon lit la cible dans `RAW_URI` / `REQUEST_URI` (nginx la transmet inchangée) ; si
  elle est absente, la requête est refusée.

## Table

```
bootstrap_proof =
  method: GET
  path: /api/method/speakdo_erpnext.api.companion.bootstrap_proof
  query: id={bootstrap_id}
  python_function: speakdo_erpnext.api.companion.bootstrap_proof
  allow_guest: true
  hmac_required: false
  response 200: {"bootstrap_id","installation_id","challenge","companion_version","protocol_version":1}
  response 404: {"ok":false,"error":{"code":"not_found"}}   (inconnu, expiré, autre flux, déjà finalisé)

repair_proof =
  method: GET
  path: /api/method/speakdo_erpnext.api.companion.repair_proof
  query: id={repair_id}
  python_function: speakdo_erpnext.api.companion.repair_proof
  allow_guest: true
  hmac_required: false
  response 200: {"repair_id","installation_id","challenge"}
  response 404: not_found

relocation_proof =
  method: GET
  path: /api/method/speakdo_erpnext.api.companion.relocation_proof
  query: id={relocation_id}
  python_function: speakdo_erpnext.api.companion.relocation_proof
  allow_guest: true
  hmac_required: false
  response 200: {"relocation_id","installation_id","new_base_url","challenge"}
  note: préparée ; le compagnon ne lance jamais de relocation ERPNext (refusée par le middleware)

enrollment_verify =
  method: POST
  path: /api/method/speakdo_erpnext.api.companion.enrollment_verify
  query: token={enrollment_token}
  body: {"consume":true,"terminal":{"terminal_id","label","public_key_pem","public_key_fingerprint"}}
  python_function: speakdo_erpnext.api.companion.enrollment_verify
  allow_guest: true (niveau Frappe)
  hmac_required: true
  response 200 valid: {"valid":true,"user":{"id":"<User.name>","active":true,"display_name"},
                       "terminal_status":"active","capabilities":[],"channel":"pwa","permissions_version":"1"}
  response 200 refus: {"valid":false,"error":{"code":"enrollment_token_invalid|enrollment_token_expired|
                       enrollment_token_consumed|terminal_already_enrolled|user_not_found"}}
  aucun credential ERP n'est renvoyé (voir « Credential »)

terminal_status =
  method: GET
  path: /api/method/speakdo_erpnext.api.companion.terminal_status
  query: terminal_uuid={terminal_uuid}
  python_function: speakdo_erpnext.api.companion.terminal_status
  allow_guest: true (niveau Frappe)
  hmac_required: true
  response 200: {"status":"active|pending_approval|revoked","permissions_version":"1"}
                (terminal inconnu ou utilisateur désactivé ⇒ "revoked")

user_capabilities =
  method: GET
  path: /api/method/speakdo_erpnext.api.companion.user_capabilities
  query: user={erp_user_id}          (User.name, ex. jane@example.fr ; encodé %40 dans la query)
  python_function: speakdo_erpnext.api.companion.user_capabilities
  allow_guest: true (niveau Frappe)
  hmac_required: true
  response 200: {"active":true|false,"capabilities":[],"permissions_version":"1"}

action =
  method: POST
  path: /api/method/speakdo_erpnext.api.companion.action
  query: action_id={action_id}
  python_function: speakdo_erpnext.api.companion.action
  allow_guest: true (niveau Frappe)
  hmac_required: true
  response 424: {"ok":false,"error":{"code":"erp_connector_unavailable"}}   (jamais d'exécution métier)
```

Erreurs communes des routes HMAC : `401 {"ok":false,"error":{"code":…}}` avec
`tenant_signature_missing`, `invalid_tenant_timestamp`, `tenant_timestamp_expired` (±300 s),
`invalid_tenant_nonce`, `invalid_tenant_signature`, `tenant_replay_detected` (nonce conservé
600 s en base, partagé entre workers) ; `400 invalid_json` ; `422 invalid_terminal_*` ;
`413 payload_too_large` (> 64 Kio). Méthode HTTP incorrecte : `403` (Frappe).

## Gabarits équivalents (forme « template »)

| Clé | Méthode | Gabarit |
|---|---|---|
| bootstrap_proof | GET | `{companion_base_url}.bootstrap_proof?id={bootstrap_id}` |
| repair_proof | GET | `{companion_base_url}.repair_proof?id={repair_id}` |
| relocation_proof | GET | `{companion_base_url}.relocation_proof?id={relocation_id}` |
| enrollment_verify | POST | `{companion_base_url}.enrollment_verify?token={token}` |
| terminal_status | GET | `{companion_base_url}.terminal_status?terminal_uuid={terminal_uuid}` |
| user_capabilities | GET | `{companion_base_url}.user_capabilities?user={erp_user_id}` |
| action | POST | `{companion_base_url}.action?action_id={action_id}` |

Ces gabarits sont identiques aux gabarits provisoires annoncés par le middleware. **Confirmé en
réel sur le LAB** (29/09/2026) pour `bootstrap_proof`, `enrollment_verify`, `terminal_status` et
`user_capabilities`. `repair_proof`, `relocation_proof` et `action` sont vérifiés en local
(tests Frappe + HTTP réel gunicorn) mais pas encore appelés par le middleware LAB.

## Point de sécurité à connaître

Les identifiants (`id`, `token`, `terminal_uuid`, `user`, `action_id`) passent en query string ;
elle fait partie du REQUEST_TARGET signé : toute modification, suppression, ajout ou réordonnancement
d'un paramètre invalide la signature. Le `token` apparaît aussi dans les journaux d'accès
nginx (`docker logs frappe-frontend-1`, constaté) / gunicorn et, si `enable_frappe_logger` est actif, dans le journal `frappe.web`
(`full_path`) ; il est à usage unique et déjà consommé à ce moment-là.
