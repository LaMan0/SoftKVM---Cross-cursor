# SoftKVM

Utilisez **une seule souris et un seul clavier** sur plusieurs ordinateurs du même réseau local. Quand le curseur sort par le bord d'un écran, il passe automatiquement sur l'ordinateur voisin, et le clavier le suit.

- Windows 10/11 : un fichier `SoftKVM.exe`, aucune installation.
- macOS (Monterey 12.7.6 visé) : un lanceur `SoftKVM-mac.command` à double-cliquer (voir ci-dessous).

## Lancer sur Mac (double-clic)

1. Installez Python 3.12 ou 3.13 depuis [python.org](https://www.python.org/downloads/) (l'installeur officiel inclut Tk, nécessaire à l'interface).
2. Décompressez `SoftKVM-mac.zip`.
3. Double-cliquez sur `SoftKVM-mac.command`. Au premier lancement, les dépendances sont installées dans `~/.softkvm-venv` (une minute environ).
4. Accordez les deux autorisations demandées par macOS (voir *Autorisations macOS* plus bas), puis relancez.

Si macOS refuse d'ouvrir le fichier (« non autorisé »), ouvrez le Terminal dans le dossier et lancez `chmod +x SoftKVM-mac.command`, puis double-cliquez à nouveau.

## Utilisation

1. Lancez SoftKVM sur **tous** les ordinateurs.
2. Saisissez **le même mot de passe commun** partout.
3. Sur l'ordinateur qui a le clavier et la souris (le **serveur**) :
   - onglet *Serveur* → « Démarrer le serveur » ;
   - l'adresse IP à utiliser sur les autres PC s'affiche.
   - La zone de disposition montre ce PC et chaque client connecté. Un nouveau client est placé à droite du PC serveur. Glissez les écrans pour les placer comme sur votre bureau : le curseur passe par les bords collés.
   - « Retirer l'écran sélectionné » enlève un écran de la disposition.
4. Sur chaque autre ordinateur (le **client**) :
   - onglet *Client* → saisissez l'adresse IP du serveur, le port (24800 par défaut) et le nom de ce PC (affiché sur le serveur) → « Connecter ».
   - Le serveur doit être démarré avant.
5. Déplacez la souris vers le bord de l'écran où vous avez placé l'autre PC : elle y passe. Pour revenir, ramenez-la vers le bord opposé.

Les deux PC doivent être sur le même réseau local (Wi-Fi ou filaire). Le trafic n'est jamais envoyé sur Internet, et le mot de passe n'est jamais transmis en clair (authentification HMAC-SHA256).

### Pare-feu Windows

Au premier lancement du serveur, Windows demande l'autorisation d'accès réseau : acceptez pour les réseaux privés. Sinon, ouvrez le port TCP 24800 (ou celui que vous avez choisi).

### Raccourcis entre Windows et macOS

Entre les deux systèmes, **Cmd et Ctrl sont échangés** automatiquement : Cmd+C sur un Mac donne Ctrl+C sur Windows.

## Autorisations macOS (obligatoires)

SoftKVM utilise deux autorisations que macOS demande explicitement :

- **Confidentialité et sécurité → Surveillance de l'entrée** (Input Monitoring) : pour lire le clavier et la souris quand SoftKVM est au premier plan ou en arrière-plan.
- **Confidentialité et sécurité → Accessibilité** : pour déplacer le curseur et envoyer les touches.

Ajoutez SoftKVM dans ces deux listes, puis redémarrez l'application.

## Compilation

PyInstaller ne sait pas fabriquer un exécutable pour une autre plateforme : construisez **sur le système cible**.

### Windows (`SoftKVM.exe`)

```bat
python -m pip install -r requirements.txt pyinstaller
python build.py
```

Résultat : `dist\SoftKVM.exe`.

### macOS 12.7.6 Monterey (`SoftKVM.app`)

Pour fabriquer une application `.app` autonome, sur le Mac, avec Python 3.12 ou 3.13 installé depuis python.org (la compatibilité avec Monterey n'a pas encore été vérifiée sur un Mac réel) :

```bash
python3 -m pip install -r requirements.txt pyinstaller
python3 build.py
```

Résultat : `dist/SoftKVM.app`. Pour le partager, compressez-le en zip. Les autorisations macOS ci-dessus doivent être accordées sur chaque Mac.

## Journal

En cas de problème, le détail est écrit dans `softkvm.log` dans votre dossier personnel (`~`).

## Tests

```bash
python -m unittest discover -s tests -t .
```

Les tests couvrent le protocole (authentification, format des messages, touches), la disposition des écrans, les passages de bord et un échange serveur/client complet sur localhost avec de faux adaptateurs de capture et d'injection.

## Limitations connues

- Testé sur une seule machine Windows. Le passage réel entre deux ordinateurs et le lanceur macOS n'ont pas encore été vérifiés sur du matériel.
- Un seul serveur à la fois ; le client se connecte à un serveur, pas à plusieurs.
- Les touches spéciales propres à un seul OS (codes virtuels) ne sont pas transmises entre Windows et macOS.
