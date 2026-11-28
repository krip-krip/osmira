# 2026-11-28 — Plusieurs sorties vidéo, essai avec un seul écran

Banc : Pi 4 1 Go `panelTest`, un seul écran (branché sur `HDMI-A-1`), 4 mires
HEVC 1080p ~43 i/s via MediaMTX. ptzview lancé à la main, agent arrêté.

| Configuration | Résultat |
|---|---|
| `outputs = 1` (comme avant) | image, bascule cam1 → cam3 en 32,2 ms, tally/UMD, entrée 3 désactivée puis rétablie ; `/output/2/select/1` → 400 « sortie 1 à 1 » |
| `outputs = 2`, sortie 2 en `auto` | « sortie 2 : pas d'écran » ; sortie 1 sur `HDMI-A-1` ; `/output/2/select/3` accepté et gardé (`active` 3) ; bascule sortie 1 cam1 → cam4 en 22,8 ms ; `/output/3/select/1` → 400 ; ligne de stats `cam1*1 … cam2*2` |
| `outputs = 2`, sortie 1 = `HDMI-A-2` (vide), sortie 2 en `auto` | sortie 1 « pas d'écran », la sortie 2 prend `HDMI-A-1` et bascule (cam1 → cam2 en 40,7 ms) ; `/status.output` = `none` |

- Plans : vidéo sur le plan 91 (primaire), OSD sur le plan 127, comme avant ;
  17 plans utilisables par le CRTC de `HDMI-A-1`.
- CMA libre avec 4 entrées et 2 sorties déclarées (une seule allumée) : 149 Mo.
- Une fois : entrée 2 vue à 79 i/s et 19,7 Mb/s pendant un relevé (le double),
  non reproduit ensuite (~43 i/s). Sans lien probable avec les sorties (le code
  des entrées ne change pas) ; à surveiller.

Reste à faire avec un 2e écran : deux sorties allumées en même temps, même
caméra sur les deux, coût en CMA de la 2e sortie, bascules simultanées.

## Agent : une caméra par sortie (de bout en bout, un seul écran)
- Ancien fichier `state/selection.json` (`{"camera_id": "test4"}`) relu : la
  sortie 1 repart sur `test4`.
- Station passée à 2 sorties dans le Core : l'agent écrit `outputs = 2` et
  `[output2]` dans ptzview.conf et relance ptzview (« sortie 2 : pas d'écran »).
- Matrice, sortie 2 → `test2` : `output 2: showing input 2`, gardé par ptzview
  (`outputs[1].active = 2`) ; sélection enregistrée `{"1": "test4", "2": "test2"}`.
- Matrice, sortie 1 → `test1` : bascule à l'écran en 36,2 ms.
- Station remise à 1 sortie : ptzview relancé avec `outputs = 1`, sortie 1 inchangée.
