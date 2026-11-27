# 0009 — Choix de la caméra affichée depuis le Core (matrice)

- Statut : Accepté
- Date : 2026-11-27

## Contexte
L'exploitation veut décider, depuis l'interface d'administration du Core,
quelle caméra s'affiche sur quelle sortie vidéo de quel poste, sous forme de
matrice (sources = caméras, destinations = sorties des postes). Plus tard, le
cadreur pourra aussi commuter lui-même avec sa manette. Or la règle de base
dit que rien de temps réel ne doit dépendre du Core, qui peut être loin (VPS).

## Décision
- La matrice du Core est une fonctionnalité **permanente**, pas un palliatif.
- Une **destination** est une sortie vidéo d'un poste (`station`, `output`) :
  un poste a `outputs` sorties (1 au départ ; un Pi 4 en a 2).
- Le Core mémorise la caméra choisie par sortie (table `selections`). Ce choix
  est un **état**, pas de la configuration : il ne change pas la version de
  config.
- Une sortie ne peut afficher qu'une caméra sur laquelle le poste a le droit
  `view`. Si ce droit disparaît, la sélection est effacée.
- Le Core **commande**, le poste **exécute** : le choix part par SSE
  (événement `select`), le poste bascule localement. Si le Core est
  injoignable, le poste garde la caméra affichée et continue.
- Avec la manette (plus tard) : **la dernière commande gagne**, qu'elle vienne
  du Core ou de la manette. Le poste remontera la caméra réellement affichée
  (`POST /status`) pour que la matrice montre la réalité.

## Options écartées
- **Bascule seulement à la manette** : l'exploitation ne pourrait pas
  distribuer les images depuis un point central.
- **Bascule temporaire depuis le Core, remplacée ensuite par la manette** :
  écartée par l'utilisateur, les deux modes sont voulus.
- **Le Core impose la caméra et bloque la manette** : retire au cadreur la
  main sur son propre écran ; un verrouillage par sortie pourra venir plus
  tard si besoin.
- **Sélection dans la configuration versionnée** : chaque bascule ferait
  recharger la config au poste.

## Conséquences
- Le temps de bascule depuis le Core inclut la latence réseau Core → poste
  (quelques dizaines de ms avec un Core distant) ; la bascule locale à la
  manette restera la plus rapide.
- La règle « rien de temps réel ne dépend du Core » devient : rien ne doit
  **s'arrêter** si le Core tombe (image, pilotage, bascule locale).
- Le poste doit gérer `camera_id: null` (aucun choix du Core) : il affiche
  alors la première caméra visible.
