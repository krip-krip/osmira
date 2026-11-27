# API d'OsmiraCore

Une seule API REST sert les postes, l'interface web et les futurs modules
(ADR 0005). Base : `http://<core>:8000/api`. Corps et réponses en JSON.
Documentation interactive générée par FastAPI : `http://<core>:8000/docs`.
Interface d'administration (HTML, mêmes règles que l'API) : `http://<core>:8000/`
(page Matrice : `/matrix`).

Routes et champs JSON en anglais, comme tout le code (ADR 0008) : un poste
OsmiraCam s'appelle `station`. Modèle des données : `docs/modele-donnees.md`.

## Codes de réponse

| Code | Cas |
|---|---|
| `200` / `201` | lu / créé |
| `204` | supprimé |
| `304` | configuration inchangée (`If-None-Match`) |
| `404` | identifiant inconnu |
| `409` | conflit : identifiant déjà pris, `position` déjà utilisée, capacité de décodage dépassée |
| `422` | données invalides (champ manquant, règle `view` ⇒ `decode` non respectée…) |

Les erreurs renvoient `{"detail": "<message lisible>"}`.

## Incrément 1 — configuration

### Santé
- `GET /api/health` → `{"status": "ok", "version": "<version du Core>"}`

### Caméras
- `GET /api/cameras` → liste
- `POST /api/cameras` → création (`201`)
- `GET /api/cameras/{id}`
- `PUT /api/cameras/{id}` → remplacement complet
- `DELETE /api/cameras/{id}` → supprime aussi ses droits (`204`)

`control.password` est accepté en écriture mais jamais renvoyé : la lecture
donne `"password_set": true|false`. En `PUT`, un `password` absent conserve
l'ancien ; `""` l'efface.

```
curl -X POST localhost:8000/api/cameras -H 'Content-Type: application/json' -d '{
  "id": "cam1", "label": "CAM 1",
  "media":   {"srt_url": "srt://192.168.104.253:8890?mode=caller&streamid=read:cam1",
              "latency_ms": 20, "codec": "hevc", "width": 1920, "height": 1080, "fps": 50},
  "control": {"driver": "panasonic_aw", "host": "192.168.105.51", "port": 80,
              "username": "admin", "password": "…", "options": {}}
}'
```

### Postes (`stations`)
- `GET /api/stations` · `POST /api/stations` · `GET|PUT|DELETE /api/stations/{id}`

```
curl -X POST localhost:8000/api/stations -H 'Content-Type: application/json' \
  -d '{"id": "panelTest", "label": "Cadreur 1", "max_decoders": 4}'
```

### Droits
- `GET /api/stations/{id}/rights` → droits du poste, triés par `position`
- `PUT /api/stations/{id}/rights/{camera_id}` → crée ou remplace le droit
- `DELETE /api/stations/{id}/rights/{camera_id}` (`204`)

```
curl -X PUT localhost:8000/api/stations/panelTest/rights/cam1 -H 'Content-Type: application/json' \
  -d '{"position": 1, "decode": true, "view": true, "control": true}'
```

### Configuration d'un poste (lue par le Pi)
- `GET /api/stations/{id}/config`
  - en-tête `ETag: "<version>"` ;
  - avec `If-None-Match: "<version>"` → `304` sans corps si rien n'a changé.

```json
{
  "station": {"id": "panelTest", "label": "Cadreur 1", "max_decoders": 4},
  "version": "sha256:3f2a…",
  "cameras": [
    {
      "id": "cam1", "label": "CAM 1", "position": 1,
      "rights": {"decode": true, "view": true, "control": true},
      "media":   {"srt_url": "srt://192.168.104.253:8890?mode=caller&streamid=read:cam1",
                  "latency_ms": 20, "codec": "hevc", "width": 1920, "height": 1080, "fps": 50}
    }
  ]
}
```

- Seules les caméras avec `decode` apparaissent, triées par `position`.
  Aucune limite globale du nombre de caméras : seule la capacité
  `max_decoders` de chaque poste compte.
- **Pilotage pas encore envoyé** : la visualisation passe d'abord. Le bloc
  `control` de la caméra (pilote, adresse, identifiants) sera ajouté à chaque
  caméra quand l'agent aura ses pilotes, et seulement pour les postes qui ont
  le droit `control`. Le droit `control` est déjà stocké et renvoyé dans
  `rights`.
