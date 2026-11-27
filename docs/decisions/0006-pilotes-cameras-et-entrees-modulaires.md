# 0006 — Pilotes caméras et entrées manettes modulaires

- Statut : Accepté
- Date : 2026-11-26

## Contexte
Tests avec des Panasonic AW-UE150, puis rapidement Sony FR7, Canon et d'autres.
Manette PS4 en USB au départ, puis d'autres manettes avec un mappage libre.
Ajouter une marque ou une manette doit être simple et ne pas toucher au reste.

## Décision
- **Pilotes caméras** : une interface commune (vitesse pan/tilt, zoom, focus,
  rappel/mémorisation de preset, stop, déclaration des capacités) ; une
  implémentation par marque dans son propre module. Le pilote gère le protocole,
  l'échelle des vitesses, l'intervalle minimal entre commandes et la reconnexion.
- **Entrées** : chaque périphérique est lu et traduit en événements génériques
  (axes normalisés, boutons). Les manettes vues par Linux comme périphériques
  d'entrée standard sont reconnues par identifiant USB et ne demandent qu'un
  profil, pas de code. D'autres types d'entrée (MIDI, pupitres) seront de
  nouveaux modules d'entrée.
- **Mappage** : profils définis dans OsmiraCore (zone morte, courbe, inversion,
  affectation des boutons) et envoyés aux postes.
- **Caméra** = bloc média + bloc contrôle indépendants.

## Options écartées
- **Code spécifique à chaque marque dans la logique principale** : chaque ajout
  toucherait tout le programme.

## Conséquences
- Une fausse caméra et une fausse manette existent dès le départ pour les tests
  automatiques.
- Les protocoles exacts de chaque marque (Panasonic CGI HTTP, Sony, Canon) sont à
  vérifier dans leur documentation au moment d'écrire chaque pilote.
