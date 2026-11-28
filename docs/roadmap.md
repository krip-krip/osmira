# Feuille de route

## Fait
- [x] Maquette du moteur vidéo `ptzview` : 4 flux HEVC 1080p50, bascule
  18–60 ms, calques tally/UMD/NO SIGNAL, API HTTP, reconnexion.
- [x] Choix d'architecture (voir `decisions/`).

## Étape 1 — Mise en place du dépôt
- [x] Dépôt `osmira` sur GitHub, `ptzview` dans `osmiracam/player/`.
- [x] Documentation de départ (ce dossier) + `CLAUDE.md`.
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
- [x] Interface web : matrice de bascule (caméras en lignes, sorties des
  stations en colonnes, repérées par l'identifiant de la station).
- [x] Interface web : pages caméras, stations, droits.
- [x] État des postes : signal de vie de l'agent (versions, matériel, flux),
  en ligne / hors ligne dans les pages Stations et Matrice.
- [x] Paramètres média des caméras en « auto » (format reçu remonté par les
  postes ; codec via MediaMTX avec les stats SRT).
- [x] Stats SRT : collecte dans MediaMTX (2 liaisons par image), postes
  reconnus par leur streamid, codec des caméras (ADR 0010).
- [x] Historique des liaisons (paires de bouts, liaisons directes par les
  relevés des postes) et page Links (période, tableau, courbes uPlot).
- [x] Mesures système de chaque poste (CPU, température, alimentation, RAM,
  CMA, réseau, processus) et page par station avec courbes.
- [ ] Sessions de mesure (protégées de la purge) et export CSV.
- [x] `ptzview` : publier les stats SRT côté réception (ADR 0013), remontées
  par l'agent.
- [x] Core : stocker et afficher les stats SRT côté réception (pages Links,
  station).
- [x] `ptzview` : changement d'une entrée à chaud (`/input/N`), entrées
  désactivées ; l'agent ne touche que les entrées modifiées.
- [x] `ptzview` découpé en modules, indépendant du matériel (ADR 0014).
- [x] `ptzview` : nombre de caméras configurable (`cameras`, `slots` de l'agent).
- [x] `ptzview` : plusieurs sorties vidéo (`outputs`, `/output/M/select/N`),
  essayé avec un seul écran.
- [x] Agent : une caméra par sortie (sélections du Core pour chaque sortie).
- [ ] Essai à deux écrans (deux sorties HDMI du Pi 4).
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
  Premier relevé (2026-11-27) : 0 % caméras → MediaMTX, 7–8,5 % MediaMTX → Pi
  (via `.252`), rattrapées par les retransmissions (voir `mesures/`).
- Latence SRT définitive : 20 ou 40 ms ?
- Débit réel des caméras (~16 Mb/s mesurés vs 12,8 visés).
- Nombre de flux réels par Pi 4 : 6 mires 1080p ~43 i/s tiennent 25 s (CMA libre
  85 Mo), à confirmer en endurance à 50 i/s (voir `mesures/2026-11-28-nombre-de-cameras.md`).
- Latence de bout en bout à mesurer sur place.
- Stabilité de la CMA sur une endurance de 30 min et plus. Essai du 27/11 :
  CMA libre 21–28 Mo (basse), coupure simultanée des 4 flux quand un seul cale
  (défaut libsrt 1.5.4, contourné : ADR 0012) ; voir `mesures/2026-11-27-endurance-30min.md`.
- Comportement de chaque marque de caméra si elle ne reçoit plus de commandes.
- Nom définitif du moteur vidéo (`ptzview` aujourd'hui).
