
## Menu : étoile sur les options récentes (règle ALBARKA, confirmée le 14/11/2026 : « Il faut que cette règle soit respectée »)
- Toute NOUVELLE option visible de la barre latérale affiche une étoile 🌟 pendant 7 jours (le propriétaire a annulé le point jaune de 3 jours).
- Mise en œuvre : chaque lien de `frontend/src/components/PortalLayout.jsx` porte `depuis: "AAAA-MM-JJ"` (date de mise en ligne) ; `JOURS_NOUVEAU = 7`.
  À renseigner pour CHAQUE nouvelle option, à CHAQUE lot (y compris les sous-menus) : sans `depuis`, aucune étoile ne s'affiche. L'étoile disparaît toute seule.

## Demandes à SAWALI (lot 91, 13/11/2026)
- Les corrections et nouvelles fonctionnalités demandées à SAWALI sont gérées dans Paramètres › « Demandes à SAWALI » (super-admin) : liste horodatée,
  remontée signée vers SAWALI (`POST /api/webhook/plateforme-demandes`), numéro (DEM-…), statut, commentaire et date de réalisation ou prévue retournés
  par SAWALI ; recherche en haut, demandes refusées comprises.
