# Osmira — instructions pour Claude Code

## Le projet

Osmira est un système de production vidéo à distance, construit par modules.
Premier module : **OsmiraCam** — un Raspberry Pi par cadreur, qui affiche une
caméra PTZ choisie parmi plusieurs (latence minimale, bascule instantanée) et
pilote cette caméra avec une manette. **OsmiraCore** est le serveur central qui
configure les postes OsmiraCam et leur envoie tally et UMD.

Vision et contraintes : @docs/vision.md
Architecture : @docs/architecture.md

## Langue et façon de travailler

- Réponds en français. Code, noms de variables et messages de commit en anglais ;
  commentaires et documentation en français.
- L'utilisateur est technicien broadcast, à l'aise en Linux et ligne de commande,
  débutant en git et peu à l'aise en C. Explique les commandes git avant de les
  lancer, en une ligne.
- Commence chaque fonctionnalité en plan mode : propose un plan, attends la
  validation avant de modifier des fichiers.
- Petites étapes testables. Une fonctionnalité = une branche = une PR.
- Pas de nouvelle dépendance ni de changement d'architecture sans le proposer d'abord.

## Règles d'architecture (ne pas enfreindre)

- Les commandes PTZ vont **directement du Pi à la caméra**. Elles ne passent
  jamais par OsmiraCore.
- La vidéo va caméras → MediaMTX → Pi. Elle ne passe jamais par OsmiraCore.
- OsmiraCore sert uniquement à la configuration, aux droits, au tally et à l'UMD.
  Il peut être loin (VPS) : rien de temps réel ne doit en dépendre.
- Si OsmiraCore est injoignable, le Pi continue avec sa dernière configuration
  enregistrée (image + pilotage caméra).
- Communication Pi ↔ OsmiraCore : API REST + flux d'événements SSE. Le Pi initie
  toujours la connexion. Pas de MQTT (voir ADR 0005).
- Les commandes PTZ sont des vitesses : toute perte de manette, plantage de
  l'agent ou coupure doit envoyer un **stop** à la caméra.
- Les marques de caméras et les types de manettes sont des modules
  interchangeables (pilotes, profils) : ajouter une marque ne doit pas toucher
  au reste du code.
- Le moteur vidéo (`ptzview`, en C) est une boîte noire pilotée en HTTP local.
  On le modifie rarement et seulement si nécessaire.
- Avant de reproposer une piste, vérifier qu'elle n'a pas été écartée dans
  `docs/decisions/`.

## Organisation du dépôt

```
osmiracam/player/   moteur vidéo ptzview (C : FFmpeg +rpt, DRM/KMS, cairo, libmicrohttpd)
osmiracam/agent/    agent du Pi (Python) : manette, pilotes caméras, lien OsmiraCore
osmiracore/         serveur central (Python, FastAPI) + interface web
docs/               vision, architecture, decisions/ (ADR), mesures/, roadmap
```

## Commandes

- Moteur vidéo : `cd osmiracam/player && make` (sur le Pi : paquets listés dans
  son README ; doit compiler sans avertissement).
- Compilation stricte, identique à la CI :
  `cd osmiracam/player && CFLAGS="-O2 -g -Wall -Wextra -Werror" make`
  (CFLAGS par l'environnement, pas en argument de `make`).
- CI GitHub (`.github/workflows/build-player.yml`) : compile `ptzview` sur
  ubuntu-latest à chaque PR et sur `main`. FFmpeg y est standard (sans `+rpt`) :
  la CI vérifie la compilation, pas le fonctionnement sur le Pi.
- Python (agent, core) : à définir lors de leur création (pytest, ruff).
  Mettre à jour cette section dès que les commandes existent.

## Conventions

- Python 3.11+, typage (type hints) partout, `ruff` pour le style, `pytest`.
- Séparer la logique du matériel : fausse caméra et fausse manette pour les
  tests, afin que la CI GitHub tourne sans Pi ni caméra.
- Commits au format Conventional Commits : `feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, `ci:`, `chore:`.
- Aucun secret dans git (identifiants caméras, jetons des Pi) : fichier
  `.example` versionné, vrai fichier dans `.gitignore`.
- Quand une décision change, mettre à jour ou ajouter un ADR dans la même PR.
- Les résultats de tests sur le matériel vont dans `docs/mesures/`.

## Matériel de référence

Raspberry Pi 4, 1 Go de RAM, Raspberry Pi OS Trixie sans bureau. Mémoire CMA
limitée : chaque décodeur HEVC coûte de l'ordre de 90 Mo de CMA. Capacité :
4 flux 1080p50 maximum. Détails : `docs/environnement-de-test.md` et `docs/mesures/`.