- Changer les droits d'un poste (ajouter, retirer, réordonner des caméras)
  change sa `version` : le poste recharge sa config (signal `config_changed`
  par SSE, incrément suivant).
- `version` = `sha256:` + empreinte du JSON canonique (clés triées, sans
  espaces) de l'objet **sans** le champ `version`.

### Caméra affichée par sortie (matrice, ADR 0009)

Une **destination** est une sortie vidéo d'un poste (`outputs` sorties par
poste, 1 par défaut). Le choix est un état, hors configuration versionnée.

- `GET /api/stations/{id}/outputs` → `[{"output": 1, "camera_id": "cam2"}]`
  (`null` : aucun choix du Core)
- `PUT /api/stations/{id}/outputs/{output}/selection` avec
  `{"camera_id": "cam2"}` : le poste doit avoir le droit `view` sur la caméra
  (sinon `409`) ; sortie inexistante : `404`.
- `GET /api/matrix` → la matrice complète pour l'interface :

```json
{
  "sources": [{"camera_id": "cam1", "label": "CAM 1"}, …],
  "destinations": [
    {"station_id": "panelTest", "station_label": "Cadreur 1", "output": 1,
     "selected": "cam2", "allowed": ["cam1", "cam2", "cam3", "cam4"]}
  ]
}
```

Retirer le droit `view` (ou supprimer la caméra, ou la sortie) efface la
sélection correspondante.

### Événements d'un poste (SSE)

- `GET /api/stations/{id}/events` — connexion permanente ouverte par le poste
  (`curl -N` pour la voir). Un commentaire de maintien (`: ping`) passe quand
  rien ne se passe.

| Événement | Données | Quand |
|---|---|---|
| `state` | `{"config_version": "sha256:…", "selections": [{"output": 1, "camera_id": "cam2"}]}` | à chaque connexion, en premier |
| `select` | `{"output": 1, "camera_id": "cam2"}` (`null` : choix effacé) | la caméra choisie pour une sortie change |
| `config_changed` | `{"version": "sha256:…"}` | la configuration du poste change : le poste refait `GET /config` |

Seuls les vrais changements sont envoyés (pas d'événement si on re-choisit la
même caméra ou si une autre station change). Après une coupure, le poste se
reconnecte et repart de l'événement `state`.

```
curl -N localhost:8000/api/stations/panelTest/events
```

### État d'un poste (signal de vie)

- `POST /api/stations/{id}/status` — envoyé par l'agent toutes les 5 s
  (`status_interval_s`) ; réponse `204`, `404` si le poste n'est pas déclaré.
  Les champs inconnus sont ignorés (un agent plus récent reste accepté).

```json
{
  "agent_version": "0.1.0",
  "hostname": "panelTest",
  "addresses": ["10.7.1.30", "100.83.219.117"],
  "config_version": "sha256:…",
  "selected_camera": "cam2",
  "player": {
    "running": true,
    "shown_camera": "cam2",
    "cameras": [{"camera_id": "cam1", "state": "streaming", "fps": 49.9, "mbps": 16.2,
                 "width": 1920, "height": 1080, "connects": 1, "decode_errors": 0,
                 "last_error": ""}]
  },
  "hardware": {"model": "Raspberry Pi 4 Model B Rev 1.5", "arch": "aarch64", "ram_mb": 905,
               "os": "Debian GNU/Linux 13 (trixie)", "kernel": "6.12…", "python": "3.13.5"},
  "system": {"uptime_s": 3600, "temp_c": 51.6, "mem_available_mb": 450,
             "cma_free_mb": 71, "cma_total_mb": 512}
}
```

- `GET /api/stations/{id}/status` → `online` (dernier état reçu il y a moins de
  `OSMIRACORE_ONLINE_TIMEOUT_S`, 15 s par défaut), `last_seen` (UTC),
  `seconds_since`, `config_up_to_date` (la version appliquée par le poste
  est-elle la version actuelle ?) et le dernier `status` reçu.
- `GET /api/matrix` : chaque destination porte aussi `online`.

## Prévu (incréments suivants, à préciser le moment venu)

- Événements `tally` (`{"camera_id", "tally"}`) et `umd`
  (`{"camera_id", "text"}`) sur le même flux ; ajoutés à `state`.
- `POST /api/tally` — pour l'interface web et les modules (mélangeur) :
  `{"camera_id": "cam1", "tally": "pgm"}` ; `POST /api/umd` idem.
- Sites, profils de manette, prise de main.
- Authentification des postes par jeton (hors périmètre pour l'instant).
