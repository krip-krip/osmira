# 0001 — Moteur vidéo en C : FFmpeg `+rpt` + DRM/KMS direct

- Statut : Accepté
- Date : 2026-11-26

## Contexte
Le poste OsmiraCam doit décoder 4 flux HEVC 1080p50 et afficher l'un d'eux avec
une latence minimale, sur un Raspberry Pi 4 à 1 Go de RAM. Les calques
(tally, UMD) doivent être dessinés à l'affichage, pas incrustés par le CPU.
Un seul processus peut piloter la sortie HDMI (maître DRM).

## Décision
Programme unique en C (`ptzview`) :
- décodage par libavcodec de Raspberry Pi (`+rpt`, hwaccel `drm`, décodeur
  sans état `rpi-hevc-dec`) → images DRM PRIME, zéro copie ;
- affichage DRM/KMS atomique direct : vidéo sur le plan primaire (NV12 SAND,
  modificateur Broadcom SAND128), calques sur un plan ARGB au-dessus (cairo) ;
- API HTTP locale (libmicrohttpd).
C'est un composant « boîte noire », modifié rarement.

## Options écartées
- **mpv / libmpv** : une instance = un flux ; une seule instance peut tenir
  l'écran ; `--lavfi-complex` + `streamselect` synchronise les entrées sur leurs
  horodatages (horloges caméras indépendantes) et se bloque si une entrée tombe.
  Mesuré aussi : rendu GPU `--vo=gpu` trop lent en 1080p50 sans `--profile=fast`,
  et mode `drmprime-overlay` refusé (EINVAL).
- **GStreamer** (`v4l2slh265dec` → `kmssink`) : un seul plan, donc calques par
  incrustation CPU ou mélange GL ; prise en charge du format SAND non vérifiée.
- **Python (PyAV + ctypes)** : accès au descripteur DRM PRIME fragile, plus de RAM.
- **Rust, Go** : bindings FFmpeg `+rpt` incertains, pas de gain sur ce composant.
- **4 processus séparés** : environ 2,5 fois plus de RAM et de CMA consommées.

## Conséquences
- Validé sur la maquette : 4 × 1080p50 stables, bascule 18–60 ms, CMA libre
  ~94–120 Mo, RAM disponible ~470 Mo (voir `../mesures/2026-11-26-maquette-pi4.md`).
- Le C est peu familier à l'utilisateur : garder ce composant petit et stable ;
  toute la logique métier va dans l'agent Python (ADR 0003).
- Évolutions nécessaires : nombre de caméras configurable, rechargement à chaud
  de la configuration.
