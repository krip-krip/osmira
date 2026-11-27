# 0004 — Commandes PTZ directes Pi → caméra, jamais via le Core

- Statut : Accepté
- Date : 2026-11-26

## Contexte
OsmiraCore peut être loin des caméras (domicile, VPS). Le pilotage d'une PTZ à
la manette est une boucle temps réel : l'opérateur juge le mouvement sur le
retour vidéo (150–200 ms) ; toute latence de commande s'y ajoute. Le poste doit
pouvoir piloter même si le Core est injoignable.

## Décision
L'agent OsmiraCam envoie les commandes **directement** à la caméra, avec le
pilote de sa marque. OsmiraCore ne fait que distribuer les droits (quelles
caméras un poste peut piloter) et les paramètres de contrôle (adresse, pilote,
identifiants).

## Options écartées
- **Commandes via OsmiraCore** (centralisation, arbitrage simple, journal
  unique) : latence d'Internet ajoutée, dépendance au Core pour une fonction
  temps réel.

## Conséquences
- Le Pi doit joindre le réseau des caméras (routes NetBird).
- L'agent porte la sécurité « homme mort » : stop sur perte de manette, arrêt de
  l'agent ou absence d'entrée récente. À vérifier par marque : la caméra
  s'arrête-t-elle seule si elle ne reçoit plus de commandes ?
- Deux postes autorisés sur la même caméra peuvent se gêner : la prise de main
  passe par le Core ; s'il est injoignable, les derniers droits connus s'appliquent.
- Chaque pilote respecte l'intervalle minimal entre commandes de sa marque
  (envoi de la dernière valeur, pas de chaque événement).
