# PRD — ALBARKA Portal

## Original problem statement
Application ALBARKA — portail de gestion des activités d'un cabinet comptable/fiscal au Burkina Faso. Base : https://github.com/ShuyahBF/albarka-portal.

## Environnement de prod
- **MongoDB Atlas** `cluster0.fjomnjr.mongodb.net`, DB `albarka`.
- **Stockage** : Cloudflare R2 bucket `albarka` (fallback local sinon).
- **IA** : Claude Sonnet 5 (clé LLM universelle Emergent).
- **Email** : Resend Emergent-managed. `email_from_address` + `email_reply_to` dans Paramètres → Cabinet.
- **WhatsApp** : Meta Cloud API via `settings.wa_*`.
- **Cron** quotidien 07:00 UTC (`/api/cron/notify-echeances`).
- **Signature électronique** : pyHanko (PAdES-B) + certificats auto-signés RSA 3072 stockés chiffrés.

## Livrés iteration 5 (Feb 2026)
- [x] **Import CSV/Excel de contacts en masse** (`POST /api/contacts/import` + `GET /api/contacts/import/template`) : upsert email/téléphone, dédoublonnage, rapport d'erreurs.
- [x] **Groupes de contacts** (`/api/contact-groups`) : scope cabinet/client, CRUD, envoi groupé de rapports par groupes (`to_groups` sur `/reports/{id}/send`).
- [x] **Modèles de rapports** (`/api/report-templates`) : CRUD, is_default idempotent, sections à la carte (KPIs, missions, échéances, pièces, IA), intro/conclusion personnalisés, filtre "ouvert uniquement".
- [x] **Signature électronique réelle** : `/api/admin/certificates` (create P12 auto-signé, activate, delete + auto-basculement) + wiring pyHanko dans `/api/reports/{id}/sign`. Passphrase chiffrée via Fernet(JWT_SECRET_KEY).
- [x] **Branding cabinet** : `/api/admin/branding` — upload logo, papier à entête, signature DG, filigrane (PNG/JPG/WEBP, 5 Mo max), toggles d'application, rendu automatique dans les PDF (logo en tête, watermark 8% opacité, signature DG en bas, letterhead en fond).
- [x] **UI Frontend** : nouveaux onglets Paramètres/Signature + Paramètres/Branding, tab Modèles dans Rapports client, sélecteur de template dans "Générer un rapport", sélecteur de groupes dans "Envoyer par email", tabs Contacts/Groupes dans la page Contacts, bouton "Importer CSV".
- [x] **Tests** : `/app/backend/tests/test_iteration5.py` — 17/17 passent (Templates CRUD, Groupes isolation client, Import CSV, Certificates lifecycle, Branding upload + toggles, Reports pipeline avec template & envoi groupes).
- [x] **Fix asyncio** : `sign_pdf_bytes` wrappé dans `asyncio.to_thread` (pyHanko utilise son propre event loop → conflit résolu).

## Livrés iteration 4 (récap)
- Contacts scope client/cabinet, notifications WA au dépôt, rappels routés via contacts, domaine email vérifié Resend.

## Livrés iteration 3 (récap)
- Rapports PDF via ReportLab, numérotation atomique `PREFIX-CLIENT-TYPE-YYYYMM-NNNN`, envoi email avec pièce jointe, signature métadonnées.

## Backlog
### P1
- Retour diagnostic amélioré sur `/reports/{id}/send` (422 undeliverable vs 429 rate-limit).
- Preview visuelle réelle des images de branding uploadées (blob URL authentifié).
- Historique de signature (log audit des signatures avec certificat utilisé).
- Fix 2 tests pré-existants cassés dans `test_iteration3.py` et `test_reports_notifications.py` (KeyError 'id' sur user fixture).

### P2
- Pagination sur listes (cap 500-1000).
- Index unique partiel Mongo sur `(scope, tenant_id, is_primary=true)`.
- GET single-contact endpoint.
- Rate-limit sur tentatives OTP + rotation.
- Password reset endpoint.
- Retry avec backoff exponentiel sur 429 Resend.
- Rendu du groupe destinataire dans l'email envoyé (mention "envoyé au groupe Direction").
- Signature visible dans le PDF (annotation champ signature avec image DG au-dessus).

## Tests
- Backend : **183/185 passent** (2 régressions pré-existantes non liées à iter5, dans `test_iteration3.TestNotificationGates` et `test_reports_notifications.TestEmailTransport`).
- Frontend (iter5) : 8/8 scénarios E2E validés par testing_agent.

## Architecture
```
/app/backend
  albarka_admin_settings.py   settings globaux
  albarka_ai.py               Claude Sonnet 5 extraction
  albarka_auth.py             OTP + JWT
  albarka_branding.py         NEW — logo/entête/signature/filigrane
  albarka_clients.py          CRUD clients
  albarka_contact_groups.py   NEW — groupes de contacts
  albarka_contacts.py         CRUD contacts
  albarka_contacts_import.py  NEW — import CSV/XLSX
  albarka_dashboard.py        KPIs
  albarka_documents.py        upload + IA
  albarka_echeances.py        échéances fiscales
  albarka_missions.py         missions
  albarka_models.py           Pydantic
  albarka_notifications.py    email + WhatsApp
  albarka_report_templates.py NEW — modèles de rapports
  albarka_reports.py          PDF ReportLab
  albarka_reports_mgmt.py     mgmt + signature réelle pyHanko
  albarka_reports_router.py   endpoints legacy
  albarka_signing.py          NEW — pyHanko + certificats P12
  albarka_storage.py          R2 + local
  db.py, seed.py, server.py
  tests/test_iteration5.py    NEW — 17 tests
```
