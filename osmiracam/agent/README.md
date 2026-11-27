# osmiracam-agent — agent du poste OsmiraCam

Programme Python qui tourne sur le Raspberry Pi à côté de `ptzview` :

1. récupère la configuration du poste auprès d'OsmiraCore
   (`GET /api/stations/<id>/config`) et en garde une copie locale
   (`state/config.json`) ;
2. écrit `ptzview.conf` à partir de cette configuration ;
3. lance `ptzview`, le relance s'il s'arrête, et le relance quand la
   configuration change (vérifiée toutes les `poll_interval_s` secondes) ;
4. si le Core est injoignable, continue avec la dernière configuration
   (au démarrage comme en cours de route).

Pas encore : bascule depuis la matrice du Core (SSE), tally/UMD, manette,
pilotage PTZ.

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
caméras ; changer ces droits (ajout, retrait, ordre) est appliqué par le Pi
au plus tard `poll_interval_s` secondes après.

## Développement

```
uv run pytest            # tests (faux Core, faux ptzview : pas besoin de Pi)
uv run ruff check        # style
uv run ruff format       # mise en forme
```
