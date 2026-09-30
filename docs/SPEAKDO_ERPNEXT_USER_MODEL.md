# Modèle utilisateur du compagnon SpeakDo ERPNext

> État au 30/09/2026 — `speakdo_erpnext` 0.1.0. SpeakDo est multi-utilisateur : tout ce qui suit est
> **par utilisateur ERPNext**, sauf le rattachement de l'instance.

```
Instance ERPNext ── rattachement au middleware (tenant, secret HMAC)      ← SpeakDo Settings
│
└── ERPNext User (User.name)
    │
    ├── ERP permissions ──→ capabilities           (calculées à la demande, jamais en cache)
    │
    ├── profils SpeakDo AUTORISÉS [0..N]           ← SpeakDo Allowed Profile (1 ligne / utilisateur × profil)
    │
    ├── credential ERPNext                         ← User.api_key/api_secret + SpeakDo ERP Credential
    │
    └── terminaux [0..N]                           ← SpeakDo Terminal (erp_user)
            ↓
        profil ACTIF = affaire de session / middleware (profile.switch) — non stocké ici
```

**Autorisation d'utiliser un profil ≠ profil actuellement actif.**

- *Profils autorisés* : les modes de travail que l'administrateur autorise à l'utilisateur. Propriété
  de l'**utilisateur**, commune à tous ses terminaux, stockée par le compagnon.
- *Profil actif* : le mode de travail en cours dans SpeakDo. Il relève du **middleware**, qui porte
  l'action sémantique `profile.switch`. Le compagnon ne le stocke pas et ne le fabrique pas.

## Sources de vérité

| Élément | Source de vérité | Stockage compagnon |
|---|---|---|
| Rattachement de l'instance | middleware (tenant) | `SpeakDo Settings` |
| Catalogue des profils | **middleware** : `GET /profiles` (HMAC tenant), alias compris | aucun ; cache Redis de 300 s, aucune liste en dur |
| Profils **autorisés** d'un utilisateur | **compagnon ERP** (décision d'administration) | `SpeakDo Allowed Profile` ; unicité (utilisateur, profil) garantie par la clé primaire (nom = empreinte du couple) |
| Profil **actif** | **middleware / session** (`profile.switch`) | aucun |
| Permissions | ERPNext (`frappe.has_permission`) | aucun |
| Capabilities | dérivées des permissions (`domain/erp_capabilities.py`) | aucun |
| Credential ERP | paire native `User.api_key`/`api_secret` | `SpeakDo ERP Credential` (preuve de propriété, jamais le secret) |
| Terminaux | middleware (émet `terminal_id`) | `SpeakDo Terminal.erp_user` (obligatoire) |

Les profils autorisés ne sont **jamais** déduits des capabilities : l'administrateur peut restreindre
un utilisateur à un sous-ensemble de modes de travail. Les capabilities appartiennent à l'utilisateur
ERPNext, pas à un profil. Changer de profil (autorisé ou actif) ne recalcule pas les permissions et ne
touche **jamais** au credential.

Aucun profil affecté ⇒ ensemble vide, restitué tel quel. Il n'est **jamais** transformé en `generic` ;
la politique de repli appartient au middleware.

### Constat middleware (LAB, 30/09/2026, lectures signées)

- `GET /profiles` renvoie 6 profils : `commercial`, `field.it_technician`, `generic`,
  `ops.site_manager`, `ops.warehouse`, `receptionist`, et l'alias `field.it_support → field.it_technician`.
  Ils exigent des **modules Dolibarr** (`requires.required`).
- `GET /semantic-actions` : l'action `profile.switch` (v1, `requires_confirmation`, entrée
  `profile_id`) « change le mode de travail (profil métier) de l'utilisateur […] ne ferme aucune
  session […] ne fait que remplacer le catalogue d'actions ». Elle précise : « le profil demandé doit
  appartenir aux profils autorisés pour cet utilisateur […] refusé par le serveur ».
- Le contrat compagnon ne connaît qu'un **`profile_id` unique** (et `profile_version`, `profile_scope`,
  `profile_missing_modules`) dans `enrollment_verify` / `user_capabilities`, décrit seulement comme
  « profil métier ». Aucun champ pour un **ensemble** de profils autorisés ; aucune définition
  indiquant s'il s'agit du profil actif, par défaut ou unique autorisé.

## Capabilities (contrat middleware confirmé le 30/09/2026)

| Action SpeakDo | Capability exigée | Permission ERPNext qui l'accorde |
|---|---|---|
| `thirdparty.search` | `thirdparty.read` | Customer / read |
| `project.search` | aucune | — |
| `task.create` | `task.create` | Task / create |
| `task.update` | aucune | — |

Seules `thirdparty.read` et `task.create` sont émises. Rien n'est ajouté pour « débloquer »
`project.search` ou `task.update` : ces actions restent contrôlées par ERPNext à l'exécution, via le
credential de l'utilisateur. Absence de capability ≠ absence de contrôle ERP.

