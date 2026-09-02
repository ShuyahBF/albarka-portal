# PRD — ALBARKA Portal

## Original problem statement
Application web ALBARKA — portail de gestion des activités d'un cabinet comptable
au Burkina Faso. Basé sur https://github.com/ShuyahBF/albarka-portal.

## Environnement de prod (iteration 3, 2026-09-02)
- **MongoDB Atlas** : `cluster0.fjomnjr.mongodb.net`, DB `albarka`.
- **Stockage** : Cloudflare R2 (bucket `albarka`, endpoint 62be7ac3...).
- **IA** : Claude Sonnet 5 via clé LLM universelle Emergent.
- **Email** : Emergent-managed Resend (batch multi-recipients supporté).
- **WhatsApp** : Meta Cloud API (Graph) via `settings.wa_*` — remplace Twilio.
- **Cron** : `.emergent/crons.yml`, quotidien 07:00 UTC — la plateforme injecte automatiquement `Authorization: Bearer $WEBHOOK_CRON_SECRET`.

## Comptes seedés
- `Admin@sawalismartsystems.com` / `Admin@Sawali2026` — superviseur + direction (production)
- `superviseur@albarka-demo.bf` / `Superviseur2026!`
- `comptable@albarka-demo.bf` / `Comptable2026!` — comptable + fiscaliste
- `client1@albarka-demo.bf` / `Client2026!` — Sawadogo Import-Export SARL
- `client2@albarka-demo.bf` / `Client2026!` — Traoré BTP SARL

## Architecture modules
### Backend (`/app/backend/`)
- `server.py` — FastAPI app, startup indexes.
- `db.py`, `albarka_models.py`, `albarka_auth.py` (OTP+JWT), `albarka_storage.py` (R2 + local + delete).
- `albarka_documents.py` — upload + IA + trigger `notify_upload` sur dépôt client.
- `albarka_ai.py` — Claude Sonnet 5.
- `albarka_missions.py`, `albarka_echeances.py`.
- `albarka_clients.py` — CRUD + `can_receive_notifications`.
- `albarka_dashboard.py`, `albarka_reports.py` (reportlab), `albarka_reports_router.py`.
- `albarka_admin_settings.py` — settings globaux (cabinet + WA + notif + report prefix).
- `albarka_reports_mgmt.py` — numérotation `PREFIX-CLIENTSLUG+HASH-TYPE-YYYYMM-NNNN`, list/download/send/sign/delete.
- `albarka_notifications.py` — email batché + WA Meta Cloud + guardrails ; respecte `is_active` et `can_receive_notifications`.

### Frontend (`/app/frontend/src/`)
- Sidebar rôle-based, `AdminSettings` (Cabinet/WA/Notifications/Rapports), `AdminReports` avec `ClientReportsPanel` (filtre mois/type, générer/envoyer/signer/supprimer).
- Checkbox `can_receive_notifications` sur AdminClients + AdminStaff.

## Livrés iteration 3
- [x] AdminSettings (WA Meta Cloud API config) — plus de Twilio.
- [x] Notifications upload aux collaborateurs actifs autorisés (email batché en un envoi).
- [x] `can_receive_notifications` — respecté par notify_echeance & notify_upload.
- [x] Numérotation rapports **unique par client** grâce au hash discriminateur.
- [x] Liste rapports client, filtre mois/type, envoi PDF par email en pièce jointe, signature (câblage prêt), suppression avec purge du blob.
- [x] Compte admin production seedé.
- [x] Indexes Mongo pour `client_reports.(tenant_id,generated_at)`, unique `client_reports.number`, unique `report_series.key`.
- [x] Diagnostic explicite dans le test WhatsApp.

## Bugs corrigés en iteration 3
- Collision de numéros de rapports entre clients partageant les 7 premières lettres (ajout d'un discriminateur SHA1[:4] du `tenant_id`).
- `notify_upload` faisait un envoi par staff → 429 rate-limit Resend ; désormais un seul envoi multi-recipients.
- `wa/test` retournait `ok:false` opaque → renvoie maintenant un `diagnostic` clair.
- Suppression de rapport ne purgeait pas le PDF → `delete_object` R2/local ajouté.

## Backlog
### P1 (prochaine itération)
- **Signature numérique réelle** : câbler `signature_provider` à un vrai service (eIDAS/DocuSign) — les crochets DB existent.
- **Envoi de rapport → guardrails partagés** : router `send_report_email` à travers `send_email` pour bénéficier de `_assert_safe_email`.
- **Notification WhatsApp au dépôt** (aujourd'hui email uniquement pour `notify_upload`).
- **SMTP réel** ou domaine d'envoi vérifié pour supprimer les 422 undeliverable.

### P2 (durci)
- Pagination sur `/reports/client/{id}/list` (aujourd'hui cap 500).
- Rate-limit sur tentatives OTP + rotation périodique.
- Password reset endpoint.
- Retry avec backoff sur 429 Resend.

## Tests
- Backend : 129/130 (une seule défaillance = 429 rate-limit Resend externe).
