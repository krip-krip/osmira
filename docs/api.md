# API d'OsmiraCore

Une seule API REST sert les postes, l'interface web et les futurs modules
(ADR 0005). Base : `http://<core>:8000/api`. Corps et réponses en JSON.
Documentation interactive générée par FastAPI : `http://<core>:8000/docs`.

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

## Prévu (incréments suivants, à préciser le moment venu)

- `GET /api/stations/{id}/events` — flux SSE, connexion permanente ouverte par
  le poste. Événements : `config_changed` (`{"version": …}`), `tally`
  (`{"camera_id", "tally"}`), `umd` (`{"camera_id", "text"}`). À la connexion,
  le Core envoie l'état courant (version, tally et UMD de ses caméras).
- `POST /api/stations/{id}/status` — toutes les quelques secondes : version de
  config appliquée, caméra affichée, état des flux, manette ; sert de signal
  de vie (poste « hors ligne » après N secondes sans message).
- `POST /api/tally` — pour l'interface web et les modules (mélangeur) :
  `{"camera_id": "cam1", "tally": "pgm"}` ; `POST /api/umd` idem.
- Sites, profils de manette, prise de main.
- Authentification des postes par jeton (hors périmètre pour l'instant).