## Ce que le compagnon envoie (sans secret)

| Route | Champs |
|---|---|
| `enrollment_verify` (valide) | `valid`, `user{id, active, display_name}`, `terminal_status`, `capabilities[]`, `channel`, `permissions_version`, **`allowed_profiles[]`**, `credential_type` + `erp_credential` (si émis) |
| `terminal_status` | `status`, `permissions_version` |
| `user_capabilities` | `active`, `capabilities[]`, `permissions_version`, **`allowed_profiles[]`** |

`profile_id` n'est **plus** émis par le compagnon ERPNext : il fabriquerait un profil actif ou
principal. Le profil actif relève du middleware.

`permissions_version` = 16 premiers caractères hexadécimaux de
SHA-256(`"<révision de mapping>|caps=<capabilities triées, sans doublon>|allowed_profiles=<profils triés, sans doublon>"`).
Elle change quand les permissions ERP ou l'ensemble des profils autorisés changent ; ni l'ordre ni les
doublons n'ont d'effet ; le profil actif n'en fait pas partie.

## Surfaces et protections serveur

| Surface | Qui | Profils |
|---|---|---|
| `/app/speakdo-admin` + `api.admin` | System Manager (contrôlé côté serveur) | lecture du catalogue ; affectation de **N** profils par utilisateur (`set_allowed_profiles`, remplacement idempotent, profil inconnu = refus de tout le changement) |
| `/app/speakdo-me` + `api.me` | tout utilisateur du desk | lecture de **ses** profils autorisés uniquement ; « Profil actif : géré par la session SpeakDo » ; aucune méthode d'écriture de profil |
| `api.companion` | middleware (HMAC) | `allowed_profiles` dans `enrollment_verify` et `user_capabilities` (voir contrat ci-dessous) |

## MIDDLEWARE CONTRACT REQUIRED

Émis par le compagnon ERPNext dès maintenant ; à accepter par le prochain chantier middleware.

1. **Nom exact du champ** : `allowed_profiles`.
2. **Format JSON exact** : tableau de chaînes, identifiants **canoniques** du catalogue `GET /profiles`
   (alias déjà résolus), **triés** lexicographiquement, **sans doublon**. Exemple :
   `"allowed_profiles": ["commercial", "field.it_technician", "generic"]`.
3. **Liste vide** : `[]` signifie « aucun profil autorisé par l'administrateur ». Ce n'est jamais
   « tous », jamais `generic`. La politique fonctionnelle (catalogue vide, profil de repli, message)
   appartient au middleware.
4. **`enrollment_verify`** : toujours présent quand `valid = true` (y compris `[]`). Absent des refus
   (`valid = false`).
5. **`user_capabilities`** : toujours présent (y compris `[]`), avec **exactement le même ensemble
   canonique** qu'`enrollment_verify` au même instant. C'est la surface de rafraîchissement à la
   revalidation.
6. **Ancien `profile_id`** : plus émis par le compagnon ERPNext. Le middleware doit le rendre
   optionnel : champ absent + `allowed_profiles` présent ⇒ nouveau modèle ; `profile_id` présent sans
   `allowed_profiles` ⇒ comportement historique inchangé (module Dolibarr, anciens compagnons).
7. **`permissions_version`** : empreinte des capabilities **et** de l'ensemble `allowed_profiles`
   (formule ci-dessus). Toute différence ⇒ relire `user_capabilities` et recalculer
   `profil actif ∈ allowed_profiles`, puis `actions(profil actif) ∩ capabilities ∩ actions supportées par l'ERP`.
   Ce calcul reste dans le middleware.
8. **Alias** : le compagnon résout les alias au moment de l'affectation et n'émet que des identifiants
   canoniques. Le middleware doit aussi résoudre les alias reçus par `profile.switch` (mot de
   l'utilisateur ou alias) avant le test d'appartenance.
9. **Responsabilités** :
   - compagnon = profils **autorisés** (décision de l'administrateur ERPNext, par utilisateur, communs
     à tous ses terminaux) ;
   - middleware/session = profil **actif** (runtime, éventuellement différent par terminal ou par
     session). Le compagnon ne le stocke pas, ne le choisit pas et ne modifie jamais une session.
10. **`profile.switch(X)`** : change uniquement le profil actif de la session/terminal. Accepté
    seulement si `canonical(X) ∈ allowed_profiles` (dernière valeur reçue du compagnon) ; sinon refus
    serveur explicite. Ne modifie jamais `allowed_profiles`. Si une revalidation fait apparaître
    `profil actif ∉ allowed_profiles` (profil retiré par l'administrateur), le middleware applique sa
    politique (repli explicite ou demande de sélection) ; le compagnon ne l'impose pas.

Autres points middleware (inchangés) : évaluation des profils sur des modules Dolibarr pour un tenant
ERPNext (messages PWA) ; ré-enrôlement du LAB après adaptation multi-profils.
