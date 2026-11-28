# 2026-11-28 — Nombre d'entrées réglable : 2, 4, 5 et 6 flux sur Pi 4

Banc : Pi 4 1 Go `panelTest`, CMA 512 Mo, mires HEVC 1920×1080 à ~43 i/s et
~10 Mb/s (`test1..test4` via MediaMTX ; les entrées 5 et 6 relisent `test1` et
`test2`), latence SRT 20 ms. ptzview lancé à la main, agent arrêté, écran HDMI
actif. Relevé après **25 s** par configuration (pas une endurance).

| `cameras` | Entrées en `streaming` | i/s par entrée | CMA libre | RAM disponible |
|---|---|---|---|---|
| 2 | 2/2 | 42,4–42,7 | 189 Mo | 584 Mo |
| 4 | 4/4 | 42,3–43,0 | 128 Mo | 503 Mo |
| 5 | 5/5 | 42,6–43,8 | 99 Mo | 462 Mo |
| 6 | 6/6 | 42,5–43,8 | 85 Mo | 424 Mo |

- Routes hors limites : `/select/N+1` → 400 « caméra 1 à N » ; `[cam3]`, `[cam4]`
  signalées comme ignorées avec `cameras = 2`.
- Bascule vers l'entrée 5 : 36,4 ms (5 entrées), 33,9 ms (6 entrées).
- Coût CMA observé : environ 15 à 30 Mo par décodeur supplémentaire, bien moins
  que les ~90 Mo estimés le 26/11 (`2026-11-26-maquette-pi4.md`) ; à confirmer.

## À retenir
Sur ces mires (1080p, 43 i/s, 10 Mb/s), 6 flux tiennent 25 s sans perte d'images.
Ce n'est **pas** la preuve que 6 flux 1080p50 de vraies caméras (~16 Mb/s)
tiennent : il faut une endurance de 30 min, des flux à 50 i/s et le débit réel.
Retour à l'agent (`slots = 4`) : `cameras = 4` écrit dans ptzview.conf, 4 entrées.
