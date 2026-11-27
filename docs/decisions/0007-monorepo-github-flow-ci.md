# 0007 — Monorepo, GitHub flow, CI dès le départ

- Statut : Accepté
- Date : 2026-11-27

## Contexte
Un seul développeur, débutant en git, assisté par Claude Code. Plusieurs
composants (moteur vidéo C, agent Python, OsmiraCore) qui évoluent ensemble via
une API commune.

## Décision
- **Un seul dépôt** `osmira` : `osmiracam/player`, `osmiracam/agent`,
  `osmiracore`, `docs`.
- **GitHub flow** : `main` fonctionne toujours ; une branche par sujet
  (`feat/…`, `fix/…`, `docs/…`) ; PR ; fusion seulement si la CI est verte ;
  branche supprimée après fusion. `main` protégée sur GitHub.
- **Conventional Commits** (`feat:`, `fix:`, `docs:`…).
- **CI GitHub Actions dès le départ** : compilation de `ptzview` (avertissements
  = erreurs), `ruff` + `pytest` pour le Python. Ensuite : image Docker du Core,
  binaires ARM64, déploiement sur étiquette de version.
- Aucun secret dans git.

## Options écartées
- **Un dépôt par composant** : synchronisation des versions d'API plus lourde
  pour un développeur seul.

## Conséquences
- Les tests ne doivent pas dépendre du matériel (fausse caméra, fausse manette).
- Les tests sur le vrai matériel restent manuels et sont consignés dans
  `docs/mesures/` ; un Pi en machine de test GitHub (runner auto-hébergé)
  pourra venir plus tard.
