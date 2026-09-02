# PRD — ALBARKA Portal

## Original problem statement
Application ALBARKA — portail de gestion des activités d'un cabinet comptable/fiscal au Burkina Faso. Base : https://github.com/ShuyahBF/albarka-portal.

## Environnement de prod (iteration 4)
- **MongoDB Atlas** `cluster0.fjomnjr.mongodb.net`, DB `albarka`.
- **Stockage** : Cloudflare R2 bucket `albarka`.
- **IA** : Claude Sonnet 5 (clé LLM universelle Emergent).
- **Email** : Resend Emergent-managed. Optional `email_from_address` + `email_reply_to` dans Paramètres → Cabinet, avec instructions de vérification DNS.
- **WhatsApp** : Meta Cloud API via `settings.wa_*`.
- **Cron** quotidien 07:00 UTC (`/api/cron/notify-echeances`).

## Livrés iteration 4
- [x] **Contacts** — carnet d'adresses par client OU cabinet (banques, impôts…) :
  - Champs : full_name, function (DG/DAF/comptable_interne/…/impots/cnss/…), email, phone, is_primary, channels (email + WhatsApp), categories, notes.
  - Auto-démote du contact principal précédent lors de la création/promotion d'un nouveau.
  - Isolation stricte : client ne voit que ses propres contacts (cabinet-scope invisible).
  - Enum validation sur `function`, `channels`, `categories`, `scope`.
- [x] **Notifications WhatsApp au dépôt** de pièce (opt-in `settings.notif_upload_wa`).
- [x] **Rappels d'échéances routés via contacts** : `notify_echeance` envoie désormais aux emails du compte client **et** des contacts actifs autorisés (email/WA selon `channels`), déduplication auto.
- [x] **Domaine email vérifié** : champs `email_from_address` + `email_reply_to` dans Paramètres avec validation format + guide DNS Resend inline.
- [x] `/reports/{id}/send` refactorisé sur `send_email()` partagé (guardrails Resend + attachments) — routing multi-canaux : `to`, `to_contacts`, ou compte client par défaut.
- [x] Sidebar : entrée « Contacts » (rôles superviseur/direction/secretariat/comptable/fiscaliste).
- [x] Onglet **Contacts** dans la fiche client (admin).

## Bugs corrigés en iteration 4
- HTML injection dans les emails de rapport : escape des valeurs interpolées.
- `notifiable_contacts_for` désormais utilisé par `notify_echeance` (helpers alignés).
- Validation stricte des enums (categories, function, channels).
- Validation du format email de `email_from_address` et `email_reply_to`.

## Backlog
### P1 (proposé pour iteration 5)
- **Signature numérique câblée** — proposition : **pyHanko** pour sceau du cabinet (100% gratuit, PAdES-B, hors ligne). Alternative : DocuSeal self-hosté pour signature à distance client.
- **Retour diagnostic** sur `/reports/{id}/send` (distinguer 422 undeliverable vs 429 rate-limit).
- **Semaphore + gather** sur fan-out WA dans `notify_upload` (concurrence bornée).

### P2
- Pagination sur listes (cap 500-1000 actuellement).
- Index unique partiel Mongo sur `(scope, tenant_id, is_primary=true)` pour éviter race auto-demote.
- GET single-contact endpoint (frontend récupère la liste puis filtre).
- Rate-limit sur tentatives OTP + rotation.
- Password reset endpoint.
- Retry avec backoff exponentiel sur 429 Resend.

## Tests
- Backend : **166/166 passent, 5 skipped (limites externes Resend)**.
