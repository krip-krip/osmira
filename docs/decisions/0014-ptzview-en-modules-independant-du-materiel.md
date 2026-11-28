# 0014 — `ptzview` découpé en modules, en C, indépendant du matériel

- Statut : Accepté
- Date : 2026-11-28
- Complète : ADR 0001

## Contexte
`ptzview.c` faisait 1 884 lignes d'un seul tenant : configuration, entrées
SRT/FFmpeg, contournements libsrt, KMS, calques, affichage, API HTTP. Les
évolutions prévues touchent toutes ce fichier :
- nombre de caméras configurable, puis plus de 4 flux ;
- deuxième sortie HDMI ;
- d'autres matériels que le Pi 4 à 1 Go (autre carte, plus de RAM).

La question d'une réécriture en Rust a été posée.

## Décision
1. **On reste en C**, découpé en modules (`osmiracam/player/src/`, un fichier
   par sujet, voir le README de `ptzview`). Le découpage ne change pas le
   comportement. Les évolutions viennent ensuite, chacune dans sa PR.
2. **Indépendance matérielle** : rien de propre au Pi 4 n'est codé en dur.
   - Décodeur matériel et périphérique : réglages (`hwaccel`, `hwaccel_device`).
   - Format et modificateur des images : lus dans l'image décodée, transmis tels
     quels au pilote d'affichage.
   - Plans d'affichage : choisis par essai (`TEST_ONLY`), pas supposés.
   - Chiffres propres à la machine (CMA, température) : isolés dans `sysinfo.c`,
     et absents (`-1`) sur une machine qui ne les a pas.
   - Les capacités (nombre d'entrées, de sorties) deviendront des réglages ou
     seront détectées, et seront remontées au Core.

## Options écartées
- **Réécriture en Rust** (réévaluée depuis l'ADR 0001). Les gains sont réels
  sur la logique : sûreté mémoire, état partagé entre threads vérifié par le
  compilateur, `serde`, `cargo test`. Mais la partie la plus délicate reste de la
  FFI `unsafe` : images DRM PRIME de FFmpeg `+rpt`, plans KMS. Le contournement
  libsrt par interposition de symboles est à refaire. La compilation sur un Pi à
  1 Go est lente, et il faudrait remesurer tout le matériel (latence, bascule,
  CMA, endurance). La portabilité ne la favorise pas : C + FFmpeg est déjà la
  combinaison la plus portable. Un essai limité (un flux décodé et affiché en
  zéro copie) reste possible si la double sortie s'avère trop pénible en C.
- **Garder un seul fichier** : chaque évolution deviendrait plus difficile à
  relire et à tester.

## Conséquences
- Un changement ne touche en général qu'un ou deux modules ; le README de
  `ptzview` indique où intervenir.
- Fonctions partagées déclarées dans `ptzview.h` (`kms.h`, `osd.h` pour
  l'affichage) ; le reste est `static`.
- `-rdynamic` reste nécessaire : `srt_cleanup`, `srt_connect` et `srt_accept`
  (`srt_hooks.c`) doivent rester exportées.
- Non-régression vérifiée sur le Pi : `../mesures/2026-11-28-ptzview-modules.md`.
