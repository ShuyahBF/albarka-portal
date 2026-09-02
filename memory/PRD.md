# PRD — ALBARKA Portal

## Original problem statement
Nouvelle application web de gestion des activités d'un cabinet comptable
(albarka-portal), basée sur https://github.com/ShuyahBF/albarka-portal.

## Environnement (iteration 2, 2026-02-06)
- **MongoDB** : Atlas `cluster0.fjomnjr.mongodb.net`, DB `albarka`.
- **Stockage** : Cloudflare R2 bucket `albarka` (endpoint 62be7ac3...).
- **IA** : Claude Sonnet 5 via clé LLM universelle Emergent.
- **Email** : Emergent-managed Resend (from_name = "Cabinet ALBARKA").
- **WhatsApp** : Twilio, guardé — actif dès que `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WA_FROM` sont dans `.env`.
- **Cron** : `.emergent/crons.yml` — quotidien 07:00 UTC, endpoint `/api/cron/notify-echeances` protégé par `WEBHOOK_CRON_SECRET`.

## Architecture
- **Backend** : FastAPI + Motor/MongoDB + emergentintegrations + PyMuPDF + boto3 + reportlab + httpx.
  - Modules : `server.py`, `db.py`, `albarka_models.py`, `albarka_auth.py`, `albarka_documents.py`,
    `albarka_ai.py`, `albarka_missions.py`, `albarka_echeances.py`, `albarka_clients.py`,
    `albarka_dashboard.py`, `albarka_storage.py`, `albarka_notifications.py` (email + WA guardé),
    `albarka_reports.py` (PDF client), `albarka_reports_router.py`, `seed.py`.
- **Frontend** : React 19 + React Router 7 + Tailwind + shadcn/UI + sonner.
  - Layouts : `PublicLayout`, `PortalLayout` (sidebar filtrée par rôles cumulés).
  - Pages : Home / Missions / Contact publiques ; Dashboard/Documents/Missions/Échéances/Historique client ;
    Clients/Staff/ClientDetail/Documents/Missions/Échéances/**Rapports** admin.

## Rôles (cumulables, `client` exclusif)
`superviseur` (full), `direction`, `secretariat`, `fiscaliste`, `comptable`,
`aide_comptable`, `rh`, `client`.
Sidebar dynamique : chaque item de menu déclare la liste de rôles autorisés ;
`superviseur` voit tout ; un `comptable+fiscaliste` voit uniquement les items
autorisés au cumul de ses rôles.

## Livrés (iteration 2)
- [x] Auth OTP + JWT + rôles cumulables.
- [x] Documents avec analyse Claude Sonnet 5 (async, base64 vision).
- [x] Missions / Échéances CRUD, isolation tenant.
- [x] Gestion clients + collaborateurs (checkboxes multi-rôles à la création).
- [x] **Rapport PDF client** (`/api/reports/client/{id}`, reportlab, brand ALBARKA).
- [x] **Notifications email + WhatsApp** J-7 / J-1 + jour J + overdue (`days_left` négatif) via cron quotidien 07:00 UTC.
- [x] **Sidebar rôle-based** dans le portail admin.
- [x] Index Mongo unique (cron_runs.run_id, notification_log.key, users.email).
- [x] R2 storage actif ; presigned URL 5 min ; fallback local disponible.

## Bugs corrigés en iteration 2
- Dedup notification_log conditionnel au succès (permet retry en cas d'échec transitoire du proxy Resend).
- `days_left` non clampé à 0 → overdue correctement identifiés.

## Backlog
- **P1** :
  - Twilio credentials à ajouter par le client pour activer WhatsApp.
  - SMTP réel (ou domaine deliverable) — le proxy Resend rejette `@albarka-demo.bf` avec 422 ; les vrais clients passeront.
  - Pagination sur listes (aujourd'hui plafond 500-1000).
  - Rate-limit sur tentatives OTP.
- **P2** :
  - Envoi du rapport PDF directement au client par email depuis la fiche client.
  - Support multi-utilisateurs par entreprise (aujourd'hui 1 tenant = 1 utilisateur).
  - Password reset endpoint.
  - Notifications additionnelles (upload d'une pièce, mission terminée).
  - Export Excel des balances / grands livres.
  - Signature électronique des rapports.

## Tests
- Backend : 90/90 passent (iteration 1: 61, iteration 2: 29 nouveaux).
