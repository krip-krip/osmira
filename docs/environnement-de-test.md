# Environnement de test

## Caméras
- 4 × Panasonic AW-UE150 (modèle d'origine, NDI HX2 seulement).
- Production 1080i50 ; flux IP progressif 1080p50 (ou 1080p25).
- Streaming **SRT(H.265)**, caméra en **listener** :
  `192.168.105.51` à `.54`, port `2020`.
- Réglages visés : CBR, « Motion priority », intervalle d'images clés ~1 s,
  latence SRT ~20 ms ; 1080p50 à 12,8 Mb/s ou 1080p25 à 8,2 Mb/s.

## MediaMTX (PC Windows, 192.168.104.253)
- Se connecte aux caméras en caller ; chemins `cam1` à `cam4`.
- Serveur SRT : port `8890`. Lecture :
  `srt://192.168.104.253:8890?mode=caller&streamid=read:camN`.
- API : port `9997` ; aperçu WebRTC : `8889` (hors projet).

Extrait de configuration utile :

```yaml
api: true
apiAddress: :9997
srt: true
srtAddress: :8890
srtMinLatency: 20ms          # sinon 120 ms par défaut sur toutes les liaisons
pathDefaults:
  sourceOnDemand: false      # caméras connectées en permanence
paths:
  cam1:
    source: srt://192.168.105.51:2020?latency=20   # latence en ms ici
  # cam2..cam4 identiques (.52, .53, .54)
```

Accès à l'API depuis le réseau : élargir les `ips` de l'utilisateur interne
qui porte les permissions `api`/`metrics`/`pprof` (par défaut localhost
seulement), en recopiant l'utilisateur par défaut (publish/read/playback), et
ouvrir le port 9997 dans le pare-feu Windows.

Vérifications utiles :
- `GET /v3/srt/conns/list` : `msReceiveTsbPdDelay`, `msSendTsbPdDelay`, `msRTT`,
  compteurs de pertes/retransmissions des connexions vers les postes.
- `GET /v3/paths/static-sources/get/camN` (versions récentes) : statistiques des
  liaisons caméra → MediaMTX.

## Réseau
- Pi sur site distant, WAN 1 Gb/s, VPN WireGuard géré par NetBird (`wt0`).
- RTT mesuré dans le tunnel : 4,2–4,9 ms.
- Vérifier : `netbird status -d` en P2P (pas Relayed) ; MTU de `wt0` compatible
  avec les paquets SRT (~1360 octets).

## Raspberry Pi (poste OsmiraCam de test)
- Pi 4 Model B Rev 1.5, 1 Go, Raspberry Pi OS Trixie sans bureau.
  Nom `panelTest`, utilisateur `alex`.
- `eth0` (NetworkManager, `netplan-eth0`) : DHCP + secours `192.168.101.50/24`.
- Affichage : `/dev/dri/card0`, écran branché sur `HDMI-A-2` (constaté le
  2026-11-27 ; la maquette utilisait `HDMI-A-1`), 1080p50. `connector = auto`
  dans `agent.toml` prend le premier écran branché.
- CMA : 512 Mo (`dtoverlay=vc4-kms-v3d` par défaut).
- Port 8080 déjà occupé (probablement `talktome-headless`) → `ptzview` sur **8081**.

## Pièges rencontrés
- **Unités de latence SRT** : millisecondes dans les URL `source:` de MediaMTX,
  **microsecondes** dans FFmpeg/mpv (`latency=20000` = 20 ms).
- FFmpeg lancé en arrière-plan : ajouter `-nostdin`, sinon il est suspendu.
- mpv numérote les cartes DRM à partir de 1 (« card 1 » = `/dev/dri/card0`).
- Un seul programme peut tenir l'écran : arrêter mpv avant `ptzview`.
