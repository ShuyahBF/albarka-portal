# lot.py — numéro du lot actuellement déployé (source UNIQUE, lue par /api/version).
#
# Règle permanente du propriétaire : à CHAQUE déploiement sur Render, mettre à jour
# LOT (et LOT_LIBELLE) dans ce fichier :
#   - nouveau lot fonctionnel : numéro entier suivant (ex. "14") ;
#   - petite mise à jour d'un lot déjà en ligne : sous-numéro (ex. "13.1").
# Effet voulu : ce fichier étant dans le dossier backend, sa modification force
# Render à redéployer le serveur, ce qui incrémente aussi le numéro de version
# (1.N, compteur de déploiements, voir version_deploiement.py).
LOT = "32.2"
LOT_LIBELLE = "Tableaux : la ligne sélectionnée garde son fond orange clair mais passe en police bleu nuit (contraste 7,7:1 au lieu de 2:1 en blanc), règle 3 modifiée par le propriétaire le 28/10/2026. Lot 32.1 : Paie : l'abattement pour charges de famille s'affiche en positif sur le bulletin (le calcul et le net ne changent pas)"
