# 2026-11-28 — Non-régression de `ptzview` découpé en modules (ADR 0014)

Banc : Pi 4 1 Go `panelTest`, 4 mires HEVC 1080p (`test1..test4`) via MediaMTX,
latence SRT 20 ms, agent OsmiraCam en marche (ptzview relancé par l'agent).

## Compilation
- `CFLAGS="-O2 -g -Wall -Wextra -Werror" make` sur le Pi : aucun avertissement.
- `nm -D ptzview` : `srt_cleanup`, `srt_connect`, `srt_accept` exportées (ADR 0012, 0013).

## Fonctionnement (binaire échangé à chaud, l'agent relance ptzview)
| Essai | Résultat |
|---|---|
| 4 entrées connectées | oui, ~43 i/s chacune (comme avant : la mire tourne à ~43 i/s) |
| `/status` : mêmes champs qu'avant | oui (racine, caméras, `system`), bloc `srt` rempli |
| Bascule `/select` | 32,0 ms, 39,7 ms, 37,1 ms |
| `/tally/2/pgm`, `/label/2` | appliqués |
| `/input/3` vide puis URL d'origine | entrée 3 `disabled` puis `streaming`, les 3 autres sans coupure |
| Routes inconnues / caméra hors limites | 404 et 400 avec les mêmes messages |

Conclusion : comportement identique à la version en un seul fichier.
