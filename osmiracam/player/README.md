# ptzview — lecteur 4 × SRT/HEVC pour Raspberry Pi 4 (maquette)

Reçoit et décode en permanence les 4 caméras (HEVC matériel, `rpi-hevc-dec`), affiche
la caméra choisie sur la sortie HDMI (DRM/KMS, sans GPU ni compositeur), dessine
tally + UMD + NO SIGNAL sur un plan matériel séparé, et se pilote par HTTP.

## 1. Installation (une fois)

```
sudo apt update
sudo apt install build-essential pkg-config \
  libavformat-dev libavcodec-dev libavutil-dev \
  libdrm-dev libcairo2-dev libmicrohttpd-dev fonts-dejavu-core curl
apt policy libavcodec-dev        # la version installée doit contenir "+rpt"
```

Copie de l'archive depuis ton poste, puis compilation sur le Pi :

```
scp ptzview.tar.gz alex@panelTest:~
ssh alex@panelTest
tar xzf ptzview.tar.gz && cd ptzview && make
```

## 2. Lancement (à la main, depuis SSH)

Rien d'autre ne doit utiliser l'écran ni les décodeurs :

```
killall mpv ffmpeg 2>/dev/null
cd ~/ptzview
./ptzview ptzview.conf   # (copier ptzview.conf.example en ptzview.conf)
```

Ctrl+C arrête proprement (un 2e Ctrl+C force la sortie). La console du Pi
réapparaît sur l'écran à l'arrêt.

Au démarrage, vérifier dans le journal :

| Ligne | Signification |
|---|---|
| `DRM : HDMI-A-1 1920x1080@50, …` | sortie HDMI en 1080p50 |
| `camN : connecté (srt://…)` | les 4 entrées SRT sont ouvertes |
| `DRM : images 1920x1080 format NV12 modificateur 0x…` | décodage matériel, images SAND |
| `DRM : essai vidéo=plan … : OK` | un plan accepte la vidéo : l'image s'affiche |
| `affichage : première image (cam1)` | premier affichage effectué |

Toutes les 10 s, une ligne d'état : i/s et débit par caméra, CMA libre, RAM, température.

**Si toutes les lignes « essai vidéo=plan … » sont en erreur** (comme le mode overlay
de mpv), l'affichage sur plan matériel n'est pas possible tel quel : envoie le journal,
il faudra passer au rendu GPU.

Diagnostic sans écran : `./ptzview -n ptzview.conf` (décodage + API seulement).

## 3. API HTTP (port 8080)

GET ou POST, au choix. Chaque commande renvoie l'état complet en JSON.

```
P=http://panelTest:8080           # ou l'adresse IP / NetBird du Pi

curl $P/status                    # état (ajouter | jq pour lire)
curl $P/select/2                  # afficher la caméra 2
curl $P/tally/2/pgm               # tally caméra 2 : off | pvw | pgm
curl $P/tally/1/pvw
curl --data 'PLATEAU LARGE' $P/label/2              # texte de la caméra 2
curl -G --data-urlencode 'text=CAM 3 été' $P/label/3  # variante (accents, espaces)
```

Changer une entrée à chaud (sans toucher aux autres ni à l'image à l'écran) :

```
curl --data-urlencode 'url=srt://192.168.104.253:8890?mode=caller&streamid=read:cam5' $P/input/3
curl --data 'url=' $P/input/3          # URL vide : entrée désactivée (aucune connexion)
curl --data 'latency_ms=40' $P/input/3 # latence SRT de cette entrée seulement
```

Chaque entrée a sa latence SRT (`latency_ms` dans `[camN]`, sinon
`srt_latency_ms` de `[general]`) ; la changer ne reconnecte que cette entrée.

Une entrée sans URL (`url =` vide dans la configuration) est désactivée :
état `disabled`, NO SIGNAL si elle est affichée.

`/status` contient, par caméra : `url`, `state` (connecting / connected / streaming /
waiting / disabled), `signal`, `fps`, `mbps`, `connects` (nombre de connexions réussies),
`decode_errors`, `last_error` ; plus `last_switch_ms` et un bloc `system`
(RAM, swap, CMA libre, température).

Les textes et tallies modifiés par l'API ne sont pas réécrits dans le fichier de
configuration (retour aux valeurs du fichier au prochain lancement).

## 4. Tests de bascule à la main

1. `curl $P/status | jq '.cameras[] | {cam,state,fps}'` : les 4 en `streaming`, ~50 i/s.
2. Basculer : `curl -s $P/select/3 >/dev/null`. Le journal affiche
   `bascule cam1 -> cam3 : X ms après la requête`. Attendu : moins de 40 ms
   en 50p (une à deux trames, selon le moment de la requête par rapport au vblank).
3. Bascules rapides en boucle :
   ```
   for i in $(seq 1 50); do for c in 1 2 3 4; do curl -s $P/select/$c >/dev/null; sleep 0.2; done; done
   ```
4. Perte de flux : couper le flux d'une caméra (sortie streaming de la caméra, ou
   câble). La caméra affichée passe en NO SIGNAL sur la dernière image figée ;
   `state` passe à `waiting`, nouvel essai toutes les 2 s ; le message disparaît
   au retour du flux.
5. Endurance 30 min : laisser tourner et surveiller les lignes d'état (CMA libre,
   RAM, température) : elles ne doivent pas dériver.

## 5. Configuration (`ptzview.conf`)

- `srt_latency_ms` : latence par défaut des entrées (`latency_ms` dans `[camN]` la remplace), en **millisecondes** (converti pour FFmpeg, qui attend des µs).
  Ne pas mettre `latency=` dans les URL. Côté MediaMTX : `srtMinLatency: 20ms`.
- `hdmi_mode` : `1920x1080@50`, un numéro de mode, ou `auto`. 50 Hz conseillé
  aussi pour les flux 25p (moins d'attente du vblank).
- `video_plane` : `auto` essaie le plan primaire puis les overlays.
- `extra_hw_frames` : images en plus par décodeur (~3 Mo de CMA chacune).
- `rt_priority = 10` (en root) : threads temps réel, si des saccades apparaissent.

## 6. Dépannage

| Message | Cause probable |
|---|---|
| `modeset impossible : Permission denied` | mpv ou un autre programme tient l'écran |
| `hwaccel « drm » indisponible` | ffmpeg/libav non `+rpt` (`apt policy libavcodec-dev`) |
| `Cannot allocate memory` à la reconnexion | CMA saturée : baisser `extra_hw_frames` à 0 ou 1 |
| `connexion : Input/output error` | MediaMTX injoignable ou chemin `camN` pas prêt |
| `plus de données (timeout)` | flux coupé plus de `stall_timeout_ms` |

## Points connus

- Le démultiplexeur MPEG-TS de FFmpeg livre une image quand la suivante commence :
  environ une trame de latence (20 ms en 50p, 40 ms en 25p).
- Si les caméras envoyaient des images B, le décodeur retiendrait des images :
  à vérifier si la latence mesurée est plus haute que prévu.
