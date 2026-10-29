# lot.py — numéro du lot actuellement déployé (source UNIQUE, lue par /api/version).
#
# Règle permanente du propriétaire : à CHAQUE déploiement sur Render, mettre à jour
# LOT (et LOT_LIBELLE) dans ce fichier :
#   - nouveau lot fonctionnel : numéro entier suivant (ex. "14") ;
#   - petite mise à jour d'un lot déjà en ligne : sous-numéro (ex. "13.1").
# Effet voulu : ce fichier étant dans le dossier backend, sa modification force
# Render à redéployer le serveur, ce qui incrémente aussi le numéro de version
# (1.N, compteur de déploiements, voir version_deploiement.py).
LOT = "80.2"
LOT_LIBELLE = "Bulletins de paie : la mention « non cadre » n'apparaît plus au niveau du statut (remarque de l'inspection du travail). Lot 80.1 : Tableaux : la ligne sélectionnée garde son fond orange clair mais passe en police bleu nuit (contraste 7,7:1 au lieu de 2:1 en blanc), règle 3 modifiée par le propriétaire le 28/10/2026. Lot 80 : Demande de services : l'envoi (texte, note vocale, pièces jointes) ne répond plus « Field required ». Lot 79 — Contrats clients : la Direction peut aussi modifier le numéro de contrat (avec le DG et le super-admin). Lot 78 : option sous « Clients », onglet « Historique des Contrats », numéro proposé automatiquement."
