# Architecture

## Trois chemins séparés

| Chemin | Trajet | Exigence | Si OsmiraCore tombe |
|---|---|---|---|
| **Vidéo** | caméras → MediaMTX → Pi (SRT) | latence minimale | continue |
| **PTZ** | manette → Pi → caméra, en direct | latence minimale | continue |
| **Contrôle** | OsmiraCore ↔ Pi (REST + SSE) | fiabilité, pas de temps réel | le Pi garde sa dernière config ; tally/UMD figés |

```
                 ┌──────────────── OsmiraCore (Linux, VPS ou autre) ───────────────┐
                 │ Modèle : caméras, sites, postes, droits, profils manette        │
                 │ Interface web · API REST · flux d'événements SSE                │
                 └──────────────┬───────────────────────────────▲──────────────────┘
          config, tally, UMD    │ SSE (poussé)                  │ REST (état, signal de vie)
                                ▼                               │
   ┌──────────────────────── Poste OsmiraCam (Raspberry Pi) ────┴───────┐
   │  agent (Python)                                                    │
   │   ├─ connecteur OsmiraCore (config enregistrée en local)           │
   │   ├─ entrées : manettes (evdev) → événements génériques            │
   │   ├─ mappage : événements → actions (profil venant du Core)        │
   │   ├─ pilotes caméras : Panasonic, Sony, Canon…  ──────────────► caméras PTZ
   │   └─ pilote ptzview en HTTP local                                  │
   │  ptzview (C) : 4 décodages HEVC permanents → HDMI + calques        │
   └────────────────────▲───────────────────────────────────────────────┘
                        │ SRT/H.265
                   MediaMTX ◄──── caméras (SRT listener)
```

## Composants

### ptzview — moteur vidéo d'OsmiraCam (C)
- Reçoit 4 flux SRT (MPEG-TS/HEVC) depuis MediaMTX et les décode en permanence
  (FFmpeg `+rpt`, hwaccel `drm`, décodeur `rpi-hevc-dec`, images DRM PRIME en
  zéro copie).
- Affichage DRM/KMS atomique : la caméra choisie sur le plan primaire (format
  NV12 SAND), calques tally/UMD/NO SIGNAL sur un plan ARGB au-dessus, redessinés
  seulement quand l'état change.
- Bascule = changement de tampon au prochain rafraîchissement : 18 à 60 ms mesurés.
- Reconnexion automatique de chaque entrée (environ toutes les 2 s) ; dernière
  image figée + « NO SIGNAL » en cas de perte.
- API HTTP locale : `/status`, `/select/N`, `/tally/N/off|pvw|pgm`, `/label/N`,
  `/input/N` (nouvelle URL d'une entrée à chaud ; vide = désactivée).
- Évolution prévue : nombre de caméras configurable.

### agent OsmiraCam (Python)
- **Connecteur Core** : récupère la configuration complète (versionnée), l'enregistre
  en local, écoute le flux SSE, envoie son état (signal de vie).
- **Entrées** : lit les manettes via `evdev`, reconnues par identifiant USB
  (fabricant/modèle) ; produit des événements génériques (axe, bouton).
- **Mappage** : profil défini dans OsmiraCore (zone morte, courbe, inversion,
  affectation des boutons) → actions (vitesse pan/tilt/zoom, focus, presets,
  choix de caméra…).
- **Pilotes caméras** : interface commune, une implémentation par marque. Gère
  le protocole, les vitesses, l'intervalle minimal entre commandes, la reconnexion.
- **Sécurité « homme mort »** : stop envoyé à la caméra si la manette disparaît,
  si l'agent s'arrête, ou en l'absence d'entrée récente.
- Pilote `ptzview` (bascule, tally, UMD).

### OsmiraCore (Python, FastAPI)
- Modèle de données (première version, à détailler dans `docs/api.md`) :
  - **Site** : lieu physique, avec ses points d'accès (MediaMTX, réseau caméras).
  - **Caméra** : nom, site, bloc **média** (URL SRT, latence, codec, résolution,
    cadence), bloc **contrôle** (pilote, adresse, port, identifiants, options).
  - **Poste** : un Pi OsmiraCam, identifiant fixe, site, capacités (nombre de
    décodages possibles).
  - **Profil de manette** : type de manette + mappage.
  - **Droits** : par poste et par caméra : voir, décoder, piloter.
  - **État** : tally et UMD par caméra.
- Calcule pour chaque poste sa configuration (adresses média et contrôle selon
  le site du poste ; respect de la capacité de décodage).
- Matrice (ADR 0009) : choisit la caméra affichée sur chaque sortie vidéo de
  chaque poste ; envoyée par SSE, exécutée par le poste. La manette pourra
  aussi commuter (la dernière commande gagne).
- Distingue dès le modèle « caméra affichée » et « caméra pilotée » (identiques
  au départ).
- Prise de main / arbitrage entre opérateurs : géré par le Core ; en cas de
  coupure, les derniers droits connus s'appliquent.
- Supervision : état remonté par chaque poste toutes les 5 s ; statistiques
  SRT des deux liaisons (caméra → MediaMTX, MediaMTX → poste) lues dans l'API
  MediaMTX en lecture seule et gardées 7 jours (ADR 0010).
- SQLite au départ ; déployé en Docker.

## Communication OsmiraCore ↔ OsmiraCam (voir ADR 0005)

1. Au démarrage : `GET /api/stations/<id>/config` → configuration complète avec
   numéro de version ; enregistrée en local.
2. Connexion permanente `GET /api/stations/<id>/events` (SSE) : événements
   `state` (à la connexion), `select`, `config_changed`, puis `tally`, `umd`…
3. `POST /api/stations/<id>/status` toutes les quelques secondes (état + signal de vie).
4. Après une coupure : reconnexion SSE, nouvelle récupération de la config si la
   version a changé.

Une seule API sert les postes, l'interface web et les futurs modules
(un module mélangeur fera `POST /api/tally`).

## Points d'attention connus

- **Latence tally** : avec un Core distant, le tally traverse Internet
  (quelques dizaines de ms). Un relais local par site pourra venir plus tard
  sans changer l'API.
- **Arrêt des caméras** : si le Pi meurt brutalement en plein mouvement, certaines
  caméras continuent de bouger. À vérifier marque par marque.
- **Capacité de décodage** : 4 flux 1080p50 par Pi 4 ; probablement 5–6 en 25p,
  limité alors par la CMA (voir mesures).
- **Réseau** : le Pi doit joindre directement MediaMTX *et* le réseau des caméras.
