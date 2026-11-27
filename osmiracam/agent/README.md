# osmiracam-agent — agent du poste OsmiraCam

Programme Python qui tourne sur le Raspberry Pi à côté de `ptzview` :

1. récupère la configuration du poste auprès d'OsmiraCore
   (`GET /api/stations/<id>/config`) et en garde une copie locale
   (`state/config.json`) ;
2. écrit `ptzview.conf` à partir de cette configuration ;
3. lance `ptzview`, le relance s'il s'arrête, et le relance quand la
   configuration change ;
4. suit le flux d'événements du Core (`GET /api/stations/<id>/events`, SSE) :
   - `select` : bascule `ptzview` sur la caméra choisie dans la matrice
     (`/select/N` de l'API locale de `ptzview`, sans relance) ;
   - `config_changed` : récupère tout de suite la nouvelle configuration ;
   - `state` (à chaque connexion) : se remet à jour ;
   - coupure : reconnexion toutes les `events_retry_s` secondes ;
5. garde aussi une copie de la dernière caméra choisie (`state/selection.json`) :
   après un redémarrage, `ptzview` repart sur elle, même sans Core ;
6. vérifie aussi la configuration toutes les `poll_interval_s` secondes, en
   secours du flux d'événements ;
7. si le Core est injoignable, continue avec la dernière configuration et la
   dernière caméra choisie.

Si le Core n'a choisi aucune caméra (ou une caméra que le poste ne peut pas
voir), le poste affiche sa première caméra visible (ADR 0009).

Il envoie aussi son **état** au Core toutes les 5 s (`POST /api/stations/<id>/status`,
c'est son signal de vie) : versions de l'agent et de la config, caméra
affichée, flux reçus par `ptzview` (i/s, débit, résolution, erreurs),
matériel (modèle du Pi, RAM, OS), température, CMA libre. La page Stations du
Core l'affiche (en ligne / hors ligne).

Identifiant du poste : `station_id` dans `agent.toml`, ou à défaut le
**hostname** du Pi.

Chaque connexion SRT est signée avec l'identifiant du poste
(`streamid=read:cam1:::station=panelTest`) : le Core attribue ainsi les
statistiques SRT lues dans MediaMTX au bon poste, même derrière un relais
(ADR 0010). Désactivable avec `tag_srt_streamid = false`.

Pas encore : tally/UMD, manette, pilotage PTZ, deuxième sortie HDMI.

## Changements de configuration sans coupure

Chaque caméra garde son entrée de `ptzview` (`state/slots.json`) : une caméra
retirée libère la sienne (désactivée, aucune tentative de connexion), une
nouvelle prend une entrée libre. À un changement de configuration, l'agent
ne met à jour que les entrées modifiées (`/input/N`, `/label/N`) : l'image à
l'écran n'est pas coupée. `ptzview` n'est relancé que si un réglage global
change (latence SRT, réglages `[ptzview.general]`).

## Limite actuelle de ptzview

`ptzview` a 4 entrées fixes. Les caméras de la configuration les remplissent
dans l'ordre des `position` puis gardent leur entrée ; au-delà de 4, elles
sont ignorées (message dans le journal) ; les entrées libres affichent NO SIGNAL.

## Installation sur le Pi (une fois)

```
curl -LsSf https://astral.sh/uv/install.sh | sh     # installe uv dans ~/.local/bin
cd ~/osmira/osmiracam/player && make                 # compile ptzview (voir son README)
cd ~/osmira/osmiracam/agent && uv sync               # environnement Python de l'agent
cp agent.toml.example agent.toml                     # puis régler core_url (station_id = hostname par défaut)
```

## Lancement (à la main, depuis SSH)

```
killall mpv ffmpeg ptzview 2>/dev/null   # rien d'autre ne doit tenir l'écran
cd ~/osmira/osmiracam/agent
uv run osmiracam-agent -c agent.toml
```

Ctrl+C arrête l'agent, qui arrête `ptzview` proprement. Le journal de
`ptzview` s'affiche dans le même terminal que celui de l'agent.

Côté Core, le poste doit exister et avoir des droits `decode` sur des
caméras. Changer ces droits (ajout, retrait, ordre) est appliqué aussitôt
(relance de `ptzview`, quelques secondes de coupure). Choisir une caméra dans
la matrice bascule sans relance :

```
curl -X PUT http://<core>:8000/api/stations/panelTest/outputs/1/selection \
  -H 'Content-Type: application/json' -d '{"camera_id": "cam2"}'
```

## Développement

```
uv run pytest            # tests (faux Core, faux ptzview : pas besoin de Pi)
uv run ruff check        # style
uv run ruff format       # mise en forme
```
