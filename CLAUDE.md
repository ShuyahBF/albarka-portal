
## Menu : étoile sur les options récentes (règle ALBARKA, confirmée le 14/11/2026 : « Il faut que cette règle soit respectée »)
- Toute NOUVELLE option visible de la barre latérale affiche une étoile 🌟 pendant 7 jours (le propriétaire a annulé le point jaune de 3 jours).
- Mise en œuvre : chaque lien de `frontend/src/components/PortalLayout.jsx` porte `depuis: "AAAA-MM-JJ"` (date de mise en ligne) ; `JOURS_NOUVEAU = 7`.
  À renseigner pour CHAQUE nouvelle option, à CHAQUE lot (y compris les sous-menus) : sans `depuis`, aucune étoile ne s'affiche. L'étoile disparaît toute seule.

## Demandes à SAWALI (lots 91-92, 13-14/11/2026)
- Les corrections et nouvelles fonctionnalités demandées à SAWALI sont gérées dans l'option « Demandes à SAWALI » de la BARRE LATÉRALE (plus dans les Paramètres),
  accessible au DG, à la Direction et au Secrétariat (mêmes droits) : liste horodatée, ajout, modification et suppression tant que SAWALI n'a pas validé
  (réalisée ou refusée), remontée signée vers SAWALI (`POST /api/webhook/plateforme-demandes`), numéro (DEM-…), statut, commentaire et date de réalisation
  ou prévue retournés par SAWALI ; recherche en haut, demandes refusées comprises.
