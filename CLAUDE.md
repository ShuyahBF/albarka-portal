
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

## Écrans colorés, conviviaux et guidés (règle 16, 14/11/2026 : « ce qui retient l'attention de l'utilisateur, ce sont des écrans riches et pas monotones »)
- **Couleurs sobres et différentes** pour mettre en valeur ce qui est important : champs clés, montants, états, échéances, références, boutons d'action. **Jamais un tableau tout en noir** :
  par exemple identifiant / référence en bleu, montants en vert (reçu) ou rouge (dû), échéances et retards en orange / rouge, action principale en bouton de couleur pleine avec son pictogramme.
- Couleurs **modestes**, juste pour attirer l'œil sur l'essentiel (pas d'arc-en-ciel) ; contraste lisible (≥ 4,5:1) et **jamais la couleur seule** : toujours aussi un pictogramme ou un texte.
- Des interfaces **plus conviviales, intuitives et marquantes, sans ajouter de complexité** : les actions importantes (imprimer, enregistrer, payer…) sont **visibles dans le tableau** (colonne d'action
  avec pictogramme coloré), jamais cachées dans un détail ou un menu replié ; l'utilisateur n'a ni à chercher ni à deviner.
- Pensée **support** : chaque action importante doit pouvoir être décrite par sa couleur et son pictogramme (« dans la colonne du bouton bleu en forme d'imprimante, cliquez dessus »).
- Cette règle complète les règles « Tableaux » (survol bleu clair, sélection orange) et « Pictogrammes » (règle 15).

## Boutons « Actualiser » et toasts (règle 17, 14/11/2026 : « C'est une règle. Ne suppose pas »)
- Après TOUTE correction ou nouveauté qui change des RÉSULTATS présentés (graphique, totaux, liste, statut, calcul), l'écran concerné a un bouton « Actualiser » (avec pictogramme,
  règle 15) que l'utilisateur peut actionner : on ne suppose jamais qu'il verra la correction apparaître tout seul.
- TOUTE actualisation affiche un TOAST « … en cours » dès l'appui, puis un toast de résultat (ce qui a été relu, nombre d'éléments, erreurs éventuelles). Jamais d'actualisation silencieuse.
- On ne suppose pas non plus ce que montre l'écran de l'utilisateur : si un résultat ne change pas après une correction, demander la capture et la version affichée, et vérifier avec les valeurs réelles.
- Mise en œuvre : Concentration = `Avis.enCours` / `Avis.resultat` ; web = `toast` de l'application ; WinForms = infobulle ou message d'état.

## Menus et sous-menus : majuscule à chaque mot (règle 18, 14/11/2026 : « chaque 1ère lettre des mots est en majuscule sauf si le contraire est précisé. Valable pour toutes les plateformes »)
- Dans TOUS les menus et sous-menus (barre latérale, groupes dépliables, onglets de navigation, menus d'application), **chaque mot du libellé commence par une majuscule** :
  « Gestion Des Contacts », « Demandes À SAWALI », « Contacts Clients ». Seule exception : quand le propriétaire précise le contraire pour un libellé.
- Seule la première lettre de chaque mot est forcée en majuscule : les sigles et noms déjà en majuscules (SAWALI, DG, OHADA, PI-SPI) ne sont jamais abaissés ; un mot qui suit une apostrophe garde sa casse (« L'ordre »).
- Mise en œuvre : UNE fonction par plateforme, appliquée au dessin des libellés (web : `titreMenu` ; WinForms / Android : équivalent), avec une option « casse libre » pour une exception. On n'écrit pas les majuscules à la main libellé par libellé.
- Valable pour toutes les plateformes, existantes ou à venir.

## Tableaux : toutes les colonnes triables (règle 19, 15/11/2026 : « pour tout tableau présentant des données, rends toutes les colonnes triables si les types de champs le permettent »)
- Sur TOUT tableau qui présente des données (écran, application, état), **chaque colonne est triable** d'un clic sur son en-tête dès que le type de champ le permet (texte, nombre, montant, date) :
  1er clic = croissant (▲), 2e clic = décroissant (▼), 3e clic = ordre d'origine. L'en-tête de la colonne triée est mis en évidence (orange) avec son pictogramme ▲ / ▼ ; les autres colonnes portent un pictogramme ⇅ discret.
- Les valeurs VIDES restent toujours en dernier, quel que soit le sens. Les textes se comparent sans accents ni majuscules, les nombres et montants numériquement, les dates chronologiquement (jamais comme du texte).
- Tableau PAGINÉ ou chargé par morceaux : le tri se fait côté SERVEUR, sur toutes les lignes filtrées, AVANT la pagination (trier seulement les lignes affichées donnerait un faux classement). Petit tableau entièrement chargé : tri dans le navigateur.
- Seules les colonnes d'ACTIONS (boutons) et les colonnes sans valeur comparable (case à cocher de sélection, pictogramme seul) ne sont pas triables.
- Mise en œuvre : SAWALI = `frontend/src/lib/tri.js` (`useTri`, `trierLignes`) et `frontend/src/components/ThTri.jsx` (en-tête triable), tri serveur de Transactions SMS dans `backend/routes/transactions_sms.py` (`trier`) ; e-Kol = `triTableaux.js` ; WinForms = `DataGridView` avec `SortMode = Automatic` ; Android Compose = en-tête cliquable. Même règle sur toute plateforme, existante ou à venir.
- Cette règle complète la règle 3 « Tableaux » (survol, sélection, nombres à droite).


## Pictogramme œil sur toute saisie secrète (règle 22, 16/11/2026 : « pour toute saisie d'un mot de passe, pin ou passphrase mettre un pictogramme œil pour afficher ou masquer. Applique cela à tous nos projets, web comme Android »)
- **Toute saisie d'un mot de passe, d'un code PIN, d'une phrase secrète, d'un jeton ou d'une clé secrète** (connexion, création, confirmation, changement, ouverture d'un coffre, fenêtre de sécurité d'un paiement, paramètres…) porte un **pictogramme œil** : œil ouvert = saisie masquée (un clic l'affiche), œil barré / singe = saisie visible (un clic la masque). **Masquée par défaut** à chaque ouverture.
- Le pictogramme est **dans le champ** (à droite), avec une description d'accessibilité (« Afficher la saisie » / « Masquer la saisie ») et une zone tactile d'au moins 44 px.
- **Un seul composant par plateforme**, utilisé partout (jamais un `<input type="password">` nu) : web = `ChampMotDePasse` / `MotDePasse` / `PasswordInput` (ou le champ de base de l'interface qui l'intègre quand `type="password"`) ; Android Compose = champ avec `trailingIcon` (`Visibility` / `VisibilityOff`) ; Android à vues = `FrameLayout` + œil ; WinForms = case ou bouton œil qui bascule `UseSystemPasswordChar`.
- Un nouvel écran, un nouveau projet : le champ secret reçoit l'œil dès la première version. Exception : la saisie d'un code à usage unique (code reçu par e-mail ou SMS, code de l'application d'authentification), qui n'est pas un secret durable.
