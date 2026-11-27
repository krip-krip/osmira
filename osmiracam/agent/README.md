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

Pas encore : tally/UMD, manette, pilotage PTZ, deuxième sortie HDMI.

## Limite actuelle de ptzview

`ptzview` a 4 entrées fixes. Les caméras de la configuration les remplissent
dans l'ordre des `position` ; au-delà de 4, elles sont ignorées (message dans
le journal) ; les entrées libres affichent NO SIGNAL.

## Installation sur le Pi (une fois)

```
curl -LsSf https://astral.sh/uv/install.sh | sh     # installe uv dans ~/.local/bin
cd ~/osmira/osmiracam/player && make                 # compile ptzview (voir son README)
cd ~/osmira/osmiracam/agent && uv sync               # environnement Python de l'agent
cp agent.toml.example agent.toml                     # puis régler core_url et station_id
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
