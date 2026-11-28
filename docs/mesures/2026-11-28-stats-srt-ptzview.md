# 2026-11-28 — Stats SRT côté réception dans ptzview (ADR 0013)

Pi `paneltest` (Pi 4, Trixie, FFmpeg `+rpt`, libsrt 1.5.4 gnutls).
Les caméras n'alimentaient pas MediaMTX ce jour-là (chemins « not ready »).
L'essai a donc utilisé une mire envoyée depuis le PC (10.7.1.63) : `ffmpeg`
testsrc2 1280x720 25p, libx265 ultrafast, 4 Mb/s, latence SRT 20 ms. Les
entrées ont été changées à chaud par `/input/N`.

| Entrée | Mode ptzview | Résultat `/status` → `srt` |
|---|---|---|
| 3 | caller → PC:9000 (listener) | rtt 2,4 ms, 4,54 Mb/s, latence 20 ms, 6438 paquets, 0 perdu / 0 jeté |
| 4 | listener :9001 ← PC (caller) | rtt 2,0 ms, 4,69 Mb/s, latence 20 ms, 5253 paquets, 0 perdu / 0 jeté |

- Les deux façons d'ouvrir une entrée (`srt_connect`, `srt_accept`) sont bien
  captées.
- Entrée 3 désactivée (`url=`) : son bloc `srt` passe à `null`. L'entrée 4
  continue sans se reconnecter (paquets 9080 → 11111 en 5 s, `connects` = 1,
  aucun « no sockets to check ») : pas de régression de l'ADR 0012.
- Compilation stricte (`-Wall -Wextra -Werror`) sans avertissement.

À faire avec les vraies caméras : comparer les pertes vues par MediaMTX
(émetteur) et par le Pi (récepteur, `lost`/`dropped`) sur la liaison via
`.252`.
