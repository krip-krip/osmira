# Mesures — essai de 30 minutes, chaîne complète (2026-11-27)

18:49 → 19:19 UTC. Core (`fded0ab`) sur le PC `10.7.1.63` en Wi-Fi, collecte
MediaMTX toutes les 5 s ; agent + `ptzview` sur `panelTest` (Pi 4, 1 Go),
4 × H.265 1080p50 via MediaMTX `192.168.104.253` (relais `.252`, NetBird),
latence SRT 20 ms. Bascule depuis la matrice toutes les 3 minutes
(cam1 → cam4 en boucle). Données : page Links (« depuis le démarrage du
Core »), relevés `station_samples`, journal du Pi.

## Liaisons (page Links)

| Liaison | Pertes | Jetés (vu par l'émetteur) | RTT moyen / max | Côté Pi |
|---|---|---|---|---|
| cam1–4 → MediaMTX | 0 % | 0 | 0,8–1,4 / 1,8–2,9 ms | – |
| MediaMTX → `panelTest` (×4) | 7,5–7,8 % | 0 | 5,2–5,8 / 19–23 ms | 49,8 i/s moy., 0 erreur de décodage remontée, 1 reconnexion, 5,2 s sans image |

- Pertes MediaMTX → Pi constantes sur 30 min, rattrapées par les
  retransmissions **côté émetteur**.
- **Mais le Pi jette des paquets** (`RCV-DROPPED … delayed for 10–64 ms`,
  jusqu'à 53 paquets d'un coup) : invisibles dans MediaMTX. Le « 0 jeté » de
  la page Links ne vaut que pour l'émetteur ; il faut les stats SRT côté
  réception (évolution de `ptzview`) pour les compter.

## Bascules depuis la matrice
10 sur 10 réussies ; `ptzview` : 20,6 à 42,1 ms entre la requête et l'image.

## Coupure des 4 flux à 19:01:12 UTC
- `cam4 : plus de données (timeout) : Immediate exit requested`, puis aussitôt
  sur cam1–3 : `EID:… no sockets to check, this would deadlock` et
  `lecture : Unknown error occurred` ; les 4 entrées se déconnectent ensemble.
- Reconnexion de toutes les entrées en 2 à 3 s (cam1–3 à +2,1 s, cam4 à +3,2 s).
- **Hypothèse** (non vérifiée) : dans `ptzview`, l'interruption d'une entrée
  bloquée (délai `stall_timeout_ms`) se propage aux autres (rappel
  d'interruption ou boucle d'attente SRT partagés). Un flux qui cale ne
  devrait couper que lui-même : à examiner dans `ptzview.c`.

## Ressources du Pi (353 relevés)
| | Début | Fin | Min | Max |
|---|---|---|---|---|
| Température | 47,7 °C | 59,9 °C | 47,7 °C | 61,3 °C |
| CMA libre | 37 Mo | 22 Mo | 21 Mo | 178 Mo (instant isolé) |

- Température stabilisée vers 59–61 °C après 5 min.
- **CMA libre basse** : 22–28 Mo la plupart du temps (94–120 Mo lors de la
  maquette du 26/11). Remonte à ~52 Mo après la reconnexion puis redescend
  en ~20 s. Risque d'échec d'allocation (`Cannot allocate memory`) à une
  reconnexion. À comparer avec `extra_hw_frames` réduit (2 → 1 ou 0).

## À faire
- Examiner la propagation de la coupure d'une entrée aux autres dans `ptzview`.
- Publier les stats SRT côté réception dans `ptzview` (paquets jetés au Pi).
- Essai CMA avec `extra_hw_frames = 1` puis `0` ; essai latence 40 ms.
