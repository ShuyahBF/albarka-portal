# Règles permanentes du propriétaire (ShuyahBF)

Ces règles s'appliquent à TOUS les sites, projets et applications, existants
(SAWALI, Ster, adLyn, beAuthentik, …) et futurs. Elles font partie de la
méthode de travail par défaut, sans qu'il soit nécessaire de les redemander.

## Livraison et déploiement
- Après chaque mise à jour prête pour Render : fusionner automatiquement,
  puis informer le propriétaire dans le chat ET par e-mail HTML
  (jfrancois.ouoba@gmail.com) : date et heure, identification (dépôt, branche,
  commit, version, lot), périmètre, comment vérifier, à activer, points
  d'attention, reste à faire.
- Commits : auteur ET committer `ShuyahBF <jfrancois.ouoba@gmail.com>`,
  messages et commentaires en français, aucune mention d'IA ni de Co-Authored-By.
- Commentaires clairs sur chaque bloc de code (le propriétaire vient de WinDev).
- Ne jamais commiter, afficher ni envoyer de secret (clés, mots de passe,
  chaînes de connexion) : ils vont uniquement dans les variables
  d'environnement, saisies par le propriétaire.

## Version et lot (règles 1 et 2)
1. À chaque déploiement, le numéro de version ET le numéro de lot sont mis à
   jour (jamais une constante figée qui n'est plus incrémentée).
2. La version et la date/heure de déploiement sont toujours affichées :
   - page de connexion ET portail (barre latérale, en-tête ou pied de page de
     toutes les pages connectées) : « Version X · déployée le JJ/MM/AAAA HH:MM »
     (ex. « Version 1.84 · déployée le 04/10/2026 01:35 ») — sans lot ni commit ;
   - pages d'administration / paramétrage : libellé complet
     « Version X · Lot N · commit · déployée le JJ/MM/AAAA HH:MM »
     (ex. « Version 1.84 · Lot 57.1 · 252c6a7 · déployée le 04/10/2026 01:35 »).
   Règle appliquée à toutes les plateformes déployées sur Render.
- Une seule source par plateforme :
  - SAWALI : `backend/lot.py` (LOT, LOT_LIBELLE), exposé par `/api/version` ;
    version = compteur de déploiements `1.N`. Modifier `lot.py` à chaque
    déploiement force aussi le redéploiement du serveur (Render ne redéploie
    un service à `rootDir` que si un fichier de son dossier change).
  - Ster : `frontend/src/version.js` (VERSION +1 à chaque déploiement,
    LOT = numéro de la PR fusionnée).
  - adLyn : même principe (lot = numéro de la PR fusionnée).
  - beAuthentik : même source (`frontend/src/version.js`, lot = numéro de la PR
    fusionnée) ; suit la règle commune depuis le 04/10/2026 (date et heure de
    compilation ; commit seulement sur les pages d'administration).
  - ALBARKA : `backend/lot.py` (LOT, LOT_LIBELLE) et compteur de déploiements
    `1.N`, exposés par `/api/version` (comme SAWALI).
- Nouveau projet : prévoir dès le départ cette source unique et l'affichage.

## Nouveautés à chaque lot (règle 5, 06/10/2026 : « Ça doit être systématique ! »)
- À CHAQUE lot déployé, la page Paramètres (AdminSettings) présente sa carte « Nouveautés » :
  - SAWALI : ajouter une entrée dans `backend/nouveautes.py` avec le MÊME numéro que `backend/lot.py`
    (titre, description d'une ligne, date, `rubrique` = titre exact de la rubrique des Paramètres).
    Le test `tests/test_regle_nouveautes.py` échoue si le lot courant n'a pas sa carte.
  - Règle du 07/10/2026 : une carte ouvre TOUJOURS la rubrique des Paramètres où se règle la nouveauté,
    jamais l'écran d'utilisation. Si la nouveauté n'a pas encore de rubrique, la créer dans AdminSettings
    (réglages, état, bouton vers l'écran d'utilisation). Seul `lien = "/admin/settings"` reste admis
    (nouveauté de la page Paramètres elle-même) ; le test le vérifie.
- Même principe sur toute plateforme qui possède une page de paramètres / nouveautés.

## Tableaux (règle 3)
- Règle du 29/10/2026 : les NOMBRES (quantités, montants, pourcentages) sont TOUJOURS alignés à DROITE, en-tête de colonne compris (écran : `text-right tabular-nums` ; PDF reportlab : style de paragraphe `alignment=2` ; WinForms : `DefaultCellStyle.Alignment = MiddleRight`).
- Sur TOUT tableau : ligne survolée = fond bleu clair transparent
  (`rgba(56, 189, 248, 0.16)`) ; ligne sélectionnée = fond orange clair
  (`#f6a35b`) avec police blanche.
- Mise en œuvre globale dans le CSS de chaque plateforme ; une ligne est
  sélectionnée si elle porte `ligne-selectionnee`, `aria-selected="true"`,
  `data-selected="true"`, ou si la case à cocher de sa première cellule est cochée.

## Présence auprès de SAWALI (règle 4)
- Toute plateforme ou application que nous créons et déployons (application
  Windows / WinDev, service Windows, serveur web…) a l'OBLIGATION de déclarer
  sa présence à SAWALI, dès sa première version :
  - `POST https://api.sawalismartsystems.com/api/presence-logiciel` au
    démarrage puis toutes les 5 minutes ;
  - corps JSON : `application`, `version`, `deploye_le`, `machine`,
    `utilisateur`, `site`, `systeme`, `demarre_le` (seuls `application`,
    `version` et `machine` sont obligatoires) ;
  - en-tête facultatif `X-Cle-Loois` (clé du support, `LOOIS_SUPPORT_CLE`)
    pour un poste « vérifié » ;
  - envoi en arrière-plan, JAMAIS bloquant ; aucun secret ni donnée
    patient / élève dans le signal.
- Suivi : SAWALI → Plateformes en temps réel → « Postes Windows — versions
  déployées » (poste en ligne si signal < 12 min, version à mettre à jour).
- Modèles : Loois `Loois/Services/PresenceLoois.cs` (C#) ; WinDev : procédure
  `SignalPresenceSawali` + `TimerSys` (envoyée par e-mail le 06/10/2026).

## Sécurité de l'interface (beAuthentik et tout nouveau site)
- Tout champ mot de passe affiche un pictogramme « œil » pour voir / masquer la saisie.
- Captures d'écran interdites sur tout le site : touche Impr. écran neutralisée
  (presse-papiers vidé, écran flouté, message), contenu flouté quand la page perd
  le focus ou est masquée, impression bloquée (page blanche), clic droit / appui
  long / glisser interdits sur les médias. Limite à rappeler : un site web ne peut
  pas bloquer une capture faite par le système ou le téléphone.
- Page de connexion centrée (carte avec logo) avec l'état du serveur
  (« Serveur actif », lent, injoignable) et la version.

## Attentes et chargements
- Toute attente longue (connexion, recherche…) affiche un toast « Patientez… »
  et une jauge circulaire transparente (arc qui tourne), comme sur SAWALI.

## Accès HFSQL (règle 6, 08/10/2026) — tous nos logiciels (Loois, services, WinDev…)
- **Serveur** : lu dans le .ini du logiciel, section `[Serveur]`, clé `Nom:Port`
  (ex : `Nom:Port=jSHUYAH:4900`). Biolog : `C:\BOOT_LOG\Bi@log.ini` ;
  Aizenta : `C:\Boot_Aizenta\Aizenta.ini`. Le .ini est LU, jamais réécrit (ANSI WinDev).
- **Application et base de données** : données par la ligne de commande —
  `/docx=CMC` → Biolog → base `myAurora-CMC` ; `/docx=PHL` → Biolog → base `myAurora`
  (EXCEPTION : sans suffixe) ; `/doc=CMC` → Aizenta (`C:\Boot_Aizenta\Aizenta.ini`) →
  base `myAizenta-CMC` ; `/ekol` → eKOL (serveur lu dans le .ini d'e-Kol) → base `e-KOL`.
  Tester `/docx=` avant `/doc=`. Application donnée par la ligne de commande → choix de
  l'espace de travail GRISÉ dans la fenêtre de connexion.
- **Tables** : ouvertes par le serveur HFSQL ; aucun chemin de fichiers .fic requis.
- **Chaînes de connexion** : déjà testées et fonctionnelles — ne PAS les refaire ;
  on leur passe seulement serveur, port et base.
- **Fournisseur OLE DB** : TOUJOURS `PCSoft.HFSQL` (pilote 32 bits, applications en x86). Toute
  valeur par défaut dans le code = celle de l'App.config testé (le paquet de mise à jour ne livre
  pas App.config).

## Dépôts GitHub des plateformes (règle permanente du propriétaire, 14/10/2026 : « rends-les permanents quelles que soient les sessions »)
Tous les dépôts sont sous le compte GitHub `ShuyahBF`. Quand une demande nomme une plateforme, utiliser CE tableau sans
le redemander. Dépôt absent de la session : `list_repos` (requête « ShuyahBF »), puis `add_repo` (accès « push » pour
modifier), cloner UNE fois (`git clone --depth 1`, délai généreux), puis `register_repo_root`.

| Plateforme | Dépôt | Branche de base / déploiement |
|---|---|---|
| SAWALI | `ShuyahBF/Emergent` | PR vers `render-production` (Render y déploie) |
| ZandGo | `ShuyahBF/zandgo` | `main` |
| Portail e-Kol (élèves et parents) | `ShuyahBF/ekol-portail` | `main` |
| adLyn | `ShuyahBF/telecom-boutique` | `main` |
| beAuthentik | `ShuyahBF/site-meetafrican` | `main` |
| ALBARKA | `ShuyahBF/albarka-portal` | `main` |
| Ster (= DentalCare, confirmé par le propriétaire le 14/10/2026) | `ShuyahBF/dentalcare` | `main` |
| Loois (logiciel Windows) et sa mise à jour | `ShuyahBF/Loois`, `ShuyahBF/Loois-MAJ` | `main` |
| Aizenta (analyse qualité des stocks) | `ShuyahBF/Aizenta-Analyse-Qualit-Gestion-Stocks` | voir ses règles |
| BF Mobility (VTC) | `ShuyahBF/sawali-bfmobility` | `main` |

Autres dépôts utiles : `ShuyahBF/Claude` (règles techniques, `TECHNICAL_RULES.md`), `ShuyahBF/reglesmetier_claude` (règles métier).
Dépôt refusé par le contrôle d'accès de la session (ex. `shuyah-mirror`) : ne pas insister, le dire au propriétaire.

## Dépôts GitHub des plateformes (règle permanente du propriétaire, 14/10/2026 : « rends-les permanents quelles que soient les sessions »)
Tous les dépôts sont sous le compte GitHub `ShuyahBF`. Quand une demande nomme une plateforme, utiliser CE tableau sans
le redemander. Dépôt absent de la session : `list_repos` (requête « ShuyahBF »), puis `add_repo` (accès « push » pour
modifier), cloner UNE fois (`git clone --depth 1`, délai généreux), puis `register_repo_root`.

| Plateforme | Dépôt | Branche de base / déploiement |
|---|---|---|
| SAWALI | `ShuyahBF/Emergent` | PR vers `render-production` (Render y déploie) |
| ZandGo | `ShuyahBF/zandgo` | `main` |
| Portail e-Kol (élèves et parents) | `ShuyahBF/ekol-portail` | `main` |
| adLyn | `ShuyahBF/telecom-boutique` | `main` |
| beAuthentik | `ShuyahBF/site-meetafrican` | `main` |
| ALBARKA | `ShuyahBF/albarka-portal` | `main` |
| Ster (= DentalCare, confirmé par le propriétaire le 14/10/2026) | `ShuyahBF/dentalcare` | `main` |
| Loois (logiciel Windows) et sa mise à jour | `ShuyahBF/Loois`, `ShuyahBF/Loois-MAJ` | `main` |
| Aizenta (analyse qualité des stocks) | `ShuyahBF/Aizenta-Analyse-Qualit-Gestion-Stocks` | voir ses règles |
| BF Mobility (VTC) | `ShuyahBF/sawali-bfmobility` | `main` |

Autres dépôts utiles : `ShuyahBF/Claude` (règles techniques, `TECHNICAL_RULES.md`), `ShuyahBF/reglesmetier_claude` (règles métier).
Dépôt refusé par le contrôle d'accès de la session (ex. `shuyah-mirror`) : ne pas insister, le dire au propriétaire.

## Chargement des pages et gros calculs (règle 7, 15/10/2026 : « C'est une RÈGLE ! »)
Constat e-Kol (lots 33 à 36) : le tableau de bord mettait 37 s en moyenne (jusqu'à 87 s) ; après correction, moins de 1 s.
Cette méthode s'applique à TOUTES les plateformes et à tout projet à venir, dès la première version.
- **Mesurer d'abord** : chaque appel au serveur note sa durée (journal des accès, route « Appels les plus lents » : moyenne,
  5 derniers, dernier, maximum). On corrige la route réellement lente, jamais au hasard. Tout nouveau projet prévoit cette mesure.
- **Jamais d'appel à un service externe lent ou limité DANS la requête d'une page** (géolocalisation d'IP, SMS, WhatsApp, API
  tierce, envoi d'e-mail…) : il part en ARRIÈRE-PLAN (`asyncio.create_task`, tâche planifiée), la page répond tout de suite avec
  la valeur connue ou « en cours d'identification », et le résultat est gardé en cache pour l'affichage suivant.
- **Jamais de boucle N+1** (une lecture de base PAR élève / client / ligne) : lire EN BLOC (une requête par collection, ou une
  agrégation) puis regrouper en mémoire.
- **Gros calculs** (statistiques, totaux, situations, tableaux de bord) : lectures indépendantes lancées EN PARALLÈLE
  (`asyncio.gather`) ; calcul lourd (> 1 s) = cache court (ex. 60 s) ou pré-calcul planifié, jamais refait à chaque clic.
- **Authentification et droits** : lire compte et droits en même temps, pas l'un après l'autre.
- **Index** sur tout filtre fréquent (école/site, type, date) : jamais de parcours complet d'une collection dans une requête de page.
- **Objectif** : toute route d'affichage répond en moins de 1 s côté serveur. Au-delà, on corrige AVANT de livrer ; un appel
  externe en arrière-plan reçoit un test qui prouve que la requête n'attend pas.
- **Écran** : afficher d'abord ce qui est prêt ; une section lente ne doit pas bloquer le reste de la page (chargement séparé).

## Outils de la session et comptes rendus par e-mail (règle 12, 17/10/2026 : « ajoute cette règle partout »)
- **Outils différés** : dans une session, les outils des connecteurs (Gmail, Google Drive, Agenda, Render, GitHub…) apparaissent par leur NOM
  seulement ; ils ne sont utilisables qu'après les avoir chargés avec ToolSearch. AVANT de dire qu'un outil manque, le CHERCHER avec ToolSearch
  (ex. « gmail send message », « google drive create file »). Ne jamais conclure « je n'ai pas l'outil » sans cette recherche.
- **Compte rendu par e-mail** : après chaque livraison, envoyer l'e-mail HTML à jfrancois.ouoba@gmail.com avec l'outil Gmail
  (`mcp__Gmail__send_message`, champ `htmlBody`) : date et heure, identification (dépôt, lot, commit), périmètre, comment vérifier, à activer,
  points d'attention, reste à faire. Ce n'est pas un envoi « à un tiers » : le propriétaire l'a demandé de façon permanente (règle « Livraison et déploiement »).
- **Google Drive** : disponible pour déposer ou lire des documents si le propriétaire le demande ; jamais de secret dans un document.
