# 0002 — Décoder en permanence tous les flux, n'en afficher qu'un

- Statut : Accepté
- Date : 2026-11-26

## Contexte
La bascule entre caméras doit être instantanée. Un décodeur vidéo ne peut
produire une image qu'à partir d'une image clé (environ 1 s d'intervalle sur les
caméras).

## Décision
Le Pi reçoit et décode **en continu** tous les flux qu'il est autorisé à
afficher ; il n'en affiche qu'un. Basculer = afficher la dernière image déjà
décodée de l'autre caméra, au rafraîchissement suivant.

## Options écartées
- **Changer la source d'un chemin MediaMTX via l'API** : MediaMTX coupe la
  connexion du lecteur → 1 à 3 s de noir.
- **Commutateur sans ré-encodage côté serveur** (recollage aux images clés) :
  bascule lente (attente d'image clé), latence ajoutée.
- **Mélangeur qui ré-encode** (OBS, etc.) : trop de latence.
- **Un seul flux décodé à la fois sur le Pi** : attente d'une image clé à chaque
  bascule.
- **H.264** : le décodeur H.264 du Pi 4 plafonne à un flux 1080p60 → passage en H.265.

## Conséquences
- Capacité limitée par le décodeur HEVC (classe 4Kp60) : 4 flux 1080p50 ≈ 83 %
  de sa capacité ; en 25p, théoriquement 8, limité en pratique par la CMA
  (~90 Mo par décodeur).
- OsmiraCore doit connaître la capacité de chaque poste et ne pas lui attribuer
  plus de flux à décoder qu'il ne peut en traiter.
