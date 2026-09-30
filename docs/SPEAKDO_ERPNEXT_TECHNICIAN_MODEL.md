# Modèle « intervention terrain » SpeakDo dans ERPNext v15

> Audit fonctionnel et technique, 30/09/2026. Aucun code, aucun Custom Field, aucun DocType créé ;
> middleware, compagnon et mapping non modifiés.
>
> **Source de vérité** : métadonnées live du LAB `erpnext.local` — Frappe 15.121.1, ERPNext 15.121.5,
> erpnext_france 15.0.7 — lues par `frappe.get_meta()`, et contrôleurs Python d'ERPNext installés
> (`maintenance_visit.py`, `maintenance_schedule.py`, `warranty_claim.py`, `task.py`, `issue.py`,
> `timesheet.py`, `sales_order.py`, `hooks.py`). Le site n'a **aucun** Custom Field, Property Setter
> ni Workflow sur les DocTypes étudiés : tout ce qui suit est le standard ERPNext v15.
> Le site ne contient pas de données métier (0 Task, 0 Issue, 0 Maintenance Visit) : les comportements
> sont établis par les métadonnées et le code, pas par des essais de création.
>
> Preuve brute : `docs/evidence/erpnext_v15_meta_dump.txt` (champs, types, options, obligatoires).
>
> Notation : **REQD** = obligatoire à l'enregistrement ; **RO** = lecture seule ; **S** = DocType
> soumissible (Draft → Submitted → Cancelled, figé après soumission sauf champs `allow_on_submit`).

---

## 1. Résumé exécutif

ERPNext n'a **pas** d'objet unique équivalent à l'intervention Dolibarr (Fichinter). Le concept est
réparti, et l'audit montre que les DocTypes candidats n'ont pas le même rôle :

