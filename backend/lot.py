# lot.py — numéro du lot actuellement déployé (source UNIQUE, lue par /api/version).
#
# Règle permanente du propriétaire : à CHAQUE déploiement sur Render, mettre à jour
# LOT (et LOT_LIBELLE) dans ce fichier :
#   - nouveau lot fonctionnel : numéro entier suivant (ex. "14") ;
#   - petite mise à jour d'un lot déjà en ligne : sous-numéro (ex. "13.1").
# Effet voulu : ce fichier étant dans le dossier backend, sa modification force
# Render à redéployer le serveur, ce qui incrémente aussi le numéro de version
# (1.N, compteur de déploiements, voir version_deploiement.py).
LOT = "78"
LOT_LIBELLE = "Contrats clients : option placée sous « Clients » dans le menu ; onglet « Historique des Contrats » dans la fiche d'un client (historique + création d'un contrat) ; numéro de contrat proposé automatiquement (dernier numéro + 1), modifiable seulement par le DG et le super-admin."
