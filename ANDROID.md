# ALBARKA sur Android (lot 31)

Le portail ALBARKA est une **application installable** : icône sur l'écran d'accueil, ouverture plein écran,
notifications, et page « Pas de connexion Internet » quand le réseau manque.
L'application charge toujours la dernière version du site : rien à mettre à jour à la main.

## 1. Installer tout de suite (sans Play Store)
Sur le téléphone, avec Chrome : ouvrir https://albarka-bf.com/login puis toucher le bouton **Installer l'application**
(ou menu ⋮ de Chrome, puis *Installer l'application*).

## 2. Fabriquer le fichier Android avec PWABuilder (par clics, sans programmer)
1. Ouvrir **https://www.pwabuilder.com** et saisir l'adresse du site : `https://albarka-bf.com` puis cliquer **Start**.
2. Vérifier que « Manifest » et « Service Worker » sont validés, puis cliquer **Package for stores**, puis **Android**.
3. Renseigner :
   - **Nom de l'application** : `ALBARKA`
   - **Identifiant de package** : `com.sawali.albarka` (à ne plus jamais changer)
   - le reste : garder les valeurs proposées.
4. **Signing key** : choisir **Create new** et laisser PWABuilder créer la clé.
5. Cliquer **Generate**, puis **Download** : un fichier ZIP est téléchargé. Il contient l'application (.apk pour tester
   sur un téléphone, .aab pour le Play Store), le fichier de clé et un petit fichier texte avec les mots de passe de la clé.
6. **Garder précieusement le ZIP** (surtout le fichier de clé et ses mots de passe) dans un endroit sûr : sans cette clé,
   il sera impossible de mettre l'application à jour sur le Play Store. Faire une copie de sauvegarde.

## 3. Donner l'empreinte à Claude (pour supprimer la barre d'adresse)
Sans cette étape, l'application affiche une barre d'adresse en haut.
1. Dans le ZIP, ouvrir le petit fichier texte (`signing-key-info.txt`) et copier la ligne **SHA-256 fingerprint**
   (une suite du type `07:30:35:B9:…`). Si l'application est publiée via la Play Console, copier plutôt l'empreinte SHA-256
   du certificat de signature de l'application (menu *Intégrité de l'application*).
2. **Donner uniquement cette empreinte à Claude** dans le chat : elle sera ajoutée dans
   `frontend/public/.well-known/assetlinks.json` (c'est le fichier qui lie le site à l'application).
3. Après la mise en ligne, réinstaller l'application : la barre d'adresse a disparu.

## Rappel de sécurité
**Ne jamais** envoyer dans le chat ni déposer dans le dépôt GitHub : le fichier de clé (.keystore / .jks),
les mots de passe de la clé, ni le ZIP complet. Seule l'empreinte SHA-256 (qui n'est pas secrète) peut être partagée.

## Contenu technique (pour mémoire)
- `frontend/public/manifest.json` : nom, couleurs, icônes 192, 512 et 512 « maskable », plein écran.
- `frontend/public/sw.js` : notifications + page `offline.html` quand Internet manque (rien d'autre n'est mis en cache).
- `frontend/public/offline.html` : page « Pas de connexion Internet » avec bouton « Réessayer ».
- `frontend/public/.well-known/assetlinks.json` : lien site / application (vide `[]` tant que l'empreinte n'est pas fournie).
- `frontend/src/components/InstallerApplication.jsx` : bouton « Installer l'application » (page de connexion et menu du portail).
- Icônes : tirées du logo ALBARKA (`icone-albarka-1024.png`).
