# Décisions d'architecture (ADR)

Un **ADR** (*Architecture Decision Record*, fiche de décision d'architecture)
est une note courte qui enregistre **une** décision importante : le contexte,
le choix fait, les options écartées et pourquoi, et les conséquences.

Pourquoi c'est utile :
- dans six mois, on sait **pourquoi** on a fait ce choix, pas seulement quoi ;
- les options écartées sont écrites : ni toi ni Claude Code ne les reproposerez
  sans raison nouvelle ;
- une décision qui change ne s'efface pas : on écrit un nouvel ADR qui
  « remplace » l'ancien, et l'historique reste lisible.

Règles :
- un fichier par décision, numéroté : `0001-titre-court.md` ;
- statut : `Proposé`, `Accepté`, `Remplacé par 00XX`, `Abandonné` ;
- une page maximum ; on ne réécrit pas un ADR accepté, on en crée un nouveau.

## Index

| N° | Décision | Statut |
|---|---|---|
| [0001](0001-moteur-video-c-ffmpeg-kms.md) | Moteur vidéo en C : FFmpeg `+rpt` + DRM/KMS direct | Accepté |
| [0002](0002-decodage-permanent-de-tous-les-flux.md) | Décoder en permanence tous les flux, n'en afficher qu'un | Accepté |
| [0003](0003-python-pour-agent-et-core.md) | Python pour l'agent OsmiraCam et pour OsmiraCore | Accepté |
| [0004](0004-ptz-direct-pi-vers-camera.md) | Commandes PTZ directes Pi → caméra, jamais via le Core | Accepté |
| [0005](0005-api-rest-sse.md) | Communication Core ↔ postes : REST + SSE (pas MQTT) | Accepté |
| [0006](0006-pilotes-cameras-et-entrees-modulaires.md) | Pilotes caméras et entrées manettes modulaires | Accepté |
| [0007](0007-monorepo-github-flow-ci.md) | Monorepo, GitHub flow, CI dès le départ | Accepté |
| [0008](0008-pile-osmiracore.md) | Pile technique d'OsmiraCore (uv, SQLAlchemy, Jinja2 + htmx, version par empreinte) | Accepté |
| [0009](0009-bascule-depuis-le-core.md) | Choix de la caméra affichée depuis le Core (matrice) | Accepté |
| [0010](0010-stats-srt-depuis-mediamtx.md) | Statistiques SRT lues par le Core dans l'API MediaMTX | Accepté |
| [0011](0011-source-des-cameras.md) | Source d'une caméra : serveur média ou direct, URL calculée ou imposée | Accepté |
| [0012](0012-contournement-libsrt-cleanup.md) | Contournement du décompte srt_startup/srt_cleanup de libsrt 1.5.4 | Accepté |

## Modèle

```markdown
# 00XX — Titre

- Statut : Proposé
- Date : AAAA-MM-JJ

## Contexte
Le problème, les contraintes, ce qui oblige à décider.

## Décision
Ce qu'on fait.

## Options écartées
- Option A : pourquoi non.
- Option B : pourquoi non.

## Conséquences
Ce que ça implique (positif et négatif), ce qu'il faudra surveiller.
```
