# 0005 — Communication Core ↔ postes : REST + SSE (pas MQTT)

- Statut : Accepté (noms des routes passés en anglais par l'ADR 0008 :
  `/api/stations/{id}/config`, `/events`, `/status`)
- Date : 2026-11-26

## Contexte
OsmiraCore doit envoyer à chaque poste sa configuration, le tally et l'UMD, et
connaître l'état des postes. Le Core peut être sur un VPS ; les postes sont
derrière NAT/VPN. L'utilisateur est à l'aise avec les API HTTP et `curl`.

## Décision
API REST + flux d'événements **SSE** (Server-Sent Events), servis par FastAPI :
1. `GET /api/postes/<id>/config` : configuration complète versionnée, enregistrée
   en local par le poste ;
2. `GET /api/postes/<id>/events` (SSE, connexion permanente) : `config_changed`,
   `tally`, `umd`… ;
3. `POST /api/postes/<id>/etat` toutes les quelques secondes : état + signal de vie ;
4. après coupure : reconnexion, nouvelle config si la version a changé.
Le poste initie toujours la connexion. La même API sert l'interface web et les
futurs modules (ex. `POST /api/tally`).

## Options écartées
- **MQTT (broker Mosquitto)** : publication-abonnement, messages retenus,
  « testament » très adaptés, mais composant de plus et modèle moins familier ;
  les modules ne peuvent pas se parler en direct sans lui (acceptable : le Core
  est le point central voulu).
- **REST seul avec interrogation en boucle** : tally retardé de l'intervalle
  d'interrogation, requêtes inutiles multipliées par le nombre de postes.
- **WebSocket** : bidirectionnel inutile ici (pas de PTZ via le Core) ; SSE est
  du HTTP pur, testable avec `curl -N`, avec reconnexion prévue par le standard.
- **gRPC** : lourd pour le besoin.

## Conséquences
- Détection des postes déconnectés par absence de signal de vie (à gérer).
- Configuration versionnée obligatoire pour la resynchronisation.
- Tally traversant Internet si le Core est distant : quelques dizaines de ms ;
  relais local par site possible plus tard sans changer l'API.
