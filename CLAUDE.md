
## Menu : étoile sur les options récentes (règle ALBARKA, confirmée le 14/11/2026 : « Il faut que cette règle soit respectée »)
- Toute NOUVELLE option visible de la barre latérale affiche une étoile 🌟 pendant 7 jours (le propriétaire a annulé le point jaune de 3 jours).
- Mise en œuvre : chaque lien de `frontend/src/components/PortalLayout.jsx` porte `depuis: "AAAA-MM-JJ"` (date de mise en ligne) ; `JOURS_NOUVEAU = 7`.
  À renseigner pour CHAQUE nouvelle option, à CHAQUE lot (y compris les sous-menus) : sans `depuis`, aucune étoile ne s'affiche. L'étoile disparaît toute seule.

## Demandes à SAWALI (lots 91-92, 13-14/11/2026)
- Les corrections et nouvelles fonctionnalités demandées à SAWALI sont gérées dans l'option « Demandes à SAWALI » de la BARRE LATÉRALE (plus dans les Paramètres),
  accessible au DG, à la Direction et au Secrétariat (mêmes droits) : liste horodatée, ajout, modification et suppression tant que SAWALI n'a pas validé
  (réalisée ou refusée), remontée signée vers SAWALI (`POST /api/webhook/plateforme-demandes`), numéro (DEM-…), statut, commentaire et date de réalisation
  ou prévue retournés par SAWALI ; recherche en haut, demandes refusées comprises.

## Compte rendu par e-mail : TOUJOURS, même pour un ajout ou une correction insignifiante (règle du 14/11/2026)
- Après CHAQUE livraison, sans exception de taille (petite correction, changement de libellé, simple règle ajoutée au CLAUDE.md), envoyer l'e-mail HTML de
  compte rendu à jfrancois.ouoba@gmail.com (`mcp__Gmail__send_message`, champ `htmlBody`) : date et heure, identification (dépôt, branche, commit, lot),
  périmètre, comment vérifier, à activer, points d'attention, reste à faire. Ne jamais attendre que le propriétaire le demande.
- Cette règle précise la règle « Livraison et déploiement » ; elle vaut aussi pour les recettes et vérifications faites sans changement de code.

## auRor = mobile-payments (précisé par le propriétaire, 14/11/2026)
- **auRor et mobile-payments désignent la MÊME plateforme** : dépôt `ShuyahBF/Claude`, dossiers `mobile-payments-web` et `mobile-payments-app` (chercher dans ce dépôt quand une demande cite auRor).
- Ses séquences USSD des opérateurs (Orange, Moov Africa, Telecel Faso) sont la SOURCE DE RÉFÉRENCE : toute copie dans une autre plateforme (ex. SAWALI, paiement au comptoir des officines) doit être corrigée en même temps.

## Pictogrammes sur toutes les actions et enregistrement jamais « deviné » (règle 15, 14/11/2026 : « C'est une règle importante »)
- **Toute action possible** dans un bloc, une page ou une fenêtre (enregistrer, modifier, supprimer, annuler, fermer, ouvrir, actualiser, ajouter, choisir, utiliser, exporter…)
  porte un **PICTOGRAMME** accompagné d'une légende courte. Jamais de bouton sans pictogramme, ni d'action cachée dans un simple texte souligné. Dans une ligne de tableau
  répétée, le pictogramme seul est admis s'il a une info-bulle et un libellé d'accessibilité.
- **Ne JAMAIS laisser l'utilisateur deviner** qu'en changeant de champ (sortie du champ, bascule, liste) les données sont enregistrées. Deux seules façons admises :
  1. **bouton « Enregistrer » avec pictogramme** (✓ / disquette), actif seulement quand la valeur a changé, avec la mention « modifié, non enregistré » ; ou
  2. si l'enregistrement est AUTOMATIQUE par choix, une indication visible à côté du champ (pictogramme + « enregistré automatiquement ») et une confirmation après
     chaque enregistrement (toast, coche) — jamais un enregistrement silencieux.
- Mise en œuvre : web = `lucide-react` ; Android Compose = `Icons` + libellé ; WinForms = image sur le bouton. Valable pour toute plateforme, existante ou à venir.
