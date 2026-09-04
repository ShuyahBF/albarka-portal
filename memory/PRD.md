# PRD — ALBARKA Portal

## Original problem statement
Application ALBARKA — portail de gestion des activités d'un cabinet comptable/fiscal au Burkina Faso. Base : https://github.com/ShuyahBF/albarka-portal.

## Environnement de prod
- **MongoDB Atlas** `cluster0.fjomnjr.mongodb.net`, DB `albarka`.
- **Stockage** : Cloudflare R2 bucket `albarka` (fallback local sinon).
- **IA** : Claude Sonnet 5 (clé LLM universelle Emergent).
- **Email** : Resend Emergent-managed.
- **WhatsApp** : Meta Cloud API (Media API pour PDF, fallback lien signé).
- **Cron** quotidien 07:00 UTC.
- **Signature électronique** : pyHanko PAdES-B + tampon visuel via PyMuPDF + certificats auto-signés RSA 3072.

## Livrés iteration 9 (Feb 2026) — Réconciliation MongoDB + Phase A + Phase B + Phase C + Phase D
### Phase 0 — Skipped par l'utilisateur (Git realignment sera fait plus tard)

### Phase B (P1) — 04/09/2026
- [x] **Feature 14 — Contrats clients + gate login** : Nouveau CRUD `/api/client-contracts` (Contract{tenant_id, title, dates, amount, status}), page admin `/admin/contrats` avec EntitySelect + éditeur. `verify-otp` refuse (403) les clients sans contrat actif avec message clair. Les 2 clients demo ont été seedés avec un contrat actif 2026.
- [x] **Feature 1 — WhatsApp retry** : `POST /reports/whatsapp/retry/{log_id}` re-envoie une entrée en échec. Bouton `[data-testid=wa-retry-{id}]` visible sur les échecs du `WhatsAppLogPanel`.
- [x] **Feature 2 — Bulk generate** : `POST /reports/bulk-generate` — génère un rapport pour tous les clients actifs (ou liste passée). Page `/admin/rapports/bulk` (KPIs generated/failed).
- [x] **Feature 3 — Auto WA J+N post-signature** : après `sign_report`, si `settings.auto_wa_after_sign_enabled=true`, planifie un envoi WA dans `scheduled_wa_sends` à J+`auto_wa_after_sign_days` (défaut 1). Marquage `auto:true` + `auto_reason`.
- [x] **Feature 4 — Export trimestriel** : `POST /reports/client/{tenant_id}/generate-quarterly {period_quarter:"2026-Q1"}` — agrège les 3 mois du trimestre dans un PDF unique. UI Phase 2 dans `/admin/rapports/bulk`.

### Phase C (P2) — 04/09/2026 (from scratch, commit legacy 1fa4095 introuvable)
- [x] **8a Chat interne** : `chat_messages` collection, thread `client:{tenant_id}`. Endpoints `/chat/messages` GET/POST, `/chat/threads` (staff). Client isolé sur son propre thread. Pages `/admin/chat` (multi-fil) + `/portal/chat`.
- [x] **8b Caisse / facturation** : `/billing/invoices` (calcul auto subtotal + TVA + total), `/billing/payments` (met à jour paid_amount et status unpaid → partial → paid), `/billing/summary` (KPIs facturé/encaissé/reste). Page `/admin/caisse` (tabs Factures/Encaissements).
- [x] **9 RH & Paie** : `/hr/employees` + `/hr/payslips` avec calcul net = brut − retenues + primes. Page `/admin/paie` (rôle rh en plus des admin).
- [x] **10 Platform logs** : `/platform-logs` (rôles superviseur/direction/administrateur). Auto-log sur invoice.create, payment.create, payslip.create, chat.post, broadcast.send. Filter action **partial regex-i**. Page `/admin/logs`.
- [x] **11 Archives** : `/archives` CRUD, tags + catégories. Page `/admin/archives`.
- [x] **12 Messagerie broadcast** : `/messaging/broadcast` (scope clients|staff|all, canal email|whatsapp), `broadcasts` + `broadcast_deliveries` collections. Page `/admin/messagerie`.

