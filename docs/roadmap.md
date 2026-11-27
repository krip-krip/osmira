# Feuille de route

## Fait
- [x] Maquette du moteur vidéo `ptzview` : 4 flux HEVC 1080p50, bascule
  18–60 ms, calques tally/UMD/NO SIGNAL, API HTTP, reconnexion.
- [x] Choix d'architecture (voir `decisions/`).

## Étape 1 — Mise en place du dépôt
- [ ] Dépôt `osmira` sur GitHub, `ptzview` dans `osmiracam/player/`.
- [ ] Documentation de départ (ce dossier) + `CLAUDE.md`.
- [x] Protection de `main` (PR obligatoire, job `build` requis).
- [x] CI minimale (compilation de `ptzview`).

## Étape 2 — Conception d'OsmiraCore (sans code)
- [x] Modèle de données détaillé (`docs/modele-donnees.md`) : site, caméra
  (média + contrôle), poste, profil de manette, droits, tally/UMD.
- [x] Spécification de l'API REST + SSE (`docs/api.md`) : incrément 1
  détaillé, SSE et signal de vie esquissés.
- [x] Pile technique du Core (ADR 0008).
- [ ] Maquettes des écrans de l'interface web.

## Étape 3 — Visualisation de bout en bout (priorité)
But : voir les caméras sur le Pi, choisir celles d'une station et la caméra
affichée depuis le Core. Pas de pilotage PTZ à cette étape.
- [x] OsmiraCore : API caméras, stations (postes) et droits.
- [x] OsmiraCore : `GET /api/stations/{id}/config` versionnée (média seul).
- [x] OsmiraCore : caméra affichée par sortie (matrice) + flux SSE (`select`,
  `config_changed`).
- [x] Agent OsmiraCam minimal : récupère sa config, la garde en local, lance
  `ptzview` et le relance quand la config change.
- [x] Agent : écoute le SSE et bascule `ptzview`.
- [x] Interface web : matrice de bascule (sources en colonnes, sorties des
  stations en lignes).
- [ ] Interface web : pages caméras, stations, droits.
- [ ] Stats SRT : collecte MediaMTX, signal de vie des Pi, page Liaisons
  (courbes uPlot, sessions de mesure, export CSV).
- [ ] `ptzview` : nombre de caméras configurable, rechargement de la config
  sans redémarrage.
- [ ] Tally/UMD par SSE.

## Étape 4 — Pilotage PTZ (plus tard ; prévu dans le modèle)
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
