# Modèle de données d'OsmiraCore

Ce document décrit ce que le Core sait du système. La colonne **Incr. 1**
indique ce qui est codé dans le premier incrément (configuration seulement) ;
le reste est prévu, pour que le schéma n'ait pas à être refait.

Conventions :
- tout ce qui apparaît dans le code est en anglais : entités, champs, JSON,
  routes (ADR 0008). Le « poste » OsmiraCam s'appelle `station` dans le code ;
- identifiants **texte** choisis par l'utilisateur (`cam1`, `panelTest`) :
  lisibles dans `curl`, stables dans la configuration des postes ;
- format d'un identifiant : lettres, chiffres, `-` et `_`, 1 à 32 caractères.

## Vue d'ensemble

```
Site 1───* Camera                Station 1───* Right *───1 Camera
Site 1───* Station               Station *───1 GamepadProfile
Camera 1───1 CameraState (tally, UMD)
```

## Camera — Incr. 1

Une caméra = un bloc **média** (comment recevoir l'image) + un bloc
**contrôle** (comment la piloter), indépendants (ADR 0006).

| Champ | Type | Exemple | Notes |
|---|---|---|---|
| `id` | texte | `cam1` | identifiant fixe |
| `label` | texte | `CAM 1` | nom affiché (UMD par défaut) |
| **média** | | | |
| `media.srt_url` | texte | `srt://192.168.104.253:8890?mode=caller&streamid=read:cam1` | sans `latency=` |
| `media.latency_ms` | entier | `20` | en **millisecondes** |
| `media.codec` | `hevc` \| `h264` | `hevc` | |
| `media.width` / `media.height` | entier | `1920` / `1080` | |
| `media.fps` | entier | `50` | 25 ou 50 |
| **contrôle** | | | |
| `control.driver` | texte | `panasonic_aw` | nom du pilote de l'agent ; `none` = pas de pilotage |
| `control.host` | texte | `192.168.105.51` | |
| `control.port` | entier | `80` | |
| `control.username` | texte | `admin` | facultatif |
| `control.password` | texte | — | facultatif, **jamais renvoyé** par l'API de gestion |
| `control.options` | objet JSON | `{}` | paramètres propres au pilote |

Plus tard : `site_id`, et des adresses média/contrôle différentes selon le
site du poste (un poste distant ne passe pas par le même MediaMTX).

## Station (poste) — Incr. 1

Un poste = un Raspberry Pi OsmiraCam.

| Champ | Type | Exemple | Notes |
|---|---|---|---|
| `id` | texte | `panelTest` | identifiant fixe, connu du Pi |
| `label` | texte | `Cadreur 1` | |
| `max_decoders` | entier | `4` | nombre de flux décodables en permanence (ADR 0002) |
| `outputs` | entier ≥ 1 | `1` | sorties vidéo (HDMI) : les destinations de la matrice |

Plus tard : `site_id`, `gamepad_profile_id`, jeton d'accès, dernier signal
de vie et état remonté (`POST /status`).

## Right (droit d'un poste sur une caméra) — Incr. 1

Une ligne par couple poste × caméra. Pas de ligne = aucun droit.

| Champ | Type | Notes |
|---|---|---|
| `station_id`, `camera_id` | texte | clé du droit |
| `position` | entier ≥ 1 | ordre des caméras sur le poste (cam1…camN de `ptzview`) ; unique par poste |
| `decode` | booléen | le poste reçoit et décode le flux en permanence ; **compte dans `max_decoders`** |
| `view` | booléen | l'opérateur peut l'afficher ; implique `decode` (ADR 0002 : on n'affiche qu'un flux déjà décodé) |
| `control` | booléen | l'opérateur peut la piloter ; implique `view` |

Règles vérifiées à l'enregistrement :
- `view` ⇒ `decode`, `control` ⇒ `view` (sinon refus) ;
- nombre de droits `decode` du poste ≤ `max_decoders` (sinon refus) ;
- `position` unique par poste.

Plus tard : « caméra affichée » et « caméra pilotée » distinctes, prise de main
et arbitrage entre postes (qui pilote quoi à l'instant t).

## Selection (caméra affichée par sortie) — ADR 0009

État, pas configuration : ne change pas la version de config.

| Champ | Type | Notes |
|---|---|---|
| `station_id`, `output` | texte, entier | clé : une sortie d'un poste (1…`outputs`) |
| `camera_id` | texte | caméra choisie ; le poste doit avoir le droit `view` |

Pas de ligne = aucun choix du Core (le poste affiche sa première caméra
visible). Effacée si le droit `view` disparaît, si la caméra est supprimée ou
si la sortie n'existe plus.

## Prévu, hors incrément 1

- **Site** : `id`, `label`, adresse du MediaMTX, réseau caméras.
- **GamepadProfile** : `id`, type de manette (identifiant USB
  fabricant/modèle), mappage (zone morte, courbe, inversion, affectation des
  boutons → actions).
- **CameraState** : `tally` (`off` \| `pvw` \| `pgm`), `umd` (texte). Modifié
  par l'interface web ou un module (mélangeur) via `POST /api/tally`, poussé
  aux postes par SSE. Ne fait **pas** partie de la configuration versionnée.

## Configuration d'un poste

Calculée à la demande (`GET /api/stations/{id}/config`) à partir de Station,
Right et Camera ; elle n'est pas stockée. Sa **version** est l'empreinte
SHA-256 de son contenu (JSON canonique) : elle change dès qu'une donnée qui
la concerne change, et seulement dans ce cas. Exemple : `docs/api.md`.

Pour l'instant la configuration ne contient que le bloc **média** (priorité à
la visualisation). Le bloc `control` d'une caméra (avec ses identifiants) y
sera ajouté avec le pilotage PTZ, et seulement pour les postes qui ont le
droit `control` sur elle.

Pas de limite globale du nombre de caméras : seule la capacité
`max_decoders` de chaque poste limite les flux qu'il reçoit.