### Phase D (P3) — 04/09/2026 — Comptabilité OHADA SYSCOHADA
- [x] **Plan comptable** : 29 comptes SYSCOHADA seed via `POST /accounting/seed-plan?tenant_id=X` (classes 1-8). Ajout libre via `POST /accounting/accounts`.
- [x] **Écritures double partie stricte** : `POST /accounting/entries` refuse si Σdébits ≠ Σcrédits (400). Validation 2 étapes (draft → validated). Numérotation `{JOURNAL}-YYYY-NNNNNN` par tenant/année.
- [x] **Grand livre** : `GET /accounting/ledger/{code}?tenant_id=X` — running balance chronologique par compte.
- [x] **Balance de vérification** : `GET /accounting/trial-balance?tenant_id=X` — agrège par compte + `balanced: bool`.
- [x] Page `/admin/comptabilite` : 3 tabs Écritures/Plan/Balance, dialog multi-lignes avec équilibrage live, validation, suppression (draft only).

### Tests Phase B/C/D
- **Backend** : 262 tests pytest (dont `test_iteration9_phaseBCD.py` 20 tests, `test_rbac_edge.py`) — 100% passants.
- **Frontend** : 92% (11 écrans Playwright, 3 défauts UX mineurs identifiés et corrigés : noms client au lieu de tenant_id dans Contracts/Chat, reload threads après post, état vide OHADA Balance).
- Rapport : `/app/test_reports/iteration_9.json`.

### Phase A (P0) — 04/09/2026
- [x] **Feature 5 — Rôle `administrateur`** : ajouté à `ALBARKA_ROLES`. `/admin/settings`, `/admin/branding`, `/admin/certificates` acceptent désormais `superviseur | direction | administrateur`. Un utilisateur avec ce rôle seul voit le lien "Paramètres" dans la sidebar staff.
- [x] **Feature 13 — Dernière connexion** : `[data-testid=sidebar-last-login]` en bas de la sidebar (`Dernière connexion : JJ/MM/AAAA HH:MM`), s'appuie sur `user.last_login` déjà persisté par `verify-otp`.
- [x] **Feature 6 — Édition Staff/Client inline** : dialogues "Modifier un collaborateur" / "Modifier le client" via `PATCH /api/clients/{id}`. Email `readOnly` (non modifiable). Pas de champ password en édition. Bouton crayon `[data-testid=edit-staff-{id}]` / `[data-testid=edit-client-{id}]`.
- [x] **Feature 7 — Composant `EntitySelect`** (`/app/frontend/src/components/EntitySelect.jsx`) : combobox shadcn (Popover + Command) chargeant `GET /clients`, filtrable. Utilisé dans `portal/Documents.jsx`, `portal/Missions.jsx`, `portal/Echeances.jsx` (mode staff) — remplace les inputs raw `tenant_id`. Contacts/Groupes/Rapports utilisent déjà un `<Select>` client (pas de changement).
- [x] **Sécurité** : validateur `UserUpdate.roles` (`albarka_clients.py`) — interdit `client` cumulé avec un rôle cabinet, interdit `roles: []`, interdit rôles inconnus. Corrige la faille RBAC HIGH remontée par le testing agent (élévation de privilège via PATCH).
- [x] **Tests** : 242 tests régression pytest passants + 13 nouveaux tests Phase A (`/app/backend/tests/test_iteration9_phaseA.py`) + 11 scénarios Playwright validés par testing_agent_v3_fork (rapport `/app/test_reports/iteration_8.json`).

### Réconciliation MongoDB (initiale de l'itération)
- [x] **Endpoint diagnostic** `GET /api/_diag/db` (staff-only) : renvoie mongo_host, db_name, compteurs de collections (sans credentials).
- [x] **Endpoint migration** `POST /api/_admin/migrate-mongo` (superviseur/direction) — upsert idempotent, backup JSON `password_hash` REDACTED, skip par défaut de `otps`/`cron_runs`, options `dry_run` / `only_collections` / `skip_collections`, protection admin/superviseur (préserve `password_hash` + `is_active` sur la cible pour ces 2 emails).
- [x] **Tests** : 23/23 pytest dans `test_iteration6_migrate.py`.
- Instructions post-fix : (1) redéployer les changements, (2) `GET /_admin/migrate-mongo/inventory` pour vérifier la source, (3) `POST /_admin/migrate-mongo` avec cible Atlas + confirm_token, (4) reconfigurer MONGO_URL/DB_NAME dans le dashboard Emergent, (5) redéployer, (6) retirer les endpoints après vérification.

