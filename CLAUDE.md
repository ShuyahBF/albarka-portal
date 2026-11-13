
## Menu : point jaune sur les options récentes (règle ALBARKA, 13/11/2026)
- Toute NOUVELLE option visible de la barre latérale affiche un point jaune (comme une bulle de notification) tant qu'elle date de moins de 3 jours.
- Mise en œuvre : chaque lien de `frontend/src/components/PortalLayout.jsx` porte `depuis: "AAAA-MM-JJ"` (date de mise en ligne) ; `JOURS_NOUVEAU = 3`.
  À renseigner pour CHAQUE nouvelle option ; le point disparaît tout seul.

## Demandes à SAWALI (lot 91, 13/11/2026)
- Les corrections et nouvelles fonctionnalités demandées à SAWALI sont gérées dans Paramètres › « Demandes à SAWALI » (super-admin) : liste horodatée,
  remontée signée vers SAWALI (`POST /api/webhook/plateforme-demandes`), numéro (DEM-…), statut, commentaire et date de réalisation ou prévue retournés
  par SAWALI ; recherche en haut, demandes refusées comprises.
