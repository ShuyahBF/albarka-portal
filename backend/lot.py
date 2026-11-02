# lot.py — numéro du lot actuellement déployé (source UNIQUE, lue par /api/version).
#
# Règle permanente du propriétaire : à CHAQUE déploiement sur Render, mettre à jour
# LOT (et LOT_LIBELLE) dans ce fichier :
#   - nouveau lot fonctionnel : numéro entier suivant (ex. "14") ;
#   - petite mise à jour d'un lot déjà en ligne : sous-numéro (ex. "13.1").
# Effet voulu : ce fichier étant dans le dossier backend, sa modification force
# Render à redéployer le serveur, ce qui incrémente aussi le numéro de version
# (1.N, compteur de déploiements, voir version_deploiement.py).
LOT = "84"
LOT_LIBELLE = "Paie : base IUTS dans le livre de paie (PDF compris), case « exonéré de la cotisation CNSS » sur la fiche de l'agent, rubriques SND / SFED / CENAMU. Rapports : reçus seulement dans « Rapports ». Formulaires : PDF d'archivage des réponses."
