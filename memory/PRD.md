# PRD — ALBARKA Portal

## Original problem statement
Nouvelle application web de gestion des activités d'un cabinet comptable
(albarka-portal). Le code est issu d'un repo GitHub
(https://github.com/ShuyahBF/albarka-portal) sur lequel nous implémentons,
maintenons et hébergeons ici.

## User choices
- **Stockage** : Cloudflare R2 (credentials à fournir par le client — fallback local activé en attendant).
- **Analyse IA** : Claude Sonnet 5 via la clé LLM universelle Emergent.
- **Modules MVP** : Login OTP, Dashboard, Documents, Clients, Missions, Échéances fiscales, Historique.
- **Langue** : Français.
- **Design** : Anti-slop — palette émeraude/ambre chaude, typographie Fraunces (headings) + Manrope (body), thème dark pour marketing et light pour portail.

## Architecture
- **Backend** : FastAPI + Motor/MongoDB + emergentintegrations (Claude Sonnet 5) + PyMuPDF + boto3 (R2 optionnel).
  - Modules : `server.py`, `db.py`, `albarka_models.py`, `albarka_auth.py` (login + OTP + JWT),
    `albarka_documents.py`, `albarka_ai.py`, `albarka_missions.py`, `albarka_echeances.py`,
    `albarka_clients.py`, `albarka_dashboard.py`, `albarka_storage.py`, `seed.py`.
- **Frontend** : React 19 + React Router 7 + Tailwind + shadcn/UI + sonner.
  - Layouts : `PublicLayout`, `PortalLayout` (sidebar + topbar, mode client / mode cabinet).
  - Pages publiques : Home, Missions/Services, Contact.
  - Pages portail (client) : Dashboard, Documents, Missions, Échéances, Historique.
  - Pages admin (cabinet) : Dashboard, Clients, ClientDetail (onglets pièces/missions/échéances), Staff, Documents, Missions, Échéances.

## User personas
1. **Superviseur du cabinet** — accès total, gestion clients + staff + tous dossiers.
2. **Comptable / Fiscaliste / RH / Secrétariat** — accès staff aux dossiers de tous clients.
3. **Client** — accès à son propre espace uniquement (isolation par `tenant_id = user_id`).

## Rôles (cumulables sauf `client` qui est exclusif)
`superviseur`, `direction`, `secretariat`, `fiscaliste`, `comptable`,
`aide_comptable`, `rh`, `client`.

## Core requirements (delivered)
- [x] Login email + password + OTP 6 chiffres + JWT (7 jours). Mode pilote : OTP renvoyé dans la réponse (`dev_otp`) tant que SMTP n'est pas configuré.
- [x] Upload pièces (PDF/image/Office) avec analyse IA async (Claude Sonnet 5) — type détecté, synthèse FR, champs extraits (montants, dates, IFU/RCCM).
- [x] Missions (CRUD staff, lecture client scoped).
- [x] Échéances fiscales TVA/IS/IRPP/IUTS/CNSS.
- [x] Dashboard KPI (documents, missions, échéances à venir/en retard + clients/staff pour cabinet).
- [x] Gestion clients + collaborateurs (cabinet).
- [x] Historique global avec onglets (pièces / missions / échéances).
- [x] Isolation stricte tenant_id.
- [x] Stockage local fallback quand R2 non configuré (endpoint téléchargement authentifié).

## Implemented (2026-02-06)
- Backend 100% : 61/61 tests passent (auth, RBAC, tenant isolation, upload+IA, CRUD complet).
- Frontend : landing dark émeraude/ambre, portail light avec sidebar, dashboard, tables shadcn.
- Seed script : 1 superviseur + 1 comptable + 2 clients de démo avec missions/échéances pré-remplies.
- Vérifié : upload facture.pdf → Claude extrait IFU, montant HT/TVA/TTC, fournisseur, date en 6 secondes.

## Backlog (P1 — reste à faire selon priorité utilisateur)
- **R2 branché** : dès que les credentials sont fournis, activation automatique (code déjà en place).
- SMTP réel (Resend Emergent-managed) → suppression du `dev_otp`.
- Gestion multi-utilisateurs par client (aujourd'hui : 1 tenant = 1 utilisateur).
- Notifications d'échéances par email (J-7, J-1, jour J).
- Édition des pièces (recatégoriser après upload).
- Génération PDF de bilans / rapports de mission.
- Signature électronique des rapports.
- Support des exports Excel des balances / grands livres.

## Backlog (P2 — hardening)
- Rate-limit + capping des tentatives OTP + invalidation des sessions OTP antérieures.
- Pagination sur toutes les listes (aujourd'hui plafond 500-1000).
- Nettoyage des fichiers physiques lors de la suppression.
- Validation cross-collection du `tenant_id`.
- Password reset / rotation utilisateur.