| DocType | Ce qu'il est réellement dans ERPNext v15 |
|---|---|
| **Maintenance Visit** (S) | le **compte rendu d'une visite effectuée** : `completion_status` (Partially/Fully Completed) est obligatoire dès la création, chaque ligne exige un `work_done` et un technicien de type **Sales Person**. Ni heure de fin, ni durée, ni lien Issue, Task, Timesheet ou facture. |
| **Task** | l'objet **de planification et d'assignation** : statut, priorité, dates prévues (Date seulement), lien `issue` et `project`, temps réel et coûts agrégés depuis les Timesheets. **Pas de champ client** (le client vient du Project ou de l'Issue). |
| **Timesheet** (S) | le **temps passé** (lignes `from_time`/`to_time` Datetime, `hours`, `activity_type`, `is_billable`, taux) et le **seul chemin natif de facturation au temps** (`make_sales_invoice`). Ne se rattache qu'à une Task ou un Project. |
| **Issue** | le **ticket** (client, contact, priorité, SLA, résolution). Création native d'une Task depuis l'Issue (`make_task`) ; aucun lien natif vers Maintenance Visit. |
| **Maintenance Schedule** (S) | le **plan de maintenance récurrent** par article (Item obligatoire) : génère les dates, crée des Events, et produit des Maintenance Visits (`make_maintenance_visit`). |
| **Asset / Asset Maintenance** | la maintenance des **immobilisations de l'entreprise** (comptabilité, amortissements, `location` obligatoire, équipe de maintenance obligatoire) : non adapté au parc des clients d'un MSP. |
| **Warranty Claim** | le « ticket de SAV » natif du module Maintenance : c'est le seul document que Maintenance Visit met à jour à sa soumission (statut, résolution). |

**Décision : C — modèle polymorphe.**
- La **Task** porte le cycle de vie opérationnel : planifier, assigner, suivre, clôturer, rattacher au temps et à la facturation.
- La **Maintenance Visit** porte le **compte rendu de visite sur site** lorsqu'il faut un document client figé (contrat de maintenance, équipement suivi, garantie).
- Le **Timesheet** porte le temps et la facturation au temps.
- L'**Issue** est la source (ticket).
- Le **Maintenance Schedule** porte la récurrence contractuelle.

Aucun de ces DocTypes seul ne couvre les dix cas terrain. Un DocType SpeakDo spécifique n'est pas justifié pour le premier connecteur. Il pourrait l'être plus tard pour **un seul manque réel** : les équipements appartenant au client (§7).

---

## 2. Comparaison des DocTypes (métadonnées réelles)

### 2.1 Maintenance Visit (module Maintenance, S, `MAT-MVS-.YYYY.-`)

| Besoin | Champ réel | Constat |
|---|---|---|
| client | `customer` Link Customer **REQD** | + `contact_person`, `customer_address`, `territory` |
| date/heure | `mntc_date` Date **REQD** (défaut Today), `mntc_time` Time | pas de fin, pas de durée |
| technicien | `purposes[].service_person` Link **Sales Person** **REQD** | Sales Person → `employee` → `user_id` : chaîne à 3 niveaux, pas un User |
| statut | `completion_status` **REQD** (`Partially Completed` \| `Fully Completed`), `status` RO (Draft/Submitted/Cancelled) | pas de statut « planifié / à faire » |
| type | `maintenance_type` **REQD** (`Scheduled` \| `Unscheduled` \| `Breakdown`, défaut Unscheduled) | |
| description / travail effectué | `purposes[].description` (Text Editor), `purposes[].work_done` Small Text **REQD** | au moins une ligne `purposes` exigée par `validate_purpose_table()` |
| Item | `purposes[].item_code` Link Item, **optionnel** | utilisable sans Item |
| Serial No | `purposes[].serial_no` Link Serial No (validé s'il est renseigné) | |
| Sales Order | aucun champ ; `prevdoc_doctype`/`prevdoc_docname` (cachés) par ligne | rempli seulement par `sales_order.make_maintenance_visit` ; utilisable **sans** Sales Order |
| feedback | `customer_feedback` Small Text | |
| planification | `maintenance_schedule` / `maintenance_schedule_detail` | contrôle de date dans la période du plan |

Hooks : `on_submit` met à jour la Warranty Claim liée (statut Closed ou Work In Progress,
`resolution_details` = `work_done`) et la ligne du Maintenance Schedule (`completion_status`,
`actual_date`). `on_cancel` refuse l'annulation si une visite plus récente existe pour la même source.

Flux de création natifs : depuis Sales Order (soumis), Maintenance Schedule, Warranty Claim.
Rôle : **Maintenance User** (lecture, écriture, création, soumission).

Pertinence MSP : bonne pour le **compte rendu** d'un déplacement (texte du travail effectué, retour
client, document figé). Mauvaise comme objet de planification : une visite future doit déjà déclarer
un `completion_status`. Temps, facturation et ticket sont hors de l'objet.

### 2.2 Maintenance Schedule (S, `MAT-MSH-.YYYY.-`)

- **REQD** : `transaction_date`, `company`, `items` (au moins une ligne). `customer` est optionnel.
- Chaque ligne `items` : `item_code` **REQD**, `start_date`/`end_date` **REQD**, `no_of_visits` **REQD**, `periodicity` (Weekly/Monthly/**Quarterly**/Half Yearly/Yearly/Random), `sales_person`, `sales_order` (RO), `serial_and_batch_bundle`.
- `generate_schedule()` remplit `schedules` : une ligne par date, avec `scheduled_date`, `completion_status` (Pending/Partially/Fully Completed, modifiable après soumission) et `actual_date`.
- `on_submit` : exige les dates générées et crée un **Event** par date prévue, à 10:00, propriétaire = l'utilisateur du Sales Person. Il met aussi à jour la date AMC des Serial No.
- Visite : `make_maintenance_visit(source_name, item_name, s_id)` produit une Maintenance Visit pré-remplie.
- Rôle : **Maintenance Manager** uniquement.

### 2.3 Task (module Projects, `TASK-.YYYY.-.#####`, non soumissible)

| Besoin | Champ réel |
|---|---|
| titre | `subject` Data **REQD** (seul champ obligatoire) |
| projet / ticket | `project` Link Project ; `issue` Link Issue |
| client | **aucun champ** (le code `get_customer_details` est un reliquat) ; déduit de `project.customer` ou `issue.customer` |
| dates | `exp_start_date`, `exp_end_date` en **Date** uniquement, pas d'heure ; `act_start_date`/`act_end_date` RO (calculés depuis les Timesheets) |
| statut | `status` : Open \| Working \| Pending Review \| Overdue \| Template \| Completed \| Cancelled ; `completed_on` requis si Completed ; `completed_by` |
| priorité | `priority` : Low \| Medium \| High \| Urgent |
| assignation | pas de champ : assignation Frappe (`_assign` / ToDo `allocated_to`), fermée automatiquement à la complétion |
| progression | `progress` Percent, `expected_time`, `actual_time` RO |
| description | `description` Text Editor |
| type | `type` Link Task Type |
| coûts / facturation | `total_costing_amount`, `total_billing_amount` RO (agrégés depuis les Timesheets soumis) |

Automatismes :
- `set_tasks_as_overdue` (tâche planifiée quotidienne) ;
- une Task Open passe à Working au premier Timesheet ;
- dépendances (`depends_on`) ;
- mise à jour du Project.

Flux : `issue.make_task`, `task.make_timesheet`. Rôle : **Projects User**. Pas d'Auto Repeat (`allow_auto_repeat = 0`).

### 2.4 Issue (module Support, `ISS-.YYYY.-`)

- **REQD** : `subject`.
- Champs : `customer`, `contact`, `raised_by` (e-mail), `lead`, `project`.
- `status` : Open \| Replied \| On Hold \| Resolved \| Closed.
- `priority` Link Issue Priority, `issue_type`.
- SLA : `service_level_agreement`, `response_by`, `sla_resolution_by`, `agreement_status`, temps de réponse et de résolution.
- `resolution_details`, `description`.
- Automatismes : `auto_close_tickets` (quotidien), calcul SLA, création depuis e-mail (`make_issue_from_communication`), `split_issue`, `make_task`.
- Lien vers Task : c'est la Task qui porte le lien (`Task.issue`).
- Rôle : **Support Team**.

Excellent déclencheur d'intervention. Pas conçu pour porter le compte rendu terrain ni le temps.

### 2.5 Timesheet (module Projects, S, `TS-.YYYY.-`)

- Entête :
  - `employee` Link Employee (optionnel) ;
  - `customer`, `parent_project`, `company` ;
  - `status` RO : Draft \| Submitted \| Partially Billed \| Billed \| Payslip \| Completed \| Cancelled ;
  - totaux RO (heures, facturable, facturé, coût, `per_billed`) ;
  - `sales_invoice`, `note`.
- `time_logs` (**REQD**, Timesheet Detail) :
  - `activity_type`, `from_time`/`to_time` **Datetime**, `hours`, `description` ;
  - `project`, `task` ;
  - `is_billable`, `billing_hours`, `billing_rate`/`billing_amount`, `costing_rate`/`costing_amount` ;
  - `sales_invoice` (RO).
- Validations : `from_time`/`to_time` obligatoires, `hours` > 0, **`activity_type` obligatoire si `employee` est renseigné**, contrôle de chevauchement, ligne de Project cohérente.
- Tarifs : Activity Type (`billing_rate`, `costing_rate`), surchargeables par employé (Activity Cost).
- Hooks : `on_submit` met à jour les temps et coûts de la Task et du Project.
- Facturation : `make_sales_invoice(source_name, item_code, customer)` alimente la table `timesheets` de la Sales Invoice. Le statut passe à Partially Billed puis Billed.
- Rôles : Projects User, Accounts User, HR User (rwcs) ; **Employee** (rwc, sans soumission).
- **Aucun lien** vers Maintenance Visit ni vers Issue.

### 2.6 Asset / Asset Maintenance / Asset Maintenance Log (module Assets)

- **Asset** (S) exige :
  - `item_code` (article immobilisable), `location`, `company`, `asset_name` ;
  - `asset_owner` (Company \| Supplier \| Customer) et `customer`, si le propriétaire est Customer ;
  - toute la mécanique d'amortissement et d'écritures comptables (`make_post_gl_entry`).

  C'est une **immobilisation comptable de l'entreprise**.
- **Asset Maintenance** (nommé par l'Asset) :
  - REQD : `asset_name`, `company`, **`maintenance_team`** (Asset Maintenance Team), `asset_maintenance_tasks` ;
  - chaque ligne `maintenance_task` : `periodicity` Daily…3 Yearly, `assign_to` Link **User**, `next_due_date`, `maintenance_status` Planned \| Overdue \| Cancelled.
- **Asset Maintenance Log** (S) :
  - `maintenance_status` Planned \| Completed \| Cancelled \| Overdue ;
  - `completion_date`, `actions_performed` (modifiable après soumission) ;
  - rôle **Manufacturing User**.

Limites MSP multi-client : ces DocTypes supposent des biens inscrits à l'actif de l'entreprise. Les utiliser pour le parc d'un client fausserait la comptabilité, et la notion de client n'y est que secondaire.

### 2.7 Serial No, Item, Event, Warranty Claim

- **Serial No** :
  - `serial_no` et `item_code` **REQD**, `company` **REQD** ;
  - **`customer` RO**, `status` RO (Active/Inactive/Consumed/Delivered/Expired), renseignés par les mouvements de stock (livraison) ;
  - `warranty_expiry_date`, `amc_expiry_date` ;
  - `maintenance_status` RO, recalculé par une tâche quotidienne.

  Pertinent pour le **matériel vendu et livré** par l'entreprise.
- **Item** : un catalogue (par défaut `is_stock_item = 1`). Un Item de service suffit à la facturation.
- **Event** : `starts_on`/`ends_on` **Datetime**, `event_participants`, `reference_doctype`/`reference_docname`, récurrence native (`repeat_this_event`, `repeat_on`, `repeat_till`). C'est le seul objet natif qui porte une **heure de rendez-vous** et une plage horaire.
- **Warranty Claim** : `customer` **REQD**, `complaint` **REQD**, `serial_no`, `status` Open \| Work In Progress \| Closed \| Cancelled, `resolution_*`. Elle produit des Maintenance Visits. C'est un « ticket SAV matériel », parallèle à Issue et non relié à elle.

---

## 3. Matrice des cas métiers

Légende : ✅ adapté · 🟡 partiellement · ❌ non adapté.

| Cas | Maintenance Visit | Task | Issue | Timesheet | Asset Maintenance | Recommandation |
|---|---|---|---|---|---|---|
| **A** Dépannage ponctuel « demain 14h chez Dupont » | 🟡 impose un `completion_status` avant la visite ; bon pour le compte rendu | 🟡 statut, assignation ; pas de client ni d'heure | 🟡 porte le client, pas la planification | ❌ temps après coup | ❌ | **Task** (client via Issue ou Project) + **Event** pour 14:00 ; Maintenance Visit au compte rendu |
| **B** Maintenance annuelle planifiée | 🟡 visite générée par le plan | 🟡 sans récurrence ni contrat | ❌ | ❌ | 🟡 seulement pour un bien de l'entreprise | **Maintenance Schedule** (Yearly) → Maintenance Visit |
| **C** Intervention issue d'un ticket | ❌ aucun lien Issue (Warranty Claim seulement) | ✅ `Task.issue`, `issue.make_task` | ✅ source | ❌ | ❌ | **Issue → Task** (`make_task`) |
| **D** Tâche technique sans déplacement | ❌ la notion de visite est hors sujet | ✅ | 🟡 si demandée par ticket | 🟡 pour le temps | ❌ | **Task** |
| **E** Compte rendu « disque remplacé, tests OK » | ✅ `work_done`, `customer_feedback`, soumission | 🟡 `description` ou commentaire, non figé | 🟡 `resolution_details` | 🟡 `description` de ligne | 🟡 `actions_performed` | **Maintenance Visit** pour une visite client ; sinon commentaire et clôture de Task |
| **F** « 1h30 chez Dupont » | ❌ aucun champ de durée | 🟡 agrège `actual_time` depuis les Timesheets | ❌ | ✅ | ❌ | **Timesheet** (ligne liée à la Task) |
| **G** Équipement « Fortigate FGT-123 » | ✅ `serial_no` par ligne | ❌ pas de champ équipement | ❌ | ❌ | 🟡 seulement pour un bien de l'entreprise | **Serial No** sur la Maintenance Visit (matériel vendu) ; manque pour le parc client (§7) |
| **H** Tous les 3 mois | 🟡 produit par le plan | ❌ pas d'Auto Repeat | ❌ | ❌ | 🟡 bien de l'entreprise | **Maintenance Schedule** (Quarterly) |
| **I** Facturer 2 h | ❌ aucun lien de facture | 🟡 montants agrégés | ❌ | ✅ `make_sales_invoice` | ❌ | **Timesheet → Sales Invoice** |
| **J** Intervention dans le projet X | ❌ pas de champ Project | ✅ `project` | 🟡 `project` | ✅ `project` | ❌ | **Task** (+ Timesheet) |

---

## 4. Modèle canonique « intervention » proposé

Indépendant de Dolibarr. Seuls les champs justifiés par au moins un cas (A–J) sont retenus. Colonnes :
**Opt.** = obligatoire (O) ou optionnel (o) ; **Task / Visit / Plan** = source ERPNext selon la
variante (§5). Mentions : *dérivé* = calculé depuis un autre objet ; *absent* = impossible sans
Custom Field.

| Champ canonique | Opt. | Cas | Task | Visit (Maintenance Visit) | Plan (Maintenance Schedule) |
|---|---|---|---|---|---|
| `id` | O | tous | `name` | `name` | `name` |
| `kind` | O | tous | `task` | `visit` | `maintenance_plan` |
| `customer` | O pour visit/plan, o pour task | A B C E G H | *dérivé* : `project.customer` sinon `issue.customer` ; **absent** si ni l'un ni l'autre | `customer` (REQD) | `customer` |
| `contact` | o | A C | *dérivé* : `issue.contact` | `contact_person` | `contact_person` |
| `subject` | O | tous | `subject` (REQD) | *dérivé* : `customer_name` + `maintenance_type` (pas de champ sujet) | *dérivé* : `items[].item_name` |
| `description` | o | A C D | `description` | `purposes[].description` | `items[].description` (RO) |
| `scheduled_start` | o | A B H | `exp_start_date` (**Date**) ; heure : Event lié (`starts_on`) | `mntc_date` + `mntc_time` | `items[].start_date` |
| `scheduled_end` | o | A | `exp_end_date` (Date) ; Event `ends_on` | **absent** | `items[].end_date` (fin de contrat, pas de visite) |
| `assigned_to` | o | A D | assignation Frappe (`_assign` / ToDo `allocated_to`, User) | `purposes[].service_person` (**Sales Person**, REQD) | `items[].sales_person` |
| `status` | O | tous | `status` (7 valeurs) | `completion_status` + `docstatus` | `status` + `schedules[].completion_status` |
| `priority` | o | A C | `priority` | **absent** | **absent** |
| `work_done` | o (O pour clôturer une visit) | E | *dérivé* : commentaire ou description (non structuré) | `purposes[].work_done` (REQD) | — |
| `duration` | o | F I | *dérivé* : `actual_time` (somme des Timesheets) | **absent** (Timesheet impossible à lier) | — |
| `equipment` | o | G | **absent** | `purposes[].serial_no` / `item_code` | `items[].item_code` (+ numéros de série) |
| `source_ticket` | o | C | `issue` | *indirect* : Warranty Claim (`prevdoc_*`) ; **absent** pour Issue | — |
| `project` | o | J | `project` | **absent** | — |
| `billable` | o | I | *dérivé* : Timesheet `time_logs[].is_billable` | **absent** | — |
| `billing_reference` | o | I | *dérivé* : Timesheet `sales_invoice` | **absent** | *indirect* : `items[].sales_order` |
| `recurrence_rule` | o | H | **absent** | — | `items[].periodicity` + `no_of_visits` + `start_date`/`end_date` |
| `created_at` / `updated_at` | O | — | `creation` / `modified` | idem | idem |

Écarts à la liste proposée par le mandat :
- `recurring` n'est pas retenu : il est redondant avec `kind = maintenance_plan`.
- `thirdparty` est renommé `customer` : ERPNext distingue Customer, Lead et Supplier, et seul Customer est pertinent ici.

Sous-objet `time_entries[]`, pour le temps (cas F et I). Il est porté par Timesheet et **toujours
lié à une Task** :

| Champ | Source réelle |
|---|---|
| `erp_user_id` | Timesheet `user` / `employee.user_id` |
| `start` / `end` | `time_logs[].from_time` / `to_time` (Datetime) |
| `hours` | `time_logs[].hours` |
| `activity` | `time_logs[].activity_type` |
| `note` | `time_logs[].description` |
| `billable` | `time_logs[].is_billable` |
| `billed_by` | `time_logs[].sales_invoice` |

---

## 5. Mapping ERPNext recommandé

Variantes retenues après l'audit : **trois**. `issue_followup`, `remote_work` et
`recurring_maintenance` ne sont pas des variantes. Ce sont respectivement une Task avec
`source_ticket`, une Task sans visite, et un plan.

```
intervention(kind=task)                          ← cas A, C, D, F, I, J (pivot opérationnel)
  → Task
  → secondaires : Issue (source), Project (client, facturation), Event (rendez-vous horaire),
                  Timesheet (temps, facturation), ToDo (assignation)
  → relations   : Task.issue, Task.project, Event.reference_doctype/docname = Task,
                  Timesheet.time_logs[].task = Task

intervention(kind=visit)                         ← cas A (compte rendu), E, G
  → Maintenance Visit (soumise = compte rendu figé)
  → secondaires : Customer, Contact, Sales Person (technicien), Serial No / Item,
                  Maintenance Schedule ou Warranty Claim (source), Task (si déjà planifiée)
  → relations   : purposes[].serial_no, maintenance_schedule(_detail), purposes[].prevdoc_*
                  lien Task ↔ Visit : **absent nativement** (voir §11)

intervention(kind=maintenance_plan)              ← cas B, H
  → Maintenance Schedule (soumis)
  → secondaires : Item (REQD), Serial No, Sales Person, Sales Order, Event (généré),
                  Maintenance Visit (produite par make_maintenance_visit)
```

### Opérations par variante (§8 du mandat)

| Opération | task (Task) | visit (Maintenance Visit) | maintenance_plan (Maintenance Schedule) |
|---|---|---|---|
| lire | ✅ natif | ✅ natif | ✅ natif |
| créer | ✅ (`subject` seul) ; depuis un ticket : `issue.make_task` | ✅ mais exige `customer`, `company`, `completion_status`, `maintenance_type` et une ligne avec `service_person` + `work_done` : c'est une création **après** la visite | 🟡 exige un Item par ligne, des dates, `no_of_visits`, `generate_schedule`, puis la soumission ; rôle Maintenance Manager |
| modifier | ✅ | 🟡 en brouillon seulement (après soumission : amendement) | 🟡 idem |
| clôturer | ✅ `status = Completed` (+ `completed_on`) | ✅ soumission avec `completion_status = Fully Completed` | 🟡 annulation ou fin de période |
| compte rendu | 🟡 commentaire ou description (non structuré, non figé) | ✅ `work_done`, `customer_feedback` | — |
| ajouter du temps | ✅ Timesheet (`task`) | ❌ natif (seulement via une Task liée, **Custom Field** nécessaire) | — |
| facturer | ✅ Timesheet → Sales Invoice | ❌ natif (Sales Invoice manuelle, sans lien) | 🟡 via le Sales Order d'origine |
| rattacher un ticket | ✅ `issue` | ❌ Issue ; ✅ Warranty Claim | ❌ |
| rattacher un équipement | ❌ (**Custom Field** nécessaire) | ✅ `serial_no` / `item_code` | ✅ `item_code` + numéros de série |

---

## 6. Gestion du temps

- Seul le **Timesheet** porte du temps exploitable : Datetime de début et de fin, heures, activité, coût, facturable.
- Il ne se rattache qu'à **Task** et **Project**. Il faut donc qu'une Task existe pour qu'un temps soit « d'intervention ».
- « J'ai passé 1h30 chez Dupont » devient : Timesheet de l'utilisateur, avec une ligne `task` = intervention, `from_time`/`to_time` ou `hours = 1.5`, l'`activity_type` du déplacement ou du dépannage, et `is_billable` selon le contrat.
- Préalables de configuration :
  - un **Employee** lié à l'utilisateur, pour le coût et les taux (Activity Cost) ; `activity_type` devient alors obligatoire ;
  - des **Activity Types** avec taux.
- Maintenance Visit ne connaît que `mntc_date` et `mntc_time` (une heure de début), sans durée.

## 7. Gestion des équipements

| Situation | Objet natif | Verdict |
|---|---|---|
| Matériel **vendu** par l'entreprise (livré, garanti) | **Serial No** (client et statut alimentés par la livraison), garantie et AMC | ✅ natif ; utilisable dans Maintenance Visit, Maintenance Schedule et Warranty Claim |
| Équipement suivi en **maintenance contractuelle** | Serial No + Maintenance Schedule | ✅ natif, s'il a été vendu ou livré via ERPNext |
| Matériel **appartenant au client**, non vendu par l'entreprise (parc existant, firewall déjà en place) | aucun objet propre : `Serial No.customer` est en lecture seule ; `Asset` avec `asset_owner = Customer` est une immobilisation (location, amortissement) | ❌ **manque réel du modèle natif** |
| Équipement MSP purement technique (VM, licence, tenant M365…) | aucun | ❌ hors du modèle ERPNext |
| Immobilisation de l'entreprise (serveur interne) | Asset + Asset Maintenance | ✅, hors du cœur SpeakDo |

À vérifier avant tout usage : la création d'un Serial No avec un `customer` renseigné par l'API REST.
Le champ est en lecture seule dans le formulaire, mais le comportement à l'insertion par l'API n'a
pas été testé ici, faute de données. Même si c'est possible, ce serait détourner le sens stock du
Serial No.

## 8. Gestion de la facturation

Chemins natifs :

1. **Au temps (recommandé)** : Timesheet (lignes `is_billable`, `billing_rate` issu de l'Activity Type ou de l'Activity Cost) → `timesheet.make_sales_invoice(source, item_code=<Item de service>, customer)` → Sales Invoice avec la table `timesheets` → le Timesheet passe à Partially Billed puis Billed.
2. **Au forfait ou avec des pièces** : Sales Invoice (ou Sales Order puis Sales Invoice) avec des lignes Item de service (frais fixes, déplacement) et Item de stock (pièces). Une même Sales Invoice peut combiner lignes d'articles et `timesheets` (temps + pièces).
3. **Au contrat** : Sales Order, puis Maintenance Schedule et Maintenance Visits, facturés selon le Sales Order. Les visites ne sont pas facturées elles-mêmes.

**Équivalent fonctionnel de `intervention.toinvoice`** : il n'existe pas de drapeau « à facturer »
sur une intervention.

- L'équivalent est l'état **« temps facturable non facturé »** : des lignes Timesheet `is_billable = 1`, `sales_invoice` vide, rattachées à la Task, avec un statut Timesheet Submitted ou Partially Billed.
- L'action serait « préparer la facture » : `make_sales_invoice` sur ces Timesheets, avec un Item de service configuré, pour produire une Sales Invoice **en brouillon**. La validation reste à un rôle comptable (Accounts User), jamais au technicien.
- Pour une `visit` sans Task ni Timesheet, aucun équivalent natif n'existe.

## 9. Gestion de la récurrence

| Mécanisme | Constat | Usage |
|---|---|---|
| **Maintenance Schedule** | périodicité Weekly…Yearly et **Quarterly**, `no_of_visits`, dates générées, Events créés, visites produites | ✅ « tous les 3 mois chez ce client », **à condition d'avoir un Item par ligne** (un Item de service « Maintenance préventive » suffit) |
| Asset Maintenance | périodicité par tâche, `next_due_date`, `assign_to` User | seulement pour les biens de l'entreprise |
| Task | pas de récurrence, `allow_auto_repeat = 0` | ❌ (Auto Repeat activable par personnalisation : configuration de site, non native) |
| Event | `repeat_this_event`, `repeat_on`, `repeat_till` | 🟡 rappel d'agenda, sans objet métier |

« Tous les 3 mois, visite préventive chez ce client » se représente ainsi : Maintenance Schedule
(`customer`, ligne `item_code` = service de maintenance, `periodicity = Quarterly`, dates du
contrat, `sales_person`) → `generate_schedule` → soumission → pour chaque échéance,
`make_maintenance_visit`. Soumission et création sont réservées au Maintenance Manager.

---

## 10. Capacités du profil technicien

Prérequis ERPNext pour un technicien :
- un **User** (System User) ;
- un **Employee** lié (`user_id`), nécessaire au Timesheet avec coût ;
- un **Sales Person** lié à l'Employee, nécessaire à Maintenance Visit ;
- les rôles **Projects User** (Task, Timesheet), **Support Team** (Issue) et **Maintenance User** (Maintenance Visit, Warranty Claim).

**Niveau 1 — lecture (premier connecteur, indispensable)**
- mes tâches : Task assignées (ToDo `allocated_to` = moi), statut, dates, Issue, Project ;
- mes tickets : Issue du client et de ses tâches ;
- mes visites : Maintenance Visit dont `purposes[].service_person` = mon Sales Person, et échéances des Maintenance Schedule ;
- détails client : Customer, Contact, Address ;
- horaires : Events liés (`reference_doctype = Task`) ;
- équipement lié : Serial No d'une visite ou d'un plan.

**Niveau 2 — écriture simple (premier connecteur, pour être utile)**
- créer une intervention : **Task** (depuis un ticket : `issue.make_task`), avec un Event facultatif pour l'heure ;
- changer le statut : Task Open → Working → Completed ;
- enregistrer du temps : ligne de Timesheet liée à la Task (Timesheet en brouillon ; soumission par le technicien ou le manager selon la politique) ;
- compte rendu : commentaire sur la Task. Pour un déplacement client, **Maintenance Visit** créée *après* la visite (`work_done`, `completion_status`), avec soumission optionnelle.

**Niveau 3 — avancé (hors premier connecteur)**
- facturation (préparation de Sales Invoice en brouillon depuis les Timesheets) ;
- récurrence (Maintenance Schedule, rôle Manager) ;
- pièces (Stock Entry ou lignes de facture) ;
- équipement du parc client (§7) ;
- workflow de validation (Frappe Workflow, configuration).

Périmètre minimal utile : **niveaux 1 et 2 sur Task + Timesheet + Issue**, avec lecture et création de Maintenance Visit comme compte rendu. C'est ce qui couvre les cas A, C, D, E, F et J.

---

## 11. Ambiguïtés et limites constatées

1. **Pas de lien natif Task ↔ Maintenance Visit** : une visite planifiée comme Task et rapportée en Maintenance Visit n'a pas de chaînage natif. Options : un Custom Field (`speakdo_task` sur Maintenance Visit, ou l'inverse), ou `Event.reference_*` et les commentaires. **Décision requise.**
2. **Pas de client sur la Task** : un dépannage sans Issue ni Project n'a pas de client. Options : un Project « Support – <client> » par client (natif), passer systématiquement par une Issue (natif), ou un Custom Field `customer`. **Décision requise.**
3. **Pas d'heure sur la Task** (Date seulement) : un rendez-vous horaire passe par Event, ou par un Custom Field Datetime.
4. **Technicien de Maintenance Visit = Sales Person** : il faut une chaîne User → Employee → Sales Person. Le connecteur doit la résoudre, et elle peut manquer.
5. **Maintenance Visit non planifiable** : `completion_status` est obligatoire à la création. L'utiliser comme « intervention à venir » obligerait à mentir sur l'état.
6. **Issue et Warranty Claim sont deux tickets distincts** : seule la Warranty Claim est reliée nativement à Maintenance Visit.
7. **Équipement du parc client** : aucun objet natif adapté (§7).
8. **Soumission et immuabilité** : une Maintenance Visit ou un Timesheet soumis ne se modifient plus. Il faut décider si le technicien soumet lui-même ou si c'est un manager.
9. Le comportement de l'API REST sur les champs RO (`Serial No.customer`) et les permissions effectives du site (au-delà des DocPerm standard) sont **à vérifier** sur données réelles.

## 12. Recommandations

1. **Adopter le modèle polymorphe (C)**, avec la Task comme pivot opérationnel et `kind ∈ {task, visit, maintenance_plan}`.
2. Premier connecteur : Task (lecture, création, statut), Timesheet (temps), Issue (lecture, `make_task`), Maintenance Visit (lecture, création du compte rendu), Customer, Contact et Serial No (lecture). Maintenance Schedule en lecture seule.
3. Imposer le **rattachement client** d'une Task par Project ou Issue (natif) avant d'envisager un Custom Field.
4. Traiter `intervention.toinvoice` comme la préparation d'une Sales Invoice brouillon depuis les Timesheets facturables. Jamais de soumission par le technicien.
5. Reporter l'équipement du parc client à un mandat dédié. C'est le seul cas où un objet SpeakDo spécifique (Custom DocType « Customer Equipment ») pourrait être justifié.
6. Documenter les prérequis de configuration côté client : Employee, Sales Person, Activity Types, Item de service, rôles.

## 13. Modifications proposées à `objects.v1.json`

> Le fichier `resources/erp/erpnext/objects.v1.json` appartient au dépôt du middleware, **absent de
> cette machine** : il n'a pas pu être lu. Les propositions portent sur le contenu décrit par le
> mandat (`task → Task`, `ticket → Issue`, `intervention → Maintenance Visit`). Elles sont à
> appliquer **après validation**, en adaptant au schéma réel du fichier.

| Objet SpeakDo | Actuel | Proposé |
|---|---|---|
| `task` | Task | **inchangé** (Task) |
| `ticket` | Issue | **inchangé** (Issue) |
| `intervention` | Maintenance Visit (candidat ambigu) | **polymorphe** : `kind=task` → Task (défaut pour création et planification) ; `kind=visit` → Maintenance Visit (compte rendu) ; `kind=maintenance_plan` → Maintenance Schedule (lecture) |
| `time_entry` (nouveau) | — | Timesheet (ligne `time_logs`, liée à `task`) |
| `equipment` (nouveau, lecture) | — | Serial No (matériel vendu) ; parc client : non mappé |
| `customer` / `contact` | (selon fichier) | Customer / Contact |
| `calendar_slot` (nouveau, optionnel) | — | Event (`reference_doctype = Task`) |

Forme indicative, pour un schéma à confirmer :

```json
{
  "intervention": {
    "polymorphic": true,
    "discriminator": "kind",
    "variants": {
      "task":             { "doctype": "Task",                 "default_for_create": true },
      "visit":            { "doctype": "Maintenance Visit",    "submittable": true },
      "maintenance_plan": { "doctype": "Maintenance Schedule", "read_only": true }
    }
  },
  "time_entry": { "doctype": "Timesheet", "child": "time_logs", "link": "task" },
  "equipment":  { "doctype": "Serial No", "read_only": true }
}
```

## 14. Proposition du prochain mandat

**« Connecteur ERPNext — profil technicien, niveau 1 et 2 »**, dans le middleware :

1. Trancher les décisions §11-1 (lien Task ↔ Visit) et §11-2 (client de la Task).
2. Mettre à jour `objects.v1.json` selon le §13.
3. Implémenter dans `ErpnextConnector` (transport `Authorization: token`, credential à trancher) :
   - lecture : mes tâches, mes visites, tickets, client, contact, équipement ;
   - écriture : créer une Task (dont depuis une Issue), changer son statut, ajouter une ligne de Timesheet en brouillon, créer une Maintenance Visit de compte rendu.
4. Tests contre `speakdo-test.local`, avec un jeu de données dédié : Customer, Employee, Sales Person, Activity Type, Item de service, Issue.
5. Hors périmètre : facturation, récurrence, parc client.

---

**Décision : C — modèle polymorphe utilisant plusieurs DocTypes.**
Task pour planifier, assigner et suivre ; Timesheet pour le temps et la facturation ; Issue comme
source ; Maintenance Visit pour le compte rendu de visite figé ; Maintenance Schedule pour la
récurrence contractuelle. Ce choix découle des contraintes réelles des métadonnées ERPNext v15 :
- `completion_status` obligatoire sur Maintenance Visit ;
- technicien de type Sales Person ;
- aucun temps ni lien de facture sur la visite ;
- facturation au temps possible seulement par Timesheet → Task ;
- lien de ticket seulement sur Task.

Imposer `intervention = Maintenance Visit` casserait les cas A, C, D, F, I et J.
`intervention = Task` perdrait le compte rendu client figé et l'équipement (E, G).
