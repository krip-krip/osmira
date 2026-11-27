# Feuille de route

## Fait
- [x] Maquette du moteur vidéo `ptzview` : 4 flux HEVC 1080p50, bascule
  18–60 ms, calques tally/UMD/NO SIGNAL, API HTTP, reconnexion.
- [x] Choix d'architecture (voir `decisions/`).

## Étape 1 — Mise en place du dépôt
- [ ] Dépôt `osmira` sur GitHub, `ptzview` dans `osmiracam/player/`.
- [ ] Documentation de départ (ce dossier) + `CLAUDE.md`.
- [ ] Protection de `main`.
- [x] CI minimale (compilation de `ptzview`).

## Étape 2 — Conception d'OsmiraCore (sans code)
- [ ] Modèle de données détaillé (`docs/modele-donnees.md`) : site, caméra
  (média + contrôle), poste, profil de manette, droits, tally/UMD.
- [ ] Spécification de l'API REST + SSE (`docs/api.md`).
- [ ] Maquettes des écrans de l'interface web.

## Étape 3 — Premier incrément de bout en bout
- [ ] OsmiraCore minimal : caméras + postes + droits, API, interface web simple.
- [ ] Agent OsmiraCam minimal : récupère sa config, pilote `ptzview`, reçoit
  tally/UMD par SSE.
- [ ] `ptzview` : nombre de caméras configurable, rechargement de la config.

## Étape 4 — Pilotage PTZ
- [ ] Interface des pilotes caméras + fausse caméra pour les tests.
- [ ] Pilote Panasonic (AW-UE150).
- [ ] Entrée manette PS4 USB (`evdev`) + profils de mappage.
- [ ] Sécurité « homme mort ».

## Ensuite
- [ ] Pilotes Sony FR7, Canon.
- [ ] Modules de tally (mélangeur…).
- [ ] Plusieurs sites, relais local.
- [ ] Déploiement : Docker pour le Core, services systemd sur les Pi, CD.

## Questions ouvertes
- Origine des pertes SRT toutes les 12 s (VPN, relais `.252`, PC, MediaMTX ?).
- Latence SRT définitive : 20 ou 40 ms ?
- Débit réel des caméras (~16 Mb/s mesurés vs 12,8 visés).
- Latence de bout en bout à mesurer sur place.
- Stabilité de la CMA sur une endurance de 30 min et plus.
- Comportement de chaque marque de caméra si elle ne reçoit plus de commandes.
- Nom définitif du moteur vidéo (`ptzview` aujourd'hui).