## Livrés iteration 6 (Feb 2026)
- [x] **Aperçu réel des images de branding** — endpoint `GET /api/admin/branding/{kind}/preview` + composant `BrandingThumbnail` (blob URL authentifié).
- [x] **Signature visible sur PDF** — `_apply_visible_stamp` via PyMuPDF avant signature pyHanko :
  - Cachet ambré coin bas-droite sur **chaque page** ("Signe electroniquement · Ref. XXXX")
  - Grand bloc "SCEAU DU CABINET" sur la **dernière page** avec Cabinet, Signataire, Certificat, N° série, Horodaté, Réf. rapport (+ image DG optionnelle).
- [x] **Journal signatures** — nouvelle collection `signature_log` + endpoint `GET /api/reports/signatures/log` (filtres tenant/certificat/agent) + page admin `Rapports client → Journal signatures` avec table, recherche et filtre certificat.
- [x] **Envoi WhatsApp du rapport** — endpoint `POST /api/reports/{id}/send-whatsapp` :
  - Stratégie 1 : upload PDF via Meta Media API + envoi comme `document`
  - Stratégie 2 (fallback) : message texte avec lien signé JWT 7 jours (`/api/reports/download/shared/{token}`)
  - Support `to` (direct), `to_contacts`, `to_groups`
  - Bouton WhatsApp vert (MessageCircle) à côté du bouton email dans chaque ligne de rapport + dialog `wa-report-dialog` avec sélecteur de groupes
- [x] **Tests** : 8 nouveaux tests dans `/app/backend/tests/test_iteration5.py` (TestSignatureAudit, TestSharedDownloadToken, TestWhatsAppReport, TestBrandingPreview) — **25/25 passent**.

## Livrés iteration 5 (récap)
- Import CSV/Excel contacts, groupes de contacts, modèles de rapports, signature pyHanko réelle, branding (logo/entête/DG/filigrane).

## Livrés iteration 4 (récap)
- Contacts scope client/cabinet, notifications WA au dépôt, rappels routés via contacts, domaine email vérifié Resend.

## Livrés iteration 3 (récap)
- Rapports PDF via ReportLab, numérotation atomique `PREFIX-CLIENT-TYPE-YYYYMM-NNNN`, envoi email avec pièce jointe.

## Backlog
### P1
- Retour diagnostic amélioré sur `/reports/{id}/send` (422 undeliverable vs 429 rate-limit).
- Ajouter historique WhatsApp au rapport (comme signature_log mais pour WA).
- Fix 2 tests pré-existants cassés dans `test_iteration3.py` et `test_reports_notifications.py` (KeyError 'id' sur user fixture).
- Export CSV du journal signatures.

### P2
- Pagination sur listes (cap 500-1000).
- Index unique partiel Mongo sur `(scope, tenant_id, is_primary=true)`.
- GET single-contact endpoint.
- Rate-limit sur tentatives OTP + rotation.
- Password reset endpoint.
- Retry avec backoff exponentiel sur 429 Resend.
- Preview visuelle en direct de la couverture PDF lors du choix de template.

## Tests
- Backend : **242+ tests régression + 13 tests Phase A (`test_iteration9_phaseA.py`)**. 2 anciennes régressions pré-existantes documentées (fixture user).
- Iteration 5 & 6 : **25/25 tests** dans `test_iteration5.py`.
- Iteration 9 Phase A : **11/11 scénarios Playwright validés** (rapport `/app/test_reports/iteration_8.json`).

## Architecture
```
/app/backend
  albarka_admin_settings.py   settings globaux
  albarka_ai.py               Claude Sonnet 5 extraction
  albarka_auth.py             OTP + JWT
  albarka_branding.py         logo/entête/signature/filigrane + /preview
  albarka_clients.py          CRUD clients
  albarka_contact_groups.py   groupes de contacts
  albarka_contacts.py         CRUD contacts
  albarka_contacts_import.py  import CSV/XLSX
  albarka_dashboard.py        KPIs
  albarka_documents.py        upload + IA
  albarka_echeances.py        échéances fiscales
  albarka_missions.py         missions
  albarka_models.py           Pydantic
  albarka_notifications.py    email + WA + WA media upload
  albarka_report_templates.py modèles de rapports
  albarka_reports.py          PDF ReportLab
  albarka_reports_mgmt.py     mgmt + sign + WhatsApp + signatures log
  albarka_reports_router.py   endpoints legacy
  albarka_signing.py          pyHanko + tampon visible PyMuPDF + certs P12
  albarka_storage.py          R2 + local
  db.py, seed.py, server.py
  tests/test_iteration5.py    25 tests (couvre iter5 + iter6)
```
