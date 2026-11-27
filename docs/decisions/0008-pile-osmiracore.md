# 0008 — Pile technique d'OsmiraCore

- Statut : Accepté
- Date : 2026-11-27

## Contexte
OsmiraCore est écrit en Python avec FastAPI (ADR 0003). Il reste à choisir
l'outillage, la base de données, l'interface web et la manière de versionner
la configuration des postes. Un seul développeur, débutant en git, à l'aise en
ligne de commande, qui ne veut pas d'un second écosystème à maîtriser.

## Décision
- **uv** : installation de Python, environnement virtuel, dépendances figées
  (`pyproject.toml` + `uv.lock`). Commandes : `uv sync`, `uv run …`.
- **SQLAlchemy 2** (modèles typés) sur **SQLite**. Tables créées au démarrage ;
  **Alembic** (migrations) ajouté dès qu'il y aura des données à préserver.
- **Interface web en Jinja2 + htmx** : pages HTML générées par FastAPI ; htmx
  (fichier statique versionné, pas de CDN) pour l'interactivité. La logique
  vit dans une couche `services/` appelée à la fois par l'API et par les pages.
- **Version de configuration = empreinte SHA-256** du JSON canonique de la
  configuration d'un poste : aucun compteur à tenir à jour, elle change si et
  seulement si le contenu change ; sert aussi d'`ETag` HTTP.
- **Tout le code en anglais**, API comprise : identifiants, routes, champs
  JSON, messages de commit. Les routes de l'ADR 0005 deviennent
  `/api/stations/{id}/config`, `/api/stations/{id}/events` et
  `/api/stations/{id}/status` (le « poste » s'appelle `station`). Seule la
  documentation reste en français pour l'instant.
- Outils de dev : `pytest`, `httpx` (client de test), `ruff`.

## Options écartées
- **pip + venv** : plus de commandes manuelles, pas de verrouillage des
  versions par défaut.
- **React / Vue** : second écosystème (npm, compilation) pour un besoin
  d'écrans de gestion simples.
- **SQLModel** : surcouche moins mûre ; SQLAlchemy 2 + Pydantic suffisent.
- **Base PostgreSQL** : serveur de plus à faire tourner ; SQLite suffit pour
  quelques dizaines de caméras et de postes.
- **Numéro de version incrémenté** : à mettre à jour à chaque modification de
  tout ce qui touche un poste, source d'oublis.

- **Routes en français** (`/postes`, `/etat`, comme écrit dans l'ADR 0005) :
  mélange de langues dans le code ; abandonné pour une règle simple, tout le
  code en anglais.

## Conséquences
- Un seul langage pour tout le Core ; CI Python avec `uv`, `ruff` et `pytest`.
- SQLite impose un seul processus d'écriture : suffisant pour le Core, à
  revoir si on le réplique.
- Sans Alembic au départ, un changement de schéma impose de recréer la base
  (acceptable tant qu'il n'y a que des données de test).
