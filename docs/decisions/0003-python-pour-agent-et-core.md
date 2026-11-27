# 0003 — Python pour l'agent OsmiraCam et pour OsmiraCore

- Statut : Accepté
- Date : 2026-11-26

## Contexte
Hormis le moteur vidéo, le reste est de la logique de contrôle : manettes
(~50 événements/s), pilotes caméras, configuration, API, interface web. Le
projet grossira par modules. L'utilisateur n'est pas à l'aise avec le C et veut
un langage confortable pour la suite.

## Décision
Python 3.11+ (typé, `asyncio`) pour :
- l'agent du Pi (`evdev` pour les manettes, client HTTP/SSE, pilotes caméras) ;
- OsmiraCore (FastAPI, SQLite au départ, interface web).

## Options écartées
- **Go** : binaire unique et robuste, mais apprentissage plus raide et moins de
  bibliothèques « clé en main ». Reste une option si la performance ou le
  déploiement posent problème.
- **Node.js / TypeScript** : plus gourmand sur le Pi, deux écosystèmes.
- **C / Rust** : trop coûteux à écrire et maintenir pour de la logique métier.

## Conséquences
- Agent sur le Pi : ~30–40 Mo de RAM, acceptable avec ~470 Mo disponibles.
- Déploiement à soigner (environnement virtuel, dépendances figées).
- Typage + `ruff` + `pytest` imposés pour compenser la souplesse du langage.
