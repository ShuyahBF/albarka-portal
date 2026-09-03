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
- Backend : **193/195 passent** (2 régressions pré-existantes non liées, dans `test_iteration3.TestNotificationGates` et `test_reports_notifications.TestEmailTransport`).
- Iteration 5 & 6 : **25/25 tests** dans `test_iteration5.py`.

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
