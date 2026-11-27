# Mesures — maquette OsmiraCam sur Raspberry Pi 4 (2026-11-26)

Matériel : Pi 4 Model B Rev 1.5, 1 Go, Raspberry Pi OS Trixie sans bureau,
FFmpeg/libav `7.1.5 +rpt2`. 4 × Panasonic AW-UE150, SRT/H.265 1080p50 via
MediaMTX (PC Windows), VPN NetBird. Écran HDMI 1080p50.

## 1. Décodage HEVC matériel
- `ffmpeg -hwaccel drm` : `Hwaccel V4L2 HEVC stateless … swfmt rpi4_8 ; V4L2fmt Nc12`,
  tampons DMABuf → décodage matériel zéro copie confirmé.
- 1 flux : temps réel (`speed=1.0x`, 50 i/s).
- 4 flux simultanés (mpv + 3 ffmpeg) : temps réel sur plus de 3 min
  (`speed=1.01x`, flux synchrones à une image près).

## 2. Affichage
- mpv `--vo=gpu` par défaut : trop lent en 1080p50 (tampon SRT saturé,
  « No room to store incoming packet »).
- mpv `--profile=fast` : fluide.
- mpv `--gpu-hwdec-interop=drmprime-overlay` : refusé (`Failed to commit atomic
  request`, EINVAL, écran noir).
- `ptzview` : vidéo sur le plan primaire 91, OSD sur le plan 127 → **accepté**.
  Images `NV12`, modificateur `0x0700000000000004` (SAND128).
- Carte d'affichage : `/dev/dri/card0`, connecteur `HDMI-A-1`, mode 1080p50
  disponible (mode 5).

## 3. Ressources

| Configuration | CPU | RAM disponible | CMA libre (sur 512 Mo) |
|---|---|---|---|
| 4 processus (mpv + 3 ffmpeg) | ~50 % libre | ~200 Mo, 117 Mo en swap | 41 Mo |
| `ptzview` (4 flux) | non mesuré | 465–493 Mo | 94–120 Mo |

- WireGuard coûte cher en CPU (`napi/wt0` ~18 % + `wg-crypt` ~30 % cumulés pour ~64 Mb/s).
- CMA : baisse par paliers de 5–7 Mo, **un seul palier par décodeur**, à sa
  première perte d'image de référence ; ensuite stable (~94 Mo). Interprétation :
  la réserve d'images du décodeur grandit une fois. À confirmer en endurance.
- Estimation : ~90 Mo de CMA par décodeur HEVC 1080p.
- Température : 51 °C au démarrage → ~61–62 °C stabilisé après 10 min ; `throttled=0x0`.

## 4. Bascule entre caméras
- 18 à 60 ms entre la requête HTTP et l'affichage de la nouvelle image
  (médiane ~33 ms, soit 1 à 3 trames à 50 Hz).
- Composantes : attente du rafraîchissement suivant (0–20 ms) + redessin complet
  des calques par cairo et copie de 8 Mo à chaque bascule. Amélioration possible :
  calques préparés à l'avance par caméra (−10 à 15 ms estimés, +32 Mo de CMA).
  Jugé satisfaisant en l'état.

## 5. Réseau et SRT
- MediaMTX → Pi : `msReceiveTsbPdDelay` = `msSendTsbPdDelay` = 20 ms sur les 4
  connexions (`srtMinLatency: 20ms` pris en compte). RTT mesuré 4,2–4,9 ms
  (et non 3 ms) → 20 ms ≈ 4,4 × RTT, juste au-dessus du minimum conseillé.
- Le Pi apparaît côté MediaMTX en `192.168.104.252` : probable relais NetBird
  (routing peer) qui masque l'adresse. Saut supplémentaire à vérifier.
- Débit vidéo mesuré : ~16 Mb/s par caméra (réglage visé : 12,8 Mb/s CBR). À vérifier.
- **Pertes `RCV-DROPPED` périodiques** : 19 à 35 paquets (~20 ms de flux), une ou
  deux connexions à la fois, à des instants multiples exacts de **12 s**, toujours
  à la même fraction de seconde. → cause périodique sur le trajet (VPN, relais,
  PC, MediaMTX), pas du bruit aléatoire.
  Effet : image dégradée jusqu'à l'image clé suivante (≤ 1 s).

## 6. Non mesuré
- Latence de bout en bout (glass-to-glass) : nécessite une présence sur place.
- Endurance 30 min complète.
- CPU de `ptzview`.

## Actions issues de ces mesures
- Ping rapproché vers MediaMTX puis vers `.252` pour localiser le blocage de 12 s.
- Essai de latence SRT à 40 ms (Pi + `srtMinLatency`).
- Endurance 30 min en surveillant la CMA libre.
- Vérifier le débit configuré sur les caméras.
