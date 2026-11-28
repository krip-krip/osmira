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

## Essai par MediaMTX avec 4 mires (même jour, plus tard)

4 mires `mire-srt.ps1` sur le PC MediaMTX (testsrc2 1080p, HEVC `hevc_qsv`,
12 Mb/s) publiées sur `test1`–`test4`. Les 4 entrées de ptzview les lisent par
le relais `.252` (`/input/N`, Core arrêté). Mesure sur 60 s, écarts des
compteurs `srt` de `/status` :

| Entrée | Latence SRT | Perdus (récepteur) | Retransmis | **Jetés** | En retard |
|---|---|---|---|---|---|
| 1 | 20 ms | 5218 (7,6 %) | 5972 | **173** | 1495 |
| 2 | 20 ms | 4620 (6,8 %) | 5398 | **198** | 1531 |
| 3 | 40 ms | 5255 (7,7 %) | 6048 | **144** | 1319 |
| 4 | 80 ms | 5570 (8,1 %) | 6051 | **20** | 1204 |

RTT 4,8–5,2 ms, 12,2 Mb/s reçus par entrée, ~69 000 paquets par entrée.

- Le Pi voit les mêmes 7–8 % de pertes que MediaMTX le 27/11 : elles sont
  réelles sur la liaison MediaMTX → Pi (via `.252`), pas un artefact de
  l'émetteur.
- À 20 ms, ~3 paquets jetés par seconde et par flux : image abîmée.
  40 ms n'aide presque pas (144). Il faut 80 ms pour descendre à 20 jetés par
  minute. Les pertes arrivent donc par rafales plus longues que quelques RTT.
- `decode_errors` reste à 0 malgré les paquets jetés : le décodeur ne signale
  rien. Seul `srt.dropped` montre les dégâts.
- ~43 i/s reçus au lieu de 50 sur les 4 entrées, à vérifier côté mires
  (`speed=` de ffmpeg sur le PC Windows).

Conclusion provisoire : avant de choisir la latence, trouver l'origine des
pertes sur le chemin `.252` (la question ouverte « pertes toutes les 12 s »).

## Les deux vues dans le Core (même jour, 12:50 UTC)

Caméras `test1`–`test4` déclarées dans le Core, latence 20 ms, 2 minutes,
résumé de la page Links (liaison MediaMTX → panelTest) :

| Chemin | Pertes MediaMTX | Jetés MediaMTX | Pertes Pi | **Jetés Pi** |
|---|---|---|---|---|
| test1 | 1,19 % | 0 | 0,73 % | **34** |
| test2 | 2,30 % | 0 | 1,79 % | **43** |
| test3 | 1,26 % | 0 | 0,88 % | **20** |
| test4 | 1,39 % | 0 | 1,36 % | **36** |

- Le « dropped » de MediaMTX (émetteur) reste à 0 alors que le Pi jette des
  paquets : seule la vue du récepteur montre l'image abîmée.
- Pertes plus faibles qu'à 12:30 (7–8 %) : elles varient fortement dans le
  temps, à suivre sur les courbes.
